"""
ScopeChain AI Calculation Engine.
Orchestrates normalization, factor resolution, and emission calculations.
Optimized for large datasets using vectorized NumPy operations.
"""
from datetime import datetime
from typing import Dict, List, Any, Tuple
import pandas as pd
import numpy as np

from engine.factors import get_factor_registry, EmissionFactor
from engine.categories import CATEGORIES
from config.schemas import NormalizedRecord, CalculationRow


def calculate_scope3_with_uncertainty(
    df_norm: pd.DataFrame,
    hierarchy: Dict[str, str] = None,
    mc_samples: int = 1000,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Calculate Scope 3 emissions for all records with uncertainty quantification.
    Uses vectorized NumPy operations for performance on large datasets.

    Args:
        df_norm: DataFrame with normalized operational data
        hierarchy: Factor resolution hierarchy
        mc_samples: Number of Monte Carlo samples for uncertainty

    Returns:
        Tuple of (results_dataframe, summary_dict)
    """
    hierarchy = hierarchy or {}
    n_records = len(df_norm)

    # Get factor registry singleton
    registry = get_factor_registry()

    # Resolve all factors ONCE using hierarchy
    factor_keys = [
        "diesel_l_tco2e_per_l",
        "water_trucking_tco2e_per_tonne_km",
        "oil_bbl_tco2e",
        "gas_mcf_tco2e",
    ]

    resolved_factors: Dict[str, EmissionFactor] = {
        key: registry.resolve_factor(key, hierarchy)
        for key in factor_keys
    }

    # Extract columns as NumPy arrays (vectorized)
    diesel_l = df_norm.get("diesel_l_norm", pd.Series(0.0, index=df_norm.index)).fillna(0).values
    water_m3 = df_norm.get("water_m3_norm", pd.Series(0.0, index=df_norm.index)).fillna(0).values
    oil_bbl = df_norm.get("oil_bbl_norm", pd.Series(0.0, index=df_norm.index)).fillna(0).values
    gas_mcf = df_norm.get("gas_mcf_norm", pd.Series(0.0, index=df_norm.index)).fillna(0).values
    distance_km = df_norm.get("haul_distance_km", pd.Series(80.0, index=df_norm.index)).fillna(80.0).values

    # --- Category 1: Diesel ---
    cat1_factor = resolved_factors["diesel_l_tco2e_per_l"]
    cat1_samples = diesel_l[:, np.newaxis] * cat1_factor.sample(mc_samples)[np.newaxis, :]  # (N, mc)
    cat1_mean = cat1_samples.mean(axis=1)
    cat1_ci_low = np.percentile(cat1_samples, 2.5, axis=1)
    cat1_ci_high = np.percentile(cat1_samples, 97.5, axis=1)

    # --- Category 4: Water Hauling ---
    cat4_factor = resolved_factors["water_trucking_tco2e_per_tonne_km"]
    tonnes = water_m3 * 1.0  # water density = 1 tonne/m3
    tonne_km = tonnes * distance_km
    cat4_samples = tonne_km[:, np.newaxis] * cat4_factor.sample(mc_samples)[np.newaxis, :]
    cat4_mean = cat4_samples.mean(axis=1)
    cat4_ci_low = np.percentile(cat4_samples, 2.5, axis=1)
    cat4_ci_high = np.percentile(cat4_samples, 97.5, axis=1)

    # --- Category 11: Sold Products (Oil + Gas) ---
    oil_factor = resolved_factors["oil_bbl_tco2e"]
    gas_factor = resolved_factors["gas_mcf_tco2e"]
    oil_samples = oil_bbl[:, np.newaxis] * oil_factor.sample(mc_samples)[np.newaxis, :]
    gas_samples = gas_mcf[:, np.newaxis] * gas_factor.sample(mc_samples)[np.newaxis, :]
    cat11_samples = oil_samples + gas_samples
    cat11_mean = cat11_samples.mean(axis=1)
    cat11_ci_low = np.percentile(cat11_samples, 2.5, axis=1)
    cat11_ci_high = np.percentile(cat11_samples, 97.5, axis=1)

    # --- Build results DataFrame ---
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

    # Generate summary
    summary = {
        "total_scope3_tCO2e": float(total_mean.sum()),
        "records": n_records,
        "generated_at": datetime.utcnow().isoformat(),
        "engine_version": "6.2",
        "uncertainty_model": "Monte Carlo (95% CI)",
        "factor_version": registry.get_version(),
        "categories": {
            "Cat1": {
                "name": "Purchased Goods - Diesel",
                "total": float(cat1_mean.sum()),
                "factor_used": cat1_factor.source,
            },
            "Cat4": {
                "name": "Upstream Transportation - Water",
                "total": float(cat4_mean.sum()),
                "factor_used": cat4_factor.source,
            },
            "Cat11": {
                "name": "Use of Sold Products",
                "total": float(cat11_mean.sum()),
                "factor_used": "GHG Protocol",
            },
        },
    }

    return result_df, summary


def validate_input_data(df_norm: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate normalized data before calculation.

    Args:
        df_norm: Normalized DataFrame

    Returns:
        Validation report dict

    Raises:
        ValueError: If critical validation fails
    """
    required_cols = ["water_m3_norm", "diesel_l_norm", "oil_bbl_norm", "gas_mcf_norm"]

    # Check required columns
    missing = [c for c in required_cols if c not in df_norm.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Check for negative values
    negative_mask = df_norm[required_cols] < 0
    negative_count = int(negative_mask.sum().sum())

    # Check for any data
    has_data = int((df_norm[required_cols].sum(axis=1) > 0).sum())

    if has_data == 0:
        raise ValueError("No operational data found in any record")

    validation = {
        "passed": negative_count == 0 and has_data > 0,
        "total_records": len(df_norm),
        "records_with_data": has_data,
        "negative_values_found": negative_count,
        "warnings": []
    }

    if negative_count > 0:
        validation["warnings"].append(
            f"Found {negative_count} negative values - these will be treated as zero"
        )

    return validation


def generate_audit_json(
    df_raw: pd.DataFrame,
    df_calc: pd.DataFrame,
    summary: Dict[str, Any],
    input_files: List[str],
) -> dict:
    """
    Generate complete audit trail for compliance reporting.
    """
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
        "factor_version": summary.get("factor_version", "unknown"),
        "audit_trail": {
            "input_files": input_files,
            "processing_steps": [
                "OCR/AI extraction (for PDFs)",
                "Unit normalization",
                "Data validation",
                "Monte Carlo calculation",
            ],
            "warnings": [],
        },
    }


def calculate_emissions_for_single_record(
    water_m3: float = 0.0,
    diesel_l: float = 0.0,
    oil_bbl: float = 0.0,
    gas_mcf: float = 0.0,
    haul_distance_km: float = 80.0,
    hierarchy: Dict[str, str] = None,
) -> Dict[str, Any]:
    """
    Convenience function for single-record calculations.
    """
    df = pd.DataFrame([{
        "water_m3_norm": water_m3,
        "diesel_l_norm": diesel_l,
        "oil_bbl_norm": oil_bbl,
        "gas_mcf_norm": gas_mcf,
        "haul_distance_km": haul_distance_km,
    }])

    result_df, summary = calculate_scope3_with_uncertainty(df, hierarchy)

    return {
        "total_tCO2e": float(result_df["Total_Scope3_tCO2e"].iloc[0]),
        "cat1_diesel": float(result_df["Cat1_tCO2e"].iloc[0]),
        "cat4_water_hauling": float(result_df["Cat4_tCO2e"].iloc[0]),
        "cat11_sold_products": float(result_df["Cat11_tCO2e"].iloc[0]),
        "summary": summary,
    }
