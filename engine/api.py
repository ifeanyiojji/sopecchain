"""
ScopeChain AI FastAPI Backend (v6.2 Refactored)
Uses modular engine architecture for enterprise-grade calculations.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from mangum import Mangum
import pandas as pd
import io

# Import modular components
from engine.normalizer import normalize_units, validate_normalized_data
from engine.calculator import calculate_scope3_with_uncertainty, validate_input_data
from extractors.pdf_extractor import get_pdf_extractor
from config.schemas import CalculationResponse, CalculationSummary, CategorySummary


# Maximum upload size: 50MB per file
MAX_FILE_SIZE = 50 * 1024 * 1024

app = FastAPI(
    title="ScopeChain AI Engine",
    version="6.2",
    description="Enterprise Scope 3 emissions calculation API"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def health():
    """Health check endpoint."""
    extractor = get_pdf_extractor()

    return {
        "status": "ok",
        "engine_version": "6.2",
        "architecture": "modular",
        "features": {
            "pdf_parsing": extractor.is_available(),
            "csv_processing": True,
            "monte_carlo_uncertainty": True,
            "hierarchical_factors": True,
        },
        "message": "ScopeChain AI backend running (refactored architecture)"
    }


@app.get("/api/factors")
async def list_factors():
    """List available emission factors and their sources."""
    from engine.factors import get_factor_registry

    registry = get_factor_registry()

    return {
        "version": registry.get_version(),
        "factors": registry.list_available_factors(),
        "metadata": registry.metadata,
    }


@app.post("/api/calculate")
async def calculate_scope3(files: List[UploadFile] = File(...)):
    """
    Calculate Scope 3 emissions from uploaded CSV or PDF files.

    Supports large datasets via chunked CSV processing and vectorized
    NumPy calculations. File size limit: 50MB per file.
    """
    if not files:
        raise HTTPException(400, "No files uploaded")

    # Get PDF extractor
    extractor = get_pdf_extractor()

    calc_frames = []
    raw_frames = []
    input_filenames = []

    for upload in files:
        filename = (upload.filename or "").lower()
        content = await upload.read()
        input_filenames.append(upload.filename or "unknown")

        # Validate file size
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                413,
                f"File '{upload.filename}' exceeds 50MB limit ({len(content) / 1024 / 1024:.1f}MB)"
            )

        # Load data based on file type
        if filename.endswith(".csv"):
            try:
                # Use chunked reading for large CSVs to avoid memory spikes
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
                    "PDF extraction unavailable - Anthropic API key not configured"
                )

            df_raw = extractor.extract_from_bytes(content)

            if df_raw.empty:
                print(f"No data extracted from PDF: {upload.filename}")
                continue

        else:
            print(f"Unsupported file type: {filename}")
            continue

        # Store raw data for audit trail
        raw_frames.append(df_raw)

        # Normalize units
        df_norm = normalize_units(df_raw)

        # Validate normalized data
        try:
            validation = validate_normalized_data(df_norm)
            if isinstance(validation, dict) and not validation.get("passed", True):
                print(f"Data quality warning for {upload.filename}: {validation}")
        except Exception as e:
            print(f"Validation check failed for {upload.filename}: {e}")

        # Scale Monte Carlo samples based on dataset size to balance
        # accuracy vs speed for large datasets
        n_rows = len(df_norm)
        if n_rows > 50000:
            mc_samples = 200
        elif n_rows > 10000:
            mc_samples = 500
        else:
            mc_samples = 1000

        # Calculate emissions (vectorized - handles large datasets efficiently)
        df_calc, _ = calculate_scope3_with_uncertainty(df_norm, mc_samples=mc_samples)
        calc_frames.append(df_calc)

    # Combine all results
    if not calc_frames:
        raise HTTPException(400, "No valid data extracted from any file")

    calc_df = pd.concat(calc_frames, ignore_index=True)
    raw_df = pd.concat(raw_frames, ignore_index=True) if raw_frames else pd.DataFrame()

    # Calculate summary statistics
    total_emissions = float(calc_df["Total_Scope3_tCO2e"].sum())

    categories = {
        f"Cat{i}": CategorySummary(
            total_tCO2e=float(calc_df[f"Cat{i}_tCO2e"].sum())
        )
        for i in [1, 4, 11]
    }

    summary = CalculationSummary(
        total_scope3_tCO2e=total_emissions,
        records=len(calc_df),
        categories=categories,
        engine_version="6.2",
    )

    # Convert results to schema
    from config.schemas import CalculationRow
    normalized_data = [
        CalculationRow(**row)
        for row in calc_df.to_dict(orient="records")
    ]

    return CalculationResponse(
        summary=summary,
        normalized_data=normalized_data
    )


@app.post("/api/calculate-single")
async def calculate_single_record(
    water_m3: float = 0.0,
    diesel_l: float = 0.0,
    oil_bbl: float = 0.0,
    gas_mcf: float = 0.0,
    haul_distance_km: float = 80.0,
):
    """Calculate emissions for a single operational record."""
    from engine.calculator import calculate_emissions_for_single_record

    result = calculate_emissions_for_single_record(
        water_m3=water_m3,
        diesel_l=diesel_l,
        oil_bbl=oil_bbl,
        gas_mcf=gas_mcf,
        haul_distance_km=haul_distance_km,
    )

    return result


@app.post("/api/reload-factors")
async def reload_emission_factors():
    """Reload emission factors from config/factors.json."""
    from engine.factors import reload_factors

    try:
        reload_factors()
        return {
            "status": "success",
            "message": "Emission factors reloaded from config/factors.json"
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to reload factors: {str(e)}")


@app.get("/api/version")
async def version_info():
    """Get detailed version information."""
    from engine.factors import get_factor_registry

    registry = get_factor_registry()

    return {
        "api_version": "6.2",
        "architecture": "modular",
        "factor_database_version": registry.get_version(),
        "modules": {
            "engine.normalizer": "active",
            "engine.calculator": "active",
            "engine.factors": "active",
            "engine.categories": "active",
            "extractors.pdf_extractor": "active",
            "config.schemas": "active",
        }
    }


handler = Mangum(app)
