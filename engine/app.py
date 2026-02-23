# =========================================================
# ScopeChain AI — v6.2 ENTERPRISE SCOPE 3 ENGINE (API)
# Single-pass normalization • Uncertainty-aware • CSV + PDF
# FastAPI backend for dashboard
# =========================================================
import os
import json
import base64
import io
import re
from datetime import datetime
from typing import Dict, List, Any, Tuple

import numpy as np
import pandas as pd
import fitz
import anthropic

# =========================================================
# 0. ANTHROPIC CLIENT — FIXED ONCE, AFTER IMPORT
# =========================================================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# =========================================================
# 1. EMISSION FACTORS + UNCERTAINTY
# =========================================================

class EmissionFactor:
    def __init__(self, value: float,
                 uncertainty_pct: float = 10.0,
                 source: str = "default",
                 version: str = "v1"):
        self.value = value
        self.uncertainty_pct = uncertainty_pct  # ± %
        self.source = source
        self.version = version

    def sample(self, n: int = 1000) -> np.ndarray:
        """Monte Carlo sampling (normal, clipped at 0)."""
        std = self.value * (self.uncertainty_pct / 100)
        samples = np.random.normal(self.value, std, n)
        return np.clip(samples, 0, None)

# Hierarchical registry – you can extend with company/supplier later
FACTOR_REGISTRY: Dict[str, Dict[str, EmissionFactor]] = {
    "diesel_l_tco2e_per_l": {
        "default": EmissionFactor(0.0027, 15, "GHG Protocol", "2023"),
    },
    "oil_bbl_tco2e": {
        "default": EmissionFactor(0.430, 18, "GHG Protocol", "2023"),
    },
    "gas_mcf_tco2e": {
        "default": EmissionFactor(0.056, 20, "GHG Protocol", "2023"),
    },
    "water_trucking_tco2e_per_tonne_km": {
        "default": EmissionFactor(0.00020, 25, "ICCT Truck Study", "2024"),
    },
}

def resolve_factor(key: str, hierarchy: Dict[str, str]) -> EmissionFactor:
    """Resolve factor using simple hierarchy: company → supplier → region → national → default."""
    entry = FACTOR_REGISTRY[key]
    levels = ["company", "supplier", "region", "national", "default"]
    for level in levels:
        tag = hierarchy.get(level)
        if tag and tag in entry:
            return entry[tag]
    return entry["default"]

# =========================================================
# 2. CATEGORIES WITH UNCERTAINTY
# =========================================================

class Scope3Category:
    def __init__(self, cat_id: int, name: str, ghg_boundary: str):
        self.cat_id = cat_id
        self.name = name
        self.ghg_boundary = ghg_boundary

    def calculate(self, row: pd.Series,
                  factors: Dict[str, EmissionFactor],
                  mc_samples: int = 1000) -> Dict[str, Any]:
        raise NotImplementedError

class Cat1_Diesel(Scope3Category):
    def __init__(self):
        super().__init__(1, "Purchased Goods - Diesel", "Well-to-wheel combustion")

    def calculate(self, row, factors, mc_samples=1000):
        diesel_l = row.get("diesel_l_norm", 0) or 0
        if diesel_l <= 0:
            return {"tCO2e_mean": 0.0, "tCO2e_std": 0.0,
                    "ci_95_low": 0.0, "ci_95_high": 0.0,
                    "factor_source": factors["diesel_l_tco2e_per_l"].source,
                    "confidence": 0.0}
        factor = factors["diesel_l_tco2e_per_l"]
        emissions = diesel_l * factor.sample(mc_samples)
        return {
            "tCO2e_mean": float(emissions.mean()),
            "tCO2e_std": float(emissions.std()),
            "ci_95_low": float(np.percentile(emissions, 2.5)),
            "ci_95_high": float(np.percentile(emissions, 97.5)),
            "factor_source": factor.source,
            "confidence": 1.0,
        }

