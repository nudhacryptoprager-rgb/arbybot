# PATH: tests/unit/test_truth_report.py
"""
Unit tests for truth_report module.

Tests TruthReport, RPCHealthMetrics, and health building functions.
Includes regression tests for schema contract stability.
"""

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from monitoring.truth_report import (
    TruthReport,
    RPCHealthMetrics,
    SCHEMA_VERSION,
    GATE_BREAKDOWN_KEYS,
    ERROR_TO_GATE_CATEGORY,
    calculate_confidence,
    build_truth_report,
    build_health_section,
    build_gate_breakdown,
    build_dex_coverage,
    map_error_to_gate_category,
)


class TestRPCHealthMetrics(unittest.TestCase):
    """Tests for RPCHealthMetrics class."""

    def test_initial_state(self):
        """Initial state has zero counts."""
        metrics = RPCHealthMetrics()
        self.assertEqual(metrics.rpc_success_count, 0)
        self.assertEqual(metrics.rpc_failed_count, 0)
        self.assertEqual(metrics.quote_call_attempts, 0)
        self.assertEqual(metrics.rpc_total_requests, 0)
        self.assertEqual(metrics.rpc_success_rate, 0.0)

    def test_record_success(self):
        """Recording success updates counts."""
        metrics = RPCHealthMetrics()
        metrics.record_success(latency_ms=100)
        metrics.record_success(latency_ms=200)

        self.assertEqual(metrics.rpc_success_count, 2)
        self.assertEqual(metrics.quote_call_attempts, 2)
        self.assertEqual(metrics.avg_latency_ms, 150)

    def test_record_failure(self):
        """Recording failure updates counts."""
        metrics = RPCHealthMetrics()
        metrics.record_failure()
        metrics.record_failure()

        self.assertEqual(metrics.rpc_failed_count, 2)
        self.assertEqual(metrics.quote_call_attempts, 2)

    def test_success_rate_calculation(self):
        """Success rate is calculated correctly."""
        metrics = RPCHealthMetrics()
        metrics.record_success()
        metrics.record_success()
        metrics.record_failure()

        self.assertAlmostEqual(metrics.rpc_success_rate, 0.6667, places=3)

    def test_reconcile_with_rejects_adds_missing(self):
        """Reconciliation adds INFRA_RPC_ERROR to failed count."""
        metrics = RPCHealthMetrics()
        metrics.reconcile_with_rejects({"INFRA_RPC_ERROR": 5})

        self.assertEqual(metrics.rpc_failed_count, 5)
        self.assertEqual(metrics.rpc_total_requests, 5)

    def test_reconcile_with_rejects_preserves_higher(self):
        """Reconciliation preserves higher failure count."""
        metrics = RPCHealthMetrics()
        for _ in range(10):
            metrics.record_failure()
        metrics.reconcile_with_rejects({"INFRA_RPC_ERROR": 5})
        self.assertEqual(metrics.rpc_failed_count, 10)

    def test_to_dict(self):
        """to_dict returns proper structure."""
        metrics = RPCHealthMetrics()
        metrics.record_success(100)
        metrics.record_failure()
        d = metrics.to_dict()

        self.assertIn("rpc_success_rate", d)
        self.assertIn("rpc_total_requests", d)
        self.assertIn("rpc_failed_requests", d)
        self.assertIn("quote_call_attempts", d)


class TestSchemaVersionPolicy(unittest.TestCase):
    """
    STEP 9: Schema version policy tests.
    
    POLICY: schema_version MUST NOT change without explicit bump.
    This test ensures SCHEMA_VERSION is the single source of truth.
    """

    def test_schema_version_is_constant(self):
        """SCHEMA_VERSION is defined as constant."""
        self.assertEqual(SCHEMA_VERSION, "3.0.0")

    def test_schema_version_in_report(self):
        """TruthReport uses SCHEMA_VERSION constant."""
        report = TruthReport()
        d = report.to_dict()
        self.assertEqual(d["schema_version"], SCHEMA_VERSION)

    def test_schema_version_format(self):
        """schema_version follows semver format."""
        import re
        pattern = r"^\d+\.\d+\.\d+$"
        self.assertRegex(SCHEMA_VERSION, pattern)

    def test_build_truth_report_uses_constant(self):
        """build_truth_report uses SCHEMA_VERSION constant."""
        report = build_truth_report({}, {}, [])
        d = report.to_dict()
        self.assertEqual(d["schema_version"], SCHEMA_VERSION)

    def test_schema_version_at_least_3_0_0(self):
        """Schema version should be >= 3.0.0 (never regress)."""
        major, minor, patch = map(int, SCHEMA_VERSION.split("."))
        self.assertGreaterEqual(major, 3)


