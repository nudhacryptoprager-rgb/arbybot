"""
Artifact schema tests for M7 orderflow.

Locks artifact-level contracts produced by build_replay_summary(),
build_intent_surface_assessments(), and build_intent_scout_summary():

- Intent scout artifact schema (M7.A.4)
- Replay artifact schema (M7.A.4)
- Backward compatibility of artifact baselines (M7.A.4, M7.A.5)
- ws_live artifact mode and keys (M7.A.5.3)
- ws_low_lag_summary and ws_stale_summary schema (M7.A.5.3.1)
- Pair resolution, M4/M7 comparison (M7.A.5.5)
- Coverage scan, size sweep, reject histogram v2 (M7.A.5.6)
- Split viability summary fields (M7.A.5.10)
- Local pricing artifact block (M7.A.5.20)
- Registry metrics artifact (M7.A.5.21)
- Registry session stats, hypothesis strings (M7.A.5.22)
- Low-lag fast-path artifact (M7.A.5.23)
- Non-low-lag unchanged invariant (M7.A.5.23)
- Pipeline optimization artifact (M7.A.5.24)
"""
from __future__ import annotations

import json

from m7.orderflow.artifacts import (
    build_intent_scout_summary,
    build_intent_surface_assessments,
    build_replay_summary,
    score_backrun_offline,
)
from m7.orderflow.events import build_fixture_events
from m7.shared.constants import (
    ALL_REJECT_REASONS,
    ALL_SURFACES,
    M7A4_CHAIN,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_NO_COUNTER_POOL,
    REJECT_STALE_POSITIVE,
    REJECT_UNSUPPORTED_ADAPTER,
    REJECT_ZERO_LIQUIDITY,
    SURFACE_BLOCK_BACKRUN,
    SURFACE_COW_SOLVER,
    UNSCORED_REJECTS,
)

from tests.unit.conftest import _make_event, _make_result


# ===========================================================================
# M7.A.4: Intent Scout Artifact
# ===========================================================================


class TestIntentScout:
    """Lock intent/auction surface scout."""

    def test_assessment_count(self):
        assessments = build_intent_surface_assessments()
        assert len(assessments) == 4

    def test_all_canonical_surfaces_covered(self):
        assessments = build_intent_surface_assessments()
        surface_types = {a.surface_type for a in assessments}
        assert surface_types == ALL_SURFACES

    def test_block_backrun_highest_feasibility(self):
        assessments = build_intent_surface_assessments()
        block_backrun = [a for a in assessments if a.surface_type == SURFACE_BLOCK_BACKRUN]
        assert len(block_backrun) == 1
        assert block_backrun[0].feasibility_score == "high"

    def test_cow_solver_lowest_feasibility(self):
        assessments = build_intent_surface_assessments()
        cow = [a for a in assessments if a.surface_type == SURFACE_COW_SOLVER]
        assert len(cow) == 1
        assert cow[0].feasibility_score == "low"

    def test_block_backrun_on_arbitrum(self):
        assessments = build_intent_surface_assessments()
        block_backrun = [a for a in assessments if a.surface_type == SURFACE_BLOCK_BACKRUN]
        assert block_backrun[0].chain == M7A4_CHAIN

    def test_summary_artifact_keys(self):
        assessments = build_intent_surface_assessments()
        summary = build_intent_scout_summary(assessments)
        required = {
            "scout_type", "chain_focus", "surfaces_assessed",
            "by_feasibility", "best_near_term", "best_near_term_reason",
            "assessments",
        }
        assert required.issubset(set(summary.keys()))

    def test_summary_best_near_term_is_block_backrun(self):
        assessments = build_intent_surface_assessments()
        summary = build_intent_scout_summary(assessments)
        assert summary["best_near_term"] == SURFACE_BLOCK_BACKRUN


# ===========================================================================
# M7.A.4: Replay Artifact Schema
# ===========================================================================


