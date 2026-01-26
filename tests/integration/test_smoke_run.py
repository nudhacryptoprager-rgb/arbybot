# PATH: tests/integration/test_smoke_run.py
"""
Integration tests for SMOKE and REAL runs.

STEP 6: Deterministic tests with mock RPC
- Use ARBY_OFFLINE=1 env var to skip live RPC tests
- Mock RPC responses for unit-style tests
"""

import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from decimal import Decimal


def _close_all_handlers():
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)
    logging.shutdown()


def is_offline_mode() -> bool:
    """Check if running in offline mode (no network)."""
    return os.environ.get("ARBY_OFFLINE", "0") == "1"


# STEP 6: Mock RPC fixtures
MOCK_RPC_RESPONSES = {
    "eth_chainId": {"jsonrpc": "2.0", "result": "0xa4b1", "id": 1},  # Arbitrum = 42161
    "eth_blockNumber": {"jsonrpc": "2.0", "result": "0x1a2b3c4", "id": 2},  # Block ~27,000,000
    # WETH/USDC quote: 1 ETH = 3500 USDC (realistic)
    "eth_call_weth_usdc_500": {
        "jsonrpc": "2.0",
        # 3500 USDC = 3500 * 10^6 = 0xD02AB486C0
        "result": "0x" + hex(3500_000_000)[2:].zfill(64),
        "id": 3
    },
    # WETH/USDC quote from another DEX: 3505 USDC (slight difference)
    "eth_call_weth_usdc_500_sushi": {
        "jsonrpc": "2.0",
        "result": "0x" + hex(3505_000_000)[2:].zfill(64),
        "id": 4
    },
    # WETH/USDC 3000 fee tier
    "eth_call_weth_usdc_3000": {
        "jsonrpc": "2.0",
        "result": "0x" + hex(3498_000_000)[2:].zfill(64),
        "id": 5
    },
    # Unrealistic quote (for sanity test): 1 ETH = 9.57 USDC
    "eth_call_insane_price": {
        "jsonrpc": "2.0",
        "result": "0x" + hex(9_570_000)[2:].zfill(64),  # 9.57 USDC
        "id": 6
    },
}


class MockRPCClient:
    """STEP 6: Mock RPC client for deterministic tests."""

    def __init__(self, responses: dict = None):
        self.responses = responses or MOCK_RPC_RESPONSES
        self.call_count = 0
        self.calls = []

    async def call(self, method: str, params: list = None, rpc_metrics=None):
        self.call_count += 1
        self.calls.append((method, params))

        if rpc_metrics:
            rpc_metrics.record_rpc_call(success=True, latency_ms=50)

        if method == "eth_chainId":
            return self.responses["eth_chainId"], {"rpc_success": True, "latency_ms": 50}

        if method == "eth_blockNumber":
            return self.responses["eth_blockNumber"], {"rpc_success": True, "latency_ms": 50}

        if method == "eth_call":
            # Return realistic quote
            return self.responses["eth_call_weth_usdc_500"], {"rpc_success": True, "latency_ms": 100}

        return {"error": {"message": "Unknown method"}}, {"rpc_success": False}

    def get_stats_summary(self):
        return {
            "total_requests": self.call_count,
            "total_success": self.call_count,
            "total_failure": 0,
            "success_rate": 1.0,
        }


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
    """REAL MODE CONTRACT TEST - with network."""

    @unittest.skipIf(is_offline_mode(), "Skipping live RPC test in offline mode")
    def test_real_mode_runs_without_raising(self):
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


class TestPriceSanityGate(unittest.TestCase):
    """STEP 1-2: Price sanity gate tests."""

    def test_check_price_sanity_accepts_realistic_price(self):
        """Realistic WETH/USDC price should pass."""
        from strategy.jobs.run_scan_real import check_price_sanity

        config = {"price_sanity_enabled": True}
        passed, deviation_bps, error = check_price_sanity("WETH", "USDC", Decimal("3500"), config)

        self.assertTrue(passed)
        self.assertIsNone(error)

    def test_check_price_sanity_rejects_insane_price(self):
        """STEP 1: '1 WETH -> 9.57 USDC' should be rejected."""
        from strategy.jobs.run_scan_real import check_price_sanity

        config = {"price_sanity_enabled": True}
        passed, deviation_bps, error = check_price_sanity("WETH", "USDC", Decimal("9.57"), config)

        self.assertFalse(passed)
        self.assertIsNotNone(error)
        self.assertIn("outside bounds", error.lower())

    def test_check_price_sanity_can_be_disabled(self):
        """Price sanity can be disabled via config."""
        from strategy.jobs.run_scan_real import check_price_sanity

        config = {"price_sanity_enabled": False}
        passed, deviation_bps, error = check_price_sanity("WETH", "USDC", Decimal("9.57"), config)

        self.assertTrue(passed)  # Passes when disabled

    def test_check_price_sanity_deviation_calculation(self):
        """Deviation from expected should be calculated."""
        from strategy.jobs.run_scan_real import check_price_sanity

        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 500}  # 5%

        # 3500 is expected, 3600 is ~2.86% deviation
        passed, deviation_bps, error = check_price_sanity("WETH", "USDC", Decimal("3600"), config)
        self.assertTrue(passed)
        self.assertIsNotNone(deviation_bps)
        self.assertLess(deviation_bps, 500)

        # 4000 is ~14% deviation - should fail with 5% max
        passed, deviation_bps, error = check_price_sanity("WETH", "USDC", Decimal("4000"), config)
        self.assertFalse(passed)
        self.assertGreater(deviation_bps, 500)


