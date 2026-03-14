# PATH: tests/unit/test_doc_contracts.py
"""
Doc-contract tests: Verify documentation matches code reality.

These tests prevent status-layer lies by detecting:
1. ONBOARDING_MATRIX adapter status contradicts file existence
2. Adapter registry claims don't match actual implementations
3. Documentation claims that can be programmatically verified

Added R28.1: Response to R28 ONBOARDING_MATRIX lies issue.
"""

import os
import re
import unittest
from pathlib import Path


class TestOnboardingMatrixAdapterConsistency(unittest.TestCase):
    """Verify ONBOARDING_MATRIX adapter statuses match code reality."""

    @classmethod
    def setUpClass(cls):
        """Load ONBOARDING_MATRIX content once."""
        matrix_path = Path(__file__).parents[2] / "docs" / "ONBOARDING_MATRIX.md"
        cls.matrix_content = matrix_path.read_text(encoding="utf-8")
        cls.adapters_dir = Path(__file__).parents[2] / "dex" / "adapters"

    def test_ve33_adapter_status_matches_file_existence(self):
        """ve33 adapter status in matrix must match file existence."""
        ve33_file = self.adapters_dir / "ve33.py"
        file_exists = ve33_file.exists()
        
        # Check if matrix says "NOT IMPLEMENTED"
        not_implemented_pattern = r"\|\s*`?ve33`?\s*\|[^|]*\|[^|]*\|\s*NOT\s+IMPLEMENTED\s*\|"
        claims_not_implemented = bool(re.search(not_implemented_pattern, self.matrix_content, re.IGNORECASE))
        
        # Contract: If file exists, matrix cannot say "NOT IMPLEMENTED"
        if file_exists:
            self.assertFalse(
                claims_not_implemented,
                f"ONBOARDING_MATRIX lies: ve33 adapter exists at {ve33_file} but matrix says 'NOT IMPLEMENTED'"
            )

    def test_uniswap_v3_adapter_status_matches_file_existence(self):
        """uniswap_v3 adapter must exist when claimed as PRODUCTION."""
        uniswap_file = self.adapters_dir / "uniswap_v3.py"
        file_exists = uniswap_file.exists()
        
        # Check if matrix claims PRODUCTION
        production_pattern = r"\|\s*`?uniswap_v3`?\s*\|[^|]*\|[^|]*\|\s*PRODUCTION\s*\|"
        claims_production = bool(re.search(production_pattern, self.matrix_content, re.IGNORECASE))
        
        # Contract: If matrix says PRODUCTION, file must exist
        if claims_production:
            self.assertTrue(
                file_exists,
                f"ONBOARDING_MATRIX lies: claims uniswap_v3 is PRODUCTION but {uniswap_file} doesn't exist"
            )

    def test_algebra_adapter_status_matches_file_existence(self):
        """algebra adapter must exist when claimed as PRODUCTION."""
        algebra_file = self.adapters_dir / "algebra.py"
        file_exists = algebra_file.exists()
        
        # Check if matrix claims PRODUCTION
        production_pattern = r"\|\s*`?algebra`?\s*\|[^|]*\|[^|]*\|\s*PRODUCTION\s*\|"
        claims_production = bool(re.search(production_pattern, self.matrix_content, re.IGNORECASE))
        
        # Contract: If matrix says PRODUCTION, file must exist
        if claims_production:
            self.assertTrue(
                file_exists,
                f"ONBOARDING_MATRIX lies: claims algebra is PRODUCTION but {algebra_file} doesn't exist"
            )

    def test_adapter_registry_status_table_exists(self):
        """ONBOARDING_MATRIX must have an Adapter Registry Status table."""
        self.assertIn("## Adapter Registry Status", self.matrix_content)


class TestAdapterRegistryMatchesFiles(unittest.TestCase):
    """Verify dex/registry.py adapter claims match actual files."""

    def test_registered_adapters_have_files(self):
        """All adapters registered in registry.py must have corresponding files."""
        adapters_dir = Path(__file__).parents[2] / "dex" / "adapters"
        registry_path = Path(__file__).parents[2] / "dex" / "registry.py"
        
        if not registry_path.exists():
            self.skipTest("registry.py not found")
        
        registry_content = registry_path.read_text(encoding="utf-8")
        
        # Find adapter registrations (pattern: from dex.adapters.X import)
        import_pattern = r"from\s+dex\.adapters\.(\w+)\s+import"
        registered_adapters = set(re.findall(import_pattern, registry_content))
        
        for adapter in registered_adapters:
            adapter_file = adapters_dir / f"{adapter}.py"
            self.assertTrue(
                adapter_file.exists(),
                f"Registry imports dex.adapters.{adapter} but {adapter_file} doesn't exist"
            )


if __name__ == "__main__":
    unittest.main()
