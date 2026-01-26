# PATH: tests/unit/test_truth_report.py
"""
Unit tests for truth_report consistency.

Tests:
- STEP 2: pool_buy/pool_sell preserved (no "unknown")
- STEP 3: amount_in_numeraire preserved
- STEP 4: PnL consistency
"""

import unittest
from decimal import Decimal


class TestTruthReportConsistency(unittest.TestCase):
    """Test truth_report consistency with scan_stats."""

    def test_build_health_uses_scan_stats(self):
        from monitoring.truth_report import build_health_section, RPCHealthMetrics

        scan_stats = {
            "quotes_fetched": 4,
            "quotes_total": 8,
            "gates_passed": 4,
            "chains_active": 1,
            "dexes_active": 2,
        }

        health = build_health_section(
            scan_stats=scan_stats,
            reject_histogram={},
            rpc_metrics=RPCHealthMetrics(),
        )

        self.assertEqual(health["quote_fetch_rate"], 0.5)  # 4/8
        self.assertEqual(health["quote_gate_pass_rate"], 1.0)  # 4/4
        self.assertEqual(health["quotes_fetched"], 4)

    def test_pools_preserved_from_spreads(self):
        """STEP 2: pool_buy/pool_sell must be preserved from all_spreads."""
        from monitoring.truth_report import build_truth_report

        all_spreads = [
            {
                "spread_id": "test_001",
                "dex_buy": "uniswap_v3",
                "dex_sell": "sushiswap_v3",
                "pool_buy": "0xUNI_POOL_123",
                "pool_sell": "0xSUSHI_POOL_456",
                "token_in": "WETH",
                "token_out": "USDC",
                "net_pnl_usdc": "0.50",
                "net_pnl_bps": "10.00",
                "confidence": 0.9,
                "is_profitable": True,
                "amount_in_numeraire": "1.000000",
                "execution_blockers": ["EXECUTION_DISABLED_M4"],
            }
        ]

        report = build_truth_report(
            scan_stats={"quotes_fetched": 2, "quotes_total": 4, "gates_passed": 2, "execution_ready_count": 0, "dexes_active": 2},
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
        )

        opp = report.top_opportunities[0]
        # Pool addresses must be preserved, not "unknown"
        self.assertEqual(opp["pool_buy"], "0xUNI_POOL_123")
        self.assertEqual(opp["pool_sell"], "0xSUSHI_POOL_456")
        self.assertNotEqual(opp["pool_buy"], "unknown")
        self.assertNotEqual(opp["pool_sell"], "unknown")

    def test_amounts_preserved_from_spreads(self):
        """STEP 3: amount_in_numeraire must be preserved."""
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
                "net_pnl_usdc": "0.50",
                "amount_in_numeraire": "1.000000",
                "amount_out_buy_numeraire": "3500.000000",
                "confidence": 0.9,
                "is_profitable": True,
                "execution_blockers": ["EXECUTION_DISABLED_M4"],
            }
        ]

        report = build_truth_report(
            scan_stats={"quotes_fetched": 2, "quotes_total": 4, "gates_passed": 2, "execution_ready_count": 0},
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
        )

        opp = report.top_opportunities[0]
        self.assertEqual(opp["amount_in_numeraire"], "1.000000")
        self.assertNotEqual(opp["amount_in_numeraire"], "0")
        self.assertNotEqual(opp["amount_in_numeraire"], "0.000000")

    def test_cross_dex_preserved(self):
        """STEP 1: dex_buy != dex_sell must be preserved."""
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
                "net_pnl_usdc": "0.50",
                "amount_in_numeraire": "1.0",
                "confidence": 0.9,
                "is_profitable": True,
                "execution_blockers": ["EXECUTION_DISABLED_M4"],
            }
        ]

        report = build_truth_report(
            scan_stats={"execution_ready_count": 0},
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
        )

        opp = report.top_opportunities[0]
        self.assertEqual(opp["dex_buy"], "uniswap_v3")
        self.assertEqual(opp["dex_sell"], "sushiswap_v3")
        self.assertNotEqual(opp["dex_buy"], opp["dex_sell"])


class TestRPCHealthMetrics(unittest.TestCase):
    def test_record_rpc_call_success(self):
        from monitoring.truth_report import RPCHealthMetrics

        metrics = RPCHealthMetrics()
        metrics.record_rpc_call(success=True, latency_ms=100)

        self.assertEqual(metrics.rpc_success_count, 1)
        self.assertEqual(metrics.rpc_failed_count, 0)
        self.assertEqual(metrics.total_latency_ms, 100)

    def test_record_rpc_call_failure(self):
        from monitoring.truth_report import RPCHealthMetrics

        metrics = RPCHealthMetrics()
        metrics.record_rpc_call(success=False, latency_ms=0)

        self.assertEqual(metrics.rpc_success_count, 0)
        self.assertEqual(metrics.rpc_failed_count, 1)


class TestBlockerHistogram(unittest.TestCase):
    def test_blocker_histogram_built(self):
        """STEP 5: blocker_histogram from spreads."""
        from monitoring.truth_report import build_blocker_histogram

        spreads = [
            {"execution_blockers": ["EXECUTION_DISABLED_M4"]},
            {"execution_blockers": ["EXECUTION_DISABLED_M4", "LOW_CONFIDENCE"]},
            {"execution_blockers": ["NOT_PROFITABLE"]},
        ]

        histogram = build_blocker_histogram(spreads)

        self.assertEqual(histogram["EXECUTION_DISABLED_M4"], 2)
        self.assertEqual(histogram["LOW_CONFIDENCE"], 1)
        self.assertEqual(histogram["NOT_PROFITABLE"], 1)


if __name__ == "__main__":
    unittest.main()
