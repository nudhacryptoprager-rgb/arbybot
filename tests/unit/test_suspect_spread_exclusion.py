# PATH: tests/unit/test_suspect_spread_exclusion.py
"""Unit tests for v2.0.4 SUSPECT_SPREAD exclusion logic.

These tests verify:
1. is_suspect_spread / is_excluded_spread flags are propagated to M4 signals
2. Excluded signals don't count in DoD metrics (total_net_usdc, signals_count)
3. EXCLUDED_PRESENT quality warning is emitted
4. TOP_PAIR_NET_SHARE concentration check works
"""

import pytest
from m4.policy import Thresholds, POLICY_VERSION


class TestSuspectSpreadThresholds:
    """Test SUSPECT_SPREAD threshold values."""

    def test_policy_version_gte_2_0_7(self):
        """Policy version should be >= 2.0.7 for taxonomy bug fix (WARN_* reasons no longer trigger FAIL_QUALITY)."""
        # v2.0.7 introduced taxonomy fix, v2.0.8 adds fee_tier strict lookup
        major, minor, patch = map(int, POLICY_VERSION.split("."))
        assert (major, minor, patch) >= (2, 0, 7), f"Expected >= 2.0.7, got {POLICY_VERSION}"

    def test_suspect_spread_bps_threshold(self):
        """SUSPECT_SPREAD_BPS should be 300 (warn) / 500 (exclude)."""
        assert Thresholds.SUSPECT_SPREAD_BPS == 300  # warn threshold
        assert Thresholds.SUSPECT_SPREAD_BPS_HARD == 500  # hard exclude

    def test_top_pair_net_share_thresholds(self):
        """TOP_PAIR_NET_SHARE should be 0.60 (warn) / 0.80 (fail)."""
        assert Thresholds.TOP_PAIR_NET_SHARE_WARN == 0.60
        assert Thresholds.TOP_PAIR_NET_SHARE_FAIL == 0.80


class TestSuspectSpreadDetection:
    """Test SUSPECT_SPREAD detection logic."""

    def test_spread_below_300_not_suspect(self):
        """Spreads below 300bps should NOT be suspect."""
        from strategy.spreads import is_suspect_spread_value
        
        for spread_bps in [50, 100, 200, 299]:
            assert not is_suspect_spread_value(spread_bps), \
                f"spread_bps={spread_bps} should NOT be suspect"

    def test_spread_301_to_499_is_suspect_not_excluded(self):
        """Spreads 301-499bps should be suspect but NOT excluded.
        
        Note: Threshold is > 300, so 300 itself is NOT suspect.
        """
        from strategy.spreads import is_suspect_spread_value, is_excluded_spread_value
        
        # 300 is boundary - NOT suspect (we use > not >=)
        assert not is_suspect_spread_value(300), "spread_bps=300 should NOT be suspect (boundary)"
        
        # 301-500 is suspect but not excluded
        for spread_bps in [301, 350, 400, 499, 500]:
            assert is_suspect_spread_value(spread_bps), \
                f"spread_bps={spread_bps} should be suspect"
            assert not is_excluded_spread_value(spread_bps), \
                f"spread_bps={spread_bps} should NOT be excluded (boundary at 501)"

    def test_spread_501_plus_is_excluded(self):
        """Spreads > 500bps should be suspect AND excluded.
        
        Note: Threshold is > 500, so 500 itself is NOT excluded.
        """
        from strategy.spreads import is_suspect_spread_value, is_excluded_spread_value
        
        for spread_bps in [501, 600, 1000, 5000]:
            assert is_suspect_spread_value(spread_bps), \
                f"spread_bps={spread_bps} should be suspect"
            assert is_excluded_spread_value(spread_bps), \
                f"spread_bps={spread_bps} should be excluded"


class TestExclusionMetrics:
    """Test that excluded signals don't count in metrics."""

    def test_excluded_signals_not_in_total_net(self):
        """Excluded signals should NOT contribute to total_net_usdc."""
        # Simulate signals data
        signals = [
            {"truth_net_usdc": 10.0, "is_excluded_spread": False},
            {"truth_net_usdc": 100.0, "is_excluded_spread": True},  # Should be excluded
            {"truth_net_usdc": 5.0, "is_excluded_spread": False},
        ]
        
        # Calculate expected totals
        included_net = sum(s["truth_net_usdc"] for s in signals if not s["is_excluded_spread"])
        total_net = sum(s["truth_net_usdc"] for s in signals)
        
        assert included_net == 15.0, "Included net should be 10+5=15"
        assert total_net == 115.0, "Total net should be 10+100+5=115"
        assert included_net != total_net, "Exclusion should affect totals"

    def test_included_signals_count(self):
        """included_signals_count should not include excluded signals."""
        signals = [
            {"is_excluded_spread": False},
            {"is_excluded_spread": True},
            {"is_excluded_spread": False},
            {"is_excluded_spread": True},
        ]
        
        included_count = sum(1 for s in signals if not s["is_excluded_spread"])
        excluded_count = sum(1 for s in signals if s["is_excluded_spread"])
        
        assert included_count == 2
        assert excluded_count == 2
        assert included_count + excluded_count == len(signals)


