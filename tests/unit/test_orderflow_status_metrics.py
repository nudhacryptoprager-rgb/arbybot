"""
Status metrics and backward compatibility tests for M7 orderflow.

Locks:
- Pre-economics metrics (M7.A.5.11)
- Unscored rejects expanded (M7.A.5.11, M7.A.5.12)
- Consistency metrics (M7.A.5.12)
- Stale/low-lag scored split fields, comparison block (M7.A.5.13)
- events_scored_low_lag contract (M7.A.5.13)
- Low-lag reject decomposition, pipeline stage rates (M7.A.5.14)
- Backward compatibility for milestones M7.A.5.11 through M7.A.5.18
"""
from __future__ import annotations

from dataclasses import asdict

from m7.orderflow.artifacts import build_replay_summary
from m7.shared.constants import (
    ALL_BLOCKER_TAGS,
    REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_NO_ACTIVE_COUNTER_POOL,
    REJECT_NO_COUNTER_POOL,
    REJECT_STALE_POSITIVE,
    REJECT_TOKEN_NOT_ADMITTED,
    REJECT_TOKEN_PAIR_UNRESOLVED,
)

from tests.unit.conftest import _make_event, _make_result


# ===========================================================================
# M7.A.5.11: Pre-Economics Metrics
# ===========================================================================


