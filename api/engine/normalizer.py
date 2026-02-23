"""
Unit Normalization Module.
Converts messy operational data into standardized units for calculation.
"""
import re
import pandas as pd
from typing import Callable


# =========================================================
# UNIT CONVERSION CONSTANTS
# =========================================================

M3_PER_BBL = 0.1589873  # Cubic meters per barrel
L_PER_GAL = 3.78541     # Liters per gallon
L_PER_M3 = 1000.0       # Liters per cubic meter


# =========================================================
# NUMERIC EXTRACTION
# =========================================================

def extract_number(value) -> float:
    """
    Extract first numeric value from a string, handling common formatting.
    
    Examples:
        "1,234.56 L" → 1234.56
        "Total: $5,000" → 5000.0
        "N/A" → 0.0
    
    Args:
        value: Any value (str, int, float, or pd.NA)
        
    Returns:
        Extracted number or 0.0 if none found
    """
    if pd.isna(value):
        return 0.0
    
    # Already a number
    if isinstance(value, (int, float)):
        return float(value)
    
    # String processing
    s = str(value).replace(",", "")  # Remove thousand separators
    matches = re.findall(r"-?\d+\.?\d*", s)
    
    return float(matches[0]) if matches else 0.0


# =========================================================
# COLUMN PATTERN MATCHING
# =========================================================

def column_contains_any(column_name: str, keywords: list) -> bool:
    """
    Check if column name contains any of the given keywords (case-insensitive).
    
    Args:
        column_name: Column name to check
        keywords: List of keywords to search for
        
    Returns:
        True if any keyword is found
    """
    col_lower = column_name.lower().strip()
    return any(kw in col_lower for kw in keywords)


# =========================================================
# UNIT-SPECIFIC NORMALIZERS
# =========================================================

def normalize_water_column(df: pd.DataFrame, col: str, numeric_values: pd.Series) -> float:
    """
    Normalize water volume to cubic meters (m³).
    
    Conversion rules:
    - If column contains "m3" or "m³" → use as-is
    - Otherwise assume barrels (bbl) → convert to m³
    
    Args:
        df: Source DataFrame
        col: Column name
        numeric_values: Pre-extracted numeric values
        
    Returns:
        Water volume in m³
    """
    col_lower = col.lower()
    
    # Already in m³
    if "m3" in col_lower or "m³" in col_lower:
        return numeric_values
    
    # Assume barrels, convert to m³
    return numeric_values * M3_PER_BBL


def normalize_diesel_column(df: pd.DataFrame, col: str, numeric_values: pd.Series) -> float:
    """
    Normalize diesel/fuel volume to liters (L).
    
    Conversion rules:
    - If column contains "gal" or "gallon" → convert gallons to liters
    - Otherwise assume liters
    
    Args:
        df: Source DataFrame
        col: Column name
        numeric_values: Pre-extracted numeric values
        
    Returns:
        Diesel volume in liters
    """
    col_lower = col.lower()
    
    # Gallons → Liters
    if "gal" in col_lower or "gallon" in col_lower:
        return numeric_values * L_PER_GAL
    
    # Already in liters (or assume liters)
    return numeric_values


# =========================================================
# MASTER NORMALIZATION FUNCTION
# =========================================================

def normalize_units(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize all operational data columns to standard units.
    
    Standard units:
    - Water: cubic meters (m³)
    - Diesel/Fuel: liters (L)
    - Oil: barrels (bbl) [no conversion needed]
    - Gas: thousand cubic feet (MCF) [no conversion needed]
    
    This function:
    1. Standardizes column names (lowercase, stripped)
    2. Extracts numeric values from all columns
    3. Identifies data types by column name patterns
    4. Converts to standard units
    5. Aggregates multiple matches (e.g., "Diesel 1" + "Diesel 2")
    
    Args:
        df: Raw operational DataFrame
        
    Returns:
        DataFrame with additional normalized columns:
        - water_m3_norm
        - diesel_l_norm
        - oil_bbl_norm
        - gas_mcf_norm
    """
    df = df.copy()
    
    # Standardize column names
    df.columns = [str(c).lower().strip() for c in df.columns]
    
    # Initialize normalized columns
    df["water_m3_norm"] = 0.0
    df["diesel_l_norm"] = 0.0
    df["oil_bbl_norm"] = 0.0
    df["gas_mcf_norm"] = 0.0

    # Preserve haul_distance_km if not already present
    if "haul_distance_km" not in df.columns:
        df["haul_distance_km"] = 80.0
    
    # Process each column
    for col in df.columns:
        # Skip if already a normalized column
        if col.endswith("_norm"):
            continue
        
        # Extract numeric values
        numeric_values = df[col].apply(extract_number)
        
        # Skip if all zeros
        if numeric_values.sum() == 0:
            continue
        
        col_lower = col.lower()
        
        # WATER (h2o, water, h₂o)
        if column_contains_any(col, ["water", "h2o", "h₂o"]):
            water_m3 = normalize_water_column(df, col, numeric_values)
            df["water_m3_norm"] += water_m3
        
        # DIESEL / FUEL
        elif column_contains_any(col, ["diesel", "fuel"]):
            diesel_l = normalize_diesel_column(df, col, numeric_values)
            df["diesel_l_norm"] += diesel_l
        
        # OIL (already in bbl, no conversion needed)
        elif column_contains_any(col, ["oil", "crude", "bbl"]) and not column_contains_any(col, ["water"]):
            df["oil_bbl_norm"] += numeric_values
        
        # GAS (already in MCF, no conversion needed)
        elif column_contains_any(col, ["gas", "mcf", "natural gas"]):
            df["gas_mcf_norm"] += numeric_values

        # DISTANCE (haul distance)
        elif column_contains_any(col, ["distance", "haul", "km"]):
            df["haul_distance_km"] = numeric_values

    return df


# =========================================================
# VALIDATION HELPERS
# =========================================================

def validate_normalized_data(df: pd.DataFrame) -> dict:
    """
    Validate normalized data and return quality metrics.
    
    Returns:
        Dict with validation results:
        - records_total: Total number of records
        - records_with_data: Records with at least one non-zero value
        - zero_records: Records with all zeros
        - negative_values: Count of negative values (data quality issue)
    """
    required_cols = ["water_m3_norm", "diesel_l_norm", "oil_bbl_norm", "gas_mcf_norm"]
    
    # Check all required columns exist
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing normalized columns: {missing}")
    
    # Calculate metrics
    has_data = (df[required_cols].sum(axis=1) > 0).sum()
    total = len(df)
    
    # Check for negative values (data quality issue)
    negative_count = (df[required_cols] < 0).sum().sum()
    
    return {
        "records_total": total,
        "records_with_data": int(has_data),
        "zero_records": int(total - has_data),
        "negative_values": int(negative_count),
        "data_quality": "PASS" if negative_count == 0 else "FAIL"
    }


def add_normalization_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add metadata columns to track normalization quality.
    
    Adds:
    - has_water: Boolean flag
    - has_diesel: Boolean flag
    - has_production: Boolean flag (oil or gas)
    - record_completeness: Score 0-1 indicating data richness
    """
    df = df.copy()
    
    df["has_water"] = df["water_m3_norm"] > 0
    df["has_diesel"] = df["diesel_l_norm"] > 0
    df["has_production"] = (df["oil_bbl_norm"] > 0) | (df["gas_mcf_norm"] > 0)
    
    # Completeness score (how many data types present)
    df["record_completeness"] = (
        df["has_water"].astype(int) +
        df["has_diesel"].astype(int) +
        df["has_production"].astype(int)
    ) / 3.0
    
    return df
