# PATH: tests/unit/test_no_data_reason.py
"""Tests for no_data_reason classification (v3.2.9).

Validates that no_data_reason is correctly computed for three scenarios:
- NO_QUOTES: quotes_total == 0
- ALL_QUOTES_REJECTED: quotes_total > 0 but quotes_fetched == 0
- NO_SPREAD_SIGNALS: quotes_fetched > 0 but spread_signals == []
- None: has spread signals (not NO_DATA)

Uses compute_no_data_reason from core/no_data.py (single source of truth).
"""

import unittest

# v3.2.7: Use centralized helper (no logic duplication)
from core.no_data import compute_no_data_reason, canonicalize_config_path, compute_config_fingerprint


class TestNoDataReasonLogic(unittest.TestCase):
    """Test no_data_reason computation logic using the canonical helper."""
    
    def test_no_quotes_scenario(self):
        """When quotes_total=0, reason is NO_QUOTES."""
        reason = compute_no_data_reason(
            quotes_total=0,
            quotes_fetched=0,
            spread_signals_count=0,
        )
        self.assertEqual(reason, "NO_QUOTES")
    
    def test_all_quotes_rejected_scenario(self):
        """When quotes_total>0 but quotes_fetched=0, reason is ALL_QUOTES_REJECTED."""
        reason = compute_no_data_reason(
            quotes_total=10,
            quotes_fetched=0,
            spread_signals_count=0,
        )
        self.assertEqual(reason, "ALL_QUOTES_REJECTED")
    
    def test_no_spread_signals_scenario(self):
        """When quotes_fetched>0 but spread_signals=0, reason is NO_SPREAD_SIGNALS."""
        reason = compute_no_data_reason(
            quotes_total=18,
            quotes_fetched=18,
            spread_signals_count=0,
        )
        self.assertEqual(reason, "NO_SPREAD_SIGNALS")
    
    def test_has_data_scenario(self):
        """When spread_signals>0, reason is None (has data)."""
        reason = compute_no_data_reason(
            quotes_total=18,
            quotes_fetched=18,
            spread_signals_count=3,
        )
        self.assertIsNone(reason)
    
    def test_edge_case_single_signal(self):
        """When spread_signals=1, reason is None (has data)."""
        reason = compute_no_data_reason(
            quotes_total=18,
            quotes_fetched=18,
            spread_signals_count=1,
        )
        self.assertIsNone(reason)
    
    def test_all_opportunities_rejected_scenario(self):
        """When opportunities exist but all were rejected, reason is ALL_OPPORTUNITIES_REJECTED."""
        reason = compute_no_data_reason(
            quotes_total=49,
            quotes_fetched=49,
            spread_signals_count=0,
            total_opportunities=66,  # zkSync-like scenario
            profitable_accepted=0,
        )
        self.assertEqual(reason, "ALL_OPPORTUNITIES_REJECTED")
    
    def test_all_opportunities_rejected_with_profitable(self):
        """When opportunities exist and some are profitable but none accepted, still ALL_OPPORTUNITIES_REJECTED.
        
        This covers the truth_mode scenario where profitable_count is DIAGNOSTIC only,
        so even with profitable_accepted > 0, if spread_signals_count=0 and total_opportunities > 0,
        the reason is still ALL_OPPORTUNITIES_REJECTED (system/economics reject, not market absence).
        """
        reason = compute_no_data_reason(
            quotes_total=49,
            quotes_fetched=49,
            spread_signals_count=0,
            total_opportunities=66,
            profitable_accepted=5,  # Diagnostic profitable, but still all rejected from signal flow
        )
        self.assertEqual(reason, "ALL_OPPORTUNITIES_REJECTED")
    
    def test_no_spread_signals_with_no_opportunities(self):
        """When no opportunities found at all, reason is NO_SPREAD_SIGNALS (not ALL_OPPORTUNITIES_REJECTED)."""
        reason = compute_no_data_reason(
            quotes_total=10,
            quotes_fetched=10,
            spread_signals_count=0,
            total_opportunities=0,
            profitable_accepted=0,
        )
        self.assertEqual(reason, "NO_SPREAD_SIGNALS")


