# PATH: tests/unit/test_truth_report.py
"""
Unit tests for truth report module.

Includes:
- RANKING CONTRACT tests (deterministic sort)
- GATE BREAKDOWN CONTRACT tests (canonical keys)
- Schema version policy tests
"""

import unittest
from decimal import Decimal

from monitoring.truth_report import (
    SCHEMA_VERSION, GATE_BREAKDOWN_KEYS, ERROR_TO_GATE_CATEGORY,
    build_gate_breakdown, map_error_to_gate_category,
    build_dex_coverage, build_health_section,
    rank_opportunities, _opportunity_sort_key,
    RPCHealthMetrics, TruthReport,
)


class TestSchemaVersionPolicy(unittest.TestCase):
    """
    Schema version policy tests.
    
    SCHEMA_VERSION is the SINGLE SOURCE OF TRUTH.
    """

    def test_schema_version_is_constant(self):
        """SCHEMA_VERSION is a constant string."""
        self.assertIsInstance(SCHEMA_VERSION, str)
        self.assertTrue(len(SCHEMA_VERSION) > 0)

    def test_schema_version_format(self):
        """SCHEMA_VERSION follows semver format."""
        parts = SCHEMA_VERSION.split(".")
        self.assertEqual(len(parts), 3)  # major.minor.patch
        for part in parts:
            self.assertTrue(part.isdigit())

    def test_schema_version_at_least_3_0_0(self):
        """SCHEMA_VERSION is at least 3.0.0."""
        major = int(SCHEMA_VERSION.split(".")[0])
        self.assertGreaterEqual(major, 3)

    def test_truth_report_uses_schema_version(self):
        """TruthReport.to_dict() includes schema_version."""
        report = TruthReport()
        d = report.to_dict()
        self.assertEqual(d["schema_version"], SCHEMA_VERSION)


class TestGateBreakdownContract(unittest.TestCase):
    """
    GATE BREAKDOWN CONTRACT tests.
    
    Keys MUST be [revert, slippage, infra, other].
    """

    def test_gate_breakdown_keys_constant(self):
        """GATE_BREAKDOWN_KEYS is a frozenset."""
        self.assertIsInstance(GATE_BREAKDOWN_KEYS, frozenset)
        self.assertEqual(GATE_BREAKDOWN_KEYS, {"revert", "slippage", "infra", "other"})

    def test_build_gate_breakdown_has_all_keys(self):
        """build_gate_breakdown returns exactly canonical keys."""
        breakdown = build_gate_breakdown({})
        self.assertEqual(set(breakdown.keys()), GATE_BREAKDOWN_KEYS)

    def test_build_gate_breakdown_empty_histogram(self):
        """Empty histogram → all zeros."""
        breakdown = build_gate_breakdown({})
        for key in GATE_BREAKDOWN_KEYS:
            self.assertEqual(breakdown[key], 0)

    def test_build_gate_breakdown_with_rejects(self):
        """Rejects are categorized correctly."""
        histogram = {
            "QUOTE_REVERT": 5,
            "SLIPPAGE_TOO_HIGH": 3,
            "INFRA_RPC_ERROR": 2,
            "UNKNOWN_ERROR": 1,
        }
        breakdown = build_gate_breakdown(histogram)
        
        self.assertEqual(breakdown["revert"], 5)
        self.assertEqual(breakdown["slippage"], 3)
        self.assertEqual(breakdown["infra"], 2)
        self.assertEqual(breakdown["other"], 1)


class TestErrorCodeMapping(unittest.TestCase):
    """
    ERROR CODE MAPPING tests.
    
    Reject reasons are mapped to gate categories.
    """

    def test_quote_revert_maps_to_revert(self):
        """QUOTE_REVERT → revert."""
        self.assertEqual(map_error_to_gate_category("QUOTE_REVERT"), "revert")

    def test_slippage_maps_to_slippage(self):
        """SLIPPAGE_TOO_HIGH → slippage."""
        self.assertEqual(map_error_to_gate_category("SLIPPAGE_TOO_HIGH"), "slippage")

    def test_infra_error_maps_to_infra(self):
        """INFRA_RPC_ERROR → infra."""
        self.assertEqual(map_error_to_gate_category("INFRA_RPC_ERROR"), "infra")

    def test_unknown_maps_to_other(self):
        """Unknown errors → other."""
        self.assertEqual(map_error_to_gate_category("UNKNOWN_ERROR"), "other")
        self.assertEqual(map_error_to_gate_category("SOMETHING_ELSE"), "other")