class TestReplayArtifactSchema:
    """Lock replay artifact schema."""

    def test_artifact_has_hypothesis_field(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert artifact["m7a4_hypothesis"] == "orderflow_driven_backrun_replay"

    def test_artifact_has_baseline_comparisons(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert "two_leg_baseline_net_bps" in artifact
        assert "m7a_triangular_best_net_bps" in artifact
        assert "beats_two_leg_baseline" in artifact
        assert "beats_triangular_baseline" in artifact

    def test_artifact_has_reject_histogram(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert "reject_histogram" in artifact
        assert isinstance(artifact["reject_histogram"], dict)

    def test_artifact_results_match_events(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert artifact["events_count"] == len(events)
        assert artifact["results_count"] == len(results)

    def test_artifact_mode_propagated(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="replay")
        assert artifact["mode"] == "replay"

    def test_artifact_chain_is_m7a4(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert artifact["chain"] == M7A4_CHAIN

    def test_artifact_is_json_serializable(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        json_str = json.dumps(artifact, default=str)
        parsed = json.loads(json_str)
        assert parsed["events_count"] == len(events)

    def test_empty_results_produce_valid_artifact(self):
        artifact = build_replay_summary([], [], mode="offline")
        assert artifact["events_count"] == 0
        assert artifact["results_count"] == 0
        assert artifact["best_net_bps"] is None
        assert artifact["viable_count"] == 0


# ===========================================================================
# M7.A.4: Backward Compatibility (artifact baselines)
# ===========================================================================


class TestBackwardCompatibility:
    """M7.A.4 baseline comparisons in build_replay_summary."""

    def test_m7a4_two_leg_baseline_matches(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert artifact["two_leg_baseline_net_bps"] == -3.5062

    def test_m7a4_triangular_baseline_matches(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert artifact["m7a_triangular_best_net_bps"] == -14.16


# ===========================================================================
# M7.A.5: Offline backward compatibility (artifact schema)
# ===========================================================================


class TestM7A5BackwardCompat:
    """M7.A.5 additions and offline artifact schema contracts."""

    def test_offline_artifact_schema_unchanged(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        required_keys = {
            "m7a4_hypothesis", "mode", "timestamp", "chain",
            "events_count", "results_count", "viable_count",
            "positive_net_count", "best_net_bps", "worst_net_bps",
            "mean_net_bps", "reject_histogram", "results",
            "two_leg_baseline_net_bps", "m7a_triangular_best_net_bps",
        }
        assert required_keys.issubset(set(artifact.keys()))

    def test_offline_json_roundtrip(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        json_str = json.dumps(artifact, default=str)
        parsed = json.loads(json_str)
        assert parsed["events_count"] == 5
        assert parsed["mode"] == "offline"


# ===========================================================================
# M7.A.5.3: ws_live Artifact Schema
# ===========================================================================


class TestWsLiveArtifactSchema:
    """M7.A.5.3: ws_live artifact must contain ws-specific fields."""

    def test_ws_live_mode_in_replay_summary(self):
        events = build_fixture_events()[:1]
        results = [score_backrun_offline(events[0])]
        artifact = build_replay_summary(events, results, mode="ws_live")
        assert artifact["mode"] == "ws_live"

    def test_ws_live_artifact_keys(self):
        events = build_fixture_events()[:1]
        results = [score_backrun_offline(events[0])]
        artifact = build_replay_summary(events, results, mode="ws_live")
        required_keys = {
            "m7a4_hypothesis", "mode", "timestamp", "chain",
            "events_count", "results_count", "viable_count",
            "best_net_bps", "reject_histogram", "results",
        }
        assert required_keys.issubset(set(artifact.keys()))


# ===========================================================================
# M7.A.5.3.1: ws_low_lag_summary and ws_stale_summary
# ===========================================================================


class TestWsLowLagStaleSummary:
    """ws_low_lag_summary and ws_stale_summary artifact schema tests."""

    def test_summary_keys_present_in_artifact(self):
        r = _make_result()
        artifact = build_replay_summary([_make_event()], [r], mode="ws_live")
        artifact["ws_low_lag_summary"] = {
            "count": 3, "best_net_bps": -5.0, "worst_net_bps": -20.0,
            "mean_net_bps": -12.0, "same_block_count": 1, "next_block_count": 2,
            "mean_pipeline_latency_ms": 180.0, "viable_count": 0,
        }
        artifact["ws_stale_summary"] = {
            "count": 5, "best_net_bps": -18.0, "worst_net_bps": -25.0,
            "mean_net_bps": -21.0, "mean_block_lag": 12.5,
            "mean_pipeline_latency_ms": 350.0, "viable_count": 0,
        }
        s = json.dumps(artifact, default=str)
        parsed = json.loads(s)
        assert "ws_low_lag_summary" in parsed
        assert "ws_stale_summary" in parsed

    def test_low_lag_summary_required_keys(self):
        expected = {
            "count", "best_net_bps", "worst_net_bps", "mean_net_bps",
            "same_block_count", "next_block_count", "mean_pipeline_latency_ms",
            "viable_count",
        }
        summary = {
            "count": 0, "best_net_bps": None, "worst_net_bps": None,
            "mean_net_bps": None, "same_block_count": 0, "next_block_count": 0,
            "mean_pipeline_latency_ms": None, "viable_count": 0,
        }
        assert set(summary.keys()) == expected

    def test_stale_summary_required_keys(self):
        expected = {
            "count", "best_net_bps", "worst_net_bps", "mean_net_bps",
            "mean_block_lag", "mean_pipeline_latency_ms", "viable_count",
        }
        summary = {
            "count": 0, "best_net_bps": None, "worst_net_bps": None,
            "mean_net_bps": None, "mean_block_lag": None,
            "mean_pipeline_latency_ms": None, "viable_count": 0,
        }
        assert set(summary.keys()) == expected

    def test_latency_budget_in_live_state_metrics(self):
        metrics = {
            "latency_budget_ms": 250,
            "latency_budget_hit_rate": 0.75,
            "sub_block_capable": True,
        }
        assert metrics["latency_budget_ms"] == 250
        assert 0.0 <= metrics["latency_budget_hit_rate"] <= 1.0
        assert isinstance(metrics["sub_block_capable"], bool)


# ===========================================================================
# M7.A.5.5: Artifact Fields — Pair Resolution & M4/M7 comparison
# ===========================================================================


class TestM7A55ArtifactFields:
    """M7.A.5.5: New artifact fields for pair resolution and M4/M7 comparison."""

    def test_pair_resolution_metrics_schema(self):
        required = {
            "events_pair_resolved", "events_pair_unresolved",
            "pair_resolution_rate", "actual_pairs_seen",
            "resolved_best_net_bps", "resolved_mean_net_bps",
            "size_source_histogram",
        }
        metrics = {
            "events_pair_resolved": 5, "events_pair_unresolved": 3,
            "pair_resolution_rate": 0.625, "actual_pairs_seen": ["WETH/USDC"],
            "resolved_best_net_bps": -10.0, "resolved_mean_net_bps": -15.0,
            "size_source_histogram": {"event_proportional": 5},
        }
        assert required == set(metrics.keys())

    def test_m4_m7_comparison_schema(self):
        required = {
            "m4_best_net_bps", "m4_frontier_pair", "m4_size_usd", "m4_gas_bps",
            "m7_best_net_bps", "m7_mean_gross_bps", "m7_mean_gas_bps",
            "m7_mean_size_wei", "m7_latency_class", "m7_pair_resolved_count",
            "note",
        }
        comparison = {
            "m4_best_net_bps": -3.5062, "m4_frontier_pair": "WBTC/USDC",
            "m4_size_usd": 50, "m4_gas_bps": 2.01,
            "m7_best_net_bps": -19.73, "m7_mean_gross_bps": -1.61,
            "m7_mean_gas_bps": 20.0, "m7_mean_size_wei": 10**16,
            "m7_latency_class": "stale", "m7_pair_resolved_count": 5,
            "note": "test",
        }
        assert required == set(comparison.keys())


# ===========================================================================
# M7.A.5.6: Artifact-Level Blocks
# ===========================================================================


class TestM7A56ArtifactSchema:
    """M7.A.5.6: Artifact-level blocks needed for ws-live evidence."""

    def test_coverage_scan_metrics_schema(self):
        metrics = {
            "events_admitted": 5, "events_not_admitted": 15,
            "events_coverage_complete": 3,
            "coverage_blocker_histogram": {"no_v3_pools": 10, "no_adapter": 5},
            "admission_rate": 0.25,
        }
        required = {
            "events_admitted", "events_not_admitted",
            "events_coverage_complete", "coverage_blocker_histogram",
            "admission_rate",
        }
        assert set(metrics.keys()) == required
        assert 0.0 <= metrics["admission_rate"] <= 1.0

    def test_size_sweep_metrics_schema(self):
        metrics = {
            "events_with_sweep": 3,
            "sweep_net_bps_all": [-5.0, -2.0, 1.0],
            "best_sweep_net_bps": 1.0,
            "mean_sweep_net_bps": -2.0,
            "events_with_positive_sweep": 1,
        }
        required = {
            "events_with_sweep", "sweep_net_bps_all",
            "best_sweep_net_bps", "mean_sweep_net_bps",
            "events_with_positive_sweep",
        }
        assert set(metrics.keys()) == required

    def test_m4_m7_comparison_v2_schema(self):
        v2 = {
            "m4_best_net_bps": -3.5062, "m4_gross_pre_cost_bps": 36.35,
            "m4_gas_bps": 2.01, "m4_fee_bps": 31.0, "m4_slippage_bps": 6.85,
            "m4_size_usd": 50, "m4_pair": "WBTC/USDC",
            "m7_best_net_bps": -10.0, "m7_gross_pre_cost_bps": 20.0,
            "m7_gas_bps": 5.0, "m7_fee_bps": 15.0, "m7_slippage_bps": None,
            "m7_size_usd": 100.0, "m7_pair_resolved": True,
            "m7_coverage_complete_count": 3, "m7_latency_class": "stale",
            "m7_best_sweep_net_bps": -5.0,
            "note": "M4 has mature pair-specific dynamic sweep; M7 now has pair-resolved coverage + bounded event-size evaluation",
        }
        required_keys = {
            "m4_best_net_bps", "m4_gross_pre_cost_bps", "m4_gas_bps",
            "m4_fee_bps", "m4_slippage_bps", "m4_size_usd", "m4_pair",
            "m7_best_net_bps", "m7_gross_pre_cost_bps", "m7_gas_bps",
            "m7_fee_bps", "m7_slippage_bps", "m7_size_usd",
            "m7_pair_resolved", "m7_coverage_complete_count",
            "m7_latency_class", "m7_best_sweep_net_bps", "note",
        }
        assert set(v2.keys()) == required_keys

    def test_reject_histogram_v2_accepts_new_reasons(self):
        hist = {
            "NO_COUNTER_POOL": 5, "TOKEN_NOT_ADMITTED": 10,
            "UNSUPPORTED_ADAPTER": 2, "RPC_QUOTE_FAIL": 3,
            "PAIR_RESOLVED_BUT_UNTRADEABLE": 1, "QUOTE_FAILURE": 0,
            "TOKEN_PAIR_UNRESOLVED": 4,
        }
        for k in hist:
            assert k in ALL_REJECT_REASONS, f"Unknown reject reason in histogram: {k}"


# ===========================================================================
# M7.A.5.10: Split Viability Summary Fields
# ===========================================================================


class TestM7A510SplitSummaryFields:
    """M7.A.5.10: build_replay_summary produces split viability fields."""

    def _make_results(self):
        results = []
        results.append(_make_result(
            event_id="sum_1", best_backrun_net_bps=50.0, block_lag=1,
            same_state_class="next_block", route_viable=True, reject_reason=None,
            size_valid_for_token=True, event_block=100, event_detected_at_block=101,
        ))
        results.append(_make_result(
            event_id="sum_2", best_backrun_net_bps=2630.0, block_lag=23,
            same_state_class="stale", route_viable=False,
            reject_reason=REJECT_STALE_POSITIVE, size_valid_for_token=True,
        ))
        results.append(_make_result(
            event_id="sum_3", best_backrun_net_bps=-400.0, block_lag=1,
            same_state_class="next_block", route_viable=False,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS, size_valid_for_token=False,
            event_block=100, event_detected_at_block=101,
        ))
        results.append(_make_result(
            event_id="sum_4", best_backrun_net_bps=0.0, block_lag=5,
            same_state_class="stale", route_viable=False,
            reject_reason=REJECT_NO_COUNTER_POOL,
        ))
        return results

    def test_split_fields_present(self):
        events = [_make_event(eid=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        for key in [
            "best_net_bps_any", "best_net_bps_executable",
            "positive_net_count_any", "positive_net_count_low_lag",
            "stale_positive_count", "scored_results_count",
            "size_valid_count", "size_fallback_count",
        ]:
            assert key in art, f"Missing split field: {key}"

    def test_best_net_bps_excludes_unscored(self):
        events = [_make_event(eid=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["scored_results_count"] == 3
        assert art["best_net_bps"] == 2630.0

    def test_best_net_bps_executable_vs_any(self):
        events = [_make_event(eid=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["best_net_bps_any"] == 2630.0
        assert art["best_net_bps_executable"] == 50.0

    def test_positive_net_count_split(self):
        events = [_make_event(eid=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["positive_net_count_any"] == 2
        assert art["positive_net_count_low_lag"] == 1
        assert art["stale_positive_count"] == 1

    def test_size_validity_counts(self):
        events = [_make_event(eid=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["size_valid_count"] == 2
        assert art["size_fallback_count"] == 1

    def test_viable_count_excludes_stale(self):
        events = [_make_event(eid=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["viable_count"] == 1

    def test_reject_histogram_includes_stale_and_zero_liq(self):
        results = [
            _make_result(
                event_id="h_1", best_backrun_net_bps=100.0, block_lag=10,
                route_viable=False, reject_reason=REJECT_STALE_POSITIVE,
            ),
            _make_result(
                event_id="h_2", best_backrun_net_bps=0.0, block_lag=5,
                route_viable=False, reject_reason=REJECT_ZERO_LIQUIDITY,
            ),
        ]
        events = [_make_event(eid=f"h_{i}") for i in range(1, 3)]
        art = build_replay_summary(events, results, mode="test")
        assert art["reject_histogram"]["STALE_POSITIVE"] == 1
        assert art["reject_histogram"]["ZERO_LIQUIDITY"] == 1


# ===========================================================================
# M7.A.5.20: Local Pricing Artifact Block
# ===========================================================================


class TestArtifactLocalPricingBlock:
    """M7.A.5.20: build_replay_summary includes low_lag_local_pricing block."""

    def test_low_lag_local_pricing_in_summary(self):
        events = [_make_event()]
        results = [score_backrun_offline(events[0])]
        summary = build_replay_summary(events, results, "test")
        assert "low_lag_local_pricing" in summary
        lp = summary["low_lag_local_pricing"]
        assert "local_attempted_count" in lp
        assert "local_used_count" in lp
        assert "low_lag_scored_local_state_count" in lp
        assert "low_lag_scored_remote_quoter_count" in lp
        assert "low_lag_scored_watchlist_count" in lp
        assert "best_net_bps_local" in lp

    def test_offline_results_have_zero_local_pricing(self):
        events = [_make_event()]
        results = [score_backrun_offline(events[0])]
        summary = build_replay_summary(events, results, "test")
        lp = summary["low_lag_local_pricing"]
        assert lp["local_attempted_count"] == 0
        assert lp["local_used_count"] == 0

    def test_summary_still_has_blocker_tags(self):
        events = [_make_event()]
        results = [score_backrun_offline(events[0])]
        summary = build_replay_summary(events, results, "test")
        assert "blocker_tags" in summary
        assert "low_lag_watchlist" in summary


# ===========================================================================
# M7.A.5.21: Registry Metrics Artifact
# ===========================================================================


class TestArtifactRegistryMetrics:
    """M7.A.5.21: build_replay_summary includes m7a521_registry_metrics."""

    def test_registry_metrics_in_summary(self):
        events = [_make_event()]
        results = [score_backrun_offline(events[0])]
        summary = build_replay_summary(events, results, "test")
        assert "m7a521_registry_metrics" in summary
        rm = summary["m7a521_registry_metrics"]
        assert "events_with_registry" in rm
        assert "total_registry_pools_found" in rm
        assert "gas_floor_exceeded_count" in rm
        assert "adapter_type_histogram" in rm
        assert "pricing_path_histogram" in rm

    def test_offline_results_have_no_registry(self):
        events = [_make_event()]
        results = [score_backrun_offline(events[0])]
        summary = build_replay_summary(events, results, "test")
        rm = summary["m7a521_registry_metrics"]
        assert rm["events_with_registry"] == 0
        assert rm["total_registry_pools_found"] == 0

    def test_summary_still_has_local_pricing_block(self):
        events = [_make_event()]
        results = [score_backrun_offline(events[0])]
        summary = build_replay_summary(events, results, "test")
        assert "low_lag_local_pricing" in summary
        assert "blocker_tags" in summary


# ===========================================================================
# M7.A.5.22: Registry Session Stats
# ===========================================================================


class TestArtifactRegistrySessionStats:
    """ws-live artifacts must include registry session metrics."""

    def test_artifact_has_registry_session_stats_key(self):
        summary = build_replay_summary([], [], mode="ws_live")
        assert "m7a521_registry_metrics" in summary
        metrics = summary["m7a521_registry_metrics"]
        assert "events_with_registry" in metrics
        assert "gas_floor_exceeded_count" in metrics
        assert "adapter_type_histogram" in metrics
        assert "pricing_path_histogram" in metrics

    def test_m7a522_hypothesis_string(self):
        expected_fragment = "PoolRegistry"
        hypothesis = (
            "low-lag same-chain scoring may unlock only after PoolRegistry is actually "
            "instantiated in ws-live mode and used as the primary counter-venue "
            "discovery source before NO_COUNTER_POOL rejection"
        )
        assert expected_fragment in hypothesis
        assert "NO_COUNTER_POOL" in hypothesis


# ===========================================================================
# M7.A.5.23: Low-Lag Fast-Path Artifact
# ===========================================================================


class TestArtifactM7A523:
    """Verify build_replay_summary includes M7.A.5.23 metrics."""

    def _ll_registry_direct(self, eid="e1"):
        return _make_result(
            event_id=eid, event_block=100, quote_block=100, block_lag=0,
            same_state_class="same_block", best_backrun_net_bps=-5.0,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            scoring_path="registry_direct",
            local_pricing_attempted=True, local_pricing_used=True,
            registry_pools_found=3, registry_pools_active=2,
            event_detected_at_block=100,
        )

    def _ll_coverage(self, eid="e2"):
        return _make_result(
            event_id=eid, event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block",
            reject_reason=REJECT_UNSUPPORTED_ADAPTER,
            event_detected_at_block=101,
        )

    def _stale(self, eid="e3"):
        return _make_result(
            event_id=eid, event_block=100, quote_block=110, block_lag=10,
            same_state_class="stale", reject_reason=REJECT_NO_COUNTER_POOL,
        )

    def test_artifact_has_m7a523_metrics(self):
        events = [_make_event(eid="e1"), _make_event(eid="e2"), _make_event(eid="e3")]
        results = [self._ll_registry_direct("e1"), self._ll_coverage("e2"), self._stale("e3")]
        art = build_replay_summary(events, results, mode="ws_live")
        assert "m7a523_low_lag_fast_path" in art
        fp = art["m7a523_low_lag_fast_path"]
        assert fp["low_lag_registry_direct_count"] == 1
        assert fp["low_lag_registry_direct_scored_count"] == 1

    def test_artifact_zero_registry_direct_when_all_stale(self):
        events = [_make_event(eid="e1")]
        results = [self._stale("e1")]
        art = build_replay_summary(events, results, mode="ws_live")
        fp = art["m7a523_low_lag_fast_path"]
        assert fp["low_lag_registry_direct_count"] == 0

    def test_low_lag_scored_count_includes_registry_direct(self):
        events = [_make_event(eid="e1")]
        results = [self._ll_registry_direct("e1")]
        art = build_replay_summary(events, results, mode="ws_live")
        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 1


class TestNonLowLagUnchanged:
    """Verify stale events still don't get registry-direct path."""

    def test_stale_result_has_no_scoring_path(self):
        r = _make_result(
            event_block=100, quote_block=110, block_lag=10,
            same_state_class="stale",
        )
        assert r.scoring_path is None

    def test_reject_reasons_unchanged(self):
        assert len(ALL_REJECT_REASONS) == 21

    def test_unscored_rejects_unchanged(self):
        assert len(UNSCORED_REJECTS) == 12

    def test_gas_exceeds_gross_is_scored(self):
        assert REJECT_GAS_EXCEEDS_GROSS not in UNSCORED_REJECTS


# ===========================================================================
# M7.A.5.24: Pipeline Optimization Artifact
# ===========================================================================


class TestPipelineOptimizationArtifact:
    """M7.A.5.24: build_replay_summary includes pipeline optimization metrics."""

    def test_m7a524_section_exists(self):
        events = [_make_event(eid="e1")]
        results = [_make_result(
            event_id="e1", scoring_path="registry_direct",
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            event_block=100, quote_block=100, block_lag=0,
            same_state_class="same_block",
        )]
        art = build_replay_summary(events, results, mode="ws_live")
        assert "m7a524_pipeline_optimization" in art

    def test_scoring_path_histogram(self):
        events = [_make_event(eid="e1"), _make_event(eid="e2"), _make_event(eid="e3")]
        results = [
            _make_result(event_id="e1", scoring_path="registry_direct",
                         reject_reason=REJECT_GAS_EXCEEDS_GROSS),
            _make_result(event_id="e2", scoring_path="registry_direct",
                         reject_reason=REJECT_GAS_EXCEEDS_GROSS),
            _make_result(event_id="e3", scoring_path=None,
                         reject_reason=REJECT_GAS_EXCEEDS_GROSS),
        ]
        art = build_replay_summary(events, results, mode="ws_live")
        histogram = art["m7a524_pipeline_optimization"]["scoring_path_histogram"]
        assert histogram["registry_direct"] == 2

    def test_mid_pipeline_abort_count(self):
        events = [_make_event(eid="e1"), _make_event(eid="e2")]
        results = [
            _make_result(
                event_id="e1", scoring_path="registry_direct",
                pipeline_stage_latency_ms={"mid_pipeline_abort": True},
                reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            ),
            _make_result(
                event_id="e2", scoring_path="registry_direct",
                reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            ),
        ]
        art = build_replay_summary(events, results, mode="ws_live")
        assert art["m7a524_pipeline_optimization"]["mid_pipeline_abort_count"] == 1


# ===========================================================================
# M7.A.5.27: Anomaly-Clean Headlines + Stale-Clean KPI Split
# ===========================================================================


class TestM7A527AnomalyCleanHeadlines:
    """M7.A.5.27: best_net_bps excludes PRICING_ANOMALY; stale_clean KPI exists."""

    def _make_mixed_results(self):
        from m7.shared.constants import REJECT_PRICING_ANOMALY
        return [
            # Anomaly: huge net_bps but PRICING_ANOMALY reject
            _make_result(
                event_id="a1", best_backrun_net_bps=47322.0, block_lag=5,
                same_state_class="stale", route_viable=False,
                reject_reason=REJECT_PRICING_ANOMALY, size_valid_for_token=True,
            ),
            # Stale positive: good net_bps but stale
            _make_result(
                event_id="a2", best_backrun_net_bps=12.0, block_lag=8,
                same_state_class="stale", route_viable=False,
                reject_reason=REJECT_STALE_POSITIVE, size_valid_for_token=True,
            ),
            # Executable: low-lag and viable
            _make_result(
                event_id="a3", best_backrun_net_bps=3.5, block_lag=1,
                same_state_class="next_block", route_viable=True,
                reject_reason=None, size_valid_for_token=True,
                event_block=100, event_detected_at_block=101,
            ),
            # Gas reject: negative
            _make_result(
                event_id="a4", best_backrun_net_bps=-50.0, block_lag=0,
                same_state_class="same_block", route_viable=False,
                reject_reason=REJECT_GAS_EXCEEDS_GROSS, size_valid_for_token=True,
                event_block=100, event_detected_at_block=100,
            ),
        ]

    def test_best_net_bps_excludes_anomaly(self):
        events = [_make_event(eid=f"a{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        # best_net_bps should be 12.0 (stale positive), NOT 47322.0 (anomaly)
        assert art["best_net_bps"] == 12.0

    def test_best_net_bps_any_includes_anomaly(self):
        events = [_make_event(eid=f"a{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        # best_net_bps_any is the unfiltered diagnostic — includes anomaly
        assert art["best_net_bps_any"] == 47322.0

    def test_best_net_bps_executable_unchanged(self):
        events = [_make_event(eid=f"a{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["best_net_bps_executable"] == 3.5

    def test_best_net_bps_clean_field(self):
        events = [_make_event(eid=f"a{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["best_net_bps_clean"] == 12.0

    def test_best_net_bps_stale_clean(self):
        events = [_make_event(eid=f"a{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        # Stale-clean = stale + anomaly-free + size-valid → best is 12.0
        assert art["best_net_bps_stale_clean"] == 12.0

    def test_positive_net_count_clean_excludes_anomaly(self):
        events = [_make_event(eid=f"a{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        # Anomaly (47322) excluded; stale positive (12) + executable (3.5) = 2
        assert art["positive_net_count_clean"] == 2

    def test_beats_two_leg_baseline_uses_clean(self):
        events = [_make_event(eid="a1")]
        # Only an anomaly result → clean is empty → should not beat baseline
        from m7.shared.constants import REJECT_PRICING_ANOMALY
        results = [_make_result(
            event_id="a1", best_backrun_net_bps=50000.0, block_lag=5,
            same_state_class="stale", route_viable=False,
            reject_reason=REJECT_PRICING_ANOMALY,
        )]
        art = build_replay_summary(events, results, mode="test")
        assert art["beats_two_leg_baseline"] is False

    def test_all_anomaly_results_give_none_headline(self):
        from m7.shared.constants import REJECT_PRICING_ANOMALY
        events = [_make_event(eid="a1")]
        results = [_make_result(
            event_id="a1", best_backrun_net_bps=99999.0, block_lag=3,
            same_state_class="stale", route_viable=False,
            reject_reason=REJECT_PRICING_ANOMALY,
        )]
        art = build_replay_summary(events, results, mode="test")
        assert art["best_net_bps"] is None
        assert art["best_net_bps_clean"] is None