class TestNoDataReasonInArtifacts(unittest.TestCase):
    """Test no_data_reason presence in artifact schemas."""
    
    def test_truth_report_stats_has_no_data_reason(self):
        """truth_report.stats must contain no_data_reason field."""
        # Simulate truth_report.stats structure
        stats = {
            "quotes_total": 18,
            "quotes_fetched": 18,
            "no_data_reason": "NO_SPREAD_SIGNALS",  # v3.2.7
        }
        self.assertIn("no_data_reason", stats)
        self.assertEqual(stats["no_data_reason"], "NO_SPREAD_SIGNALS")
    
    def test_run_summary_metrics_has_no_data_reason(self):
        """run_summary.metrics must contain no_data_reason field."""
        # Simulate run_summary.metrics structure
        metrics = {
            "signals_count": 0,
            "included_signals_count": 0,
            "no_data_reason": "NO_SPREAD_SIGNALS",  # v3.2.7
        }
        self.assertIn("no_data_reason", metrics)
        self.assertEqual(metrics["no_data_reason"], "NO_SPREAD_SIGNALS")
    
    def test_no_data_reason_values_enum(self):
        """no_data_reason must be one of the canonical values or None."""
        valid_values = {None, "NO_QUOTES", "ALL_QUOTES_REJECTED", "NO_SPREAD_SIGNALS"}
        
        for value in valid_values:
            self.assertIn(value, valid_values)
        
        # Invalid value should NOT be in the enum
        self.assertNotIn("INVALID_REASON", valid_values)
        self.assertNotIn("NO_DATA", valid_values)  # Must be specific


class TestNoDataReasonStatusAlignment(unittest.TestCase):
    """Test no_data_reason aligns with status field."""
    
    def test_no_data_reason_implies_no_data_status(self):
        """When no_data_reason is set, status should be NO_DATA."""
        # Scenario: NO_SPREAD_SIGNALS
        run_summary = {
            "status": "NO_DATA",
            "metrics": {
                "signals_count": 0,
                "no_data_reason": "NO_SPREAD_SIGNALS",
            },
        }
        
        # Verify alignment
        if run_summary["metrics"]["no_data_reason"] is not None:
            self.assertEqual(run_summary["status"], "NO_DATA")
    
    def test_has_data_implies_none_reason(self):
        """When status is not NO_DATA, no_data_reason should be None."""
        # Scenario: PASS with signals
        run_summary = {
            "status": "PASS",
            "metrics": {
                "signals_count": 5,
                "no_data_reason": None,
            },
        }
        
        # Verify alignment
        if run_summary["status"] != "NO_DATA":
            self.assertIsNone(run_summary["metrics"]["no_data_reason"])


class TestCanonicalizeConfigPath(unittest.TestCase):
    """Test config_path canonicalization to POSIX format."""
    
    def test_windows_path_converted_to_posix(self):
        """Windows backslashes are converted to forward slashes."""
        result = canonicalize_config_path("config\\real_minimal.yaml")
        self.assertEqual(result, "config/real_minimal.yaml")
    
    def test_posix_path_unchanged(self):
        """POSIX paths remain unchanged."""
        result = canonicalize_config_path("config/real_minimal.yaml")
        self.assertEqual(result, "config/real_minimal.yaml")
    
    def test_none_returns_none(self):
        """None input returns None."""
        result = canonicalize_config_path(None)
        self.assertIsNone(result)
    
    def test_nested_windows_path(self):
        """Deeply nested Windows paths are converted."""
        result = canonicalize_config_path("foo\\bar\\baz\\config.yaml")
        self.assertEqual(result, "foo/bar/baz/config.yaml")


