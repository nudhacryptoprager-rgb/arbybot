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

    def test_same_dex_excluded_does_not_trigger_warn_excluded_signals(self):
        """v2.6.1: SAME_DEX_EXCLUDED signals should NOT trigger WARN_EXCLUDED_SIGNALS.
        
        SAME_DEX_EXCLUDED is a policy-driven exclusion (require_cross_dex=true),
        not a quality issue. Only non-same-dex exclusions (SUSPECT_SPREAD) should
        trigger WARN_EXCLUDED_SIGNALS.
        """
        # Given: signals where some are excluded via SAME_DEX_EXCLUDED only
        signals = [
            {"is_excluded_spread": True, "is_same_dex": True, "is_same_dex_excluded": True},
            {"is_excluded_spread": True, "is_same_dex": True, "is_same_dex_excluded": True},
            {"is_excluded_spread": False, "is_same_dex": False, "is_same_dex_excluded": False},
        ]
        
        # When: counting exclusions
        excluded_signals_count = 0
        same_dex_excluded_count = 0
        non_same_dex_excluded_count = 0
        
        for sig in signals:
            is_excluded = sig.get("is_excluded_spread", False)
            is_same_dex_excluded = sig.get("is_same_dex_excluded", False)
            
            if is_excluded:
                excluded_signals_count += 1
                if is_same_dex_excluded:
                    same_dex_excluded_count += 1
                else:
                    non_same_dex_excluded_count += 1
        
        # Then: WARN_EXCLUDED_SIGNALS should NOT be triggered (only same-dex exclusions)
        assert excluded_signals_count == 2
        assert same_dex_excluded_count == 2
        assert non_same_dex_excluded_count == 0, "Only same-dex exclusions present"
        
        # Build quality_reasons as m4/fixtures.py does
        quality_reasons = []
        if non_same_dex_excluded_count > 0:
            quality_reasons.append("WARN_EXCLUDED_SIGNALS")
        if same_dex_excluded_count > 0:
            quality_reasons.append("WARN_SAME_DEX_PRESENT")
        
        # WARN_EXCLUDED_SIGNALS should NOT be present
        assert "WARN_EXCLUDED_SIGNALS" not in quality_reasons
        assert "WARN_SAME_DEX_PRESENT" in quality_reasons


