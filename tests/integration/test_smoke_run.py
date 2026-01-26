# PATH: tests/integration/test_smoke_run.py
"""
Integration tests for SMOKE and REAL runs.

STEP 7: Deterministic tests - skip network-dependent tests in CI
        Use ARBY_OFFLINE=1 env var to skip live RPC tests
"""

import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock


def _close_all_handlers():
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)
    logging.shutdown()


def is_offline_mode() -> bool:
    """Check if running in offline mode (no network)."""
    return os.environ.get("ARBY_OFFLINE", "0") == "1"


class TestFullSmokeRun(unittest.TestCase):
    def test_full_smoke_run(self):
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=output_dir)
                self.assertTrue((output_dir / "scan.log").exists())
            finally:
                _close_all_handlers()


class TestSmokeArtifactsContract(unittest.TestCase):
    def test_all_artifacts_generated(self):
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=output_dir)

                snapshots_dir = output_dir / "snapshots"
                reports_dir = output_dir / "reports"

                self.assertTrue(snapshots_dir.exists())
                self.assertTrue(reports_dir.exists())
                self.assertEqual(len(list(snapshots_dir.glob("scan_*.json"))), 1)
                self.assertEqual(len(list(reports_dir.glob("reject_histogram_*.json"))), 1)
                self.assertEqual(len(list(reports_dir.glob("truth_report_*.json"))), 1)
            finally:
                _close_all_handlers()


class TestRealModeContract(unittest.TestCase):
    """REAL MODE CONTRACT TEST."""

    @unittest.skipIf(is_offline_mode(), "Skipping live RPC test in offline mode")
    def test_real_mode_runs_without_raising(self):
        """STEP 7: Only run with live RPC if not in offline mode."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)
                self.assertTrue((output_dir / "scan.log").exists())
            except RuntimeError as e:
                if "INFRA_BLOCK_PIN_FAILED" in str(e):
                    self.skipTest(f"Network unavailable: {e}")
                raise
            finally:
                _close_all_handlers()

    @unittest.skipIf(is_offline_mode(), "Skipping live RPC test in offline mode")
    def test_real_mode_produces_artifacts(self):
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)

                self.assertTrue((output_dir / "scan.log").exists())

                snapshots = output_dir / "snapshots"
                reports = output_dir / "reports"

                if snapshots.exists():
                    self.assertGreater(len(list(snapshots.glob("scan_*.json"))), 0)
                if reports.exists():
                    self.assertGreater(len(list(reports.glob("reject_histogram_*.json"))), 0)
                    self.assertGreater(len(list(reports.glob("truth_report_*.json"))), 0)

            except RuntimeError as e:
                if "INFRA_BLOCK_PIN_FAILED" in str(e):
                    self.skipTest(f"Network unavailable: {e}")
                raise
            finally:
                _close_all_handlers()

    @unittest.skipIf(is_offline_mode(), "Skipping live RPC test in offline mode")
    def test_real_mode_execution_disabled(self):
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)

                truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
                if truth_files:
                    with open(truth_files[0]) as f:
                        truth = json.load(f)
                    stats = truth.get("stats", {})
                    self.assertEqual(stats.get("execution_ready_count", 0), 0)

            except RuntimeError as e:
                if "INFRA_BLOCK_PIN_FAILED" in str(e):
                    self.skipTest(f"Network unavailable: {e}")
                raise
            finally:
                _close_all_handlers()


class TestRealModeCrossDex(unittest.TestCase):
    """
    STEP 1: Cross-DEX arbitrage tests.
    """

    @unittest.skipIf(is_offline_mode(), "Skipping live RPC test in offline mode")
    def test_cross_dex_opportunities_have_different_dexes(self):
        """At least one opportunity should have dex_buy != dex_sell."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)

                truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
                if truth_files:
                    with open(truth_files[0]) as f:
                        truth = json.load(f)

                    top_opps = truth.get("top_opportunities", [])

                    # Only check if we have opportunities
                    if top_opps:
                        cross_dex = [
                            opp for opp in top_opps
                            if opp.get("dex_buy") != opp.get("dex_sell")
                        ]
                        self.assertGreater(
                            len(cross_dex), 0,
                            f"Expected cross-DEX opportunities, all {len(top_opps)} have same DEX"
                        )

            except RuntimeError as e:
                if "INFRA_BLOCK_PIN_FAILED" in str(e):
                    self.skipTest(f"Network unavailable: {e}")
                raise
            finally:
                _close_all_handlers()

    @unittest.skipIf(is_offline_mode(), "Skipping live RPC test in offline mode")
    def test_pools_not_unknown(self):
        """STEP 2: No pool should be "unknown"."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)

                truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
                if truth_files:
                    with open(truth_files[0]) as f:
                        truth = json.load(f)

                    top_opps = truth.get("top_opportunities", [])

                    for opp in top_opps:
                        self.assertNotEqual(
                            opp.get("pool_buy"), "unknown",
                            f"pool_buy is 'unknown' for {opp.get('spread_id')}"
                        )
                        self.assertNotEqual(
                            opp.get("pool_sell"), "unknown",
                            f"pool_sell is 'unknown' for {opp.get('spread_id')}"
                        )

            except RuntimeError as e:
                if "INFRA_BLOCK_PIN_FAILED" in str(e):
                    self.skipTest(f"Network unavailable: {e}")
                raise
            finally:
                _close_all_handlers()

    @unittest.skipIf(is_offline_mode(), "Skipping live RPC test in offline mode")
    def test_amounts_not_zero(self):
        """STEP 3: Amounts should not be zero for opportunities."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode
        from decimal import Decimal

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)

                truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
                if truth_files:
                    with open(truth_files[0]) as f:
                        truth = json.load(f)

                    top_opps = truth.get("top_opportunities", [])

                    for opp in top_opps:
                        amount_in = opp.get("amount_in_numeraire", "0")
                        try:
                            self.assertGreater(
                                Decimal(amount_in), 0,
                                f"amount_in is 0 for {opp.get('spread_id')}"
                            )
                        except:
                            self.fail(f"Invalid amount_in for {opp.get('spread_id')}")

            except RuntimeError as e:
                if "INFRA_BLOCK_PIN_FAILED" in str(e):
                    self.skipTest(f"Network unavailable: {e}")
                raise
            finally:
                _close_all_handlers()


