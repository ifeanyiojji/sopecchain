"""
ScopeChain AI FastAPI Backend - Vercel Serverless (Self-Contained)
All engine modules inlined for Vercel Lambda compatibility.
"""
import os
import sys
import re
import json
import base64
import io
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# =====================================================
# PYDANTIC SCHEMAS
# =====================================================

class CategorySummary(BaseModel):
    total_tCO2e: float

class CalculationSummary(BaseModel):
    total_scope3_tCO2e: float
    records: int
    categories: Dict[str, CategorySummary]
    engine_version: str
    generated_at: Optional[str] = None

class CalculationRow(BaseModel):
    record_id: int
    Cat1_tCO2e: float = 0.0
    Cat1_ci_95: str = "\u00b10.000"
    Cat4_tCO2e: float = 0.0
    Cat4_ci_95: str = "\u00b10.000"
    Cat11_tCO2e: float = 0.0
    Cat11_ci_95: str = "\u00b10.000"
    Total_Scope3_tCO2e: float = 0.0

class CalculationResponse(BaseModel):
    summary: CalculationSummary
    normalized_data: List[CalculationRow]

# =====================================================
# EMISSION FACTORS
# =====================================================

class EmissionFactor:
    def __init__(self, value: float, uncertainty_pct: float = 10.0,
                 source: str = "default", version: str = "v1", notes: str = ""):
        self.value = value
        self.uncertainty_pct = uncertainty_pct
        self.source = source
        self.version = version
        self.notes = notes

    def sample(self, n: int = 1000) -> np.ndarray:
        std = self.value * (self.uncertainty_pct / 100)
        samples = np.random.normal(self.value, std, n)
        return np.clip(samples, 0, None)

class FactorRegistry:
    def __init__(self, factors_path: Optional[str] = None):
        if factors_path is None:
            factors_path = Path(__file__).parent / "config" / "factors.json"
        self.factors_path = Path(factors_path)
        self.registry: Dict[str, Dict[str, EmissionFactor]] = {}
        self.metadata: dict = {}
        self._load_factors()

    def _load_factors(self):
        if not self.factors_path.exists():
            # Fallback: use hardcoded defaults
            self._load_defaults()
            return
        with open(self.factors_path, 'r') as f:
            data = json.load(f)
        self.metadata = data.get("metadata", {})
        factors_data = data.get("factors", {})
        for factor_key, variants in factors_data.items():
            self.registry[factor_key] = {}
            for variant_name, variant_data in variants.items():
                self.registry[factor_key][variant_name] = EmissionFactor(
                    value=variant_data["value"],
                    uncertainty_pct=variant_data.get("uncertainty_pct", 10.0),
                    source=variant_data.get("source", "unknown"),
                    version=variant_data.get("version", "v1"),
                    notes=variant_data.get("notes", "")
                )

    def _load_defaults(self):
        self.metadata = {"version": "1.0.0-inline"}
        self.registry = {
            "diesel_l_tco2e_per_l": {
                "default": EmissionFactor(0.0027, 15.0, "GHG Protocol 2023")
            },
            "oil_bbl_tco2e": {
                "default": EmissionFactor(0.430, 18.0, "GHG Protocol 2023")
            },
            "gas_mcf_tco2e": {
                "default": EmissionFactor(0.056, 20.0, "GHG Protocol 2023")
            },
            "water_trucking_tco2e_per_tonne_km": {
                "default": EmissionFactor(0.00020, 25.0, "ICCT Truck Study 2024")
            },
        }

    def resolve_factor(self, key: str, hierarchy: Dict[str, str]) -> EmissionFactor:
        if key not in self.registry:
            raise KeyError(f"Unknown factor key: '{key}'")
        factor_variants = self.registry[key]
        for level in ["company", "supplier", "region", "national", "default"]:
            tag = hierarchy.get(level)
            if tag:
                variant_key = f"{level}_{tag}"
                if variant_key in factor_variants:
                    return factor_variants[variant_key]
        if "default" not in factor_variants:
            raise ValueError(f"No default factor found for '{key}'")
        return factor_variants["default"]

    def list_available_factors(self) -> Dict[str, list]:
        return {key: list(variants.keys()) for key, variants in self.registry.items()}

    def get_version(self) -> str:
        return self.metadata.get("version", "unknown")