class TestGateBreakdownContract(unittest.TestCase):
    """
    STEP 3: Gate breakdown contract tests.
    
    CONTRACT: gate_breakdown must have exactly [revert, slippage, infra, other].
    """

    def test_gate_breakdown_keys_constant(self):
        """GATE_BREAKDOWN_KEYS is defined."""
        self.assertEqual(GATE_BREAKDOWN_KEYS, frozenset(["revert", "slippage", "infra", "other"]))

    def test_build_gate_breakdown_has_all_keys(self):
        """build_gate_breakdown returns all canonical keys."""
        breakdown = build_gate_breakdown({})
        self.assertEqual(set(breakdown.keys()), set(GATE_BREAKDOWN_KEYS))

    def test_build_gate_breakdown_categories(self):
        """Gate breakdown categorizes rejects correctly."""
        reject_histogram = {
            "QUOTE_REVERT": 10,
            "SLIPPAGE_TOO_HIGH": 5,
            "INFRA_RPC_ERROR": 3,
            "OTHER_REASON": 2,
        }
        breakdown = build_gate_breakdown(reject_histogram)

        self.assertEqual(breakdown["revert"], 10)
        self.assertEqual(breakdown["slippage"], 5)
        self.assertEqual(breakdown["infra"], 3)
        self.assertEqual(breakdown["other"], 2)

    def test_gate_breakdown_in_health_section(self):
        """Health section includes gate_breakdown with canonical keys."""
        reject_histogram = {
            "QUOTE_REVERT": 5,
            "SLIPPAGE_TOO_HIGH": 3,
            "INFRA_RPC_ERROR": 2,
        }
        health = build_health_section({}, reject_histogram)

        self.assertIn("gate_breakdown", health)
        self.assertEqual(set(health["gate_breakdown"].keys()), set(GATE_BREAKDOWN_KEYS))


class TestErrorToGateMapping(unittest.TestCase):
    """
    STEP 4: Error code to gate category mapping tests.
    
    QUOTE_REVERT and INFRA_RPC_ERROR must not mask each other.
    """

    def test_error_mapping_defined(self):
        """ERROR_TO_GATE_CATEGORY is defined."""
        self.assertIn("QUOTE_REVERT", ERROR_TO_GATE_CATEGORY)
        self.assertIn("SLIPPAGE_TOO_HIGH", ERROR_TO_GATE_CATEGORY)
        self.assertIn("INFRA_RPC_ERROR", ERROR_TO_GATE_CATEGORY)

    def test_quote_revert_maps_to_revert(self):
        """QUOTE_REVERT maps to 'revert'."""
        self.assertEqual(map_error_to_gate_category("QUOTE_REVERT"), "revert")

    def test_infra_error_maps_to_infra(self):
        """INFRA_RPC_ERROR maps to 'infra' (not 'revert')."""
        self.assertEqual(map_error_to_gate_category("INFRA_RPC_ERROR"), "infra")

    def test_slippage_maps_to_slippage(self):
        """SLIPPAGE_TOO_HIGH maps to 'slippage'."""
        self.assertEqual(map_error_to_gate_category("SLIPPAGE_TOO_HIGH"), "slippage")

    def test_unknown_maps_to_other(self):
        """Unknown reasons map to 'other'."""
        self.assertEqual(map_error_to_gate_category("UNKNOWN_REASON"), "other")
        self.assertEqual(map_error_to_gate_category("SOME_NEW_ERROR"), "other")


