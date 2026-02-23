"""
Emission Factor Registry and Resolution Logic.
Loads factors from external JSON and resolves hierarchically.
"""
import json
import os
from pathlib import Path
from typing import Dict, Optional
import numpy as np


class EmissionFactor:
    """
    Represents a single emission factor with uncertainty.
    Supports Monte Carlo sampling for uncertainty propagation.
    """
    
    def __init__(
        self,
        value: float,
        uncertainty_pct: float = 10.0,
        source: str = "default",
        version: str = "v1",
        notes: str = ""
    ):
        self.value = value
        self.uncertainty_pct = uncertainty_pct
        self.source = source
        self.version = version
        self.notes = notes
    
    def sample(self, n: int = 1000) -> np.ndarray:
        """
        Generate Monte Carlo samples using normal distribution.
        Clipped at zero to prevent negative emissions.
        
        Args:
            n: Number of samples to generate
            
        Returns:
            Array of sampled emission factor values
        """
        std = self.value * (self.uncertainty_pct / 100)
        samples = np.random.normal(self.value, std, n)
        return np.clip(samples, 0, None)
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for audit trails."""
        return {
            "value": self.value,
            "uncertainty_pct": self.uncertainty_pct,
            "source": self.source,
            "version": self.version,
            "notes": self.notes
        }
    
    def __repr__(self):
        return f"EmissionFactor({self.value} ±{self.uncertainty_pct}% tCO2e, source={self.source})"


class FactorRegistry:
    """
    Centralized registry for all emission factors.
    Loads from external JSON and provides hierarchical resolution.
    """
    
    def __init__(self, factors_path: Optional[str] = None):
        """
        Initialize registry from JSON file.
        
        Args:
            factors_path: Path to factors.json (defaults to config/factors.json)
        """
        if factors_path is None:
            # Default to config/factors.json relative to this file
            config_dir = Path(__file__).parent.parent / "config"
            factors_path = config_dir / "factors.json"
        
        self.factors_path = Path(factors_path)
        self.registry: Dict[str, Dict[str, EmissionFactor]] = {}
        self.metadata: dict = {}
        self._load_factors()
    
    def _load_factors(self):
        """Load and parse factors from JSON file."""
        if not self.factors_path.exists():
            raise FileNotFoundError(
                f"Factors file not found: {self.factors_path}\n"
                f"Expected location: {self.factors_path.absolute()}"
            )
        
        with open(self.factors_path, 'r') as f:
            data = json.load(f)
        
        self.metadata = data.get("metadata", {})
        factors_data = data.get("factors", {})
        
        # Parse each factor category
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
    
    def resolve_factor(self, key: str, hierarchy: Dict[str, str]) -> EmissionFactor:
        """
        Resolve emission factor using hierarchical lookup.
        
        Resolution order (from highest to lowest priority):
        1. company (e.g., "company_suncor")
        2. supplier (e.g., "supplier_halliburton")
        3. region (e.g., "region_alberta")
        4. national (e.g., "national_canada")
        5. default (always exists as fallback)
        
        Args:
            key: Factor key (e.g., "diesel_l_tco2e_per_l")
            hierarchy: Dict with optional keys: company, supplier, region, national
            
        Returns:
            EmissionFactor instance
            
        Raises:
            KeyError: If factor key doesn't exist
        """
        if key not in self.registry:
            raise KeyError(
                f"Unknown factor key: '{key}'\n"
                f"Available keys: {list(self.registry.keys())}"
            )
        
        factor_variants = self.registry[key]
        
        # Define resolution order
        resolution_order = ["company", "supplier", "region", "national", "default"]
        
        # Try each level in hierarchy
        for level in resolution_order:
            tag = hierarchy.get(level)
            if tag:
                # Construct variant name (e.g., "region_alberta")
                variant_key = f"{level}_{tag}"
                if variant_key in factor_variants:
                    return factor_variants[variant_key]
        
        # Fallback to default (always exists)
        if "default" not in factor_variants:
            raise ValueError(f"No default factor found for '{key}'")
        
        return factor_variants["default"]
    
    def get_all_factors_for_hierarchy(
        self,
        hierarchy: Dict[str, str]
    ) -> Dict[str, EmissionFactor]:
        """
        Resolve all factors in the registry for a given hierarchy.
        
        Args:
            hierarchy: Factor resolution hierarchy
            
        Returns:
            Dict mapping factor keys to resolved EmissionFactor instances
        """
        return {
            key: self.resolve_factor(key, hierarchy)
            for key in self.registry.keys()
        }
    
    def list_available_factors(self) -> Dict[str, list]:
        """List all available factors and their variants."""
        return {
            key: list(variants.keys())
            for key, variants in self.registry.items()
        }
    
    def reload(self):
        """Reload factors from JSON file (useful for hot-reloading config)."""
        self.registry.clear()
        self._load_factors()
    
    def get_version(self) -> str:
        """Get the version of the loaded factor database."""
        return self.metadata.get("version", "unknown")
    
    def __repr__(self):
        return (
            f"FactorRegistry(version={self.get_version()}, "
            f"factors={len(self.registry)}, "
            f"path={self.factors_path})"
        )


# =========================================================
# GLOBAL REGISTRY INSTANCE (SINGLETON PATTERN)
# =========================================================

_global_registry: Optional[FactorRegistry] = None


def get_factor_registry(factors_path: Optional[str] = None) -> FactorRegistry:
    """
    Get or create the global factor registry singleton.
    
    Args:
        factors_path: Optional custom path to factors.json
        
    Returns:
        FactorRegistry instance
    """
    global _global_registry
    
    if _global_registry is None:
        _global_registry = FactorRegistry(factors_path)
    
    return _global_registry


def reload_factors():
    """Reload factors from disk (useful for config updates without restart)."""
    global _global_registry
    if _global_registry is not None:
        _global_registry.reload()