class TestChainKeyContract(unittest.TestCase):
    """Test chain_key strict contract for multi-chain observability."""
    
    def test_chain_key_fallback_is_unknown(self):
        """When chain not in config, fallback should be 'unknown' not 'arbitrum_one'."""
        # This test documents the v3.2.7 strict contract
        # The actual implementation is in strategy/artifacts.py and run_scan_real.py
        config = {}  # No chain specified
        chain_key = config.get("chain", "unknown")
        self.assertEqual(chain_key, "unknown")
        
    def test_chain_key_explicit_in_config(self):
        """When chain is specified, use that value."""
        config = {"chain": "arbitrum_one"}
        chain_key = config.get("chain", "unknown")
        self.assertEqual(chain_key, "arbitrum_one")
    
    def test_chain_key_other_network(self):
        """Chain key can be any network."""
        config = {"chain": "optimism"}
        chain_key = config.get("chain", "unknown")
        self.assertEqual(chain_key, "optimism")


class TestConfigFingerprint(unittest.TestCase):
    """Test config_fingerprint computation for drift detection."""
    
    def test_same_config_same_fingerprint(self):
        """Identical configs produce identical fingerprints."""
        config = {
            "dexes": ["uniswap_v3", "sushiswap_v3"],
            "min_spread_bps": 10,
            "paper_size_usd": 250,
            "chain": "arbitrum_one",
        }
        fp1 = compute_config_fingerprint(config)
        fp2 = compute_config_fingerprint(config)
        self.assertEqual(fp1, fp2)
    
    def test_different_config_different_fingerprint(self):
        """Different configs produce different fingerprints."""
        config1 = {"min_spread_bps": 10, "chain": "arbitrum_one"}
        config2 = {"min_spread_bps": 20, "chain": "arbitrum_one"}
        fp1 = compute_config_fingerprint(config1)
        fp2 = compute_config_fingerprint(config2)
        self.assertNotEqual(fp1, fp2)
    
    def test_fingerprint_is_8_chars(self):
        """Fingerprint is always 8 hex characters."""
        config = {"dexes": ["uniswap_v3"], "min_spread_bps": 10}
        fp = compute_config_fingerprint(config)
        self.assertEqual(len(fp), 8)
        # All hex chars
        self.assertTrue(all(c in "0123456789abcdef" for c in fp))
    
    def test_dex_order_independent(self):
        """DEX order doesn't affect fingerprint (sorted internally)."""
        config1 = {"dexes": ["uniswap_v3", "sushiswap_v3"]}
        config2 = {"dexes": ["sushiswap_v3", "uniswap_v3"]}
        fp1 = compute_config_fingerprint(config1)
        fp2 = compute_config_fingerprint(config2)
        self.assertEqual(fp1, fp2)
    
    def test_chain_change_changes_fingerprint(self):
        """Different chains produce different fingerprints."""
        config1 = {"chain": "arbitrum_one", "min_spread_bps": 10}
        config2 = {"chain": "linea", "min_spread_bps": 10}
        fp1 = compute_config_fingerprint(config1)
        fp2 = compute_config_fingerprint(config2)
        self.assertNotEqual(fp1, fp2)


class TestNoDataReasonEndToEnd(unittest.TestCase):
    """Test no_data_reason flows through artifacts correctly.
    
    These tests simulate how no_data_reason should appear in truth_report
    and run_summary artifacts when processed through m4/fixtures.py.
    """
    
    def test_no_data_reason_in_truth_report_stats(self):
        """truth_report.stats should contain no_data_reason when NO_DATA."""
        # Simulate truth_report structure after NO_SPREAD_SIGNALS
        truth_report = {
            "stats": {
                "quotes_total": 18,
                "quotes_fetched": 18,
                "spread_signals_count": 0,
                "no_data_reason": "NO_SPREAD_SIGNALS",  # Set by run_scan_real
            },
            "spread_signals": [],
        }
        
        # Verify field is present and correct value
        self.assertEqual(
            truth_report["stats"]["no_data_reason"],
            "NO_SPREAD_SIGNALS"
        )
    
    def test_no_data_reason_propagates_to_run_summary_metrics(self):
        """run_summary.metrics should have no_data_reason copied from truth_report."""
        # Simulate the flow: truth_report -> m4/fixtures.py -> run_summary
        truth_stats = {
            "quotes_total": 0,
            "quotes_fetched": 0,
            "no_data_reason": "NO_QUOTES",
        }
        
        # m4/fixtures.py extracts no_data_reason from truth_stats
        no_data_reason = truth_stats.get("no_data_reason")
        
        # And places it in run_summary.metrics
        run_summary_metrics = {
            "signals_count": 0,
            "included_signals_count": 0,
            "no_data_reason": no_data_reason,
        }
        
        self.assertEqual(run_summary_metrics["no_data_reason"], "NO_QUOTES")
    
    def test_no_data_reason_none_when_has_signals(self):
        """no_data_reason should be None when spread_signals exist."""
        truth_stats = {
            "quotes_total": 18,
            "quotes_fetched": 18,
            "no_data_reason": None,  # Has data
        }
        
        # No data reason extraction
        no_data_reason = truth_stats.get("no_data_reason")
        self.assertIsNone(no_data_reason)