class TestDexCoverage(unittest.TestCase):
    """
    STEP 2: DEX coverage tests.
    
    Separate configured vs active vs passed gates.
    """

    def test_build_dex_coverage(self):
        """build_dex_coverage returns proper structure."""
        coverage = build_dex_coverage(
            configured_dex_ids={"uniswap_v3", "sushiswap_v3", "camelot_v3"},
            dexes_with_quotes={"uniswap_v3", "sushiswap_v3"},
            dexes_passed_gates={"uniswap_v3"},
        )

        self.assertEqual(coverage["configured_dexes"], 3)
        self.assertEqual(coverage["dexes_active"], 2)
        self.assertEqual(coverage["dexes_passed_gates"], 1)
        self.assertIn("uniswap_v3", coverage["configured_dex_ids"])
        self.assertIn("uniswap_v3", coverage["dexes_active_ids"])
        self.assertIn("uniswap_v3", coverage["dexes_passed_gates_ids"])

    def test_health_section_with_dex_coverage(self):
        """Health section includes dex_coverage when provided."""
        health = build_health_section(
            scan_stats={},
            reject_histogram={},
            configured_dex_ids={"a", "b"},
            dexes_with_quotes={"a"},
            dexes_passed_gates=set(),
        )

        self.assertIn("dex_coverage", health)
        self.assertEqual(health["dex_coverage"]["configured_dexes"], 2)
        self.assertEqual(health["dex_coverage"]["dexes_active"], 1)


class TestBuildHealthSection(unittest.TestCase):
    """Tests for build_health_section function."""

    def test_basic_health_section(self):
        """Builds basic health section."""
        scan_stats = {
            "quote_fetch_rate": 0.9,
            "quote_gate_pass_rate": 0.8,
            "chains_active": 2,
            "dexes_active": 4,
            "pairs_covered": 10,
            "pools_scanned": 50,
        }
        reject_histogram = {"QUOTE_REVERT": 5, "SLIPPAGE_TOO_HIGH": 3}

        health = build_health_section(scan_stats, reject_histogram)

        self.assertAlmostEqual(health["quote_fetch_rate"], 0.9, places=2)
        self.assertEqual(health["chains_active"], 2)
        self.assertEqual(len(health["top_reject_reasons"]), 2)

    def test_rpc_consistency_with_errors(self):
        """Health section reconciles RPC metrics with rejects."""
        scan_stats = {}
        reject_histogram = {"INFRA_RPC_ERROR": 10}
        rpc_metrics = RPCHealthMetrics()

        health = build_health_section(scan_stats, reject_histogram, rpc_metrics)

        self.assertGreater(health["rpc_total_requests"], 0)
        self.assertGreaterEqual(health["rpc_failed_requests"], 10)