class TestConfidenceScoring(unittest.TestCase):
    """STEP 5: Dynamic confidence scoring tests."""

    def test_calculate_confidence_high_quality(self):
        """High quality metrics should give high confidence."""
        from strategy.jobs.run_scan_real import calculate_confidence

        confidence, factors = calculate_confidence(
            rpc_success_rate=1.0,
            quote_fetch_rate=1.0,
            reject_rate=0.0,
            price_deviation_bps=50,  # Low deviation
            dex_count=2,
            spread_bps=Decimal("20"),  # Reasonable spread
        )

        self.assertGreater(confidence, 0.8)
        self.assertIn("rpc_health", factors)
        self.assertIn("price_stability", factors)

    def test_calculate_confidence_low_quality(self):
        """Low quality metrics should give low confidence."""
        from strategy.jobs.run_scan_real import calculate_confidence

        confidence, factors = calculate_confidence(
            rpc_success_rate=0.5,
            quote_fetch_rate=0.3,
            reject_rate=0.7,
            price_deviation_bps=800,  # High deviation
            dex_count=1,  # Single DEX
            spread_bps=Decimal("1000"),  # Suspiciously large
        )

        self.assertLess(confidence, 0.5)

    def test_confidence_penalizes_large_spread(self):
        """Suspiciously large spreads should lower confidence."""
        from strategy.jobs.run_scan_real import calculate_confidence

        # Reasonable spread
        conf1, _ = calculate_confidence(
            rpc_success_rate=1.0, quote_fetch_rate=1.0, reject_rate=0.0,
            price_deviation_bps=50, dex_count=2, spread_bps=Decimal("20"),
        )

        # Very large spread (suspicious)
        conf2, factors2 = calculate_confidence(
            rpc_success_rate=1.0, quote_fetch_rate=1.0, reject_rate=0.0,
            price_deviation_bps=50, dex_count=2, spread_bps=Decimal("1000"),
        )

        self.assertGreater(conf1, conf2)
        self.assertLess(factors2["spread_quality"], 0.5)


class TestPnLSplit(unittest.TestCase):
    """STEP 3-4: PnL split tests."""

    def test_truth_report_has_both_pnl_types(self):
        """Truth report should have signal_pnl and would_execute_pnl."""
        from monitoring.truth_report import build_truth_report

        all_spreads = [
            {
                "spread_id": "test_001",
                "dex_buy": "uniswap_v3",
                "dex_sell": "sushiswap_v3",
                "pool_buy": "0x123",
                "pool_sell": "0x456",
                "token_in": "WETH",
                "token_out": "USDC",
                "signal_pnl_usdc": "5.000000",
                "signal_pnl_bps": "14.28",
                "would_execute_pnl_usdc": "4.500000",  # After costs
                "would_execute_pnl_bps": "12.85",
                "amount_in_numeraire": "1.0",
                "confidence": 0.85,
                "is_profitable": True,
                "execution_blockers": ["EXECUTION_DISABLED_M4"],
            }
        ]

        report = build_truth_report(
            scan_stats={"execution_ready_count": 0, "spread_ids_profitable": 1},
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
        )

        # Check PnL section
        pnl = report.pnl
        self.assertIn("signal_pnl_usdc", pnl)
        self.assertIn("would_execute_pnl_usdc", pnl)

        # Check top opportunities
        opp = report.top_opportunities[0]
        self.assertIn("signal_pnl_usdc", opp)
        self.assertIn("would_execute_pnl_usdc", opp)


class TestMockRPCIntegration(unittest.TestCase):
    """STEP 6: Tests with mock RPC (always run, no network needed)."""

    def test_mock_rpc_client_returns_valid_responses(self):
        """Mock RPC client should return valid responses."""
        import asyncio

        client = MockRPCClient()

        async def test():
            result, debug = await client.call("eth_chainId")
            return result

        result = asyncio.run(test())
        self.assertIn("result", result)
        self.assertEqual(result["result"], "0xa4b1")

    def test_mock_rpc_tracks_calls(self):
        """Mock RPC client should track calls."""
        import asyncio

        client = MockRPCClient()

        async def test():
            await client.call("eth_chainId")
            await client.call("eth_blockNumber")
            await client.call("eth_call", [{"to": "0x123"}])

        asyncio.run(test())
        self.assertEqual(client.call_count, 3)
        self.assertEqual(len(client.calls), 3)


class TestQuoteNormalization(unittest.TestCase):
    """STEP 2: Quote normalization tests."""

    def test_wei_to_human_weth(self):
        """1 ETH in wei should convert to '1.000000'."""
        from strategy.jobs.run_scan_real import wei_to_human

        result = wei_to_human(1_000_000_000_000_000_000, 18)
        self.assertEqual(result, "1.000000")

    def test_wei_to_human_usdc(self):
        """3500 USDC should convert correctly."""
        from strategy.jobs.run_scan_real import wei_to_human

        result = wei_to_human(3_500_000_000, 6)
        self.assertEqual(result, "3500.000000")

    def test_quote_price_calculation(self):
        """Price should be amount_out / amount_in (normalized)."""
        # 1 ETH = 10^18 wei
        # 3500 USDC = 3500 * 10^6 = 3.5 * 10^9 wei

        amount_in_wei = 1_000_000_000_000_000_000  # 1 ETH
        amount_out_wei = 3_500_000_000  # 3500 USDC

        decimals_in = 18
        decimals_out = 6

        in_normalized = Decimal(amount_in_wei) / Decimal(10 ** decimals_in)
        out_normalized = Decimal(amount_out_wei) / Decimal(10 ** decimals_out)
        price = out_normalized / in_normalized

        self.assertEqual(in_normalized, Decimal("1"))
        self.assertEqual(out_normalized, Decimal("3500"))
        self.assertEqual(price, Decimal("3500"))


if __name__ == "__main__":
    unittest.main()