_global_registry: Optional[FactorRegistry] = None

def get_factor_registry() -> FactorRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = FactorRegistry()
    return _global_registry

# =====================================================
# NORMALIZER
# =====================================================

M3_PER_BBL = 0.1589873
L_PER_GAL = 3.78541

def extract_number(value) -> float:
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace(",", "")
    matches = re.findall(r"-?\d+\.?\d*", s)
    return float(matches[0]) if matches else 0.0

def column_contains_any(column_name: str, keywords: list) -> bool:
    col_lower = column_name.lower().strip()
    return any(kw in col_lower for kw in keywords)

def normalize_units(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).lower().strip() for c in df.columns]
    df["water_m3_norm"] = 0.0
    df["diesel_l_norm"] = 0.0
    df["oil_bbl_norm"] = 0.0
    df["gas_mcf_norm"] = 0.0
    if "haul_distance_km" not in df.columns:
        df["haul_distance_km"] = 80.0
    for col in df.columns:
        if col.endswith("_norm"):
            continue
        numeric_values = df[col].apply(extract_number)
        if numeric_values.sum() == 0:
            continue
        col_lower = col.lower()
        if column_contains_any(col, ["water", "h2o", "h\u2082o"]):
            if "m3" in col_lower or "m\u00b3" in col_lower:
                df["water_m3_norm"] += numeric_values
            else:
                df["water_m3_norm"] += numeric_values * M3_PER_BBL
        elif column_contains_any(col, ["diesel", "fuel"]):
            if "gal" in col_lower or "gallon" in col_lower:
                df["diesel_l_norm"] += numeric_values * L_PER_GAL
            else:
                df["diesel_l_norm"] += numeric_values
        elif column_contains_any(col, ["oil", "crude", "bbl"]) and not column_contains_any(col, ["water"]):
            df["oil_bbl_norm"] += numeric_values
        elif column_contains_any(col, ["gas", "mcf", "natural gas"]):
            df["gas_mcf_norm"] += numeric_values
        elif column_contains_any(col, ["distance", "haul", "km"]):
            df["haul_distance_km"] = numeric_values
    return df