class TestRankingContract(unittest.TestCase):
    """
    RANKING CONTRACT tests.
    
    Opportunities are sorted by:
      1. is_profitable DESC
      2. net_pnl_usdc DESC
      3. net_pnl_bps DESC
      4. confidence DESC
      5. spread_id ASC (tiebreaker)
    """

    def test_ranking_profitable_first(self):
        """Profitable opportunities come first."""
        opps = [
            {"spread_id": "spread_a", "is_profitable": False, "net_pnl_usdc": "0", "net_pnl_bps": "0", "confidence": 0.5},
            {"spread_id": "spread_b", "is_profitable": True, "net_pnl_usdc": "1", "net_pnl_bps": "10", "confidence": 0.5},
        ]
        ranked = rank_opportunities(opps)
        self.assertEqual(ranked[0]["spread_id"], "spread_b")

    def test_ranking_higher_pnl_first(self):
        """Higher PnL opportunities come first (within profitable)."""
        opps = [
            {"spread_id": "spread_a", "is_profitable": True, "net_pnl_usdc": "1.0", "net_pnl_bps": "10", "confidence": 0.5},
            {"spread_id": "spread_b", "is_profitable": True, "net_pnl_usdc": "5.0", "net_pnl_bps": "50", "confidence": 0.5},
        ]
        ranked = rank_opportunities(opps)
        self.assertEqual(ranked[0]["spread_id"], "spread_b")

    def test_ranking_higher_confidence_tiebreaker(self):
        """Higher confidence is tiebreaker for equal PnL."""
        opps = [
            {"spread_id": "spread_a", "is_profitable": True, "net_pnl_usdc": "1.0", "net_pnl_bps": "10", "confidence": 0.7},
            {"spread_id": "spread_b", "is_profitable": True, "net_pnl_usdc": "1.0", "net_pnl_bps": "10", "confidence": 0.9},
        ]
        ranked = rank_opportunities(opps)
        self.assertEqual(ranked[0]["spread_id"], "spread_b")

    def test_ranking_spread_id_final_tiebreaker(self):
        """spread_id ASC is final tiebreaker."""
        opps = [
            {"spread_id": "spread_b", "is_profitable": True, "net_pnl_usdc": "1.0", "net_pnl_bps": "10", "confidence": 0.5},
            {"spread_id": "spread_a", "is_profitable": True, "net_pnl_usdc": "1.0", "net_pnl_bps": "10", "confidence": 0.5},
        ]
        ranked = rank_opportunities(opps)
        self.assertEqual(ranked[0]["spread_id"], "spread_a")

    def test_ranking_deterministic(self):
        """Same input → same output (deterministic)."""
        opps = [
            {"spread_id": "spread_c", "is_profitable": True, "net_pnl_usdc": "2.0", "net_pnl_bps": "20", "confidence": 0.6},
            {"spread_id": "spread_a", "is_profitable": True, "net_pnl_usdc": "5.0", "net_pnl_bps": "50", "confidence": 0.8},
            {"spread_id": "spread_b", "is_profitable": False, "net_pnl_usdc": "-1.0", "net_pnl_bps": "-10", "confidence": 0.3},
        ]
        
        ranked1 = rank_opportunities(opps.copy())
        ranked2 = rank_opportunities(opps.copy())
        
        self.assertEqual(
            [o["spread_id"] for o in ranked1],
            [o["spread_id"] for o in ranked2],
        )

    def test_ranking_stability_order(self):
        """Full sort order is verified."""
        opps = [
            {"spread_id": "spread_3", "is_profitable": False, "net_pnl_usdc": "-1.0", "net_pnl_bps": "-10", "confidence": 0.9},
            {"spread_id": "spread_1", "is_profitable": True, "net_pnl_usdc": "5.0", "net_pnl_bps": "50", "confidence": 0.8},
            {"spread_id": "spread_2", "is_profitable": True, "net_pnl_usdc": "3.0", "net_pnl_bps": "30", "confidence": 0.7},
        ]
        
        ranked = rank_opportunities(opps)
        
        # Expected order: spread_1 (profitable, $5), spread_2 (profitable, $3), spread_3 (not profitable)
        self.assertEqual(ranked[0]["spread_id"], "spread_1")
        self.assertEqual(ranked[1]["spread_id"], "spread_2")
        self.assertEqual(ranked[2]["spread_id"], "spread_3")


class TestDexCoverage(unittest.TestCase):
    """DEX coverage tests."""

    def test_build_dex_coverage(self):
        """build_dex_coverage returns correct structure."""
        coverage = build_dex_coverage(
            configured_dex_ids={"uniswap_v3", "sushiswap_v3"},
            dexes_with_quotes={"uniswap_v3"},
            dexes_passed_gates={"uniswap_v3"},
        )
        
        self.assertEqual(coverage["configured_dexes"], 2)
        self.assertEqual(coverage["dexes_active"], 1)
        self.assertEqual(coverage["dexes_passed_gates"], 1)


class TestRPCHealthMetrics(unittest.TestCase):
    """RPC health metrics tests."""

    def test_success_rate_calculation(self):
        """Success rate is calculated correctly."""
        metrics = RPCHealthMetrics()
        metrics.record_success(100)
        metrics.record_success(100)
        metrics.record_failure()
        
        self.assertAlmostEqual(metrics.rpc_success_rate, 2/3, places=3)

    def test_reconcile_with_rejects(self):
        """Reconciliation adjusts failed count."""
        metrics = RPCHealthMetrics()
        metrics.record_success(100)
        
        metrics.reconcile_with_rejects({"INFRA_RPC_ERROR": 5})
        
        self.assertEqual(metrics.rpc_failed_count, 5)


if __name__ == "__main__":
    unittest.main()