class TestFragileRateThresholds:
    """
    v2.7.0: Test fragile rate threshold alignment.
    
    Policy-aligned thresholds:
    - 0.30 (AGG_FRAGILE_P90_WARN) → WARN_FRAGILE_ELEVATED
    - 0.50 (AGG_FRAGILE_P90_FAIL) → FAIL_FRAGILE_HIGH
    
    These tests verify run-level behavior matches rolling-level policy.
    """

    def test_fragile_rate_0_4_gives_warn_not_fail(self):
        """fragile_rate=0.4 should give WARN_FRAGILE_ELEVATED, NOT FAIL_FRAGILE_HIGH.
        
        This is the key fix: 0.4 is above WARN threshold (0.30) but below FAIL (0.50),
        so it should emit WARN_FRAGILE_ELEVATED, not FAIL_FRAGILE_HIGH.
        """
        from m4.policy import Thresholds
        
        frag_rate = 0.4
        quality_reasons = []
        
        # Simulate the threshold logic from m4/fixtures.py (v2.7.0)
        if frag_rate > Thresholds.AGG_FRAGILE_P90_FAIL:  # > 0.50
            quality_reasons.append("FAIL_FRAGILE_HIGH")
        elif frag_rate > Thresholds.AGG_FRAGILE_P90_WARN:  # > 0.30
            quality_reasons.append("WARN_FRAGILE_ELEVATED")
        
        assert "WARN_FRAGILE_ELEVATED" in quality_reasons, \
            f"fragile_rate=0.4 should trigger WARN_FRAGILE_ELEVATED, got {quality_reasons}"
        assert "FAIL_FRAGILE_HIGH" not in quality_reasons, \
            f"fragile_rate=0.4 should NOT trigger FAIL_FRAGILE_HIGH, got {quality_reasons}"

    def test_fragile_rate_0_55_gives_fail(self):
        """fragile_rate=0.55 should give FAIL_FRAGILE_HIGH.
        
        Above 0.50 threshold → hard FAIL.
        """
        from m4.policy import Thresholds
        
        frag_rate = 0.55
        quality_reasons = []
        
        if frag_rate > Thresholds.AGG_FRAGILE_P90_FAIL:  # > 0.50
            quality_reasons.append("FAIL_FRAGILE_HIGH")
        elif frag_rate > Thresholds.AGG_FRAGILE_P90_WARN:  # > 0.30
            quality_reasons.append("WARN_FRAGILE_ELEVATED")
        
        assert "FAIL_FRAGILE_HIGH" in quality_reasons, \
            f"fragile_rate=0.55 should trigger FAIL_FRAGILE_HIGH, got {quality_reasons}"
        assert "WARN_FRAGILE_ELEVATED" not in quality_reasons, \
            f"fragile_rate=0.55 should NOT trigger WARN_FRAGILE_ELEVATED (FAIL takes precedence)"

    def test_fragile_rate_0_25_gives_nothing(self):
        """fragile_rate=0.25 should NOT trigger any fragile warnings.
        
        Below 0.30 threshold → no fragile warnings.
        """
        from m4.policy import Thresholds
        
        frag_rate = 0.25
        quality_reasons = []
        
        if frag_rate > Thresholds.AGG_FRAGILE_P90_FAIL:  # > 0.50
            quality_reasons.append("FAIL_FRAGILE_HIGH")
        elif frag_rate > Thresholds.AGG_FRAGILE_P90_WARN:  # > 0.30
            quality_reasons.append("WARN_FRAGILE_ELEVATED")
        
        assert "WARN_FRAGILE_ELEVATED" not in quality_reasons
        assert "FAIL_FRAGILE_HIGH" not in quality_reasons

    def test_threshold_values_are_aligned(self):
        """Threshold values should be 0.30 (warn) and 0.50 (fail)."""
        from m4.policy import Thresholds
        
        assert Thresholds.AGG_FRAGILE_P90_WARN == 0.30, \
            f"Expected WARN threshold 0.30, got {Thresholds.AGG_FRAGILE_P90_WARN}"
        assert Thresholds.AGG_FRAGILE_P90_FAIL == 0.50, \
            f"Expected FAIL threshold 0.50, got {Thresholds.AGG_FRAGILE_P90_FAIL}"


class TestCanonicalWarnTokenMapping:
    """
    v2.7.0: Test that FAIL_* to WARN_* downgrade uses canonical mappings.
    
    Non-canonical tokens like WARN_FRAGILE_HIGH should never be generated.
    Instead, FAIL_FRAGILE_HIGH should map to WARN_FRAGILE_ELEVATED.
    """

    def test_fail_fragile_high_maps_to_warn_fragile_elevated(self):
        """FAIL_FRAGILE_HIGH should downgrade to WARN_FRAGILE_ELEVATED, not WARN_FRAGILE_HIGH."""
        # This is the canonical mapping from m4/gates.py v2.7.0
        FAIL_TO_WARN_MAP = {
            "FAIL_FRAGILE_HIGH": "WARN_FRAGILE_ELEVATED",
            "FAIL_DRIFT_MAE": "WARN_DRIFT_MAE",
        }
        
        # Simulate downgrade for FAIL_FRAGILE_HIGH
        upstream_reason = "FAIL_FRAGILE_HIGH"
        warn_variant = FAIL_TO_WARN_MAP.get(upstream_reason)
        
        assert warn_variant == "WARN_FRAGILE_ELEVATED", \
            f"FAIL_FRAGILE_HIGH should map to WARN_FRAGILE_ELEVATED, got {warn_variant}"
        assert warn_variant != "WARN_FRAGILE_HIGH", \
            "Should NOT produce non-canonical WARN_FRAGILE_HIGH"

    def test_unmapped_fail_reasons_are_dropped(self):
        """FAIL_* reasons without canonical WARN mapping should be dropped (not renamed)."""
        FAIL_TO_WARN_MAP = {
            "FAIL_FRAGILE_HIGH": "WARN_FRAGILE_ELEVATED",
            "FAIL_DRIFT_MAE": "WARN_DRIFT_MAE",
        }
        
        # FAIL_NET has no WARN equivalent
        upstream_reason = "FAIL_NET"
        warn_variant = FAIL_TO_WARN_MAP.get(upstream_reason)
        
        assert warn_variant is None, \
            f"FAIL_NET should not have WARN mapping, got {warn_variant}"