class TestTruthReport(unittest.TestCase):
    """Tests for TruthReport class."""

    def test_create_truth_report(self):
        """Can create TruthReport."""
        report = TruthReport()
        self.assertIsNotNone(report.timestamp)
        self.assertEqual(report.mode, "REGISTRY")

    def test_to_dict(self):
        """to_dict includes all fields."""
        report = TruthReport(mode="DISCOVERY")
        d = report.to_dict()

        self.assertEqual(d["schema_version"], "3.0.0")
        self.assertEqual(d["mode"], "DISCOVERY")
        self.assertIn("health", d)
        self.assertIn("pnl_normalized", d)

    def test_to_json(self):
        """to_json produces valid JSON."""
        report = TruthReport()
        json_str = report.to_json()
        parsed = json.loads(json_str)
        self.assertIn("schema_version", parsed)

    def test_save_report(self):
        """Can save report to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = TruthReport()
            path = Path(tmpdir) / "test_report.json"
            report.save(path)

            self.assertTrue(path.exists())
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(loaded["schema_version"], "3.0.0")


class TestRunModeInReport(unittest.TestCase):
    """Tests for run_mode field in TruthReport."""

    def test_default_run_mode(self):
        """Default run_mode is SMOKE_SIMULATOR."""
        report = TruthReport()
        self.assertEqual(report.run_mode, "SMOKE_SIMULATOR")

    def test_run_mode_in_dict(self):
        """run_mode is included in to_dict output."""
        report = TruthReport(run_mode="REGISTRY_REAL")
        d = report.to_dict()
        self.assertIn("run_mode", d)
        self.assertEqual(d["run_mode"], "REGISTRY_REAL")


class TestTopRejectReasonsFormat(unittest.TestCase):
    """Tests for top_reject_reasons format."""

    def test_top_reject_reasons_is_list(self):
        """top_reject_reasons is a list."""
        reject_histogram = {"QUOTE_REVERT": 5, "SLIPPAGE_TOO_HIGH": 3}
        health = build_health_section({}, reject_histogram)
        
        self.assertIsInstance(health["top_reject_reasons"], list)

    def test_top_reject_reasons_format(self):
        """Each entry is [reason, count] format."""
        reject_histogram = {"QUOTE_REVERT": 5, "SLIPPAGE_TOO_HIGH": 3}
        health = build_health_section({}, reject_histogram)
        
        for entry in health["top_reject_reasons"]:
            self.assertIsInstance(entry, list)
            self.assertEqual(len(entry), 2)
            self.assertIsInstance(entry[0], str)
            self.assertIsInstance(entry[1], int)

    def test_top_reject_reasons_sorted_descending(self):
        """top_reject_reasons are sorted by count descending."""
        reject_histogram = {"A": 1, "B": 5, "C": 3}
        health = build_health_section({}, reject_histogram)
        
        counts = [entry[1] for entry in health["top_reject_reasons"]]
        self.assertEqual(counts, sorted(counts, reverse=True))


class TestExecutableTerminology(unittest.TestCase):
    """Tests for executable terminology clarity."""

    def test_stats_has_both_fields(self):
        """Stats includes both paper_executable_spreads and execution_ready_count."""
        scan_stats = {
            "spread_ids_total": 10,
            "spread_ids_profitable": 5,
            "spread_ids_executable": 2,
            "execution_ready_count": 0,
        }
        report = build_truth_report(scan_stats, {}, [])

        self.assertIn("paper_executable_spreads", report.stats)
        self.assertIn("execution_ready_count", report.stats)

    def test_opportunities_have_execution_blockers(self):
        """Opportunities include execution_blockers field."""
        opportunities = [{"spread_id": "s1", "net_pnl_usdc": "1.00"}]
        report = build_truth_report({}, {}, opportunities, run_mode="SMOKE_SIMULATOR")

        for opp in report.top_opportunities:
            self.assertIn("execution_blockers", opp)
            self.assertIn("is_execution_ready", opp)


class TestBuildTruthReport(unittest.TestCase):
    """Tests for build_truth_report function."""

    def test_build_complete_report(self):
        """Builds complete report from scan data."""
        scan_stats = {
            "spread_ids_total": 10,
            "spread_ids_profitable": 5,
            "spread_ids_executable": 2,
        }
        reject_histogram = {"QUOTE_REVERT": 3}
        opportunities = [
            {"spread_id": "s1", "net_pnl_usdc": "1.00"},
            {"spread_id": "s2", "net_pnl_usdc": "0.50"},
        ]
        paper_stats = {
            "total_pnl_usdc": "1.500000",
            "notion_capital_usdc": "10000.000000",
        }

        report = build_truth_report(
            scan_stats=scan_stats,
            reject_histogram=reject_histogram,
            opportunities=opportunities,
            paper_session_stats=paper_stats,
        )

        self.assertEqual(report.stats["spread_ids_total"], 10)
        self.assertEqual(len(report.top_opportunities), 2)

    def test_pnl_fields_are_strings(self):
        """All PnL fields are strings (no float)."""
        report = build_truth_report({}, {}, [])
        d = report.to_dict()

        self.assertIsInstance(d["cumulative_pnl"]["total_usdc"], str)
        self.assertIsInstance(d["pnl"]["signal_pnl_usdc"], str)


class TestCalculateConfidence(unittest.TestCase):
    """Tests for calculate_confidence function."""

    def test_all_ones(self):
        """All 1.0 inputs returns 1.0."""
        score = calculate_confidence(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertEqual(score, 1.0)

    def test_all_zeros(self):
        """All 0.0 inputs returns 0.0."""
        score = calculate_confidence(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(score, 0.0)

    def test_returns_float(self):
        """Returns float type."""
        score = calculate_confidence(0.5, 0.5, 0.5)
        self.assertIsInstance(score, float)


if __name__ == "__main__":
    unittest.main()
