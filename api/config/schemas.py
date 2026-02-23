"""
Pydantic schemas for ScopeChain AI data validation.
Enforces strict contracts between data ingestion and calculation.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# =========================================================
# INPUT VALIDATION SCHEMAS
# =========================================================

class NormalizedRecord(BaseModel):
    """Validated operational record after unit normalization."""
    
    # Normalized quantities (always in standard units)
    water_m3_norm: float = Field(default=0.0, ge=0, description="Water volume in cubic meters")
    diesel_l_norm: float = Field(default=0.0, ge=0, description="Diesel volume in liters")
    oil_bbl_norm: float = Field(default=0.0, ge=0, description="Oil volume in barrels")
    gas_mcf_norm: float = Field(default=0.0, ge=0, description="Gas volume in thousand cubic feet")
    
    # Optional metadata
    haul_distance_km: Optional[float] = Field(default=80.0, ge=0, description="Trucking distance in km")
    date: Optional[str] = Field(default=None, description="Operation date (YYYY-MM-DD)")
    vendor: Optional[str] = Field(default=None, description="Supplier/vendor name")
    location: Optional[str] = Field(default=None, description="Well pad or site location")
    
    # Source tracking
    source: Optional[str] = Field(default="unknown", description="Data source (e.g., 'PDF_page_1', 'CSV_row_42')")
    
    model_config = {"extra": "allow"}


class EmissionResult(BaseModel):
    """Single category emission calculation result."""
    
    tCO2e_mean: float = Field(description="Mean emission value (tonnes CO2e)")
    tCO2e_std: float = Field(default=0.0, description="Standard deviation")
    ci_95_low: float = Field(default=0.0, description="95% confidence interval lower bound")
    ci_95_high: float = Field(default=0.0, description="95% confidence interval upper bound")
    factor_source: str = Field(description="Emission factor source reference")
    confidence: float = Field(ge=0.0, le=1.0, description="Data quality confidence (0-1)")


class CalculationRow(BaseModel):
    """Complete calculation result for a single operational record."""
    
    record_id: int
    Cat1_tCO2e: float = Field(default=0.0, description="Category 1: Purchased Goods")
    Cat1_ci_95: str = Field(default="±0.000", description="Category 1 uncertainty")
    Cat4_tCO2e: float = Field(default=0.0, description="Category 4: Upstream Transportation")
    Cat4_ci_95: str = Field(default="±0.000", description="Category 4 uncertainty")
    Cat11_tCO2e: float = Field(default=0.0, description="Category 11: Use of Sold Products")
    Cat11_ci_95: str = Field(default="±0.000", description="Category 11 uncertainty")
    Total_Scope3_tCO2e: float = Field(description="Total Scope 3 emissions")


# =========================================================
# HIERARCHY CONFIGURATION
# =========================================================

class HierarchyLevel(str, Enum):
    """Available hierarchy levels for factor resolution."""
    COMPANY = "company"
    SUPPLIER = "supplier"
    REGION = "region"
    NATIONAL = "national"
    DEFAULT = "default"


class FactorHierarchy(BaseModel):
    """Defines the factor resolution hierarchy for a calculation."""
    
    company: Optional[str] = Field(default=None, description="Company-specific factor tag (e.g., 'suncor')")
    supplier: Optional[str] = Field(default=None, description="Supplier-specific factor tag (e.g., 'halliburton')")
    region: Optional[str] = Field(default=None, description="Regional factor tag (e.g., 'alberta')")
    national: Optional[str] = Field(default=None, description="National factor tag (e.g., 'canada')")
    
    model_config = {"extra": "allow"}


# =========================================================
# API REQUEST/RESPONSE SCHEMAS
# =========================================================

class CalculationRequest(BaseModel):
    """Request payload for /api/calculate endpoint."""
    
    files: List[str] = Field(description="List of uploaded file names")
    hierarchy: Optional[FactorHierarchy] = Field(default=None, description="Factor resolution hierarchy")
    mc_samples: int = Field(default=1000, ge=100, le=10000, description="Monte Carlo sample size")


class CategorySummary(BaseModel):
    """Summary for a single Scope 3 category."""
    total_tCO2e: float


class CalculationSummary(BaseModel):
    """High-level summary of calculation results."""
    
    total_scope3_tCO2e: float
    records: int
    categories: Dict[str, CategorySummary]
    engine_version: str
    generated_at: Optional[str] = None


class CalculationResponse(BaseModel):
    """Response payload for /api/calculate endpoint."""
    
    summary: CalculationSummary
    normalized_data: List[CalculationRow]


# =========================================================
# AUDIT TRAIL SCHEMAS
# =========================================================

class AuditTrail(BaseModel):
    """Complete audit trail for compliance reporting."""
    
    report_id: str
    generated_at: str
    engine_version: str
    total_scope3_tCO2e: float
    records_processed: int
    raw_data_sample: List[Dict[str, Any]]
    normalized_data: List[CalculationRow]
    summary_by_category: Dict[str, CategorySummary]
    methodology: str = "GHG Protocol Corporate Value Chain (Scope 3) Standard"
    uncertainty_model: str = "Monte Carlo simulation (95% CI)"
    factor_sources: str
    input_files: List[str]
    processing_steps: List[str]
    warnings: List[str] = Field(default_factory=list)