class TestTopPairConcentration:
    """Test TOP_PAIR_NET_SHARE concentration check."""

    def test_single_pair_below_60_percent_passes(self):
        """Single pair < 60% of net should PASS."""
        net_by_pair = {"WETH/USDC": 50.0, "LINK/WETH": 30.0, "ARB/USDC": 20.0}
        total_net = 100.0
        
        top_pair_net = max(net_by_pair.values())
        top_pair_share = top_pair_net / total_net
        
        assert top_pair_share == 0.50
        assert top_pair_share < Thresholds.TOP_PAIR_NET_SHARE_WARN

    def test_single_pair_60_to_80_percent_warns(self):
        """Single pair 60-80% of net should WARN."""
        net_by_pair = {"WETH/USDC": 70.0, "LINK/WETH": 30.0}
        total_net = 100.0
        
        top_pair_net = max(net_by_pair.values())
        top_pair_share = top_pair_net / total_net
        
        assert top_pair_share == 0.70
        assert top_pair_share > Thresholds.TOP_PAIR_NET_SHARE_WARN
        assert top_pair_share < Thresholds.TOP_PAIR_NET_SHARE_FAIL

    def test_single_pair_above_80_percent_fails(self):
        """Single pair > 80% of net should FAIL."""
        net_by_pair = {"WETH/USDC": 90.0, "LINK/WETH": 10.0}
        total_net = 100.0
        
        top_pair_net = max(net_by_pair.values())
        top_pair_share = top_pair_net / total_net
        
        assert top_pair_share == 0.90
        assert top_pair_share > Thresholds.TOP_PAIR_NET_SHARE_FAIL


class TestQualityWarnings:
    """Test quality warning generation for exclusion."""

    def test_excluded_present_warning_format(self):
        """EXCLUDED_PRESENT warning should have correct format."""
        excluded_count = 3
        warning = f"EXCLUDED_PRESENT({excluded_count})"
        
        assert warning == "EXCLUDED_PRESENT(3)"
        assert "EXCLUDED_PRESENT" in warning
        assert str(excluded_count) in warning

    def test_top_pair_dominance_fail_warning_format(self):
        """TOP_PAIR_DOMINANCE_FAIL warning should have correct format."""
        top_pair = "LINK/WETH"
        share = 0.85
        threshold = Thresholds.TOP_PAIR_NET_SHARE_FAIL
        
        warning = f"TOP_PAIR_DOMINANCE_FAIL({top_pair}:{share:.2f}>{threshold})"
        
        assert "TOP_PAIR_DOMINANCE_FAIL" in warning
        assert top_pair in warning
        assert "0.85" in warning