class Cat4_WaterHauling(Scope3Category):
    def __init__(self):
        super().__init__(4, "Upstream Transportation - Water", "Third-party trucking")

    def calculate(self, row, factors, mc_samples=1000):
        water_m3 = row.get("water_m3_norm", 0) or 0
        if water_m3 <= 0:
            return {"tCO2e_mean": 0.0, "tCO2e_std": 0.0,
                    "ci_95_low": 0.0, "ci_95_high": 0.0,
                    "factor_source": factors["water_trucking_tco2e_per_tonne_km"].source,
                    "confidence": 0.0}
        tonnes = water_m3 * 1.0
        distance_km = row.get("haul_distance_km", 80) or 80
        factor = factors["water_trucking_tco2e_per_tonne_km"]
        emissions = tonnes * distance_km * factor.sample(mc_samples)
        return {
            "tCO2e_mean": float(emissions.mean()),
            "tCO2e_std": float(emissions.std()),
            "ci_95_low": float(np.percentile(emissions, 2.5)),
            "ci_95_high": float(np.percentile(emissions, 97.5)),
            "factor_source": factor.source,
            "confidence": 0.9,
        }

class Cat11_SoldProducts(Scope3Category):
    def __init__(self):
        super().__init__(11, "Use of Sold Products", "End-use combustion")

    def calculate(self, row, factors, mc_samples=1000):
        oil_bbl = row.get("oil_bbl_norm", 0) or 0
        gas_mcf = row.get("gas_mcf_norm", 0) or 0
        if oil_bbl <= 0 and gas_mcf <= 0:
            return {"tCO2e_mean": 0.0, "tCO2e_std": 0.0,
                    "ci_95_low": 0.0, "ci_95_high": 0.0,
                    "factor_source": "GHG Protocol",
                    "confidence": 0.0}
        oil_em = oil_bbl * factors["oil_bbl_tco2e"].sample(mc_samples)
        gas_em = gas_mcf * factors["gas_mcf_tco2e"].sample(mc_samples)
        total = oil_em + gas_em
        return {
            "tCO2e_mean": float(total.mean()),
            "tCO2e_std": float(total.std()),
            "ci_95_low": float(np.percentile(total, 2.5)),
            "ci_95_high": float(np.percentile(total, 97.5)),
            "factor_source": "GHG Protocol",
            "confidence": 0.95,
        }

CATEGORIES = {
    1: Cat1_Diesel(),
    4: Cat4_WaterHauling(),
    11: Cat11_SoldProducts(),
}

# =========================================================
# 3. UNIT NORMALIZER (SINGLE PASS)
# =========================================================

M3_PER_BBL = 0.1589873
L_PER_GAL = 3.78541

