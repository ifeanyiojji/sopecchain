"""
Scope 3 Category Calculation Classes.
Implements GHG Protocol Category 1, 4, and 11 calculations with uncertainty.
"""
import numpy as np
import pandas as pd
from typing import Dict, Any
from engine.factors import EmissionFactor


class Scope3Category:
    """
    Base class for Scope 3 emission categories.
    Each category implements its own calculation logic.
    """
    
    def __init__(self, cat_id: int, name: str, ghg_boundary: str):
        """
        Initialize Scope 3 category.
        
        Args:
            cat_id: GHG Protocol category number (1-15)
            name: Category name
            ghg_boundary: Description of emission boundary
        """
        self.cat_id = cat_id
        self.name = name
        self.ghg_boundary = ghg_boundary
    
    def calculate(
        self,
        row: pd.Series,
        factors: Dict[str, EmissionFactor],
        mc_samples: int = 1000
    ) -> Dict[str, Any]:
        """
        Calculate emissions for this category.
        Must be implemented by subclasses.
        
        Args:
            row: Normalized operational record
            factors: Resolved emission factors for this calculation
            mc_samples: Number of Monte Carlo samples for uncertainty
            
        Returns:
            Dict with calculation results including uncertainty
        """
        raise NotImplementedError
    
    def _zero_result(self, factor: EmissionFactor) -> Dict[str, Any]:
        """Return a zero-emission result (used when no applicable data)."""
        return {
            "tCO2e_mean": 0.0,
            "tCO2e_std": 0.0,
            "ci_95_low": 0.0,
            "ci_95_high": 0.0,
            "factor_source": factor.source,
            "confidence": 0.0,
        }


class Cat1_Diesel(Scope3Category):
    """
    Category 1: Purchased Goods and Services - Diesel Fuel.
    
    Scope: Well-to-wheel combustion emissions from diesel consumption.
    Data required: diesel_l_norm (liters)
    """
    
    def __init__(self):
        super().__init__(
            cat_id=1,
            name="Purchased Goods - Diesel",
            ghg_boundary="Well-to-wheel combustion"
        )
    
    def calculate(
        self,
        row: pd.Series,
        factors: Dict[str, EmissionFactor],
        mc_samples: int = 1000
    ) -> Dict[str, Any]:
        """
        Calculate diesel combustion emissions.
        
        Formula: tCO2e = diesel_liters × emission_factor
        """
        diesel_l = row.get("diesel_l_norm", 0) or 0
        factor = factors["diesel_l_tco2e_per_l"]
        
        # No diesel consumed
        if diesel_l <= 0:
            return self._zero_result(factor)
        
        # Monte Carlo calculation
        emissions_samples = diesel_l * factor.sample(mc_samples)
        
        return {
            "tCO2e_mean": float(emissions_samples.mean()),
            "tCO2e_std": float(emissions_samples.std()),
            "ci_95_low": float(np.percentile(emissions_samples, 2.5)),
            "ci_95_high": float(np.percentile(emissions_samples, 97.5)),
            "factor_source": factor.source,
            "confidence": 1.0,  # High confidence - direct measurement
        }


