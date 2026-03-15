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


class TestConfigInventoryDocContract(unittest.TestCase):
    """Verify Status docs config inventory count matches actual allowed set."""

    def test_stage2_configs_exist_when_claimed(self):
        """Stage2 configs mentioned in Status_M5_0 must exist on disk."""
        config_dir = Path(__file__).parents[2] / "config"
        status_path = Path(__file__).parents[2] / "docs" / "status" / "Status_M5_0.md"
        content = status_path.read_text(encoding="utf-8")
        # Find all onboard_*_stage2.yaml references
        stage2_refs = set(re.findall(r"(onboard_\w+_stage2\.yaml)", content))
        for cfg_name in stage2_refs:
            self.assertTrue(
                (config_dir / cfg_name).exists(),
                f"Status_M5_0.md references {cfg_name} but file does not exist"
            )

    def test_stage1_yaml_comments_no_not_implemented_lie(self):
        """Stage1 YAML comment headers must not say 've33 NOT YET IMPLEMENTED' when adapter exists."""
        config_dir = Path(__file__).parents[2] / "config"
        adapters_dir = Path(__file__).parents[2] / "dex" / "adapters"
        ve33_exists = (adapters_dir / "ve33.py").exists()
        if not ve33_exists:
            self.skipTest("ve33 adapter not found — comment is accurate")
        for yaml_name in ["onboard_base_stage1.yaml", "onboard_mantle_stage1.yaml"]:
            yaml_path = config_dir / yaml_name
            if not yaml_path.exists():
                continue
            content = yaml_path.read_text(encoding="utf-8")
            self.assertNotIn(
                "NOT YET IMPLEMENTED",
                content,
                f"{yaml_name} says 'NOT YET IMPLEMENTED' but ve33 adapter exists at {adapters_dir / 've33.py'}"
            )
            self.assertNotIn(
                "NOT IMPLEMENTED",
                content,
                f"{yaml_name} says 'NOT IMPLEMENTED' but ve33 adapter exists at {adapters_dir / 've33.py'}"
            )


class TestProfitSemanticsContract(unittest.TestCase):
    """R28.2: Verify profit_truth semantics require real_quote_count > 0."""

    def test_profitable_without_real_quotes_is_not_canonical(self):
        """Core contract: profitable_count > 0 but real_quote_count = 0 must NOT produce ROUNDTRIP_CANONICAL."""
        from strategy.artifacts import build_truth_data

        stats = {
            "roundtrip": {
                "profitable_count": 5,
                "evaluated_count": 10,
                "real_quote_count": 0,  # No real quotes
            },
            "quotes_fetched": 10,
            "quotes_total": 10,
            "dexes_active": ["uniswap_v3"],
            "price_sanity_passed": 10,
            "price_sanity_failed": 0,
            "gates_passed": 10,
        }

        truth_data = build_truth_data(
            config={"truth_mode_m42": True},
            stats=stats,
            current_block=12345,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=100,
            spread_threshold_bps=50,
        )

        self.assertTrue(truth_data["profit_is_diagnostic"],
                        "profit_is_diagnostic must be True when real_quote_count=0")
        self.assertNotEqual(truth_data["profit_truth_source"], "ROUNDTRIP_CANONICAL",
                            "profit_truth_source must NOT be ROUNDTRIP_CANONICAL when real_quote_count=0")
        self.assertNotEqual(truth_data["profit_realism_status"], "ROUNDTRIP_PROFITABLE",
                            "profit_realism_status must NOT be ROUNDTRIP_PROFITABLE when real_quote_count=0")


if __name__ == "__main__":
    unittest.main()