def normalize_units(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # standardize column names
    df.columns = [str(c).lower().strip() for c in df.columns]

    # numeric extractor
    def extract_number(x):
        if pd.isna(x):
            return 0
        s = str(x).replace(",", "")
        m = re.findall(r"-?\d+\.?\d*", s)
        return float(m[0]) if m else 0

    # initialize normalized columns
    df["water_m3_norm"] = 0
    df["diesel_l_norm"] = 0
    df["oil_bbl_norm"] = 0
    df["gas_mcf_norm"] = 0

    for col in df.columns:
        col_lower = col.lower()
        num = df[col].apply(extract_number)

        # WATER (m3 or bbl → convert)
        if any(w in col_lower for w in ["water", "h2o", "h₂o"]):
            if "m3" in col_lower or "m³" in col_lower:
                df["water_m3_norm"] = num
            else:
                # assume bbl → convert to m3
                df["water_m3_norm"] = num * 0.1589873

        # DIESEL / FUEL
        elif any(w in col_lower for w in ["diesel", "fuel"]):
            df["diesel_l_norm"] = num

        # OIL
        elif any(w in col_lower for w in ["oil", "bbl"]):
            df["oil_bbl_norm"] = num

        # GAS
        elif any(w in col_lower for w in ["gas", "mcf"]):
            df["gas_mcf_norm"] = num

    return df

# =========================================================
# 4. MASTER CALC ENGINE (ASSUMES ALREADY NORMALIZED)
# =========================================================

def calculate_scope3_with_uncertainty(
    df_norm: pd.DataFrame,
    hierarchy: Dict[str, str] = None,
    mc_samples: int = 1000,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    hierarchy = hierarchy or {}
    results: List[Dict[str, Any]] = []

    for _, row in df_norm.iterrows():
        row_result: Dict[str, Any] = {"record_id": len(results)}
        total_emissions: List[float] = []

        # Resolve all factors ONCE per row
        factor_keys = [
            "diesel_l_tco2e_per_l",
            "water_trucking_tco2e_per_tonne_km",
            "oil_bbl_tco2e",
            "gas_mcf_tco2e",
        ]
        factors = {k: resolve_factor(k, hierarchy) for k in factor_keys}

        for cat_id, category in CATEGORIES.items():
            calc = category.calculate(row, factors, mc_samples)
            mean = calc["tCO2e_mean"]
            row_result[f"Cat{cat_id}_tCO2e"] = mean
            row_result[f"Cat{cat_id}_ci_95"] = f"±{(calc['ci_95_high'] - calc['ci_95_low'])/2:.3f}"
            total_emissions.append(mean)

        row_result["Total_Scope3_tCO2e"] = float(sum(total_emissions))
        results.append(row_result)

    result_df = pd.DataFrame(results)
    summary = {
        "total_scope3_tCO2e": float(result_df["Total_Scope3_tCO2e"].sum()),
        "records": int(len(result_df)),
        "generated_at": datetime.utcnow().isoformat(),
        "engine_version": "6.2",
        "uncertainty_model": "Monte Carlo (95% CI)",
        "categories": {
            f"Cat{i}": {
                "total": float(result_df.get(f"Cat{i}_tCO2e", pd.Series([0.0])).sum())
            } for i in [1, 4, 11]
        },
    }
    return result_df, summary

# =========================================================
# 5. PDF → DATAFRAME VIA CLAUDE (NO STREAMLIT)
# =========================================================

def parse_pdf_to_df_enhanced(pdf_bytes: bytes) -> pd.DataFrame:
    if not client:
        # No Anthropic key → behave like old app (show warning there, here just skip)
        print("❗ Anthropic client not available — PDF extraction disabled.")
        return pd.DataFrame()

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    rows = []

    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=300)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()

        prompt = """
Extract numeric operational data from this ticket.
Return ONLY valid JSON.

Allowed keys:
- date
- diesel_l
- water_bbl
- water_m3
- distance_km
- vendor

Extraction rules:
- Convert “L” or “litres” → diesel_l
- Convert “bbl / bbls” → water_bbl
- Convert “m3 / m³” → water_m3
- Convert “km” → distance_km
- If value exists, return it; if not, omit the field.
- NEVER add commentary. Return ONLY JSON.
"""

        try:
            resp = client.messages.create(
                model="claude-sonnet-4-5-20250929",  # same as your working app
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type":"image",
                         "source":{"type":"base64","media_type":"image/png","data":img_b64}},
                        {"type":"text","text":prompt}
                    ]
                }]
            )

            text = resp.content[0].text.strip()
            start = text.find("{"); end = text.rfind("}") + 1

            if start != -1 and end > start:
                data = json.loads(text[start:end])
                data["source"] = f"PDF_page_{i+1}"
                rows.append(data)

        except Exception as e:
            print(f"⚠️ Failed to parse page {i+1}: {str(e)[:100]}")

    return pd.DataFrame(rows) if rows else pd.DataFrame()

# =========================================================
# 6. AUDIT JSON (OPTIONAL, NOT USED BY DASHBOARD YET)
# =========================================================

def generate_audit_json(
    df_raw: pd.DataFrame,
    df_calc: pd.DataFrame,
    summary: Dict[str, Any],
    input_files: List[str],
) -> dict:
    return {
        "report_id": f"SCOPE3-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
        "generated_at": datetime.utcnow().isoformat(),
        "engine_version": "6.2",
        "total_scope3_tCO2e": round(summary["total_scope3_tCO2e"], 3),
        "records_processed": int(len(df_calc)),
        "raw_data_sample": df_raw.head(5).to_dict(orient="records"),
        "normalized_data": df_calc.to_dict(orient="records"),
        "summary_by_category": summary["categories"],
        "methodology": "GHG Protocol Corporate Value Chain (Scope 3) Standard",
        "uncertainty_model": "Monte Carlo simulation (n=1000, 95% CI)",
        "factor_sources": "Hierarchical: Company > Supplier > Region > National > GHG Protocol",
        "audit_trail": {
            "input_files": input_files,
            "processing_steps": [
                "OCR/AI extraction (for PDFs)",
                "Unit normalization",
                "Monte Carlo calculation",
            ],
            "warnings": [],
        },
    }