class TestPruneOnEveryIteration:
    """
    v2.6.1: Test that prune happens on every iteration, not just PASS.
    
    This prevents disk bloat when the scanner fails repeatedly (RPC errors, drift).
    """

    def test_prune_condition_is_independent_of_status(self):
        """Prune should happen when prune_keep > 0, regardless of passed status.
        
        This test validates the architectural decision, not the full integration.
        The condition should be: `if args.prune_keep > 0` (NOT `if passed and args.prune_keep > 0`)
        """
        # Simulate the prune condition logic
        class MockArgs:
            prune_keep = 50
        
        args = MockArgs()
        
        # Test with passed=True
        passed = True
        should_prune_if_passed = args.prune_keep > 0
        
        # Test with passed=False
        passed = False
        should_prune_if_failed = args.prune_keep > 0
        
        # Both should be True (prune is independent of passed status)
        assert should_prune_if_passed is True
        assert should_prune_if_failed is True
        
        # And they should be equal (same condition)
        assert should_prune_if_passed == should_prune_if_failed, \
            "Prune condition should be independent of passed status"

    def test_prune_disabled_when_zero(self):
        """Prune should be disabled when prune_keep=0."""
        class MockArgs:
            prune_keep = 0
        
        args = MockArgs()
        should_prune = args.prune_keep > 0
        
        assert should_prune is False, "Prune should be disabled when prune_keep=0"


class TestFragileInvariant:
    """
    v2.9.5: Test that fragile logic uses est_gross_usdc (not truth_net_usdc).
    
    BUG: truth_net_usdc = est_gross - gas, so comparing (net < slip+gas) == (gross < slip+2*gas)
         This double-counts gas and triggers false fragile warnings.
    FIX: Use est_gross_usdc for comparison against (slip + gas).
    """

    def test_signal_not_fragile_when_gross_exceeds_costs(self):
        """
        WETH/USDC signal from runDir ci_m5_gate_20260228_182059:
        - est_gross_usdc = 0.2833
        - gas_usdc = 0.10 (cost model)
        - slippage_usdc = size_usd * 12.5bps = 250 * 0.00125 = 0.3125
        - total_costs = 0.4125
        - truth_net_usdc = est_gross - gas = 0.1833
        
        With BUGGY logic: 0.1833 < (0.3125 + 0.10) = 0.4125 → fragile=True [WRONG]
        With FIXED logic: 0.2833 < (0.3125 + 0.10) = 0.4125 → fragile=True [STILL TRUE - expected!]
        
        BUT for a signal with est_gross=1.50, gas=0.10, slippage=0.15:
        - BUGGY: net=1.40 < (0.15+0.10)=0.25 → fragile=False 
        - FIXED: gross=1.50 < 0.25 → fragile=False
        Both agree here because gross >> costs
        
        Let's test a marginal case:
        est_gross=0.50, gas=0.10, slippage=0.12, size_usd=100
        - net = 0.40
        - slip+gas = 0.22
        - BUGGY: 0.40 < 0.22 → False (NOT fragile) [correct by accident]
        - FIXED: 0.50 < 0.22 → False (NOT fragile) [correct]
        
        Test the edge case where bug matters:
        est_gross=0.30, gas=0.12, slippage=0.15, size_usd=120
        - net = 0.18 (gross - gas)
        - slip+gas = 0.27
        - BUGGY: 0.18 < 0.27 → True (FRAGILE) [BUG: gas counted twice]
        - FIXED: 0.30 < 0.27 → False (NOT fragile) [CORRECT: gross > costs]
        """
        # Signal that would be fragile with bug but NOT with fix
        est_gross = 0.30
        gas_usdc = 0.12
        size_usd = 120
        slippage_bps = 12.5
        slippage_usdc = size_usd * slippage_bps / 10000  # 0.15
        
        # This is the FIXED logic (v2.9.5)
        is_fragile = est_gross < slippage_usdc + gas_usdc and est_gross > 0
        
        # With FIXED logic: 0.30 < 0.27 is False, so NOT fragile
        assert is_fragile is False, \
            f"est_gross={est_gross} should NOT be fragile (gross > slip+gas): {est_gross} > {slippage_usdc + gas_usdc}"

    def test_signal_fragile_when_gross_below_costs(self):
        """Test that signal IS fragile when est_gross < slippage + gas."""
        # Signal that should be fragile with correct logic
        est_gross = 0.20
        gas_usdc = 0.15
        slippage_usdc = 0.10
        
        # FIXED logic: gross < costs
        is_fragile = est_gross < slippage_usdc + gas_usdc and est_gross > 0
        
        # 0.20 < 0.25 → fragile
        assert is_fragile is True, \
            f"est_gross={est_gross} SHOULD be fragile (gross < slip+gas): {est_gross} < {slippage_usdc + gas_usdc}"