def validate_normalized_data(df: pd.DataFrame) -> dict:
    required_cols = ["water_m3_norm", "diesel_l_norm", "oil_bbl_norm", "gas_mcf_norm"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing normalized columns: {missing}")
    has_data = (df[required_cols].sum(axis=1) > 0).sum()
    total = len(df)
    negative_count = (df[required_cols] < 0).sum().sum()
    return {
        "records_total": total,
        "records_with_data": int(has_data),
        "zero_records": int(total - has_data),
        "negative_values": int(negative_count),
        "data_quality": "PASS" if negative_count == 0 else "FAIL"
    }

# =====================================================
# CALCULATOR (Vectorized)
# =====================================================

def calculate_scope3_with_uncertainty(
    df_norm: pd.DataFrame,
    hierarchy: Dict[str, str] = None,
    mc_samples: int = 1000,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    hierarchy = hierarchy or {}
    n_records = len(df_norm)
    registry = get_factor_registry()

    resolved_factors = {
        key: registry.resolve_factor(key, hierarchy)
        for key in ["diesel_l_tco2e_per_l", "water_trucking_tco2e_per_tonne_km",
                     "oil_bbl_tco2e", "gas_mcf_tco2e"]
    }

    diesel_l = df_norm.get("diesel_l_norm", pd.Series(0.0, index=df_norm.index)).fillna(0).values
    water_m3 = df_norm.get("water_m3_norm", pd.Series(0.0, index=df_norm.index)).fillna(0).values
    oil_bbl = df_norm.get("oil_bbl_norm", pd.Series(0.0, index=df_norm.index)).fillna(0).values
    gas_mcf = df_norm.get("gas_mcf_norm", pd.Series(0.0, index=df_norm.index)).fillna(0).values
    distance_km = df_norm.get("haul_distance_km", pd.Series(80.0, index=df_norm.index)).fillna(80.0).values

    cat1_factor = resolved_factors["diesel_l_tco2e_per_l"]
    cat1_samples = diesel_l[:, np.newaxis] * cat1_factor.sample(mc_samples)[np.newaxis, :]
    cat1_mean = cat1_samples.mean(axis=1)
    cat1_ci_low = np.percentile(cat1_samples, 2.5, axis=1)
    cat1_ci_high = np.percentile(cat1_samples, 97.5, axis=1)

    cat4_factor = resolved_factors["water_trucking_tco2e_per_tonne_km"]
    tonne_km = water_m3 * distance_km
    cat4_samples = tonne_km[:, np.newaxis] * cat4_factor.sample(mc_samples)[np.newaxis, :]
    cat4_mean = cat4_samples.mean(axis=1)
    cat4_ci_low = np.percentile(cat4_samples, 2.5, axis=1)
    cat4_ci_high = np.percentile(cat4_samples, 97.5, axis=1)

    oil_factor = resolved_factors["oil_bbl_tco2e"]
    gas_factor = resolved_factors["gas_mcf_tco2e"]
    cat11_samples = (oil_bbl[:, np.newaxis] * oil_factor.sample(mc_samples)[np.newaxis, :] +
                     gas_mcf[:, np.newaxis] * gas_factor.sample(mc_samples)[np.newaxis, :])
    cat11_mean = cat11_samples.mean(axis=1)
    cat11_ci_low = np.percentile(cat11_samples, 2.5, axis=1)
    cat11_ci_high = np.percentile(cat11_samples, 97.5, axis=1)

    total_mean = cat1_mean + cat4_mean + cat11_mean

    result_df = pd.DataFrame({
        "record_id": np.arange(n_records),
        "Cat1_tCO2e": cat1_mean,
        "Cat1_ci_95": [f"\u00b1{(h - l) / 2:.3f}" for h, l in zip(cat1_ci_high, cat1_ci_low)],
        "Cat4_tCO2e": cat4_mean,
        "Cat4_ci_95": [f"\u00b1{(h - l) / 2:.3f}" for h, l in zip(cat4_ci_high, cat4_ci_low)],
        "Cat11_tCO2e": cat11_mean,
        "Cat11_ci_95": [f"\u00b1{(h - l) / 2:.3f}" for h, l in zip(cat11_ci_high, cat11_ci_low)],
        "Total_Scope3_tCO2e": total_mean,
    })

    summary = {
        "total_scope3_tCO2e": float(total_mean.sum()),
        "records": n_records,
        "generated_at": datetime.utcnow().isoformat(),
        "engine_version": "6.2",
    }
    return result_df, summary

# =====================================================
# PDF EXTRACTOR
# =====================================================

try:
    import fitz
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    from anthropic import Anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

class PDFExtractor:
    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.client = Anthropic(api_key=self.api_key) if (HAS_ANTHROPIC and self.api_key) else None

    def is_available(self) -> bool:
        return bool(self.client and HAS_FITZ)

    def extract_from_bytes(self, pdf_bytes: bytes) -> pd.DataFrame:
        if not self.is_available():
            return pd.DataFrame()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        results = []
        for page_num in range(len(doc)):
            try:
                page = doc[page_num]
                pix = page.get_pixmap(dpi=150)
                img_b64 = base64.b64encode(pix.tobytes("png")).decode()
                response = self.client.messages.create(
                    model="claude-sonnet-4-5-20250929", max_tokens=2000,
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                        {"type": "text", "text": 'Extract numeric data from this field ticket. Return ONLY JSON. Keys: date, diesel_l, diesel_gal, water_bbl, water_m3, oil_bbl, gas_mcf, distance_km, vendor. Omit missing fields. Example: {"diesel_l": 2500, "water_bbl": 150}'}
                    ]}]
                )
                text = response.content[0].text.strip()
                start, end = text.find("{"), text.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(text[start:end])
                    data["source"] = f"PDF_page_{page_num + 1}"
                    results.append(data)
            except Exception as e:
                print(f"Page {page_num + 1} failed: {e}")
        doc.close()
        return pd.DataFrame(results) if results else pd.DataFrame()