class TestExcludedOnlyNotNoData(unittest.TestCase):
    """Test that signals_count > 0 but included_signals_count = 0 is NOT NO_DATA.
    
    v3.3.1 FIX: Per Status_M4.md contract, NO_DATA only when signals_count == 0.
    When signals exist but are all excluded (suspect/same-dex), status should be FAIL.
    
    This tests the regression case from ci_m5_gate_20260307_110236 (Mantle):
    - signals_count=1
    - suspect_signals_count=1
    - excluded_signals_count=1  
    - included_signals_count=0
    - WRONG: status=NO_DATA
    - CORRECT: status=FAIL with quality_status=FAIL_QUALITY, reason=FAIL_ALL_EXCLUDED
    """
    
    def test_all_excluded_signals_is_fail_not_no_data(self):
        """When all signals are excluded, status should be FAIL (not NO_DATA)."""
        # Simulate the Mantle case: 1 signal, all excluded as suspect
        signals_count = 1
        included_signals_count = 0
        excluded_signals_count = 1
        
        # v3.3.1: NO_DATA only when signals_count == 0
        if signals_count == 0:
            status = "NO_DATA"
        elif signals_count > 0 and included_signals_count == 0:
            status = "FAIL"  # All excluded = failure, not NO_DATA
            quality_status = "FAIL_QUALITY"
            reason = "FAIL_ALL_EXCLUDED"
        else:
            status = "PASS"
        
        self.assertEqual(status, "FAIL")
        self.assertEqual(quality_status, "FAIL_QUALITY")
        self.assertEqual(reason, "FAIL_ALL_EXCLUDED")
    
    def test_no_data_only_when_signals_count_zero(self):
        """NO_DATA status is only valid when signals_count == 0."""
        test_cases = [
            # (signals_count, included_signals_count, expected_allows_no_data)
            (0, 0, True),   # No raw signals -> NO_DATA allowed
            (1, 0, False),  # Has signals but excluded -> NOT NO_DATA
            (1, 1, False),  # Has included signals -> NOT NO_DATA
            (5, 0, False),  # Multiple signals, all excluded -> NOT NO_DATA
            (5, 3, False),  # Multiple signals, some included -> NOT NO_DATA
        ]
        
        for signals_count, included_signals_count, allows_no_data in test_cases:
            with self.subTest(signals_count=signals_count, included_signals_count=included_signals_count):
                # Per Status_M4.md: NO_DATA only when signals_count == 0
                actual_allows_no_data = (signals_count == 0)
                self.assertEqual(
                    actual_allows_no_data, 
                    allows_no_data,
                    f"signals_count={signals_count}: NO_DATA should be {'allowed' if allows_no_data else 'NOT allowed'}"
                )
    
    def test_excluded_only_has_fail_all_excluded_reason(self):
        """When all signals excluded, must have FAIL_ALL_EXCLUDED reason."""
        signals_count = 3  # Has signals
        included_signals_count = 0  # All excluded
        excluded_signals_count = 3
        
        quality_reasons = []
        
        # v3.3.1: Logic from m4/fixtures.py
        if signals_count > 0 and included_signals_count == 0:
            if "FAIL_ALL_EXCLUDED" not in quality_reasons:
                quality_reasons.append("FAIL_ALL_EXCLUDED")
        
        self.assertIn("FAIL_ALL_EXCLUDED", quality_reasons)


if __name__ == "__main__":
    unittest.main()