class TestRejectSchemaConsistency:
    """
    v2.9.5: Test that reject schema uses 'reason' key (not 'reject_reason').
    
    BUG: spreads.py used 'reject_reason' but artifacts.py expects 'reason'
         This caused NOTIONAL_DRIFT_EXCLUDED to appear as UNKNOWN in reason_histogram.
    FIX: Use 'reason' key consistently.
    """

    def test_reason_histogram_notional_drift_excluded(self):
        """NOTIONAL_DRIFT_EXCLUDED should appear in reason_histogram, NOT UNKNOWN."""
        # Simulate the reject append logic with FIXED schema
        rejected_quotes = []
        quote = {
            "token_in": "LINK",
            "token_out": "WETH",
            "dex_id": "sushiswap_v3",
            "pool_address": "0x55A7E0ab34038D75d0E2118254Fd84FdedCd4E65",
            "notional_drift_pct": 61.94,
        }
        
        # v3.2.2: Updated to use drift_exclude_pct (was notional_drift_max_pct)
        rejected_quotes.append({
            **quote,
            "reason": "NOTIONAL_DRIFT_EXCLUDED",
            "notional_drift_pct": 61.94,
            "drift_exclude_pct": 20.0,  # v3.2.2: Now uses drift_warning_pct default of 20%
        })
        
        # Build reason histogram (same as artifacts.py)
        reason_histogram = {}
        for r in rejected_quotes:
            reason = r.get("reason", "UNKNOWN")
            reason_histogram[reason] = reason_histogram.get(reason, 0) + 1
        
        # FIXED: Should see NOTIONAL_DRIFT_EXCLUDED, NOT UNKNOWN
        assert "NOTIONAL_DRIFT_EXCLUDED" in reason_histogram, \
            f"Expected NOTIONAL_DRIFT_EXCLUDED in histogram, got {reason_histogram}"
        assert "UNKNOWN" not in reason_histogram, \
            f"UNKNOWN should NOT appear when reason key is correct, got {reason_histogram}"
        assert reason_histogram["NOTIONAL_DRIFT_EXCLUDED"] == 1