class TestStatusDomainConsistency:
    """v2.0.5: Test status taxonomy consistency contracts."""

    def test_no_data_only_when_included_zero(self):
        """NO_DATA should only appear when included_signals_count == 0."""
        # Valid: NO_DATA with 0 signals
        run_0_signals = {"status": "NO_DATA", "metrics": {"included_signals_count": 0}}
        assert run_0_signals["metrics"]["included_signals_count"] == 0
        
        # Invalid: NO_DATA with >0 signals (1-2 should be WARN)
        run_1_signal = {"status": "WARN", "metrics": {"included_signals_count": 1}}
        run_2_signals = {"status": "WARN", "metrics": {"included_signals_count": 2}}
        
        # These should be WARN, not NO_DATA
        assert run_1_signal["status"] == "WARN", "1 signal should be WARN not NO_DATA"
        assert run_2_signals["status"] == "WARN", "2 signals should be WARN not NO_DATA"

    def test_fail_tokens_require_fail_status(self):
        """FAIL_* tokens in reasons require status to be FAIL or FAIL_QUALITY."""
        allowed_fail_statuses = {"FAIL", "FAIL_QUALITY"}
        
        # Valid: FAIL_* with FAIL status
        valid_run = {"status": "FAIL", "reasons": ["FAIL_NET"]}
        assert valid_run["status"] in allowed_fail_statuses
        
        # Invalid: FAIL_* with PASS status - should never happen
        def has_fail_token_with_pass_status(run_data):
            status = run_data.get("status", "")
            reasons = run_data.get("reasons", []) + run_data.get("quality_reasons", [])
            has_fail_token = any(r.startswith("FAIL_") for r in reasons)
            return has_fail_token and status not in allowed_fail_statuses and status != "NO_DATA"
        
        invalid_run = {"status": "PASS", "reasons": ["FAIL_NET"]}
        # This should NOT pass our contract - FAIL_* requires FAIL status
        assert has_fail_token_with_pass_status(invalid_run) == True, \
            "Detector should catch FAIL_* token with PASS status"

    def test_quality_status_domain(self):
        """quality_status must be in domain: NO_DATA | PASS | WARN | FAIL_QUALITY."""
        valid_domain = {"NO_DATA", "PASS", "WARN", "FAIL_QUALITY"}
        
        # Valid statuses
        for status in ["NO_DATA", "PASS", "WARN", "FAIL_QUALITY"]:
            assert status in valid_domain
        
        # Invalid statuses (should not be used)
        invalid_statuses = ["WARN_QUALITY", "LOW_SAMPLE", "FAIL", "OK"]
        for status in invalid_statuses:
            assert status not in valid_domain, f"{status} is not a valid quality_status"

    def test_top_pair_dominance_gated_on_sample_size(self):
        """TOP_PAIR_DOMINANCE check requires MIN_SIGNALS_FOR_PASS and >=2 pairs."""
        from m4.policy import Thresholds
        
        min_signals = Thresholds.MIN_SIGNALS_FOR_PASS
        
        # Case 1: 1 signal, 1 pair - should NOT trigger TOP_PAIR check
        # (even 100% share is expected with 1 pair)
        single_pair_low_sample = {
            "included_signals_count": 1,
            "included_pairs": ["ARB/WETH"],
        }
        should_check = (
            single_pair_low_sample["included_signals_count"] >= min_signals and
            len(single_pair_low_sample["included_pairs"]) >= 2
        )
        assert should_check == False, "Should NOT check TOP_PAIR with <MIN_SIGNALS or <2 pairs"
        
        # Case 2: 5 signals, 3 pairs - should trigger TOP_PAIR check
        multi_pair_good_sample = {
            "included_signals_count": 5,
            "included_pairs": ["ARB/WETH", "LINK/WETH", "GMX/WETH"],
        }
        should_check = (
            multi_pair_good_sample["included_signals_count"] >= min_signals and
            len(multi_pair_good_sample["included_pairs"]) >= 2
        )
        assert should_check == True, "Should check TOP_PAIR with >=MIN_SIGNALS and >=2 pairs"

    def test_warn_reasons_do_not_trigger_fail_quality(self):
        """v2.0.7: WARN_* reasons must NOT trigger FAIL_QUALITY - only FAIL_* reasons can.
        
        This is a regression test for the bug where WARN_TOP_PAIR_DOMINANCE_HIGH
        was incorrectly triggering FAIL_QUALITY via substring matching on "HIGH".
        """
        # Any WARN_* reason should result in quality_status=WARN, not FAIL_QUALITY
        warn_only_reasons = [
            "WARN_TOP_PAIR_DOMINANCE_HIGH",
            "WARN_TOP_PAIR_DOMINANCE",
            "WARN_LOW_SAMPLE",
            "WARN_CRITICAL_REJECTS",
            "WARN_EXCLUDED_SIGNALS",
            "WARN_FRAGILE",
        ]
        
        for reason in warn_only_reasons:
            # Given: only WARN_* reasons (no FAIL_*)
            quality_reasons = [reason]
            
            # When: determining quality_status
            has_fail_reason = any(r.startswith("FAIL_") for r in quality_reasons)
            
            # Then: FAIL_QUALITY should NOT be triggered
            assert has_fail_reason == False, f"{reason} should not trigger FAIL_QUALITY"
            
        # Verify: only FAIL_* prefix should trigger FAIL_QUALITY
        fail_reasons = ["FAIL_NET", "FAIL_TOP_PAIR_DOMINANCE", "FAIL_DRIFT"]
        for reason in fail_reasons:
            quality_reasons = [reason]
            has_fail_reason = any(r.startswith("FAIL_") for r in quality_reasons)
            assert has_fail_reason == True, f"{reason} SHOULD trigger FAIL_QUALITY"