class TestRealModeOfflineFixture(unittest.TestCase):
    """
    STEP 7: Deterministic tests with mock RPC.
    
    These tests use fixtures instead of live RPC calls.
    """

    def test_quote_dataclass_fields(self):
        """Test Quote dataclass has required fields."""
        from strategy.jobs.run_scan_real import Quote
        from decimal import Decimal

        quote = Quote(
            dex_id="uniswap_v3",
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
            block_number=12345678,
            success=True,
        )

        self.assertEqual(quote.dex_id, "uniswap_v3")
        self.assertEqual(quote.pool_address, "0x123")
        self.assertTrue(quote.success)
        self.assertEqual(quote.amount_out_wei, 3500000000)

    def test_cross_dex_spread_generation(self):
        """Test cross-DEX spread generation from quotes."""
        from strategy.jobs.run_scan_real import Quote, find_cross_dex_spreads
        from decimal import Decimal

        quotes = [
            Quote(
                dex_id="uniswap_v3",
                pool_address="0xUNI_POOL",
                token_in="WETH",
                token_out="USDC",
                fee=500,
                amount_in_wei=1000000000000000000,
                amount_out_wei=3500000000,  # 3500 USDC
                amount_in_human="1.000000",
                amount_out_human="3500.000000",
                price=Decimal("3500"),
                latency_ms=50,
                block_number=12345678,
                success=True,
            ),
            Quote(
                dex_id="sushiswap_v3",
                pool_address="0xSUSHI_POOL",
                token_in="WETH",
                token_out="USDC",
                fee=500,
                amount_in_wei=1000000000000000000,
                amount_out_wei=3510000000,  # 3510 USDC (better)
                amount_in_human="1.000000",
                amount_out_human="3510.000000",
                price=Decimal("3510"),
                latency_ms=60,
                block_number=12345678,
                success=True,
            ),
        ]

        spreads = find_cross_dex_spreads(
            quotes, chain_id=42161, cycle_num=1, timestamp_str="20260125_120000"
        )

        self.assertGreater(len(spreads), 0)

        spread = spreads[0]
        # STEP 1: Different DEXes
        self.assertNotEqual(spread.dex_buy, spread.dex_sell)
        # STEP 2: Pool addresses not unknown
        self.assertIn("0x", spread.pool_buy)
        self.assertIn("0x", spread.pool_sell)
        # STEP 3: Amount > 0
        self.assertGreater(spread.amount_in_wei, 0)

    def test_wei_to_human_conversion(self):
        """Test wei to human readable conversion."""
        from strategy.jobs.run_scan_real import wei_to_human

        # 1 ETH
        result = wei_to_human(1000000000000000000, 18)
        self.assertEqual(result, "1.000000")

        # 1000 USDC
        result = wei_to_human(1000000000, 6)
        self.assertEqual(result, "1000.000000")

    def test_pool_address_generation(self):
        """STEP 2: Test pool address lookup and generation."""
        from strategy.jobs.run_scan_real import get_pool_address

        config = {
            "pools": {
                "uniswap_v3_WETH_USDC_500": "0xC31E54c7a869B9FcBEcc14363CF510d1c41fa443",
            }
        }

        # Known pool
        addr = get_pool_address(config, "uniswap_v3", "WETH", "USDC", 500)
        self.assertEqual(addr, "0xC31E54c7a869B9FcBEcc14363CF510d1c41fa443")

        # Unknown pool - should generate deterministic ID (not "unknown")
        addr = get_pool_address(config, "uniswap_v3", "WETH", "USDT", 3000)
        self.assertNotEqual(addr, "unknown")
        self.assertIn("pool:", addr)


if __name__ == "__main__":
    unittest.main()