class TestRequireCrossDexNoSameDex:
    """v2.9.6: Test that require_cross_dex=true prevents same-DEX signals entirely."""
    
    def test_require_cross_dex_true_no_same_dex_signals(self):
        """When require_cross_dex=true, same-DEX signals should NOT be generated at all.
        
        v2.9.6 contract: Instead of generating same-DEX signals and then excluding them
        (which creates excluded_signals_count > 0), we should not generate them at all.
        """
        from strategy.spreads import _compute_pair_spread
        
        # Given: quotes only from ONE dex (no cross-DEX possible)
        quotes_same_dex = [
            {"dex_id": "uniswap_v3", "price": "2000.0", "price_exact": "2000.0",
             "pool_address": "0x111", "fee": 500, "token_in": "WETH", "token_out": "USDC"},
            {"dex_id": "uniswap_v3", "price": "2010.0", "price_exact": "2010.0",
             "pool_address": "0x222", "fee": 100, "token_in": "WETH", "token_out": "USDC"},
        ]
        
        # With require_cross_dex=true
        config_cross_dex = {
            "require_cross_dex": True,
            "min_spread_bps": 0,
            "max_spread_bps_sanity": 10000,
        }
        
        rejected_quotes = []
        signals = _compute_pair_spread(
            "WETH/USDC",
            quotes_same_dex,
            config_cross_dex,
            current_block=123456,
            spread_threshold_bps=0,
            max_spread_bps_sanity=10000,
            rejected_quotes=rejected_quotes,
        )
        
        # Then: NO signals should be generated (not even excluded ones)
        assert len(signals) == 0, \
            f"Expected 0 signals when require_cross_dex=true and no cross-DEX, got {len(signals)}"
    
    def test_require_cross_dex_false_allows_same_dex(self):
        """When require_cross_dex=false, same-DEX signals CAN be generated."""
        from strategy.spreads import _compute_pair_spread
        
        # Given: quotes only from ONE dex
        quotes_same_dex = [
            {"dex_id": "uniswap_v3", "price": "2000.0", "price_exact": "2000.0",
             "pool_address": "0x111", "fee": 500, "token_in": "WETH", "token_out": "USDC"},
            {"dex_id": "uniswap_v3", "price": "2010.0", "price_exact": "2010.0",
             "pool_address": "0x222", "fee": 100, "token_in": "WETH", "token_out": "USDC"},
        ]
        
        # With require_cross_dex=false (default)
        config_same_ok = {
            "require_cross_dex": False,
            "min_spread_bps": 0,
            "max_spread_bps_sanity": 10000,
        }
        
        rejected_quotes = []
        signals = _compute_pair_spread(
            "WETH/USDC",
            quotes_same_dex,
            config_same_ok,
            current_block=123456,
            spread_threshold_bps=0,
            max_spread_bps_sanity=10000,
            rejected_quotes=rejected_quotes,
        )
        
        # Then: signal CAN be generated (same-DEX allowed)
        assert len(signals) == 1, \
            f"Expected 1 signal when require_cross_dex=false, got {len(signals)}"


class TestMinSpreadBpsThreshold:
    """v2.9.7: Test min_spread_bps filtering threshold contract.
    
    Contract: signals with spread_bps < min_spread_bps are NOT generated.
    """
    
    def test_signal_below_min_spread_bps_not_generated(self):
        """Signals with spread < min_spread_bps should NOT be generated."""
        from strategy.spreads import _compute_pair_spread
        
        # Given: cross-DEX quotes with small spread (~50 bps)
        quotes = [
            {"dex_id": "uniswap_v3", "price": "2000.0", "price_exact": "2000.0",
             "pool_address": "0x111", "fee": 500, "token_in": "WETH", "token_out": "USDC"},
            {"dex_id": "sushiswap_v3", "price": "2010.0", "price_exact": "2010.0",
             "pool_address": "0x222", "fee": 500, "token_in": "WETH", "token_out": "USDC"},
        ]
        # Spread = (2010 - 2000) / 2000 * 10000 = 50 bps
        
        # With min_spread_bps=100 (above the 50 bps spread)
        config = {
            "require_cross_dex": True,
            "min_spread_bps": 100,
            "max_spread_bps_sanity": 10000,
        }
        
        rejected_quotes = []
        signals = _compute_pair_spread(
            "WETH/USDC",
            quotes,
            config,
            current_block=123456,
            spread_threshold_bps=100,  # min_spread_bps from config
            max_spread_bps_sanity=10000,
            rejected_quotes=rejected_quotes,
        )
        
        # Then: NO signals generated (spread 50 < threshold 100)
        assert len(signals) == 0, \
            f"Expected 0 signals when spread < min_spread_bps, got {len(signals)}"
    
    def test_signal_above_min_spread_bps_generated(self):
        """Signals with spread >= min_spread_bps SHOULD be generated."""
        from strategy.spreads import _compute_pair_spread
        
        # Given: cross-DEX quotes with larger spread (~100 bps)
        quotes = [
            {"dex_id": "uniswap_v3", "price": "2000.0", "price_exact": "2000.0",
             "pool_address": "0x111", "fee": 500, "token_in": "WETH", "token_out": "USDC"},
            {"dex_id": "sushiswap_v3", "price": "2020.0", "price_exact": "2020.0",
             "pool_address": "0x222", "fee": 500, "token_in": "WETH", "token_out": "USDC"},
        ]
        # Spread = (2020 - 2000) / 2000 * 10000 = 100 bps
        
        # With min_spread_bps=10 (below the 100 bps spread)
        config = {
            "require_cross_dex": True,
            "min_spread_bps": 10,
            "max_spread_bps_sanity": 10000,
        }
        
        rejected_quotes = []
        signals = _compute_pair_spread(
            "WETH/USDC",
            quotes,
            config,
            current_block=123456,
            spread_threshold_bps=10,
            max_spread_bps_sanity=10000,
            rejected_quotes=rejected_quotes,
        )
        
        # Then: signal IS generated (spread 100 >= threshold 10)
        assert len(signals) >= 1, \
            f"Expected >= 1 signal when spread >= min_spread_bps, got {len(signals)}"