class TestM7A511PreEconMetrics:
    """M7.A.5.11: build_replay_summary includes pre-economics coverage metrics."""

    def _make_mixed_results(self):
        results = []
        results.append(_make_result(
            event_id="pe_1", best_backrun_net_bps=50.0, block_lag=1,
            same_state_class="next_block", route_viable=True, reject_reason=None,
            coverage_result={"coverage_complete": True, "known_pools_total": 2, "active_pools_total": 2},
        ))
        results.append(_make_result(
            event_id="pe_2", best_backrun_net_bps=-400.0, block_lag=1,
            same_state_class="next_block", route_viable=False,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            coverage_result={"coverage_complete": True, "known_pools_total": 1, "active_pools_total": 1},
        ))
        results.append(_make_result(
            event_id="pe_3", best_backrun_net_bps=0.0, block_lag=2,
            same_state_class="next_block", route_viable=False,
            reject_reason=REJECT_NO_ACTIVE_COUNTER_POOL,
            coverage_result={"coverage_complete": False, "known_pools_total": 3, "active_pools_total": 0},
        ))
        results.append(_make_result(
            event_id="pe_4", best_backrun_net_bps=0.0, block_lag=5,
            same_state_class="stale", route_viable=False,
            reject_reason=REJECT_NO_COUNTER_POOL,
        ))
        return results

    def test_pre_econ_fields_present(self):
        events = [_make_event(eid=f"pe_{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        for key in [
            "pre_econ_reject_rate", "active_coverage_rate",
            "inactive_coverage_false_positive_rate", "scored_results_rate",
        ]:
            assert key in art, f"Missing M7.A.5.11 field: {key}"

    def test_pre_econ_reject_rate(self):
        events = [_make_event(eid=f"pe_{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["pre_econ_reject_rate"] == 0.5
        assert art["scored_results_rate"] == 0.5

    def test_active_coverage_rate(self):
        events = [_make_event(eid=f"pe_{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["active_coverage_rate"] == 0.5

    def test_inactive_false_positive_rate(self):
        events = [_make_event(eid=f"pe_{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["inactive_coverage_false_positive_rate"] == 0.25

    def test_empty_results(self):
        art = build_replay_summary([], [], mode="test")
        assert art["pre_econ_reject_rate"] == 0.0
        assert art["active_coverage_rate"] == 0.0
        assert art["scored_results_rate"] == 0.0


class TestM7A511UnscoredRejectsExpanded:
    """M7.A.5.11: New rejects counted as unscored in artifact."""

    def test_new_rejects_are_unscored(self):
        events = [_make_event(eid=f"us_{i}") for i in range(1, 3)]
        results = [
            _make_result(event_id="us_1", reject_reason=REJECT_NO_ACTIVE_COUNTER_POOL),
            _make_result(event_id="us_2", reject_reason=REJECT_ALL_POOLS_ZERO_LIQUIDITY),
        ]
        art = build_replay_summary(events, results, mode="test")
        assert art["scored_results_count"] == 0


class TestM7A511BackwardCompat:
    """M7.A.5.11: build_replay_summary has pre_econ_fields."""

    def test_summary_has_pre_econ_fields(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "pre_econ_reject_rate", "active_coverage_rate",
            "inactive_coverage_false_positive_rate", "scored_results_rate",
        ]:
            assert key in art


# ===========================================================================
# M7.A.5.12: Consistency Metrics
# ===========================================================================


class TestM7A512ConsistencyMetrics:
    """M7.A.5.12: build_replay_summary must include consistency metrics."""

    def test_summary_has_consistency_fields(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "coverage_local_mismatch_count", "truly_inactive_count",
            "quote_reachability_rate", "coverage_complete_no_quote_count",
        ]:
            assert key in art

    def test_consistency_defaults_for_empty(self):
        art = build_replay_summary([], [], mode="test")
        assert art["coverage_local_mismatch_count"] == 0
        assert art["truly_inactive_count"] == 0
        assert art["quote_reachability_rate"] is None
        assert art["coverage_complete_no_quote_count"] == 0

    def test_mismatch_count_from_reject_histogram(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(3)]
        results = [
            _make_result(event_id="ev_0", reject_reason="COVERAGE_SAYS_ACTIVE_BUT_LOCAL_SIM_ZERO"),
            _make_result(event_id="ev_1", reject_reason="ALL_CANDIDATE_POOLS_TRULY_INACTIVE"),
            _make_result(event_id="ev_2", reject_reason="NO_COUNTER_POOL"),
        ]
        art = build_replay_summary(events, results, mode="test")
        assert art["coverage_local_mismatch_count"] == 1
        assert art["truly_inactive_count"] == 1


class TestM7A512UnscoredRejectsExpanded:
    """M7.A.5.12 new rejects in UNSCORED_REJECTS."""

    def test_new_rejects_counted_as_unscored(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(2)]
        results = [
            _make_result(event_id="ev_0", reject_reason="COVERAGE_SAYS_ACTIVE_BUT_LOCAL_SIM_ZERO"),
            _make_result(event_id="ev_1", reject_reason="ALL_CANDIDATE_POOLS_TRULY_INACTIVE"),
        ]
        art = build_replay_summary(events, results, mode="test")
        assert art["scored_results_count"] == 0


class TestM7A512BackwardCompat:
    """M7.A.5.12: summary has 512 consistency fields."""

    def test_summary_has_512_consistency_fields(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "coverage_local_mismatch_count", "truly_inactive_count",
            "quote_reachability_rate", "coverage_complete_no_quote_count",
        ]:
            assert key in art


# ===========================================================================
# M7.A.5.13: Stale/Low-Lag Scored Split
# ===========================================================================


class TestM7A513StaleLowLagSplitFields:
    """M7.A.5.13 summary must include stale/low-lag scored split fields."""

    def test_split_fields_present_in_empty_summary(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "events_detected_low_lag", "events_scored_low_lag",
            "best_net_bps_stale", "best_net_bps_low_lag_scored",
            "mean_net_bps_stale", "mean_net_bps_low_lag_scored",
        ]:
            assert key in art, f"Missing key: {key}"

    def test_split_fields_none_when_no_results(self):
        art = build_replay_summary([], [], mode="test")
        assert art["events_detected_low_lag"] == 0
        assert art["events_scored_low_lag"] == 0
        assert art["best_net_bps_stale"] is None
        assert art["best_net_bps_low_lag_scored"] is None

    def test_stale_result_goes_to_stale_metrics(self):
        e = _make_event()
        r = _make_result(
            event_id="stale_1", best_backrun_net_bps=-50.0, block_lag=100,
            same_state_class="stale", reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            route_viable=False,
        )
        art = build_replay_summary([e], [r], mode="test")
        assert art["events_detected_low_lag"] == 0
        assert art["best_net_bps_stale"] == -50.0
        assert art["best_net_bps_low_lag_scored"] is None

    def test_low_lag_scored_result_goes_to_low_lag_metrics(self):
        e = _make_event()
        r = _make_result(
            event_id="ll_1", best_backrun_net_bps=-20.0, block_lag=0,
            same_state_class="same_block", reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            route_viable=False, event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([e], [r], mode="test")
        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 1
        assert art["best_net_bps_low_lag_scored"] == -20.0

    def test_unscored_low_lag_detected_not_scored(self):
        e = _make_event()
        r = _make_result(
            event_id="unscore_ll", best_backrun_net_bps=0.0, block_lag=0,
            same_state_class="same_block", reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            route_viable=False, event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([e], [r], mode="test")
        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 0


class TestM7A513ComparisonBlock:
    """M7.A.5.13: machine-readable stale_low_lag_comparison."""

    def test_comparison_block_present(self):
        art = build_replay_summary([], [], mode="test")
        assert "stale_low_lag_comparison" in art
        comp = art["stale_low_lag_comparison"]
        for key in [
            "stale_scored_count", "stale_positive_count",
            "low_lag_scored_count", "low_lag_positive_count",
            "beats_m4_baseline_stale", "beats_m4_baseline_low_lag",
        ]:
            assert key in comp

    def test_comparison_empty_has_zeros_and_false(self):
        art = build_replay_summary([], [], mode="test")
        comp = art["stale_low_lag_comparison"]
        assert comp["stale_scored_count"] == 0
        assert comp["low_lag_scored_count"] == 0
        assert comp["beats_m4_baseline_stale"] is False
        assert comp["beats_m4_baseline_low_lag"] is False

    def test_comparison_with_stale_positive(self):
        e = _make_event()
        r = _make_result(
            event_id="sp_1", best_backrun_net_bps=100.0, block_lag=500,
            same_state_class="stale", reject_reason=REJECT_STALE_POSITIVE,
            route_viable=False,
        )
        art = build_replay_summary([e], [r], mode="test")
        comp = art["stale_low_lag_comparison"]
        assert comp["stale_scored_count"] == 1
        assert comp["stale_positive_count"] == 1
        assert comp["beats_m4_baseline_stale"] is True

    def test_comparison_with_low_lag_positive(self):
        e = _make_event()
        r = _make_result(
            event_id="llv_1", best_backrun_net_bps=50.0, block_lag=0,
            same_state_class="same_block", reject_reason=None,
            route_viable=True, event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([e], [r], mode="test")
        comp = art["stale_low_lag_comparison"]
        assert comp["low_lag_scored_count"] == 1
        assert comp["low_lag_positive_count"] == 1
        assert comp["beats_m4_baseline_low_lag"] is True


class TestM7A513EventsScoredLowLagContract:
    """M7.A.5.13: events_scored_low_lag counts only scored results."""

    def test_events_scored_low_lag_excludes_unscored(self):
        e = _make_event()
        r_unscored = _make_result(
            event_id="unscore_ll", best_backrun_net_bps=0.0, block_lag=1,
            same_state_class="next_block", reject_reason=REJECT_NO_COUNTER_POOL,
            route_viable=False, event_block=100, event_detected_at_block=101,
        )
        r_scored = _make_result(
            event_id="scored_ll", best_backrun_net_bps=-10.0, block_lag=0,
            same_state_class="same_block", reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            route_viable=False, event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([e, e], [r_unscored, r_scored], mode="test")
        assert art["events_detected_low_lag"] == 2
        assert art["events_scored_low_lag"] == 1

    def test_best_net_bps_executable_only_viable(self):
        e = _make_event()
        r_stale_pos = _make_result(
            event_id="sp", best_backrun_net_bps=200.0, block_lag=100,
            same_state_class="stale", reject_reason=REJECT_STALE_POSITIVE,
            route_viable=False,
        )
        r_viable = _make_result(
            event_id="v", best_backrun_net_bps=5.0, block_lag=0,
            same_state_class="same_block", reject_reason=None,
            route_viable=True, event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([e, e], [r_stale_pos, r_viable], mode="test")
        assert art["best_net_bps_executable"] == 5.0
        assert art["best_net_bps_any"] == 200.0


class TestM7A513BackwardCompat:
    """M7.A.5.13: field count and key presence checks."""

    def test_backrun_result_field_count_still_66(self):
        r = _make_result()
        d = asdict(r)
        assert len(d) == 66

    def test_old_summary_fields_still_present(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "events_count", "results_count", "viable_count",
            "best_net_bps_any", "best_net_bps_executable",
            "positive_net_count_any", "positive_net_count_low_lag",
            "stale_positive_count", "scored_results_count",
            "reject_histogram", "two_leg_baseline_net_bps",
            "coverage_local_mismatch_count", "truly_inactive_count",
        ]:
            assert key in art

    def test_new_513_fields_additive(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "events_detected_low_lag", "events_scored_low_lag",
            "best_net_bps_stale", "best_net_bps_low_lag_scored",
            "mean_net_bps_stale", "mean_net_bps_low_lag_scored",
            "stale_low_lag_comparison",
        ]:
            assert key in art


# ===========================================================================
# M7.A.5.14: Low-Lag Reject Decomposition
# ===========================================================================


class TestM7A514LowLagRejectDecomposition:
    """M7.A.5.14: Low-lag reject histogram and pipeline stage rates."""

    def _make_mixed_lag_results(self):
        results = []
        results.append(_make_result(
            event_id="ll_1", best_backrun_net_bps=50.0, block_lag=1,
            same_state_class="next_block", route_viable=True, reject_reason=None,
            event_block=100, event_detected_at_block=101,
        ))
        results.append(_make_result(
            event_id="ll_2", best_backrun_net_bps=-100.0, block_lag=0,
            same_state_class="same_block", route_viable=False,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            event_block=100, event_detected_at_block=100,
        ))
        results.append(_make_result(
            event_id="ll_3", best_backrun_net_bps=0.0, block_lag=2,
            same_state_class="next_block", route_viable=False,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            event_block=100, event_detected_at_block=102,
        ))
        results.append(_make_result(
            event_id="ll_4", best_backrun_net_bps=0.0, block_lag=1,
            same_state_class="next_block", route_viable=False,
            reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100, event_detected_at_block=101,
        ))
        results.append(_make_result(
            event_id="st_1", best_backrun_net_bps=200.0, block_lag=10,
            same_state_class="stale", route_viable=False,
            reject_reason=REJECT_STALE_POSITIVE,
        ))
        results.append(_make_result(
            event_id="st_2", best_backrun_net_bps=0.0, block_lag=15,
            same_state_class="stale", route_viable=False,
            reject_reason=REJECT_TOKEN_NOT_ADMITTED,
        ))
        return results

    def test_low_lag_reject_histogram_present(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        assert "low_lag_reject_histogram" in art

    def test_low_lag_reject_histogram_only_low_lag(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        ll_hist = art["low_lag_reject_histogram"]
        assert ll_hist.get(REJECT_GAS_EXCEEDS_GROSS) == 1
        assert ll_hist.get(REJECT_TOKEN_PAIR_UNRESOLVED) == 1
        assert ll_hist.get(REJECT_NO_COUNTER_POOL) == 1
        assert REJECT_STALE_POSITIVE not in ll_hist
        assert REJECT_TOKEN_NOT_ADMITTED not in ll_hist

    def test_low_lag_pipeline_stage_rates_present(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        for key in [
            "low_lag_pair_resolution_rate", "low_lag_counter_coverage_rate",
            "low_lag_scored_results_rate", "low_lag_pre_econ_reject_rate",
        ]:
            assert key in art

    def test_low_lag_pair_resolution_rate(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["low_lag_pair_resolution_rate"] == 0.75

    def test_low_lag_scored_results_rate(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["low_lag_scored_results_rate"] == 0.5

    def test_low_lag_rates_none_when_no_low_lag(self):
        results = [_make_result(
            event_id="stale_only", best_backrun_net_bps=100.0, block_lag=10,
            same_state_class="stale", route_viable=False,
            reject_reason=REJECT_STALE_POSITIVE,
        )]
        events = [_make_event(eid="stale_only")]
        art = build_replay_summary(events, results, mode="test")
        assert art["low_lag_pair_resolution_rate"] is None
        assert art["low_lag_reject_histogram"] == {}


class TestM7A514BackwardCompat:
    """M7.A.5.14 compat."""

    def test_backrun_result_field_count_66(self):
        r = _make_result()
        d = asdict(r)
        assert len(d) == 66

    def test_new_514_fields_additive(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "low_lag_reject_histogram",
            "low_lag_pair_resolution_rate",
            "low_lag_counter_coverage_rate",
            "low_lag_scored_results_rate",
            "low_lag_pre_econ_reject_rate",
        ]:
            assert key in art


# ===========================================================================
# M7.A.5.15: Backward Compatibility
# ===========================================================================


class TestM7A515BackwardCompat:
    """M7.A.5.15: field count and key presence."""

    def test_backrun_result_field_count_66(self):
        r = _make_result()
        d = asdict(r)
        assert len(d) == 66

    def test_new_515_fields_present(self):
        art = build_replay_summary([], [], mode="test")
        for key in ["low_lag_debug_rows", "low_lag_coverage_truth"]:
            assert key in art


# ===========================================================================
# M7.A.5.16: Backward Compatibility
# ===========================================================================


class TestM7A516BackwardCompat:
    """M7.A.5.16: field count and new artifact keys."""

    def test_backrun_result_field_count_66(self):
        r = _make_result()
        d = asdict(r)
        assert len(d) == 66

    def test_new_516_fields_present(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_pool_class_truth" in art
        pct = art["low_lag_pool_class_truth"]
        for key in [
            "unsupported_pool_rate", "no_counter_pool_rate",
            "inactive_known_pool_rate", "known_but_untradeable_rate",
            "dex_family_histogram", "pool_truth_count",
        ]:
            assert key in pct


# ===========================================================================
# M7.A.5.17: Backward Compatibility
# ===========================================================================


class TestM7A517BackwardCompat:
    """M7.A.5.17: field count and new artifact keys."""

    def test_backrun_result_field_count_66(self):
        r = _make_result()
        d = asdict(r)
        assert len(d) == 66

    def test_new_517_artifact_present(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_v2_truth" in art

    def test_old_516_fields_still_present(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "low_lag_pool_class_truth", "low_lag_debug_rows",
            "low_lag_coverage_truth", "low_lag_reject_histogram",
        ]:
            assert key in art


# ===========================================================================
# M7.A.5.18: Backward Compatibility
# ===========================================================================


class TestM7A518BackwardCompat:
    """M7.A.5.18: field count and key presence."""

    def test_backrun_result_field_count_66(self):
        r = _make_result()
        d = asdict(r)
        assert len(d) == 66

    def test_all_blocker_tags_count_is_8(self):
        assert len(ALL_BLOCKER_TAGS) == 8

    def test_new_518_artifact_keys(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_watchlist" in art
        assert "blocker_tags" in art

    def test_old_517_artifact_keys_still_present(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "low_lag_v2_truth", "low_lag_pool_class_truth",
            "low_lag_debug_rows", "low_lag_coverage_truth",
            "low_lag_reject_histogram", "stale_low_lag_comparison",
            "reject_histogram",
        ]:
            assert key in art
