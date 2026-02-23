"""
ScopeChain AI FastAPI Backend - Vercel Serverless Entry Point
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from mangum import Mangum
import pandas as pd
import io

from engine.normalizer import normalize_units, validate_normalized_data
from engine.calculator import calculate_scope3_with_uncertainty, validate_input_data
from extractors.pdf_extractor import get_pdf_extractor
from config.schemas import CalculationResponse, CalculationSummary, CategorySummary

MAX_FILE_SIZE = 50 * 1024 * 1024

app = FastAPI(
    title="ScopeChain AI Engine",
    version="6.2",
    description="Enterprise Scope 3 emissions calculation API"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    from engine.factors import get_factor_registry
    registry = get_factor_registry()
    return {
        "version": registry.get_version(),
        "factors": registry.list_available_factors(),
        "metadata": registry.metadata,
    }


@app.get("/api/version")
async def version_info():
    from engine.factors import get_factor_registry
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
    raw_frames = []

    for upload in files:
        filename = (upload.filename or "").lower()
        content = await upload.read()

        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                413,
                f"File '{upload.filename}' exceeds 50MB limit ({len(content) / 1024 / 1024:.1f}MB)"
            )

        if filename.endswith(".csv"):
            try:
                chunk_size = 10000
                chunks = pd.read_csv(io.BytesIO(content), chunksize=chunk_size)
                df_raw = pd.concat(chunks, ignore_index=True)
            except Exception as e:
                print(f"Failed to parse CSV {upload.filename}: {e}")
                continue

        elif filename.endswith(".pdf"):
            if not extractor.is_available():
                raise HTTPException(
                    503,
                    "PDF extraction unavailable - ANTHROPIC_API_KEY not configured"
                )
            df_raw = extractor.extract_from_bytes(content)
            if df_raw.empty:
                continue
        else:
            continue

        raw_frames.append(df_raw)
        df_norm = normalize_units(df_raw)

        try:
            validation = validate_normalized_data(df_norm)
            if isinstance(validation, dict) and not validation.get("passed", True):
                print(f"Data quality warning: {validation}")
        except Exception as e:
            print(f"Validation failed: {e}")

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

    from config.schemas import CalculationRow
    normalized_data = [
        CalculationRow(**row)
        for row in calc_df.to_dict(orient="records")
    ]

    return CalculationResponse(summary=summary, normalized_data=normalized_data)


@app.post("/api/calculate-single")
async def calculate_single_record(
    water_m3: float = 0.0,
    diesel_l: float = 0.0,
    oil_bbl: float = 0.0,
    gas_mcf: float = 0.0,
    haul_distance_km: float = 80.0,
):
    from engine.calculator import calculate_emissions_for_single_record
    return calculate_emissions_for_single_record(
        water_m3=water_m3, diesel_l=diesel_l,
        oil_bbl=oil_bbl, gas_mcf=gas_mcf,
        haul_distance_km=haul_distance_km,
    )


handler = Mangum(app)