_extractor = None
def get_pdf_extractor():
    global _extractor
    if _extractor is None:
        _extractor = PDFExtractor()
    return _extractor

# =====================================================
# FASTAPI APP
# =====================================================

MAX_FILE_SIZE = 50 * 1024 * 1024

app = FastAPI(title="ScopeChain AI Engine", version="6.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.get("/api")
@app.get("/api/")
async def health():
    extractor = get_pdf_extractor()
    return {
        "status": "ok",
        "engine_version": "6.2",
        "architecture": "vercel-serverless",
        "features": {
            "pdf_parsing": extractor.is_available(),
            "csv_processing": True,
            "monte_carlo_uncertainty": True,
            "hierarchical_factors": True,
        },
    }

@app.get("/api/factors")
async def list_factors():
    registry = get_factor_registry()
    return {
        "version": registry.get_version(),
        "factors": registry.list_available_factors(),
        "metadata": registry.metadata,
    }

@app.get("/api/version")
async def version_info():
    registry = get_factor_registry()
    return {
        "api_version": "6.2",
        "architecture": "vercel-serverless",
        "factor_database_version": registry.get_version(),
    }

@app.post("/api/calculate")
async def calculate_scope3(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "No files uploaded")

    extractor = get_pdf_extractor()
    calc_frames = []

    for upload in files:
        filename = (upload.filename or "").lower()
        content = await upload.read()

        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(413, f"File exceeds 50MB limit")

        if filename.endswith(".csv"):
            try:
                df_raw = pd.read_csv(io.BytesIO(content))
            except Exception as e:
                print(f"CSV parse error: {e}")
                continue
        elif filename.endswith(".pdf"):
            if not extractor.is_available():
                raise HTTPException(503, "PDF extraction unavailable - set ANTHROPIC_API_KEY")
            df_raw = extractor.extract_from_bytes(content)
            if df_raw.empty:
                continue
        else:
            continue

        df_norm = normalize_units(df_raw)

        n_rows = len(df_norm)
        mc_samples = 200 if n_rows > 50000 else 500 if n_rows > 10000 else 1000

        df_calc, _ = calculate_scope3_with_uncertainty(df_norm, mc_samples=mc_samples)
        calc_frames.append(df_calc)

    if not calc_frames:
        raise HTTPException(400, "No valid data extracted from any file")

    calc_df = pd.concat(calc_frames, ignore_index=True)
    total_emissions = float(calc_df["Total_Scope3_tCO2e"].sum())

    categories = {
        f"Cat{i}": CategorySummary(total_tCO2e=float(calc_df[f"Cat{i}_tCO2e"].sum()))
        for i in [1, 4, 11]
    }

    summary = CalculationSummary(
        total_scope3_tCO2e=total_emissions,
        records=len(calc_df),
        categories=categories,
        engine_version="6.2",
    )

    normalized_data = [
        CalculationRow(**row) for row in calc_df.to_dict(orient="records")
    ]

    return CalculationResponse(summary=summary, normalized_data=normalized_data)

@app.post("/api/calculate-single")
async def calculate_single_record(
    water_m3: float = 0.0, diesel_l: float = 0.0,
    oil_bbl: float = 0.0, gas_mcf: float = 0.0,
    haul_distance_km: float = 80.0,
):
    df = pd.DataFrame([{
        "water_m3_norm": water_m3, "diesel_l_norm": diesel_l,
        "oil_bbl_norm": oil_bbl, "gas_mcf_norm": gas_mcf,
        "haul_distance_km": haul_distance_km,
    }])
    result_df, summary = calculate_scope3_with_uncertainty(df)
    return {
        "total_tCO2e": float(result_df["Total_Scope3_tCO2e"].iloc[0]),
        "cat1_diesel": float(result_df["Cat1_tCO2e"].iloc[0]),
        "cat4_water_hauling": float(result_df["Cat4_tCO2e"].iloc[0]),
        "cat11_sold_products": float(result_df["Cat11_tCO2e"].iloc[0]),
    }
