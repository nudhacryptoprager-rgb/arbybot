# PATH: tests/unit/test_blocker_evidence.py
"""
Contract tests for _compute_blocker_evidence() in start.py.

Verifies the auto-computed blocker taxonomy:
  ROUNDTRIP_PROFITABLE > INFRA_FAIL > NO_SIGNAL > QUOTE_PATH_BLOCKED > OE_ECONOMICS > MIXED_SOURCE
"""

from start import _compute_blocker_evidence


def _base_stats(**overrides):
    s = {
        "runs": 10,
        "fail": 0,
        "profitable_roundtrips_total": 0,
        "included_signals_total": 10,
        "last_truth_verdict": None,
        "last_quote_source_summary": {},
        "last_oe_rejection_funnel": {},
        "blocker_evidence": None,
    }
    s.update(overrides)
    return s


class TestComputeBlockerEvidence:
    def test_roundtrip_profitable_wins(self):
        s = _base_stats(profitable_roundtrips_total=1)
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "ROUNDTRIP_PROFITABLE"

    def test_infra_fail(self):
        s = _base_stats(runs=10, fail=6)
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "INFRA_FAIL"

    def test_no_signal(self):
        s = _base_stats(included_signals_total=0, last_cross_dex_pairs_count=10)
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "NO_SIGNAL"

    def test_quote_path_constrained(self):
        """R37: Few cross-dex pairs + no signals = surface-constrained (e.g. base)."""
        s = _base_stats(included_signals_total=0, last_cross_dex_pairs_count=2)
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "QUOTE_PATH_CONSTRAINED"

    def test_quote_path_blocked(self):
        qss = {"quotes_fetched_executable": 2, "quotes_fetched_diagnostic": 3,
               "quoter_v2_failed_count": 20}
        s = _base_stats(last_quote_source_summary=qss)
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "QUOTE_PATH_BLOCKED"

    def test_oe_economics(self):
        oe_rf = {"rejected_count": 10, "rejected_reasons": {"NET_PROFIT_TOO_LOW": 8}}
        s = _base_stats(last_oe_rejection_funnel=oe_rf)
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "OE_ECONOMICS"

    def test_mixed_source(self):
        oe_rf = {"rejected_count": 10, "rejected_reasons": {"MIXED_SOURCE": 5}}
        s = _base_stats(last_oe_rejection_funnel=oe_rf)
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "MIXED_SOURCE"

    def test_priority_profitable_over_infra_fail(self):
        s = _base_stats(profitable_roundtrips_total=1, fail=8, runs=10)
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "ROUNDTRIP_PROFITABLE"

    def test_fallback_from_truth_verdict_diagnostic(self):
        s = _base_stats(last_truth_verdict="DIAGNOSTIC_PROFIT_ONLY")
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "OE_ECONOMICS"

    def test_fallback_from_truth_verdict_no_profit(self):
        s = _base_stats(last_truth_verdict="NO_PROFIT")
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "NO_SIGNAL"

    def test_none_when_no_evidence(self):
        s = _base_stats()
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] is None

    def test_slot0_diagnostic_is_quote_path_blocked(self):
        """R33: SLOT0_DIAGNOSTIC dominance in OE means quoter_v2 not answering."""
        oe_rf = {"rejected_count": 200,
                 "rejected_reasons": {"SLOT0_DIAGNOSTIC": 115, "NET_PROFIT_TOO_LOW": 50,
                                      "QUOTER_V2_FAILED": 35}}
        s = _base_stats(last_oe_rejection_funnel=oe_rf)
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "QUOTE_PATH_BLOCKED"

    def test_slot0_below_threshold_falls_to_oe_economics(self):
        """When SLOT0 is below 40% but NET_PROFIT_TOO_LOW is dominant, OE_ECONOMICS."""
        oe_rf = {"rejected_count": 100,
                 "rejected_reasons": {"SLOT0_DIAGNOSTIC": 20, "NET_PROFIT_TOO_LOW": 60}}
        s = _base_stats(last_oe_rejection_funnel=oe_rf)
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "OE_ECONOMICS"

    def test_slot0_with_diagnostic_sweep_still_quote_path_blocked(self):
        """R39i: base scenario — SLOT0 dominant + runs_with_sweep > 0 but rq=0.
        Sweep evidence from diagnostic-only routes should NOT override QUOTE_PATH_BLOCKED
        when real_quote_count is zero (proves executable quote path broken)."""
        oe_rf = {"rejected_count": 120,
                 "rejected_reasons": {"SLOT0_DIAGNOSTIC": 93, "MIXED_SOURCE": 15,
                                      "NET_PROFIT_TOO_LOW": 12}}
        s = _base_stats(
            last_oe_rejection_funnel=oe_rf,
            runs_with_sweep=2,           # some sweeps from diagnostic routes
            real_quote_count_total=0,    # but zero real quotes
        )
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "QUOTE_PATH_BLOCKED"

    def test_slot0_with_real_quotes_falls_through(self):
        """When SLOT0 dominant but rq > 0, sweep evidence legitimately overrides —
        some real quotes do work, so economics classification is appropriate."""
        oe_rf = {"rejected_count": 120,
                 "rejected_reasons": {"SLOT0_DIAGNOSTIC": 60, "NET_PROFIT_TOO_LOW": 50,
                                      "MIXED_SOURCE": 10}}
        s = _base_stats(
            last_oe_rejection_funnel=oe_rf,
            runs_with_sweep=3,
            real_quote_count_total=5,
        )
        _compute_blocker_evidence(s)
        assert s["blocker_evidence"] == "OE_ECONOMICS"