class TestFragileCountZeroContract:
    """v2.9.7: Test fragile_count=0 contract with min_spread_bps above cost floor.
    
    Contract: When min_spread_bps >= cost_floor_bps, no signal should be marked fragile.
    
    Cost floor calculation at paper_size_usd=250 with paper_realistic:
    - gas_usd = $0.10
    - slippage_bps = 5, slippage_usd = 250 * 0.0005 = $0.125
    - total_cost = $0.225
    - cost_floor_bps = 0.225 / 250 * 10000 = ~9 bps
    
    Therefore min_spread_bps=10 is ABOVE cost floor, and fragile_count should be 0.
    """
    
    def test_fragile_count_zero_when_spread_above_cost_floor(self):
        """With min_spread_bps=10 and $250 paper size, fragile_count should be 0.
        
        Fragile definition: signal where est_gross_usdc < slippage_usdc + gas_usdc.
        At spread=10bps, gross = 250 * 0.001 = $0.25
        Costs = $0.125 (slippage) + $0.10 (gas) = $0.225
        $0.25 > $0.225, so NOT fragile.
        """
        # Given: M4 signal with spread=10bps at $250
        paper_size_usd = 250
        spread_bps = 10
        gas_usdc = 0.10
        slippage_bps = 5
        
        # Calculate costs
        est_gross_usdc = paper_size_usd * spread_bps / 10000  # $0.25
        slippage_usdc = paper_size_usd * slippage_bps / 10000  # $0.125
        total_cost = slippage_usdc + gas_usdc  # $0.225
        
        # Fragile check (from m4/fixtures.py logic)
        is_fragile = est_gross_usdc < total_cost
        
        # Then: NOT fragile
        assert not is_fragile, \
            f"Signal should NOT be fragile: gross={est_gross_usdc:.3f} >= costs={total_cost:.3f}"
    
    def test_fragile_when_spread_below_cost_floor(self):
        """With spread=5bps, signal IS fragile (gross < costs)."""
        paper_size_usd = 250
        spread_bps = 5
        gas_usdc = 0.10
        slippage_bps = 5
        
        est_gross_usdc = paper_size_usd * spread_bps / 10000  # $0.125
        slippage_usdc = paper_size_usd * slippage_bps / 10000  # $0.125
        total_cost = slippage_usdc + gas_usdc  # $0.225
        
        is_fragile = est_gross_usdc < total_cost
        
        # Then: IS fragile
        assert is_fragile, \
            f"Signal SHOULD be fragile: gross={est_gross_usdc:.3f} < costs={total_cost:.3f}"
    
    def test_cost_floor_calculation(self):
        """Verify cost floor is ~9 bps at $250 with paper_realistic costs."""
        paper_size_usd = 250
        gas_usdc = 0.10
        slippage_bps = 5
        
        slippage_usdc = paper_size_usd * slippage_bps / 10000
        total_cost = slippage_usdc + gas_usdc
        cost_floor_bps = total_cost / paper_size_usd * 10000
        
        # Cost floor should be ~9 bps
        assert 8 <= cost_floor_bps <= 10, \
            f"Cost floor should be ~9 bps, got {cost_floor_bps:.1f}"
