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


class TestStatusHeaderBodyConsistency(unittest.TestCase):
    """R28.3: Detect stale status files where header is updated but body has old R-tags."""

    @classmethod
    def setUpClass(cls):
        cls.status_dir = Path(__file__).parents[2] / "docs" / "status"

    def _get_header_round(self, content):
        """Extract R-tag from the header Updated: line (e.g. R28.2)."""
        m = re.search(r"\*\*Updated\*\*:\s*\d{4}-\d{2}-\d{2}\s*\(R(\d+(?:\.\d+)?)", content)
        return m.group(1) if m else None

    def test_status_m5_0_no_stale_next_steps(self):
        """Status_M5_0.md must not have Next Steps referencing old rounds."""
        path = self.status_dir / "Status_M5_0.md"
        if not path.exists():
            self.skipTest("Status_M5_0.md not found")
        content = path.read_text(encoding="utf-8")
        # "Next Steps (R27.2)" or similar stale next-steps sections
        stale_next = re.findall(r"Next Steps?\s*\(R\d+(?:\.\d+)?\)", content)
        self.assertEqual(stale_next, [],
                         f"Status_M5_0.md has stale Next Steps sections: {stale_next}")

    def test_status_m5_0_chain_classification_matches_header(self):
        """Chain Quality Classification section tag must not lag behind header round."""
        path = self.status_dir / "Status_M5_0.md"
        if not path.exists():
            self.skipTest("Status_M5_0.md not found")
        content = path.read_text(encoding="utf-8")
        header_round = self._get_header_round(content)
        if not header_round:
            self.skipTest("Cannot parse header round")
        # Check the Chain Quality Classification section tag
        m = re.search(r"## Chain Quality Classification \(R(\d+(?:\.\d+)?)\)", content)
        if m:
            section_round = m.group(1)
            # The section round's major must not be more than 1 behind the header
            header_major = int(header_round.split(".")[0])
            section_major = int(section_round.split(".")[0])
            self.assertGreaterEqual(section_major, header_major - 1,
                                    f"Chain Classification (R{section_round}) is stale vs header (R{header_round})")

    def test_status_m4_rollout_no_needs_online_test_when_tested(self):
        """If a stage2 config exists, rollout table should not say 'NEEDS ONLINE TEST'."""
        path = self.status_dir / "Status_M4.md"
        if not path.exists():
            self.skipTest("Status_M4.md not found")
        content = path.read_text(encoding="utf-8")
        config_dir = Path(__file__).parents[2] / "config"
        for chain in ["base", "mantle"]:
            stage2_file = config_dir / f"onboard_{chain}_stage2.yaml"
            if stage2_file.exists():
                # If stage2 config exists, the rollout table should not say NEEDS ONLINE TEST for that chain
                pattern = rf"{chain}.*NEEDS ONLINE TEST"
                matches = re.findall(pattern, content, re.IGNORECASE)
                self.assertEqual(matches, [],
                                 f"Status_M4.md says '{chain}' NEEDS ONLINE TEST but stage2 config exists")

    def test_status_m5_0_test_count_format(self):
        """Test count line must be 'N passed / M skipped', not 'N collected / N passed / M skipped'."""
        path = self.status_dir / "Status_M5_0.md"
        if not path.exists():
            self.skipTest("Status_M5_0.md not found")
        content = path.read_text(encoding="utf-8")
        # Reject the redundant "collected" format
        bad_format = re.search(r"\*\*Tests\*\*:\s*\d+\s+collected\s*/\s*\d+\s+passed", content)
        self.assertIsNone(bad_format,
                          "Status_M5_0.md test count uses redundant 'collected / passed' format. "
                          "Use 'N passed / M skipped' instead.")

    def test_deprecated_pnl_block_has_no_none_fields(self):
        """The deprecated pnl block in truth_report must not contain None fields that look like TODOs."""
        from strategy.artifacts import build_truth_data

        truth_data = build_truth_data(
            config={"truth_mode_m42": False},
            stats={"quotes_fetched": 1, "quotes_total": 1, "dexes_active": [],
                    "price_sanity_passed": 0, "price_sanity_failed": 0, "gates_passed": 0},
            current_block=1,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=50,
        )

        pnl = truth_data.get("pnl", {})
        self.assertTrue(pnl.get("_deprecated"), "pnl block must be marked _deprecated")
        # No None values that look like unfilled fields
        for key, val in pnl.items():
            if key.startswith("_"):
                continue
            self.assertIsNotNone(val,
                                 f"pnl.{key}=None looks like an unfilled TODO. "
                                 "Remove it or use execution_pnl instead.")


if __name__ == "__main__":
    unittest.main()