class Cat4_WaterHauling(Scope3Category):
    """
    Category 4: Upstream Transportation and Distribution - Water Trucking.
    
    Scope: Third-party trucking emissions for water transport.
    Data required: water_m3_norm (cubic meters), haul_distance_km (optional, defaults to 80 km)
    """
    
    def __init__(self):
        super().__init__(
            cat_id=4,
            name="Upstream Transportation - Water",
            ghg_boundary="Third-party trucking"
        )
    
    def calculate(
        self,
        row: pd.Series,
        factors: Dict[str, EmissionFactor],
        mc_samples: int = 1000
    ) -> Dict[str, Any]:
        """
        Calculate water hauling emissions.
        
        Formula: tCO2e = (water_m3 × 1.0 tonnes/m³) × distance_km × emission_factor
        
        Notes:
        - Water density assumed = 1.0 tonne/m³
        - Default haul distance = 80 km (if not provided)
        """
        water_m3 = row.get("water_m3_norm", 0) or 0
        factor = factors["water_trucking_tco2e_per_tonne_km"]
        
        # No water transported
        if water_m3 <= 0:
            return self._zero_result(factor)
        
        # Convert to tonnes (water density = 1.0 tonne/m³)
        tonnes = water_m3 * 1.0
        
        # Get haul distance (default to 80 km if not specified)
        distance_km = row.get("haul_distance_km", 80) or 80
        
        # Monte Carlo calculation
        emissions_samples = tonnes * distance_km * factor.sample(mc_samples)
        
        # Confidence depends on whether distance was measured or estimated
        has_distance = pd.notna(row.get("haul_distance_km"))
        confidence = 0.9 if has_distance else 0.6
        
        return {
            "tCO2e_mean": float(emissions_samples.mean()),
            "tCO2e_std": float(emissions_samples.std()),
            "ci_95_low": float(np.percentile(emissions_samples, 2.5)),
            "ci_95_high": float(np.percentile(emissions_samples, 97.5)),
            "factor_source": factor.source,
            "confidence": confidence,
        }


class Cat11_SoldProducts(Scope3Category):
    """
    Category 11: Use of Sold Products.
    
    Scope: End-use combustion emissions from oil and gas products.
    Data required: oil_bbl_norm (barrels), gas_mcf_norm (thousand cubic feet)
    """
    
    def __init__(self):
        super().__init__(
            cat_id=11,
            name="Use of Sold Products",
            ghg_boundary="End-use combustion"
        )
    
    def calculate(
        self,
        row: pd.Series,
        factors: Dict[str, EmissionFactor],
        mc_samples: int = 1000
    ) -> Dict[str, Any]:
        """
        Calculate downstream combustion emissions from sold oil and gas.
        
        Formula: tCO2e = (oil_bbl × oil_factor) + (gas_mcf × gas_factor)
        """
        oil_bbl = row.get("oil_bbl_norm", 0) or 0
        gas_mcf = row.get("gas_mcf_norm", 0) or 0
        
        oil_factor = factors["oil_bbl_tco2e"]
        gas_factor = factors["gas_mcf_tco2e"]
        
        # No production
        if oil_bbl <= 0 and gas_mcf <= 0:
            return self._zero_result(oil_factor)
        
        # Monte Carlo calculation for each product type
        oil_emissions = oil_bbl * oil_factor.sample(mc_samples)
        gas_emissions = gas_mcf * gas_factor.sample(mc_samples)
        total_emissions = oil_emissions + gas_emissions
        
        return {
            "tCO2e_mean": float(total_emissions.mean()),
            "tCO2e_std": float(total_emissions.std()),
            "ci_95_low": float(np.percentile(total_emissions, 2.5)),
            "ci_95_high": float(np.percentile(total_emissions, 97.5)),
            "factor_source": "GHG Protocol",  # Both factors from same source
            "confidence": 0.95,  # High confidence - production data is reliable
        }


# =========================================================
# CATEGORY REGISTRY
# =========================================================

# All implemented categories
CATEGORIES = {
    1: Cat1_Diesel(),
    4: Cat4_WaterHauling(),
    11: Cat11_SoldProducts(),
}


def get_category(cat_id: int) -> Scope3Category:
    """
    Get category calculator by ID.
    
    Args:
        cat_id: GHG Protocol category number
        
    Returns:
        Scope3Category instance
        
    Raises:
        KeyError: If category not implemented
    """
    if cat_id not in CATEGORIES:
        raise KeyError(
            f"Category {cat_id} not implemented. "
            f"Available categories: {list(CATEGORIES.keys())}"
        )
    return CATEGORIES[cat_id]


def list_categories() -> Dict[int, str]:
    """List all implemented categories."""
    return {
        cat_id: category.name
        for cat_id, category in CATEGORIES.items()
    }
