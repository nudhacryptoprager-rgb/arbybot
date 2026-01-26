# PATH: tests/integration/test_smoke_run.py
"""
Integration tests for REAL pipeline smoke run.

METRICS CONTRACT:
- quotes_total = attempted quote calls
- quotes_fetched = got valid RPC response (amount > 0)  
- gates_passed = passed all gates (sanity, etc.)
- dexes_active = DEXes with at least 1 response

M4 Requirements:
- quotes_fetched >= 1
- dexes_active >= 2
- price_sanity_passed >= 1
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def is_offline_mode() -> bool:
    """Check if running in offline mode (no network)."""
    return os.environ.get("ARBY_OFFLINE", "").lower() in ("1", "true", "yes")


class TestSmokeRunREAL(unittest.TestCase):
    """Smoke tests for REAL pipeline."""

    @unittest.skipIf(is_offline_mode(), "Skipping network test in offline mode")
    def test_real_scan_produces_artifacts(self):
        """REAL scan produces all 4 artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            cmd = [
                sys.executable, "-m", "strategy.jobs.run_scan",
                "--mode", "real",
                "--cycles", "1",
                "--output-dir", str(output_dir),
                "--config", "config/real_minimal.yaml",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            # Should complete without error
            self.assertEqual(
                result.returncode, 0,
                f"Scan failed: {result.stderr}"
            )

            # Check artifacts
            self.assertTrue(
                (output_dir / "scan.log").exists(),
                "Missing scan.log"
            )

            snapshots = list((output_dir / "snapshots").glob("scan_*.json"))
            self.assertGreater(len(snapshots), 0, "Missing scan snapshot")

            reports_dir = output_dir / "reports"
            histograms = list(reports_dir.glob("reject_histogram_*.json"))
            self.assertGreater(len(histograms), 0, "Missing reject histogram")

            truths = list(reports_dir.glob("truth_report_*.json"))
            self.assertGreater(len(truths), 0, "Missing truth report")

    @unittest.skipIf(is_offline_mode(), "Skipping network test in offline mode")
    def test_real_scan_metrics_contract(self):
        """REAL scan satisfies metrics contract."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            cmd = [
                sys.executable, "-m", "strategy.jobs.run_scan",
                "--mode", "real",
                "--cycles", "1",
                "--output-dir", str(output_dir),
                "--config", "config/real_minimal.yaml",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            self.assertEqual(result.returncode, 0)

            # Load scan snapshot
            snapshots = list((output_dir / "snapshots").glob("scan_*.json"))
            self.assertGreater(len(snapshots), 0)

            with open(snapshots[0], "r") as f:
                scan_data = json.load(f)

            stats = scan_data.get("stats", {})

            # STEP 1: Metrics contract checks
            quotes_total = stats.get("quotes_total", 0)
            quotes_fetched = stats.get("quotes_fetched", 0)
            gates_passed = stats.get("gates_passed", 0)

            # Invariant: gates_passed <= quotes_fetched <= quotes_total
            self.assertLessEqual(
                gates_passed, quotes_fetched,
                f"gates_passed ({gates_passed}) > quotes_fetched ({quotes_fetched})"
            )
            self.assertLessEqual(
                quotes_fetched, quotes_total,
                f"quotes_fetched ({quotes_fetched}) > quotes_total ({quotes_total})"
            )

            # M4: quotes_fetched >= 1
            self.assertGreaterEqual(
                quotes_fetched, 1,
                f"M4 requires quotes_fetched >= 1, got {quotes_fetched}"
            )

            # M4: dexes_active >= 2
            dexes_active = stats.get("dexes_active", 0)
            self.assertGreaterEqual(
                dexes_active, 2,
                f"M4 requires dexes_active >= 2, got {dexes_active}"
            )

    @unittest.skipIf(is_offline_mode(), "Skipping network test in offline mode")  
    def test_real_scan_price_sanity(self):
        """REAL scan has price sanity checks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            cmd = [
                sys.executable, "-m", "strategy.jobs.run_scan",
                "--mode", "real",
                "--cycles", "1", 
                "--output-dir", str(output_dir),
                "--config", "config/real_minimal.yaml",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            self.assertEqual(result.returncode, 0)

            snapshots = list((output_dir / "snapshots").glob("scan_*.json"))
            self.assertGreater(len(snapshots), 0)

            with open(snapshots[0], "r") as f:
                scan_data = json.load(f)

            stats = scan_data.get("stats", {})

            # Price sanity metrics should exist
            self.assertIn("price_sanity_passed", stats)
            self.assertIn("price_sanity_failed", stats)

            # M4: At least 1 quote should pass sanity
            price_sanity_passed = stats.get("price_sanity_passed", 0)
            self.assertGreaterEqual(
                price_sanity_passed, 1,
                f"M4 requires price_sanity_passed >= 1, got {price_sanity_passed}"
            )

    @unittest.skipIf(is_offline_mode(), "Skipping network test in offline mode")
    def test_real_scan_rejects_invariant(self):
        """If rejects have prices, quotes_fetched must be > 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            cmd = [
                sys.executable, "-m", "strategy.jobs.run_scan",
                "--mode", "real",
                "--cycles", "1",
                "--output-dir", str(output_dir),
                "--config", "config/real_minimal.yaml",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            self.assertEqual(result.returncode, 0)

            snapshots = list((output_dir / "snapshots").glob("scan_*.json"))
            self.assertGreater(len(snapshots), 0)

            with open(snapshots[0], "r") as f:
                scan_data = json.load(f)

            stats = scan_data.get("stats", {})
            sample_rejects = scan_data.get("sample_rejects", [])

            # STEP 9: If rejects have prices, quotes_fetched > 0
            rejects_with_price = [r for r in sample_rejects if r.get("price") is not None]
            quotes_fetched = stats.get("quotes_fetched", 0)

            if rejects_with_price:
                self.assertGreater(
                    quotes_fetched, 0,
                    f"INVARIANT VIOLATION: {len(rejects_with_price)} rejects have prices "
                    f"but quotes_fetched=0"
                )


class TestSmokeRunOffline(unittest.TestCase):
    """Offline tests that don't require network."""

    def test_config_exists(self):
        """Config file exists."""
        config_path = Path("config/real_minimal.yaml")
        self.assertTrue(
            config_path.exists(),
            f"Missing config: {config_path}"
        )

    def test_config_has_required_fields(self):
        """Config has M4 required fields."""
        import yaml

        config_path = Path("config/real_minimal.yaml")
        if not config_path.exists():
            self.skipTest("Config not found")

        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        # Required fields
        self.assertIn("chain_id", config)
        self.assertIn("dexes", config)
        self.assertIn("pairs", config)
        self.assertIn("tokens", config)
        self.assertIn("quote_decimals", config)

        # M4: Need 2+ DEXes
        self.assertGreaterEqual(
            len(config.get("dexes", [])), 2,
            "M4 requires 2+ DEXes in config"
        )

        # Price sanity should be enabled
        self.assertTrue(
            config.get("price_sanity_enabled", True),
            "Price sanity should be enabled for M4"
        )

    def test_import_contracts(self):
        """Import contracts work."""
        # calculate_confidence from truth_report
        from monitoring.truth_report import calculate_confidence
        self.assertTrue(callable(calculate_confidence))

        # Also check re-export from package
        from monitoring import calculate_confidence as conf_func
        self.assertTrue(callable(conf_func))


class TestMetricsContract(unittest.TestCase):
    """Unit tests for metrics contract."""

    def test_quote_dataclass_has_rpc_success(self):
        """Quote dataclass has rpc_success field."""
        from strategy.jobs.run_scan_real import Quote
        from decimal import Decimal

        # Create a quote
        quote = Quote(
            dex_id="test",
            pool_address="0x123",
            token_in="WETH",
            token_out="USDC",
            fee=500,
            amount_in_wei=1000000000000000000,
            amount_out_wei=3500000000,
            amount_in_human="1.000000",
            amount_out_human="3500.000000",
            price=Decimal("3500"),
            latency_ms=50,
            block_number=1000,
            rpc_success=True,
            gate_passed=True,
        )

        self.assertTrue(quote.rpc_success)
        self.assertTrue(quote.gate_passed)

    def test_price_sanity_check_returns_diagnostics(self):
        """Price sanity check returns diagnostics dict."""
        from strategy.jobs.run_scan_real import check_price_sanity
        from decimal import Decimal

        config = {"price_sanity_enabled": True}
        
        passed, deviation, error, diagnostics = check_price_sanity(
            token_in="WETH",
            token_out="USDC",
            price=Decimal("3500"),
            config=config,
        )

        self.assertTrue(passed)
        self.assertIsInstance(diagnostics, dict)
        self.assertIn("implied_price", diagnostics)
        self.assertIn("anchor_price", diagnostics)


if __name__ == "__main__":
    unittest.main()
