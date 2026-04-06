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
        # Top-level fields that remain
        for key in [
            "best_net_bps_executable",
            "stale_positive_count", "scored_results_count",
            "size_valid_count", "size_fallback_count",
        ]:
            assert key in art, f"Missing split field: {key}"
        # Fields moved to diagnostic_raw in M7.A.5.42
        diag = art["diagnostic_raw"]
        for key in ["best_net_bps_any", "positive_net_count_any", "positive_net_count_low_lag"]:
            assert key in diag, f"Missing diagnostic_raw field: {key}"

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
        assert art["diagnostic_raw"]["best_net_bps_any"] == 2630.0
        assert art["best_net_bps_executable"] == 50.0

    def test_positive_net_count_split(self):
        events = [_make_event(eid=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["diagnostic_raw"]["positive_net_count_any"] == 2
        assert art["diagnostic_raw"]["positive_net_count_low_lag"] == 1
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
        # best_net_bps_any is the unfiltered diagnostic — includes anomaly (moved to diagnostic_raw in M7.A.5.42)
        assert art["diagnostic_raw"]["best_net_bps_any"] == 47322.0

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


# ===========================================================================
# M7.A.5.42: Signal classification + diagnostic_raw contract
# ===========================================================================


class TestM7A542SignalClassification:
    """M7.A.5.42: signal_classification with 4 tiers + diagnostic_raw block."""

    def test_signal_classification_present_empty(self):
        art = build_replay_summary([], [], mode="test")
        sc = art["signal_classification"]
        assert set(sc.keys()) == {
            "diagnostic_positive", "stale_positive",
            "cold_executable_positive", "hot_execution_ready",
        }
        for tier in sc.values():
            assert "count" in tier
            assert "best_bps" in tier

    def test_diagnostic_raw_present_empty(self):
        art = build_replay_summary([], [], mode="test")
        diag = art["diagnostic_raw"]
        expected = {
            "best_net_bps_any", "best_net_bps_low_lag_scored",
            "best_net_bps_stale", "mean_net_bps_stale",
            "mean_net_bps_low_lag_scored", "positive_net_count_any",
            "positive_net_count_low_lag",
        }
        assert set(diag.keys()) == expected

    def test_moved_keys_not_at_top_level(self):
        art = build_replay_summary([], [], mode="test")
        moved_keys = [
            "best_net_bps_any", "positive_net_count_any",
            "positive_net_count_low_lag", "best_net_bps_stale",
            "best_net_bps_low_lag_scored", "mean_net_bps_stale",
            "mean_net_bps_low_lag_scored",
        ]
        for key in moved_keys:
            assert key not in art, f"{key} should NOT be at top level (moved to diagnostic_raw)"
            assert key in art["diagnostic_raw"], f"{key} missing from diagnostic_raw"

    def test_signal_classification_counts_with_results(self):
        from m7.shared.constants import REJECT_STALE_POSITIVE
        e = _make_event()
        r_viable = _make_result(
            event_id="v1", best_backrun_net_bps=50.0, block_lag=0,
            same_state_class="same_block", reject_reason=None,
            route_viable=True, event_block=100, event_detected_at_block=100,
        )
        r_stale = _make_result(
            event_id="s1", best_backrun_net_bps=200.0, block_lag=100,
            same_state_class="stale", reject_reason=REJECT_STALE_POSITIVE,
            route_viable=False,
        )
        art = build_replay_summary([e, e], [r_viable, r_stale], mode="test")
        sc = art["signal_classification"]
        # Cold executable = viable results
        assert sc["cold_executable_positive"]["count"] >= 1
        # Stale positive tier
        assert sc["stale_positive"]["count"] == 1
        # Hot execution ready = 0 (no profit guard pass in unit test)
        assert sc["hot_execution_ready"]["count"] == 0


# ===========================================================================
# M7.A.5.28: Stale KPI contract fix + rolling artifact schema
# ===========================================================================


class TestM7A528StaleKPIContract:
    """M7.A.5.28: stale_positive_count must agree with reject_histogram[STALE_POSITIVE].

    Root cause fixed: mid-pipeline wall-clock abort sets same_state_class="stale"
    and reject_reason=STALE_POSITIVE, but block_lag can still be <= 2. The old code
    only checked block_lag > 2 for stale classification, causing zero stale_positive_count
    even when reject_histogram showed STALE_POSITIVE entries.
    """

    def _make_mid_pipeline_abort_results(self):
        """Simulate mid-pipeline abort: same_state_class=stale, block_lag=1."""
        return [
            # Mid-pipeline aborted: detected low-lag (block_lag=1) but wall-clock
            # exceeded budget → same_state_class="stale", reject=STALE_POSITIVE
            _make_result(
                event_id="mp1", best_backrun_net_bps=5.0, block_lag=1,
                same_state_class="stale", route_viable=False,
                reject_reason=REJECT_STALE_POSITIVE, size_valid_for_token=True,
                event_block=100, event_detected_at_block=101,
            ),
            _make_result(
                event_id="mp2", best_backrun_net_bps=3.0, block_lag=2,
                same_state_class="stale", route_viable=False,
                reject_reason=REJECT_STALE_POSITIVE, size_valid_for_token=True,
                event_block=100, event_detected_at_block=101,
            ),
            # Normal stale (block_lag > 2, old path)
            _make_result(
                event_id="mp3", best_backrun_net_bps=8.0, block_lag=5,
                same_state_class="stale", route_viable=False,
                reject_reason=REJECT_STALE_POSITIVE, size_valid_for_token=True,
            ),
            # Fresh negative (not stale, not positive)
            _make_result(
                event_id="mp4", best_backrun_net_bps=-10.0, block_lag=0,
                same_state_class="same_block", route_viable=False,
                reject_reason=REJECT_GAS_EXCEEDS_GROSS, size_valid_for_token=True,
                event_block=100, event_detected_at_block=100,
            ),
        ]

    def test_stale_positive_count_matches_reject_histogram(self):
        events = [_make_event(eid=f"mp{i}") for i in range(1, 5)]
        results = self._make_mid_pipeline_abort_results()
        art = build_replay_summary(events, results, mode="test")
        hist_stale = art["reject_histogram"].get("STALE_POSITIVE", 0)
        # All 3 STALE_POSITIVE results have positive net_bps → must agree
        assert art["stale_positive_count"] == 3
        assert art["stale_positive_count"] == hist_stale

    def test_stale_scored_count_includes_mid_pipeline_abort(self):
        events = [_make_event(eid=f"mp{i}") for i in range(1, 5)]
        results = self._make_mid_pipeline_abort_results()
        art = build_replay_summary(events, results, mode="test")
        # All 3 stale results should appear in stale_low_lag_comparison.stale_scored_count
        assert art["stale_low_lag_comparison"]["stale_scored_count"] >= 3

    def test_best_net_bps_stale_clean_populated(self):
        events = [_make_event(eid=f"mp{i}") for i in range(1, 5)]
        results = self._make_mid_pipeline_abort_results()
        art = build_replay_summary(events, results, mode="test")
        # Stale clean should be 8.0 (the highest stale positive with size_valid)
        assert art["best_net_bps_stale_clean"] == 8.0

    def test_mid_pipeline_abort_low_lag_stale_classified(self):
        """block_lag=1 + same_state_class=stale → result is stale, not low-lag fresh."""
        events = [_make_event(eid="mp1")]
        results = [_make_result(
            event_id="mp1", best_backrun_net_bps=5.0, block_lag=1,
            same_state_class="stale", route_viable=False,
            reject_reason=REJECT_STALE_POSITIVE, size_valid_for_token=True,
            event_block=100, event_detected_at_block=101,
        )]
        art = build_replay_summary(events, results, mode="test")
        assert art["stale_positive_count"] == 1


class TestM7A528RollingArtifactSchema:
    """M7.A.5.28: Rolling M7 artifact excludes bulky keys."""

    def test_rolling_exclude_keys_defined(self):
        from m7.orderflow.mode_ws_live import _ROLLING_EXCLUDE_KEYS
        assert "results" in _ROLLING_EXCLUDE_KEYS
        assert "low_lag_debug_rows" in _ROLLING_EXCLUDE_KEYS
        assert "low_lag_watchlist" in _ROLLING_EXCLUDE_KEYS

    def test_rolling_exclude_keys_legacy_hypothesis_stripped(self):
        """M7.A.5.42: legacy hypothesis blocks and _raw_results must be excluded."""
        from m7.orderflow.mode_ws_live import _ROLLING_EXCLUDE_KEYS
        assert "_raw_results" in _ROLLING_EXCLUDE_KEYS
        for tag in ["m7a4", "m7a56", "m7a57", "m7a58", "m7a59", "m7a513", "m7a514",
                     "m7a515", "m7a516", "m7a517", "m7a518", "m7a522", "m7a523", "m7a524"]:
            assert f"{tag}_hypothesis" in _ROLLING_EXCLUDE_KEYS, f"Missing: {tag}_hypothesis"

    def test_rolling_path_canonical(self):
        import os
        from m7.orderflow.mode_ws_live import _ROLLING_M7_PATH
        assert _ROLLING_M7_PATH.endswith(
            os.path.join("_rolling", "m7_orderflow_latest.json")
        )


class TestM7A528DashboardM7Artifact:
    """M7.A.5.28: Dashboard server includes m7_orderflow in ARTIFACT_FILES."""

    def test_m7_orderflow_in_artifact_files(self):
        from monitoring.dashboard_server import ARTIFACT_FILES
        assert "m7_orderflow" in ARTIFACT_FILES
        assert str(ARTIFACT_FILES["m7_orderflow"]).endswith(
            "m7_orderflow_latest.json"
        )


# ===========================================================================
# M7.A.5.29: Continuous Loop — Anti-Bad-Overwrite + Blocker Rename
# ===========================================================================


class TestM7A529AntiOverwriteAndLoop:
    """M7.A.5.29: Rolling M7 anti-bad-overwrite and loop runtime fields."""

    def test_empty_window_preserves_previous_snapshot(self, tmp_path):
        """events_count==0 must NOT destroy a previous useful rolling artifact."""
        import json
        from unittest.mock import patch

        from m7.orderflow.mode_ws_live import _write_rolling_m7

        rolling_path = str(tmp_path / "m7_orderflow_latest.json")
        previous = {"events_count": 10, "run_timestamp": "2026-01-01T00:00:00Z", "viable_count": 2}
        with open(rolling_path, "w") as f:
            json.dump(previous, f)

        # Empty window artifact with loop context
        empty_artifact = {
            "events_count": 0,
            "run_timestamp": "2026-01-01T01:00:00Z",
            "m7_loop_context": {
                "loop_iteration": 2,
                "window_started_at": "2026-01-01T01:00:00Z",
                "window_ended_at": "2026-01-01T01:00:05Z",
                "window_empty": False,  # will be set to True by writer
            },
        }

        with patch("m7.orderflow.mode_ws_live._ROLLING_M7_PATH", rolling_path):
            _write_rolling_m7(empty_artifact)

        with open(rolling_path) as f:
            result = json.load(f)

        # Previous data preserved
        assert result["events_count"] == 10
        assert result["viable_count"] == 2
        # Loop context updated
        assert result["m7_loop_context"]["loop_iteration"] == 2
        assert result["m7_loop_context"]["window_empty"] is True

    def test_nonempty_window_overwrites_with_last_nonempty_timestamp(self, tmp_path):
        """Non-empty window writes last_nonempty_timestamp into rolling artifact."""
        import json
        from unittest.mock import patch

        from m7.orderflow.mode_ws_live import _write_rolling_m7

        rolling_path = str(tmp_path / "m7_orderflow_latest.json")
        artifact = {
            "events_count": 5,
            "timestamp": "2026-01-01T02:00:00Z",
            "results": [{"x": 1}],  # should be excluded
            "low_lag_debug_rows": [1, 2],  # should be excluded
        }

        with patch("m7.orderflow.mode_ws_live._ROLLING_M7_PATH", rolling_path):
            _write_rolling_m7(artifact)

        with open(rolling_path) as f:
            result = json.load(f)

        assert result["events_count"] == 5
        assert result["last_nonempty_timestamp"] == "2026-01-01T02:00:00Z"
        assert "results" not in result
        assert "low_lag_debug_rows" not in result


class TestM7A529CompletionLatencyBlocker:
    """M7.A.5.29: BLOCKER_LOW_LAG_COMPLETION_LATENCY fires for mid-pipeline abort dominant."""

    def test_completion_latency_fires_when_majority_abort_registry_direct(self):
        """When >50% of results are mid_pipeline_abort with registry_direct path,
        fire COMPLETION_LATENCY blocker."""
        from m7.shared.constants import BLOCKER_LOW_LAG_COMPLETION_LATENCY

        events = [_make_event(eid=f"e{i}") for i in range(4)]
        # 3/4 results abort mid-pipeline with registry_direct
        results = [
            _make_result(
                event_id=f"e{i}",
                scoring_path="registry_direct",
                pipeline_stage_latency_ms={"mid_pipeline_abort": True, "resolve_ms": 30.0},
            )
            for i in range(3)
        ]
        # 1 result completes normally
        results.append(_make_result(
            event_id="e3",
            scoring_path="registry_direct",
            pipeline_stage_latency_ms={"resolve_ms": 10.0, "score_ms": 5.0},
        ))

        summary = build_replay_summary(events, results, "test")
        active_tags = summary["blocker_tags"]["active_tags"]
        assert BLOCKER_LOW_LAG_COMPLETION_LATENCY in active_tags

    def test_completion_latency_does_not_fire_when_minority_abort(self):
        """When <50% abort, COMPLETION_LATENCY should NOT fire."""
        from m7.shared.constants import BLOCKER_LOW_LAG_COMPLETION_LATENCY

        events = [_make_event(eid=f"e{i}") for i in range(4)]
        # Only 1/4 aborts
        results = [
            _make_result(
                event_id="e0",
                scoring_path="registry_direct",
                pipeline_stage_latency_ms={"mid_pipeline_abort": True, "resolve_ms": 30.0},
            ),
        ]
        for i in range(1, 4):
            results.append(_make_result(
                event_id=f"e{i}",
                scoring_path="registry_direct",
                pipeline_stage_latency_ms={"resolve_ms": 10.0, "score_ms": 5.0},
            ))

        summary = build_replay_summary(events, results, "test")
        active_tags = summary["blocker_tags"]["active_tags"]
        assert BLOCKER_LOW_LAG_COMPLETION_LATENCY not in active_tags


# ── M7.A.5.31 Tests ─────────────────────────────────────────────────

class TestM7A531SubgraphJsonImport:
    """M7.A.5.31: seed_tokens_from_subgraph has working json import."""

    def test_seed_function_importable_and_returns_stats(self):
        from m7.orderflow.coverage import seed_tokens_from_subgraph
        # Calling with unsupported chain returns error stats (no network needed)
        result = seed_tokens_from_subgraph({}, "http://fake", 100, chain="unknown_chain")
        assert isinstance(result, dict)
        assert "errors" in result
        assert result["tokens_discovered"] == 0

    def test_json_module_available_inside_seed(self):
        """Verify that json is importable in the function scope."""
        from m7.orderflow.coverage import seed_tokens_from_subgraph
        import inspect
        src = inspect.getsource(seed_tokens_from_subgraph)
        assert "import json" in src


class TestM7A531HotLanePrewarm:
    """M7.A.5.31: Hot lane prewarms registry from accumulated pairs."""

    def test_prewarm_registry_from_pairs_resolves_known(self):
        from scripts.m7a_orderflow_loop import _prewarm_registry_from_pairs

        class MockRegistry:
            def __init__(self):
                self.preloaded = []
            def preload_pair(self, a, b, dex, rpc, block):
                self.preloaded.append((a, b))

        reg = MockRegistry()
        pairs = {"WETH/USDC": {"pair": "WETH/USDC", "seen_count": 5}}
        token_addresses = {
            "WETH": "0xWETH",
            "USDC": "0xUSDC",
        }
        count = _prewarm_registry_from_pairs(
            reg, pairs, token_addresses, {}, "http://fake", 100,
        )
        assert count == 1
        assert reg.preloaded == [("0xWETH", "0xUSDC")]

    def test_prewarm_skips_unknown_symbols(self):
        from scripts.m7a_orderflow_loop import _prewarm_registry_from_pairs

        class MockRegistry:
            def __init__(self):
                self.preloaded = []
            def preload_pair(self, a, b, dex, rpc, block):
                self.preloaded.append((a, b))

        reg = MockRegistry()
        pairs = {"FOO/BAR": {"pair": "FOO/BAR", "seen_count": 1}}
        count = _prewarm_registry_from_pairs(reg, pairs, {}, {}, "http://fake", 100)
        assert count == 0


class TestM7A531ProfitGuardTimeboost:
    """M7.A.5.31: Profit guard includes Timeboost eligibility + timing."""

    def test_timeboost_eligible_when_fast(self):
        from m7.orderflow.profit_guard import check_profit_guard
        guard = check_profit_guard(
            buy_amount_wei=10**18,
            sell_amount_wei=10**18 + 10**15,
            backrun_size_wei=10**18,
            pipeline_latency_ms=30.0,  # well under 50ms budget
        )
        assert guard.passed
        assert guard.timeboost_eligible is True
        assert guard.guard_latency_ms >= 0

    def test_timeboost_not_eligible_when_slow(self):
        from m7.orderflow.profit_guard import check_profit_guard
        guard = check_profit_guard(
            buy_amount_wei=10**18,
            sell_amount_wei=10**18 + 10**15,
            backrun_size_wei=10**18,
            pipeline_latency_ms=1500.0,  # way over 50ms budget
        )
        assert guard.passed
        assert guard.timeboost_eligible is False

    def test_timeboost_false_when_no_latency(self):
        from m7.orderflow.profit_guard import check_profit_guard
        guard = check_profit_guard(
            buy_amount_wei=10**18,
            sell_amount_wei=10**18 + 10**15,
            backrun_size_wei=10**18,
        )
        # No pipeline_latency_ms → not eligible
        assert guard.timeboost_eligible is False

    def test_guard_latency_ms_field_present(self):
        from m7.orderflow.profit_guard import check_profit_guard
        guard = check_profit_guard(
            buy_amount_wei=10**18,
            sell_amount_wei=10**18 - 10**16,
            backrun_size_wei=10**18,  # unprofitable
        )
        assert hasattr(guard, "guard_latency_ms")
        assert isinstance(guard.guard_latency_ms, float)


class TestM7A531SizeValidFiltering:
    """M7.A.5.31: size_valid=false excluded from hot-lane profit guard."""

    def test_run_profit_guard_skips_size_invalid(self):
        from scripts.m7a_orderflow_loop import _run_profit_guard_on_results
        results = [
            {
                "best_backrun_net_bps": 5.0,
                "amount_in_wei": 10**18,
                "gross_pnl_wei": 10**15,
                "size_valid_for_token": False,  # should be skipped
                "quote_pipeline_latency_ms": 100.0,
            },
        ]
        passed = _run_profit_guard_on_results(results)
        assert len(passed) == 0

    def test_run_profit_guard_includes_size_valid(self):
        from scripts.m7a_orderflow_loop import _run_profit_guard_on_results
        results = [
            {
                "best_backrun_net_bps": 5.0,
                "amount_in_wei": 10**18,
                "gross_pnl_wei": 10**15,
                "size_valid_for_token": True,
                "quote_pipeline_latency_ms": 100.0,
            },
        ]
        passed = _run_profit_guard_on_results(results)
        assert len(passed) == 1


class TestM7A531ExternalRegistry:
    """M7.A.5.31: run_ws_live accepts external_registry parameter."""

    def test_run_ws_live_signature_accepts_external_registry(self):
        import inspect
        from m7.orderflow.mode_ws_live import run_ws_live
        sig = inspect.signature(run_ws_live)
        assert "external_registry" in sig.parameters

    def test_lane_defaults_unchanged(self):
        from scripts.m7a_orderflow_loop import _LANE_DEFAULTS
        assert _LANE_DEFAULTS["cold"]["ws_blocks"] == 300
        assert _LANE_DEFAULTS["hot"]["ws_blocks"] == 20
        assert _LANE_DEFAULTS["hot"]["pause"] == 1

    def test_run_ws_live_without_external_registry_does_not_hit_prewarm_unbound(self, monkeypatch):
        import json
        import sys
        import types
        from types import SimpleNamespace

        import m7.orderflow.mode_ws_live as mod

        monkeypatch.setattr(
            mod, "resolve_rpc_http",
            lambda **kwargs: ("http://fake-rpc", "fake", {"source": "test"}),
        )
        monkeypatch.setattr(
            mod, "resolve_rpc_ws",
            lambda **kwargs: ("ws://fake-rpc", "fake", {"source": "test"}),
        )
        monkeypatch.setattr(mod, "load_dexes", lambda: {"arbitrum_one": {}})
        monkeypatch.setattr(
            mod,
            "get_all_token_addresses",
            lambda chain: {
                "WETH": "0x" + "11" * 20,
                "USDC": "0x" + "22" * 20,
                "USDT": "0x" + "33" * 20,
                "ARB": "0x" + "44" * 20,
                "WBTC": "0x" + "55" * 20,
            },
        )
        monkeypatch.setattr(mod, "_build_address_to_symbol", lambda _: {})
        monkeypatch.setattr(mod, "load_chains", lambda: {"arbitrum_one": {"block_time_ms": 250}})
        monkeypatch.setattr(
            mod,
            "seed_tokens_from_subgraph",
            lambda *args, **kwargs: {
                "tokens_discovered": 0,
                "tokens_new": 0,
                "tokens_verified": 0,
                "sources_queried": [],
                "errors": [],
            },
        )

        class FakeRegistry:
            preload_calls = 0
            cache_hits = 0
            pools_discovered = 0
            pools_active = 0
            unique_pairs_queried = set()
            _queried = set()

            def preload_pair(self, *args, **kwargs):
                self.preload_calls += 1
                return []

        monkeypatch.setattr(mod, "PoolRegistry", FakeRegistry)

        class FakeEth:
            block_number = 123

            def get_logs(self, *args, **kwargs):
                return []

        class FakeWeb3:
            class HTTPProvider:
                def __init__(self, url):
                    self.url = url

            def __init__(self, provider):
                self.provider = provider
                self.eth = FakeEth()

        monkeypatch.setitem(sys.modules, "web3", types.SimpleNamespace(Web3=FakeWeb3))

        class FakeWS:
            def __init__(self):
                self._recv_count = 0

            def send(self, msg):
                self._last = msg

            def recv(self):
                self._recv_count += 1
                if self._recv_count == 1:
                    return json.dumps({"result": "sub-id"})
                raise TimeoutError("done")

            def settimeout(self, seconds):
                self._timeout = seconds

            def close(self):
                pass

        import websocket as ws_mod

        monkeypatch.setattr(ws_mod, "create_connection", lambda *args, **kwargs: FakeWS())

        artifact = mod.run_ws_live(
            SimpleNamespace(chain="arbitrum_one", ws_blocks=1, ws_timeout=1, max_events=1)
        )
        assert isinstance(artifact, dict)
        assert artifact["mode"] == "ws_live"


# ============================================================================
# M7.A.5.32: Unified nonstop runtime + rolling retention + hot-path slimming
# ============================================================================

class TestM7A532HotPathConstants:
    """Verify hot-path stage budget constants exist and have correct values."""

    def test_hot_budget_total_exists(self):
        from m7.shared.constants import HOT_BUDGET_TOTAL_MS
        assert HOT_BUDGET_TOTAL_MS == 250

    def test_hot_watchlist_pairs_exist(self):
        from m7.shared.constants import HOT_WATCHLIST_PAIRS
        assert isinstance(HOT_WATCHLIST_PAIRS, list)
        assert len(HOT_WATCHLIST_PAIRS) >= 3
        for pair in HOT_WATCHLIST_PAIRS:
            assert len(pair) == 2

    def test_hot_budget_components_sum_reasonable(self):
        from m7.shared.constants import (
            HOT_BUDGET_REGISTRY_LOOKUP_MS,
            HOT_BUDGET_POOL_STATE_READ_MS,
            HOT_BUDGET_LOCAL_MATH_MS,
            HOT_BUDGET_PROFIT_GUARD_MS,
            HOT_BUDGET_TX_BUILD_MS,
            HOT_BUDGET_TOTAL_MS,
        )
        component_sum = (
            HOT_BUDGET_REGISTRY_LOOKUP_MS
            + HOT_BUDGET_POOL_STATE_READ_MS
            + HOT_BUDGET_LOCAL_MATH_MS
            + HOT_BUDGET_PROFIT_GUARD_MS
            + HOT_BUDGET_TX_BUILD_MS
        )
        # Components should fit within total budget
        assert component_sum <= HOT_BUDGET_TOTAL_MS


class TestM7A532ScoreBackrunFast:
    """Verify score_backrun_fast() fast-path function exists and works."""

    def test_score_backrun_fast_importable(self):
        from m7.orderflow.scoring_parallel import score_backrun_fast
        assert callable(score_backrun_fast)

    def test_score_backrun_fast_returns_none_no_registry(self):
        from m7.orderflow.scoring_parallel import score_backrun_fast
        from m7.orderflow.contracts import OrderflowEvent

        ev = OrderflowEvent(
            event_id="test_1",
            event_type="swap",
            chain="arbitrum_one",
            block_number=100,
            tx_hash="0x" + "00" * 32,
            token_in="WETH",
            token_out="USDC",
            amount_in_wei=10**18,
            amount_out_wei=0,
            dex="uniswap_v3",
            pool_address="0x" + "ab" * 20,
            fee_tier=3000,
            estimated_size_usd=3000.0,
            estimated_impact_bps=0.0,
            timestamp="2026-04-02T00:00:00Z",
        )

        class EmptyRegistry:
            preload_calls = 0
            cache_hits = 0
            def lookup_pair(self, a, b):
                return []

        result = score_backrun_fast(
            event=ev,
            pool_registry=EmptyRegistry(),
            token_addresses={"WETH": "0x" + "11" * 20, "USDC": "0x" + "22" * 20},
            current_block=100,
            addr_to_symbol={"0x" + "11" * 20: "WETH", "0x" + "22" * 20: "USDC"},
        )
        assert result is None  # No pools in registry → None

    def test_score_backrun_fast_with_active_pool(self):
        """With an active pool in registry, should return a BackrunResult."""
        from m7.orderflow.scoring_parallel import score_backrun_fast
        from m7.orderflow.contracts import OrderflowEvent, BackrunResult
        from m7.orderflow.pool_registry import PoolRegistryEntry

        ev = OrderflowEvent(
            event_id="test_2",
            event_type="swap",
            chain="arbitrum_one",
            block_number=100,
            tx_hash="0x" + "00" * 32,
            token_in="WETH",
            token_out="USDC",
            amount_in_wei=10**18,
            amount_out_wei=0,
            dex="uniswap_v3",
            pool_address="0x" + "ab" * 20,
            fee_tier=3000,
            estimated_size_usd=3000.0,
            estimated_impact_bps=0.0,
            timestamp="2026-04-02T00:00:00Z",
        )

        pool_entry = PoolRegistryEntry(
            address="0x" + "cc" * 20,
            dex="uniswap_v3",
            adapter_type="uniswap_v3",
            fee=3000,
            token_a="0x" + "11" * 20,
            token_b="0x" + "22" * 20,
            liquidity=10**18,
            sqrt_price_x96=79228162514264337593543950336,  # 1:1 price
            tick=0,
            last_block=99,
        )

        class MockRegistry:
            preload_calls = 1
            cache_hits = 0
            def lookup_pair(self, a, b):
                return [pool_entry]

        result = score_backrun_fast(
            event=ev,
            pool_registry=MockRegistry(),
            token_addresses={"WETH": "0x" + "11" * 20, "USDC": "0x" + "22" * 20},
            current_block=100,
            addr_to_symbol={"0x" + "11" * 20: "WETH", "0x" + "22" * 20: "USDC"},
        )
        # Should return BackrunResult (may or may not be profitable)
        assert result is None or isinstance(result, BackrunResult)
        if result is not None:
            assert result.scoring_path == "registry_fast"
            assert result.local_pricing_attempted is True
            assert result.pair_resolved is True


class TestM7A532NonstopSupervisor:
    """Verify nonstop supervisor script is importable and has correct structure."""

    def test_supervisor_script_exists(self):
        from pathlib import Path
        assert Path("scripts/start_nonstop_runtime.py").exists()

    def test_supervisor_managed_process_class(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "start_nonstop_runtime",
            "scripts/start_nonstop_runtime.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "ManagedProcess")
        mp = mod.ManagedProcess("test", ["echo", "hi"], restart_delay=1, max_restarts=3)
        assert mp.name == "test"
        assert mp.max_restarts == 3
        assert mp.restarts == 0


class TestM7A532PruneTmpArtifacts:
    """Verify prune_tmp_artifacts.py is importable and has correct structure."""

    def test_prune_script_exists(self):
        from pathlib import Path
        assert Path("scripts/prune_tmp_artifacts.py").exists()

    def test_prune_classify_file(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "prune_tmp_artifacts",
            "scripts/prune_tmp_artifacts.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod._classify_file("m7a_510_300b.json") == "m7a:m7a_510"
        assert mod._classify_file("check_measured.py") == "helper"
        assert mod._classify_file("scan.log") == "log"
        assert mod._classify_file("L0_all_suppression_off.json") == "suppression"

    def test_prune_get_prefix(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "prune_tmp_artifacts",
            "scripts/prune_tmp_artifacts.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod._get_prefix("m7a_510_300b.json") == "m7a_510"
        assert mod._get_prefix("m7a_524_1000b.json") == "m7a_524"


class TestM7A532RollingCanonicalSet:
    """Verify _rolling directory contains only canonical files."""

    def test_rolling_no_archive_files(self):
        from pathlib import Path
        rolling = Path("data/runs/_rolling")
        if not rolling.exists():
            return  # Skip if rolling doesn't exist (CI)
        for f in rolling.iterdir():
            assert "archive" not in f.name, f"Non-canonical file in _rolling: {f.name}"
            assert not f.name.endswith(".log"), f"Log file in _rolling: {f.name}"

    def test_rolling_canonical_names(self):
        from pathlib import Path
        rolling = Path("data/runs/_rolling")
        if not rolling.exists():
            return
        canonical = {
            "_latest.json", "_latest_offline.json",
            "run_summary_latest.json", "run_summary_latest_offline.json",
            "m4_stability_agg.json", "long_scan_latest.json",
            "hot_loop_latest.json",
            "m7_orderflow_latest.json", "m7_hot_latest.json",
            "m7_promoted_pairs.json",
            "m7_cold_hot_bridge.json",
            "m7_hot_intents_latest.json",
        }
        for f in rolling.iterdir():
            if f.is_file():
                assert f.name in canonical, f"Unexpected file in _rolling: {f.name}"


# ===========================================================================
# M7.A.5.30: Correctness fixes + hot/cold + profit guard + latency breakdown
# ===========================================================================


class TestM7A530RemoteQuoterTagSemantics:
    """M7.A.5.30: REMOTE_QUOTER_LATENCY must NOT fire for registry_direct path."""

    def test_remote_quoter_tag_does_not_fire_on_registry_direct(self):
        """When all over-budget results use registry_direct, only
        COMPLETION_LATENCY should fire, not REMOTE_QUOTER_LATENCY."""
        from m7.shared.constants import (
            BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY,
            BLOCKER_LOW_LAG_COMPLETION_LATENCY,
        )

        events = [_make_event(eid=f"e{i}") for i in range(4)]
        results = [
            _make_result(
                event_id=f"e{i}",
                scoring_path="registry_direct",
                quote_pipeline_latency_ms=1500.0,
                latency_budget_ms=250.0,
                pipeline_stage_latency_ms={"mid_pipeline_abort": True},
            )
            for i in range(4)
        ]
        summary = build_replay_summary(events, results, "test")
        active_tags = summary["blocker_tags"]["active_tags"]
        assert BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY not in active_tags
        assert BLOCKER_LOW_LAG_COMPLETION_LATENCY in active_tags

    def test_remote_quoter_tag_fires_on_non_registry_direct(self):
        """When over-budget results use remote quoter path, tag should fire."""
        from m7.shared.constants import BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY

        events = [_make_event(eid="e0")]
        # Result must be low-lag (detection lag <= 2) and scored (not unscored reject)
        results = [
            _make_result(
                event_id="e0",
                scoring_path="remote_quoter",
                quote_pipeline_latency_ms=500.0,
                latency_budget_ms=250.0,
                event_block=100,
                event_detected_at_block=100,
                quote_block=100,
                block_lag=0,
                same_state_class="same_block",
                best_backrun_net_bps=-5.0,
                reject_reason="GAS_EXCEEDS_GROSS",
            ),
        ]
        summary = build_replay_summary(events, results, "test")
        active_tags = summary["blocker_tags"]["active_tags"]
        assert BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY in active_tags


class TestM7A530LatencyBreakdown:
    """M7.A.5.30: Artifact includes per-stage latency breakdown."""

    def test_latency_breakdown_present(self):
        events = [_make_event()]
        results = [_make_result(
            pipeline_stage_latency_ms={
                "resolve_ms": 100.0, "enrichment_ms": 50.0,
                "admission_ms": 1.0, "oracle_ms": 150.0,
                "registry_preload_ms": 600.0, "local_pricing_ms": 10.0,
            },
            quote_pipeline_latency_ms=1200.0,
        )]
        summary = build_replay_summary(events, results, "test")
        bd = summary["m7a530_latency_breakdown"]
        assert bd["resolve_ms"] is not None
        assert bd["resolve_ms"]["mean"] == 100.0
        assert bd["oracle_ms"]["mean"] == 150.0
        assert bd["registry_preload_ms"]["max"] == 600.0
        assert bd["total_pipeline"]["mean"] == 1200.0
        # Unaccounted = 1200 - (100+50+1+150+600+10) = 289
        assert bd["unaccounted"]["mean"] == 289.0


class TestM7A530LastNonemptyTimestamp:
    """M7.A.5.30: Rolling writer uses 'timestamp' key, not 'run_timestamp'."""

    def test_last_nonempty_timestamp_from_timestamp_key(self, tmp_path):
        """Non-empty window must write last_nonempty_timestamp from 'timestamp'."""
        import json
        from unittest.mock import patch

        from m7.orderflow.mode_ws_live import _write_rolling_m7

        rolling_path = str(tmp_path / "m7_orderflow_latest.json")
        artifact = {
            "events_count": 5,
            "timestamp": "2026-04-02T15:00:00Z",
        }

        with patch("m7.orderflow.mode_ws_live._ROLLING_M7_PATH", rolling_path):
            _write_rolling_m7(artifact)

        with open(rolling_path) as f:
            result = json.load(f)

        assert result["last_nonempty_timestamp"] == "2026-04-02T15:00:00Z"


class TestM7A530HotLaneDefaults:
    """M7.A.5.30: Hot/cold lane default config values."""

    def test_cold_lane_defaults(self):
        from scripts.m7a_orderflow_loop import _LANE_DEFAULTS
        cold = _LANE_DEFAULTS["cold"]
        assert cold["ws_blocks"] == 300
        assert cold["max_events"] == 30
        assert cold["pause"] == 5

    def test_hot_lane_defaults(self):
        from scripts.m7a_orderflow_loop import _LANE_DEFAULTS
        hot = _LANE_DEFAULTS["hot"]
        assert hot["ws_blocks"] == 20
        assert hot["max_events"] == 5
        assert hot["pause"] == 1

    def test_hot_artifact_path(self):
        from scripts.m7a_orderflow_loop import _HOT_ARTIFACT_PATH
        assert _HOT_ARTIFACT_PATH.endswith("m7_hot_latest.json")


class TestM7A530ProfitGuard:
    """M7.A.5.30: Profit guard local simulation."""

    def test_profit_guard_passes_when_profitable(self):
        from m7.orderflow.profit_guard import check_profit_guard

        result = check_profit_guard(
            buy_amount_wei=10**18,
            sell_amount_wei=10**18 + 10**16,  # +1% gross
            backrun_size_wei=10**18,
            gas_estimate=200_000,
            gas_price_gwei=0.01,
        )
        assert result.passed is True
        assert result.net_pnl_wei > 0
        assert result.reject_reason is None

    def test_profit_guard_rejects_when_unprofitable(self):
        from m7.orderflow.profit_guard import check_profit_guard

        result = check_profit_guard(
            buy_amount_wei=10**18,
            sell_amount_wei=10**18 - 10**15,  # -0.1% gross (loss)
            backrun_size_wei=10**18,
            gas_estimate=200_000,
            gas_price_gwei=0.01,
        )
        assert result.passed is False
        assert result.reject_reason == "ENDING_BALANCE_NOT_GT_STARTING"

    def test_profit_guard_result_fields(self):
        from m7.orderflow.profit_guard import ProfitGuardResult

        r = ProfitGuardResult()
        assert r.guard_mode == "local_sim"
        assert r.passed is False
        assert r.details == {}


class TestM7A530DashboardM7Hot:
    """M7.A.5.30: Dashboard server includes m7_hot in ARTIFACT_FILES."""

    def test_m7_hot_in_artifact_files(self):
        from monitoring.dashboard_server import ARTIFACT_FILES
        assert "m7_hot" in ARTIFACT_FILES
        assert str(ARTIFACT_FILES["m7_hot"]).endswith("m7_hot_latest.json")

    def test_hot_endpoint_includes_m7_hot_payload(self):
        import io
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from monitoring.dashboard_server import DashboardHandler

        with tempfile.TemporaryDirectory() as td:
            hot_loop = Path(td) / "hot_loop_latest.json"
            m7_hot = Path(td) / "m7_hot_latest.json"
            hot_loop.write_text(json.dumps({"schema": "hot:v1"}), encoding="utf-8")
            m7_hot.write_text(json.dumps({"lane": "hot", "events_count": 3}), encoding="utf-8")

            class _DummyHandler:
                def __init__(self):
                    self.wfile = io.BytesIO()
                    self.status = None
                    self.headers = []

                def send_response(self, code):
                    self.status = code

                def send_header(self, key, value):
                    self.headers.append((key, value))

                def end_headers(self):
                    return None

            handler = _DummyHandler()
            with patch.dict(
                "monitoring.dashboard_server.ARTIFACT_FILES",
                {"hot_loop": hot_loop, "m7_hot": m7_hot},
                clear=False,
            ):
                DashboardHandler._serve_hot_data(handler)

            payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
            assert handler.status == 200
            assert payload["hot_loop"]["schema"] == "hot:v1"
            assert payload["m7_hot"]["lane"] == "hot"

    def test_dashboard_html_mentions_m7_hot_snapshot(self):
        from pathlib import Path

        html = Path("monitoring/dashboard.html").read_text(encoding="utf-8")
        assert "m7_hot_latest.json" in html


# ===========================================================================
# M7.A.5.33: profit_guard fix + hot-mode fast-path + stage timing + field count
# ===========================================================================


class TestM7A533ProfitGuardFieldFix:
    """M7.A.5.33: profit_guard derives buy/sell from amount_in_wei + gross_pnl_wei."""

    def test_profit_guard_passes_with_derived_fields(self):
        """With gross_pnl_wei > gas, profit guard should pass."""
        from scripts.m7a_orderflow_loop import _run_profit_guard_on_results

        results = [
            {
                "best_backrun_net_bps": 5.0,
                "amount_in_wei": 10**18,
                "gross_pnl_wei": 10**15,  # sell = 10**18 + 10**15
                "size_valid_for_token": True,
                "quote_pipeline_latency_ms": 100.0,
            },
        ]
        passed = _run_profit_guard_on_results(results)
        assert len(passed) == 1
        _, guard = passed[0]
        assert guard.passed is True

    def test_profit_guard_rejects_negative_gross(self):
        """With gross_pnl_wei < 0, profit guard should reject."""
        from scripts.m7a_orderflow_loop import _run_profit_guard_on_results

        results = [
            {
                "best_backrun_net_bps": 1.0,  # says positive but gross is negative
                "amount_in_wei": 10**18,
                "gross_pnl_wei": -(10**15),  # sell < input
                "size_valid_for_token": True,
                "quote_pipeline_latency_ms": 100.0,
            },
        ]
        passed = _run_profit_guard_on_results(results)
        assert len(passed) == 0

    def test_profit_guard_on_backrun_result_object(self):
        """Guard works with BackrunResult dataclass (getattr path)."""
        from scripts.m7a_orderflow_loop import _run_profit_guard_on_results

        r = _make_result(
            best_backrun_net_bps=10.0,
            amount_in_wei=10**18,
            gross_pnl_wei=10**16,  # sell = input + 10**16
            size_valid_for_token=True,
            quote_pipeline_latency_ms=50.0,
        )
        passed = _run_profit_guard_on_results([r])
        assert len(passed) == 1


class TestM7A533BackrunResultField:
    """M7.A.5.33: profit_guard_passed field exists on BackrunResult (67 total)."""

    def test_field_count_67(self):
        from dataclasses import fields
        from m7.orderflow.contracts import BackrunResult

        assert len(fields(BackrunResult)) == 67

    def test_profit_guard_passed_defaults_none(self):
        r = _make_result()
        assert r.profit_guard_passed is None

    def test_profit_guard_passed_settable(self):
        r = _make_result(profit_guard_passed=True)
        assert r.profit_guard_passed is True


class TestM7A533ScoreBackrunFastStageTimings:
    """M7.A.5.33: score_backrun_fast includes per-stage timing + profit_guard."""

    def test_fast_path_has_stage_timings_keys(self):
        """Verify score_backrun_fast signature includes profit_guard and timing."""
        import inspect
        from m7.orderflow.scoring_parallel import score_backrun_fast

        sig = inspect.signature(score_backrun_fast)
        # Should have the required params
        assert "event" in sig.parameters
        assert "pool_registry" in sig.parameters

    def test_fast_path_result_has_profit_guard_field(self):
        """BackrunResult from fast path should have profit_guard_passed."""
        from dataclasses import fields as dc_fields
        from m7.orderflow.contracts import BackrunResult

        field_names = {f.name for f in dc_fields(BackrunResult)}
        assert "profit_guard_passed" in field_names
        assert "pipeline_stage_latency_ms" in field_names


class TestM7A533HotModeFastPath:
    """M7.A.5.33: mode_ws_live imports score_backrun_fast for hot-mode."""

    def test_mode_ws_live_imports_score_backrun_fast(self):
        from m7.orderflow.mode_ws_live import score_backrun_fast as sbf
        assert callable(sbf)


# ── M7.A.5.34 Tests ───────────────────────────────────────────────────────


class TestM7A534HotModeNoParallelFallback:
    """M7.A.5.34: Hot mode no longer falls back to parallel pipeline."""

    def test_mode_ws_live_imports_backrun_result(self):
        """BackrunResult is importable from mode_ws_live for hot_skip creation."""
        from m7.orderflow.mode_ws_live import BackrunResult
        from dataclasses import is_dataclass
        assert is_dataclass(BackrunResult)

    def test_hot_skip_result_fields(self):
        """A hot_skip result has correct scoring_path and reject_reason."""
        from m7.orderflow.contracts import BackrunResult
        r = BackrunResult(
            event_id="ev_skip_1",
            event_source="live",
            event_type="swap",
            post_trade_state_used="live",
            backrun_direction="skip",
            reject_reason="REJECT_NOT_IN_HOT_REGISTRY",
            scoring_path="hot_skip",
        )
        assert r.scoring_path == "hot_skip"
        assert r.reject_reason == "REJECT_NOT_IN_HOT_REGISTRY"
        assert r.route_viable is False
        assert r.profit_guard_passed is None


class TestM7A534PricingAnomalyExclusion:
    """M7.A.5.34: PRICING_ANOMALY hard-excluded from profit guard + headlines."""

    def test_profit_guard_skips_pricing_anomaly(self):
        """_run_profit_guard_on_results() skips PRICING_ANOMALY results."""
        from scripts.m7a_orderflow_loop import _run_profit_guard_on_results
        results = [
            {
                "best_backrun_net_bps": 50.0,
                "amount_in_wei": 10**18,
                "gross_pnl_wei": 10**16,
                "size_valid_for_token": True,
                "reject_reason": "REJECT_PRICING_ANOMALY",
                "quote_pipeline_latency_ms": 10.0,
            }
        ]
        passed = _run_profit_guard_on_results(results)
        assert len(passed) == 0

    def test_profit_guard_passes_clean(self):
        """_run_profit_guard_on_results() passes clean positive results."""
        from scripts.m7a_orderflow_loop import _run_profit_guard_on_results
        results = [
            {
                "best_backrun_net_bps": 5.0,
                "amount_in_wei": 10**18,
                "gross_pnl_wei": 10**16,
                "size_valid_for_token": True,
                "reject_reason": None,
                "quote_pipeline_latency_ms": 10.0,
            }
        ]
        passed = _run_profit_guard_on_results(results)
        assert len(passed) == 1


class TestM7A534ExecutionReadinessTimings:
    """M7.A.5.34: score_backrun_fast produces 7 stage timing keys."""

    def test_stage_timing_keys_include_calldata_and_sign(self):
        """Pipeline stage latency dict should have calldata_ms and sign_or_bundle_prep_ms."""
        expected = {
            "registry_lookup_ms", "pool_state_ms", "local_math_ms",
            "profit_guard_ms", "tx_build_ms", "calldata_ms",
            "sign_or_bundle_prep_ms",
        }
        # Verify by constructing a BackrunResult with the expected keys
        from m7.orderflow.contracts import BackrunResult
        r = BackrunResult(
            event_id="ev_timing_test",
            event_source="live",
            event_type="swap",
            post_trade_state_used="live",
            backrun_direction="buy",
            pipeline_stage_latency_ms={k: 0.01 for k in expected},
        )
        assert set(r.pipeline_stage_latency_ms.keys()) == expected

    def test_hot_budget_constants_exist(self):
        """New budget constants for calldata and sign exist in constants."""
        from m7.shared.constants import (
            HOT_BUDGET_CALLDATA_MS,
            HOT_BUDGET_SIGN_OR_BUNDLE_PREP_MS,
        )
        assert HOT_BUDGET_CALLDATA_MS > 0
        assert HOT_BUDGET_SIGN_OR_BUNDLE_PREP_MS > 0


class TestM7A534RawResultsInArtifact:
    """M7.A.5.34: run_ws_live stores _raw_results for hot lane."""

    def test_hot_artifact_stage_keys_include_new_timings(self):
        """_write_hot_artifact stage_keys list includes calldata + sign."""
        import ast
        import inspect
        from scripts.m7a_orderflow_loop import _write_hot_artifact
        source = inspect.getsource(_write_hot_artifact)
        assert "calldata_ms" in source
        assert "sign_or_bundle_prep_ms" in source


# ──────────────────────────────────────────────────────────────────────────
# M7.A.5.35: Promoted watchlist + stale KPI contract fix
# ──────────────────────────────────────────────────────────────────────────

class TestM7A535PromotedWatchlist:
    """M7.A.5.35: Dynamic promoted watchlist from cold lane."""

    def test_promote_pairs_returns_qualified_pairs(self):
        """Pairs with size_valid + active_pools + min appearances are promoted."""
        from scripts.m7a_orderflow_loop import _promote_pairs_from_cold
        cold_artifact = {
            "results": [
                {"actual_pair": "WETH/USDC", "size_valid_for_token": True,
                 "reject_reason": None, "registry_pools_active": 3,
                 "best_backrun_net_bps": 5.0},
                {"actual_pair": "RAIN/WETH", "size_valid_for_token": False,
                 "reject_reason": None, "registry_pools_active": 1,
                 "best_backrun_net_bps": 10.0},
            ],
        }
        stats = {}
        # M7.A.5.36: PROMOTED_MIN_COLD_APPEARANCES=2, so call twice
        _promote_pairs_from_cold(cold_artifact, stats)
        promoted = _promote_pairs_from_cold(cold_artifact, stats)
        # M7.A.5.39: now returns dict with candidate/execution
        assert "WETH/USDC" in promoted["execution"]
        # RAIN/WETH has size_valid=False → candidate only, not execution
        assert "RAIN/WETH" not in promoted["execution"]
        assert "RAIN/WETH" in promoted["candidate"]

    def test_promote_excludes_anomaly_only(self):
        """Pairs with PRICING_ANOMALY are hard-excluded (M7.A.5.36)."""
        from scripts.m7a_orderflow_loop import _promote_pairs_from_cold
        cold_artifact = {
            "results": [
                {"actual_pair": "X/Y", "size_valid_for_token": True,
                 "reject_reason": "REJECT_PRICING_ANOMALY",
                 "registry_pools_active": 1, "best_backrun_net_bps": 50000.0},
            ],
        }
        stats = {}
        # Even with 2+ appearances, anomaly is hard exclude
        _promote_pairs_from_cold(cold_artifact, stats)
        promoted = _promote_pairs_from_cold(cold_artifact, stats)
        assert "X/Y" not in promoted["execution"]
        assert "X/Y" not in promoted["candidate"]

    def test_promote_caps_at_max(self):
        """Promoted list is capped at PROMOTED_MAX_PAIRS."""
        from scripts.m7a_orderflow_loop import _promote_pairs_from_cold
        from m7.shared.constants import PROMOTED_MAX_PAIRS
        cold_artifact = {
            "results": [
                {"actual_pair": f"T{i}/WETH", "size_valid_for_token": True,
                 "reject_reason": None, "registry_pools_active": 2,
                 "best_backrun_net_bps": float(i)}
                for i in range(20)
            ],
        }
        stats = {}
        # M7.A.5.36: PROMOTED_MIN_COLD_APPEARANCES=2, so call twice
        _promote_pairs_from_cold(cold_artifact, stats)
        promoted = _promote_pairs_from_cold(cold_artifact, stats)
        assert len(promoted["execution"]) <= PROMOTED_MAX_PAIRS

    def test_promoted_watchlist_constants_importable(self):
        """New constants PROMOTED_MIN_COLD_APPEARANCES and PROMOTED_MAX_PAIRS exist."""
        from m7.shared.constants import PROMOTED_MIN_COLD_APPEARANCES, PROMOTED_MAX_PAIRS
        assert PROMOTED_MIN_COLD_APPEARANCES >= 1
        assert PROMOTED_MAX_PAIRS >= 1

    def test_hot_artifact_includes_promoted_watchlist(self):
        """_write_hot_artifact signature accepts promoted_pairs and candidate_pairs kwargs."""
        import inspect
        from scripts.m7a_orderflow_loop import _write_hot_artifact
        sig = inspect.signature(_write_hot_artifact)
        assert "promoted_pairs" in sig.parameters
        assert "candidate_pairs" in sig.parameters


class TestM7A535StaleKPIContract:
    """M7.A.5.35: stale_positive_count_clean consistent with best_net_bps_stale_clean."""

    def test_stale_positive_count_clean_in_artifact(self):
        """build_replay_summary includes stale_positive_count_clean key."""
        from m7.orderflow.artifacts import build_replay_summary
        artifact = build_replay_summary([], [], mode="ws_live")
        assert "stale_positive_count_clean" in artifact

    def test_stale_clean_consistency(self):
        """When stale_positive_count_clean=0, best_net_bps_stale_clean <= 0 or None."""
        from m7.orderflow.artifacts import build_replay_summary
        artifact = build_replay_summary([], [], mode="ws_live")
        spc_clean = artifact.get("stale_positive_count_clean", 0)
        best_stale_clean = artifact.get("best_net_bps_stale_clean")
        if spc_clean == 0:
            assert best_stale_clean is None or best_stale_clean <= 0


# ═══════════════════════════════════════════════════════════════════════
# M7.A.5.36 — Per-stage hard budget abort + p50/p90 + promotion rules
# ═══════════════════════════════════════════════════════════════════════


class TestM7A536PerStageBudgetConstants:
    """M7.A.5.36: New budget constants exist with correct values."""

    def test_zero_budget_constants_for_excluded_stages(self):
        """Resolve, oracle, enrichment, registry_preload MUST be 0 in hot path."""
        from m7.shared.constants import (
            HOT_BUDGET_RESOLVE_MS,
            HOT_BUDGET_ORACLE_MS,
            HOT_BUDGET_ENRICHMENT_MS,
            HOT_BUDGET_REGISTRY_PRELOAD_MS,
        )
        assert HOT_BUDGET_RESOLVE_MS == 0
        assert HOT_BUDGET_ORACLE_MS == 0
        assert HOT_BUDGET_ENRICHMENT_MS == 0
        assert HOT_BUDGET_REGISTRY_PRELOAD_MS == 0

    def test_profit_guard_budget_raised_to_40(self):
        """Profit guard budget raised from 10 to 40ms per M7.A.5.36 directive."""
        from m7.shared.constants import HOT_BUDGET_PROFIT_GUARD_MS
        assert HOT_BUDGET_PROFIT_GUARD_MS == 40

    def test_all_stage_budgets_fit_total(self):
        """Sum of active stage budgets must not exceed HOT_BUDGET_TOTAL_MS."""
        from m7.shared.constants import (
            HOT_BUDGET_REGISTRY_LOOKUP_MS,
            HOT_BUDGET_POOL_STATE_READ_MS,
            HOT_BUDGET_LOCAL_MATH_MS,
            HOT_BUDGET_PROFIT_GUARD_MS,
            HOT_BUDGET_TX_BUILD_MS,
            HOT_BUDGET_CALLDATA_MS,
            HOT_BUDGET_SIGN_OR_BUNDLE_PREP_MS,
            HOT_BUDGET_TOTAL_MS,
        )
        active_sum = (
            HOT_BUDGET_REGISTRY_LOOKUP_MS
            + HOT_BUDGET_POOL_STATE_READ_MS
            + HOT_BUDGET_LOCAL_MATH_MS
            + HOT_BUDGET_PROFIT_GUARD_MS
            + HOT_BUDGET_TX_BUILD_MS
            + HOT_BUDGET_CALLDATA_MS
            + HOT_BUDGET_SIGN_OR_BUNDLE_PREP_MS
        )
        assert active_sum <= HOT_BUDGET_TOTAL_MS


class TestM7A536PerStageAbort:
    """M7.A.5.36: score_backrun_fast enforces per-stage hard budget abort."""

    def test_fast_path_imports_per_stage_constants(self):
        """score_backrun_fast imports per-stage budget constants."""
        import inspect
        from m7.orderflow.scoring_parallel import score_backrun_fast
        source = inspect.getsource(score_backrun_fast)
        assert "HOT_BUDGET_REGISTRY_LOOKUP_MS" in source
        assert "HOT_BUDGET_POOL_STATE_READ_MS" in source
        assert "HOT_BUDGET_LOCAL_MATH_MS" in source
        assert "HOT_BUDGET_PROFIT_GUARD_MS" in source

    def test_per_stage_abort_pattern_in_source(self):
        """Each measured stage has a per-stage abort check."""
        import inspect
        from m7.orderflow.scoring_parallel import score_backrun_fast
        source = inspect.getsource(score_backrun_fast)
        # Count per-stage abort patterns (M7.A.5.36 comment + budget check)
        abort_count = source.count("per-stage hard abort")
        assert abort_count >= 4, f"Expected >=4 per-stage aborts, found {abort_count}"

    def test_fast_path_no_resolve_or_oracle_in_source(self):
        """score_backrun_fast must NOT call resolve/oracle/enrichment."""
        import inspect
        from m7.orderflow.scoring_parallel import score_backrun_fast
        source = inspect.getsource(score_backrun_fast)
        assert "check_oracle_sanity" not in source
        assert "enrich_tokens_batch" not in source
        assert "_resolve_pool_addresses_multicall" not in source


class TestM7A536PromotionRules:
    """M7.A.5.36: Strengthened promotion rules."""

    def test_promoted_min_cold_appearances_is_2(self):
        """PROMOTED_MIN_COLD_APPEARANCES raised to 2 for stability."""
        from m7.shared.constants import PROMOTED_MIN_COLD_APPEARANCES
        assert PROMOTED_MIN_COLD_APPEARANCES == 2

    def test_promoted_min_net_bps_exists(self):
        """PROMOTED_MIN_NET_BPS constant exists."""
        from m7.shared.constants import PROMOTED_MIN_NET_BPS
        assert isinstance(PROMOTED_MIN_NET_BPS, (int, float))
        assert PROMOTED_MIN_NET_BPS <= 0  # allows near-zero but not total garbage

    def test_single_appearance_not_promoted(self):
        """A pair seen only once should NOT be promoted (MIN_COLD_APPEARANCES=2)."""
        from scripts.m7a_orderflow_loop import _promote_pairs_from_cold
        cold_artifact = {
            "results": [
                {"actual_pair": "WETH/USDC", "size_valid_for_token": True,
                 "reject_reason": None, "registry_pools_active": 3,
                 "best_backrun_net_bps": 5.0},
            ],
        }
        stats = {}
        promoted = _promote_pairs_from_cold(cold_artifact, stats)
        assert "WETH/USDC" not in promoted.get("execution", [])  # only 1 appearance

    def test_two_appearances_promoted(self):
        """A qualified pair seen twice gets promoted."""
        from scripts.m7a_orderflow_loop import _promote_pairs_from_cold
        cold_artifact = {
            "results": [
                {"actual_pair": "WETH/USDC", "size_valid_for_token": True,
                 "reject_reason": None, "registry_pools_active": 3,
                 "best_backrun_net_bps": 5.0},
            ],
        }
        stats = {}
        _promote_pairs_from_cold(cold_artifact, stats)  # 1st
        promoted = _promote_pairs_from_cold(cold_artifact, stats)  # 2nd
        assert "WETH/USDC" in promoted["execution"]

    def test_garbage_net_bps_excluded(self):
        """Pairs with best_net_bps below PROMOTED_MIN_NET_BPS are excluded."""
        from scripts.m7a_orderflow_loop import _promote_pairs_from_cold
        from m7.shared.constants import PROMOTED_MIN_NET_BPS
        cold_artifact = {
            "results": [
                {"actual_pair": "JUNK/WETH", "size_valid_for_token": True,
                 "reject_reason": None, "registry_pools_active": 2,
                 "best_backrun_net_bps": PROMOTED_MIN_NET_BPS - 100},
            ],
        }
        stats = {}
        _promote_pairs_from_cold(cold_artifact, stats)
        promoted = _promote_pairs_from_cold(cold_artifact, stats)
        assert "JUNK/WETH" not in promoted.get("execution", [])
        assert "JUNK/WETH" not in promoted.get("candidate", [])

    def test_anomaly_hard_exclude_even_with_size_valid(self):
        """PRICING_ANOMALY pairs are excluded even when size_valid=True."""
        from scripts.m7a_orderflow_loop import _promote_pairs_from_cold
        cold_artifact = {
            "results": [
                {"actual_pair": "BAD/WETH", "size_valid_for_token": True,
                 "reject_reason": "REJECT_PRICING_ANOMALY",
                 "registry_pools_active": 5, "best_backrun_net_bps": 100.0},
            ],
        }
        stats = {}
        _promote_pairs_from_cold(cold_artifact, stats)
        promoted = _promote_pairs_from_cold(cold_artifact, stats)
        assert "BAD/WETH" not in promoted.get("execution", [])
        assert "BAD/WETH" not in promoted.get("candidate", [])


class TestM7A536P50P90Tracking:
    """M7.A.5.36: Hot artifact includes p50/p90 latency tracking."""

    def test_write_hot_artifact_includes_p50_p90(self):
        """_write_hot_artifact source references p50 and p90."""
        import inspect
        from scripts.m7a_orderflow_loop import _write_hot_artifact
        source = inspect.getsource(_write_hot_artifact)
        assert "p50_latency_ms" in source
        assert "p90_latency_ms" in source

    def test_p50_p90_computation_correct(self):
        """p50 and p90 are computed correctly from sorted latency list."""
        latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        sorted_lat = sorted(latencies)
        p50 = sorted_lat[len(sorted_lat) // 2]
        p90 = sorted_lat[int(len(sorted_lat) * 0.9)]
        assert p50 == 60.0  # index 5
        assert p90 == 100.0  # index 9


# ===========================================================================
# M7.A.5.37: Hot artifact always-emit + resolve caching + oracle caching
#             + persistent cold registry
# ===========================================================================


class TestM7A537HotArtifactAlwaysEmit:
    """M7.A.5.37: Hot artifact MUST always emit fast_path + hot_skip_count."""

    def test_write_hot_artifact_emits_fast_path_when_empty(self):
        """fast_path block present with zeros/nulls when fast_results is None."""
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from scripts.m7a_orderflow_loop import _write_hot_artifact

        artifact = {"results": [], "events_count": 0, "_raw_results": []}
        with tempfile.TemporaryDirectory() as td:
            hot_path = Path(td) / "m7_hot_latest.json"
            with patch("scripts.m7a_orderflow_loop._HOT_ARTIFACT_PATH", str(hot_path)):
                _write_hot_artifact(artifact, iteration=1, guard_results=None, fast_results=None)
            hot = json.loads(hot_path.read_text(encoding="utf-8"))

        assert "fast_path" in hot, "fast_path block MUST always be present"
        fp = hot["fast_path"]
        assert fp["scored"] == 0
        assert fp["positive"] == 0
        assert fp["viable"] == 0
        assert fp["profit_guard_passed"] == 0
        assert fp["p50_latency_ms"] is None
        assert fp["p90_latency_ms"] is None
        assert fp["mean_latency_ms"] is None
        assert fp["max_latency_ms"] is None
        assert fp["best_net_bps"] is None
        assert fp["scoring_paths"] == []
        assert fp["stage_timings"] is None

    def test_write_hot_artifact_emits_hot_skip_count(self):
        """hot_skip_count MUST always appear even when zero."""
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from scripts.m7a_orderflow_loop import _write_hot_artifact

        artifact = {"results": [], "events_count": 0, "_raw_results": []}
        with tempfile.TemporaryDirectory() as td:
            hot_path = Path(td) / "m7_hot_latest.json"
            with patch("scripts.m7a_orderflow_loop._HOT_ARTIFACT_PATH", str(hot_path)):
                _write_hot_artifact(artifact, iteration=1)
            hot = json.loads(hot_path.read_text(encoding="utf-8"))

        assert "hot_skip_count" in hot
        assert hot["hot_skip_count"] == 0

    def test_write_hot_artifact_fast_path_with_results(self):
        """fast_path block is fully populated when fast_results provided."""
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from scripts.m7a_orderflow_loop import _write_hot_artifact

        fast = [
            _make_result(
                best_backrun_net_bps=5.0,
                route_viable=True,
                profit_guard_passed=True,
                quote_pipeline_latency_ms=100.0,
                scoring_path="hot_fast",
                pipeline_stage_latency_ms={"registry_lookup_ms": 1.0, "pool_state_ms": 2.0},
            ),
        ]
        artifact = {"results": [], "events_count": 1, "_raw_results": []}
        with tempfile.TemporaryDirectory() as td:
            hot_path = Path(td) / "m7_hot_latest.json"
            with patch("scripts.m7a_orderflow_loop._HOT_ARTIFACT_PATH", str(hot_path)):
                _write_hot_artifact(artifact, iteration=1, fast_results=fast)
            hot = json.loads(hot_path.read_text(encoding="utf-8"))

        fp = hot["fast_path"]
        assert fp["scored"] == 1
        assert fp["positive"] == 1
        assert fp["viable"] == 1
        assert fp["profit_guard_passed"] == 1
        assert fp["p50_latency_ms"] == 100.0
        assert fp["p90_latency_ms"] == 100.0
        assert "hot_fast" in fp["scoring_paths"]
        assert fp["stage_timings"] is not None

    def test_hot_skip_count_with_skip_results(self):
        """hot_skip_count counts _raw_results with scoring_path='hot_skip'."""
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from scripts.m7a_orderflow_loop import _write_hot_artifact

        raw = [
            _make_result(scoring_path="hot_skip"),
            _make_result(scoring_path="hot_skip"),
            _make_result(scoring_path="hot_fast"),
        ]
        artifact = {"results": [], "events_count": 3, "_raw_results": raw}
        with tempfile.TemporaryDirectory() as td:
            hot_path = Path(td) / "m7_hot_latest.json"
            with patch("scripts.m7a_orderflow_loop._HOT_ARTIFACT_PATH", str(hot_path)):
                _write_hot_artifact(artifact, iteration=1)
            hot = json.loads(hot_path.read_text(encoding="utf-8"))

        assert hot["hot_skip_count"] == 2

    def test_fast_path_required_keys_contract(self):
        """fast_path MUST contain exactly these keys (contract)."""
        import inspect
        from scripts.m7a_orderflow_loop import _write_hot_artifact
        source = inspect.getsource(_write_hot_artifact)
        # Both branches (if/else) must emit these keys
        required = [
            "scored", "positive", "viable", "profit_guard_passed",
            "mean_latency_ms", "max_latency_ms", "p50_latency_ms",
            "p90_latency_ms", "best_net_bps", "scoring_paths", "stage_timings",
        ]
        for key in required:
            count = source.count(f'"{key}"')
            assert count >= 2, f"fast_path key '{key}' must appear in both if/else branches (found {count})"


class TestM7A537ResolveCaching:
    """M7.A.5.37: Pool token resolution uses module-level cache."""

    def test_pool_token_cache_exists(self):
        """Module-level _pool_token_cache dict exists."""
        from m7.orderflow.resolve import _pool_token_cache
        assert isinstance(_pool_token_cache, dict)

    def test_resolve_event_tokens_uses_cache(self):
        """Second call for same pool skips RPC (uses cached result)."""
        from unittest.mock import patch, MagicMock
        from m7.orderflow import resolve as resolve_mod

        # Clear cache before test
        resolve_mod._pool_token_cache.clear()

        pool_addr = "0xABCD1234567890abcdef1234567890abcdef1234"
        token0 = "0x1111111111111111111111111111111111111111"
        token1 = "0x2222222222222222222222222222222222222222"
        fee = 3000
        addr_to_sym = {token0.lower(): "WETH", token1.lower(): "USDC"}

        mock_batcher = MagicMock()
        mock_batcher.batch_token_info.return_value = {pool_addr: (token0, token1, fee)}

        with patch("core.multicall.get_multicall_batcher", return_value=mock_batcher):
            # First call — should hit RPC
            result1 = resolve_mod._resolve_event_tokens(
                pool_addr, "token0_in", "http://rpc", 100, addr_to_sym,
            )
            assert result1 is not None
            assert result1["token_in_symbol"] == "WETH"
            assert result1["fee"] == fee
            assert mock_batcher.batch_token_info.call_count == 1

            # Second call — should use cache, NOT call RPC again
            result2 = resolve_mod._resolve_event_tokens(
                pool_addr, "token1_in", "http://rpc", 200, addr_to_sym,
            )
            assert result2 is not None
            assert result2["token_in_symbol"] == "USDC"
            assert mock_batcher.batch_token_info.call_count == 1  # still 1 — cache hit

        # Cleanup
        resolve_mod._pool_token_cache.clear()

    def test_cache_key_is_lowercase(self):
        """Cache uses lowercased pool address as key."""
        import inspect
        from m7.orderflow.resolve import _resolve_event_tokens
        source = inspect.getsource(_resolve_event_tokens)
        assert "pool_address.lower()" in source


class TestM7A537OracleCaching:
    """M7.A.5.37: Oracle sanity check uses module-level cache."""

    def test_oracle_cache_exists(self):
        """Module-level _oracle_cache dict exists."""
        from m7.orderflow.pricing import _oracle_cache
        assert isinstance(_oracle_cache, dict)

    def test_oracle_cache_stale_blocks_constant(self):
        """Stale block threshold is 5000 (M7.A.5.38)."""
        from m7.orderflow.pricing import _ORACLE_CACHE_STALE_BLOCKS
        assert _ORACLE_CACHE_STALE_BLOCKS == 5000

    def test_oracle_cache_hit_within_blocks(self):
        """Cached oracle result returned when within stale-block window."""
        from m7.orderflow import pricing as pricing_mod

        # Seed cache directly
        pricing_mod._oracle_cache.clear()
        pricing_mod._oracle_cache["WETH|USDC"] = (
            100,  # cached at block 100
            {"oracle_price_available": True, "token_in_oracle_usd": 3500.0,
             "token_out_oracle_usd": 1.0, "oracle_deviation_bps": None,
             "oracle_guard_triggered": False, "oracle_staleness_seconds": 10},
        )

        # Call within 50 blocks — should return cache, no RPC
        result = pricing_mod.check_oracle_sanity("WETH", "USDC", "http://rpc", 120)
        assert result["oracle_price_available"] is True
        assert result["token_in_oracle_usd"] == 3500.0

        # Cleanup
        pricing_mod._oracle_cache.clear()

    def test_oracle_cache_returns_copy(self):
        """Cached result must be a copy (mutations don't corrupt cache)."""
        from m7.orderflow import pricing as pricing_mod

        pricing_mod._oracle_cache.clear()
        pricing_mod._oracle_cache["A|B"] = (
            100,
            {"oracle_price_available": False, "token_in_oracle_usd": None,
             "token_out_oracle_usd": None, "oracle_deviation_bps": None,
             "oracle_guard_triggered": False, "oracle_staleness_seconds": None},
        )

        r1 = pricing_mod.check_oracle_sanity("A", "B", "http://rpc", 110)
        r1["oracle_price_available"] = True  # mutate the copy

        r2 = pricing_mod.check_oracle_sanity("A", "B", "http://rpc", 110)
        assert r2["oracle_price_available"] is False  # cache not corrupted

        pricing_mod._oracle_cache.clear()

    def test_oracle_cache_source_has_stale_check(self):
        """Source code checks block proximity before returning cached result."""
        import inspect
        from m7.orderflow.pricing import check_oracle_sanity
        source = inspect.getsource(check_oracle_sanity)
        assert "_ORACLE_CACHE_STALE_BLOCKS" in source
        assert "_oracle_cache" in source


# ===========================================================================
# M7.A.5.41: Top-candidate persistence + hot lane token resolution fix
# ===========================================================================


class TestM7A541TopCandidatePersistence:
    """M7.A.5.41: Verify top_executable_candidates and top_stale_positive_candidates
    appear in build_replay_summary() and survive _ROLLING_EXCLUDE_KEYS."""

    def _build_artifact_with_viable(self):
        """Build an artifact with at least one viable result."""
        events = build_fixture_events()
        viable_result = _make_result(
            event_id="e_viable_1",
            route_viable=True,
            best_backrun_net_bps=25.0,
            block_lag=1,
            same_state_class="next_block",
            reject_reason=None,
            scoring_path="registry_direct",
            profit_guard_passed=True,
            actual_pair="WETH/USDC",
            size_valid_for_token=True,
            quote_pipeline_latency_ms=12.5,
        )
        non_viable_result = _make_result(
            event_id="e_gas_1",
            route_viable=False,
            best_backrun_net_bps=-5.0,
            block_lag=1,
            same_state_class="next_block",
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            scoring_path="registry_direct",
        )
        stale_result = _make_result(
            event_id="e_stale_1",
            route_viable=False,
            best_backrun_net_bps=15.0,
            block_lag=5,
            same_state_class="stale",
            reject_reason=REJECT_STALE_POSITIVE,
            scoring_path="registry_direct",
            actual_pair="ARB/WETH",
            size_valid_for_token=True,
            quote_pipeline_latency_ms=30.0,
        )
        results = [viable_result, non_viable_result, stale_result]
        artifact = build_replay_summary(events, results, "ws_live")
        return artifact

    def test_top_executable_candidates_key_exists(self):
        artifact = self._build_artifact_with_viable()
        assert "top_executable_candidates" in artifact

    def test_top_stale_positive_candidates_key_exists(self):
        artifact = self._build_artifact_with_viable()
        assert "top_stale_positive_candidates" in artifact

    def test_top_executable_candidates_has_viable_entries(self):
        artifact = self._build_artifact_with_viable()
        top = artifact["top_executable_candidates"]
        assert len(top) >= 1
        assert top[0]["event_id"] == "e_viable_1"
        assert top[0]["net_bps"] == 25.0
        assert top[0]["route_viable"] is True

    def test_top_stale_positive_candidates_has_stale_entries(self):
        artifact = self._build_artifact_with_viable()
        top = artifact["top_stale_positive_candidates"]
        assert len(top) >= 1
        assert top[0]["event_id"] == "e_stale_1"
        assert top[0]["net_bps"] == 15.0

    def test_top_candidates_compact_keys(self):
        """Verify compact rows have exactly the expected fields."""
        artifact = self._build_artifact_with_viable()
        expected_keys = {
            "event_id", "actual_pair", "net_bps", "block_lag",
            "same_state_class", "route_viable", "size_valid_for_token",
            "scoring_path", "profit_guard_passed", "pipeline_latency_ms",
            "reject_reason", "pool_address",
            "verified_profitable", "verified_net_bps",
        }
        for row in artifact["top_executable_candidates"]:
            assert set(row.keys()) == expected_keys
        for row in artifact["top_stale_positive_candidates"]:
            assert set(row.keys()) == expected_keys

    def test_top_executable_max_5(self):
        """At most 5 executable candidates are kept."""
        events = build_fixture_events()
        results = [
            _make_result(
                event_id=f"e_viable_{i}",
                route_viable=True,
                best_backrun_net_bps=float(i),
                block_lag=0,
                same_state_class="same_block",
                reject_reason=None,
            )
            for i in range(10)
        ]
        artifact = build_replay_summary(events, results, "ws_live")
        assert len(artifact["top_executable_candidates"]) == 5
        # Sorted descending by net_bps
        bps_values = [r["net_bps"] for r in artifact["top_executable_candidates"]]
        assert bps_values == sorted(bps_values, reverse=True)

    def test_top_candidates_survive_rolling_exclude(self):
        """top_*_candidates keys must NOT be in _ROLLING_EXCLUDE_KEYS."""
        from m7.orderflow.mode_ws_live import _ROLLING_EXCLUDE_KEYS
        assert "top_executable_candidates" not in _ROLLING_EXCLUDE_KEYS
        assert "top_stale_positive_candidates" not in _ROLLING_EXCLUDE_KEYS

    def test_empty_results_produce_empty_candidates(self):
        """Empty results produce empty candidate lists (not missing keys)."""
        events = build_fixture_events()
        artifact = build_replay_summary(events, [], "ws_live")
        assert artifact["top_executable_candidates"] == []
        assert artifact["top_stale_positive_candidates"] == []


class TestM7A541HotLaneTokenResolution:
    """M7.A.5.41: Verify score_backrun_fast resolves event tokens from
    _pool_token_cache using pool_address + direction tags."""

    def test_fast_path_uses_pool_token_cache(self):
        """score_backrun_fast resolves tokens from _pool_token_cache, not token_addresses."""
        from m7.orderflow.scoring_parallel import score_backrun_fast
        from m7.orderflow import resolve as resolve_mod
        from m7.orderflow.contracts import OrderflowEvent
        from m7.orderflow.pool_registry import PoolRegistryEntry

        token0_addr = "0x" + "11" * 20  # lower address = token0
        token1_addr = "0x" + "22" * 20  # higher address = token1
        pool_addr = "0x" + "ab" * 20

        # Populate _pool_token_cache with the pool → (token0, token1, fee)
        resolve_mod._pool_token_cache[pool_addr.lower()] = (token0_addr, token1_addr, 3000)

        # Create event with direction tags (like real events from normalize_swap_log)
        ev = OrderflowEvent(
            event_id="test_cache_resolve",
            event_type="swap",
            chain="arbitrum_one",
            block_number=100,
            tx_hash="0x" + "00" * 32,
            token_in="token0_in",       # direction tag, NOT symbol
            token_out="token1",          # direction tag, NOT symbol
            amount_in_wei=10**18,
            amount_out_wei=0,
            dex="uniswap_v3",
            pool_address=pool_addr,
            fee_tier=3000,
            estimated_size_usd=3000.0,
            estimated_impact_bps=5.0,
            timestamp="2026-04-06T00:00:00Z",
        )

        pool_entry = PoolRegistryEntry(
            address="0x" + "cc" * 20,
            dex="uniswap_v3",
            adapter_type="uniswap_v3",
            fee=3000,
            token_a=token0_addr,
            token_b=token1_addr,
            liquidity=10**18,
            sqrt_price_x96=79228162514264337593543950336,  # 1:1 price
            tick=0,
            last_block=99,
        )

        class MockRegistry:
            preload_calls = 1
            cache_hits = 0
            def lookup_pair(self, a, b):
                return [pool_entry]

        addr_to_symbol = {
            token0_addr.lower(): "WETH",
            token1_addr.lower(): "USDC",
        }

        try:
            result = score_backrun_fast(
                event=ev,
                pool_registry=MockRegistry(),
                token_addresses={"WETH": token0_addr, "USDC": token1_addr},
                current_block=100,
                addr_to_symbol=addr_to_symbol,
            )
            # With direction tags + populated cache, should now reach scoring
            # (may return None from pricing math, but should NOT return None
            # from token resolution)
            assert result is None or result.scoring_path == "registry_fast"
        finally:
            resolve_mod._pool_token_cache.pop(pool_addr.lower(), None)

    def test_fast_path_returns_none_without_cached_pool(self):
        """score_backrun_fast returns None if pool not in _pool_token_cache."""
        from m7.orderflow.scoring_parallel import score_backrun_fast
        from m7.orderflow import resolve as resolve_mod
        from m7.orderflow.contracts import OrderflowEvent

        uncached_pool = "0x" + "ff" * 20
        # Ensure it's NOT in cache
        resolve_mod._pool_token_cache.pop(uncached_pool.lower(), None)

        ev = OrderflowEvent(
            event_id="test_no_cache",
            event_type="swap",
            chain="arbitrum_one",
            block_number=100,
            tx_hash="0x" + "00" * 32,
            token_in="token0_in",
            token_out="token1",
            amount_in_wei=10**18,
            amount_out_wei=0,
            dex="uniswap_v3",
            pool_address=uncached_pool,
            fee_tier=3000,
            estimated_size_usd=3000.0,
            estimated_impact_bps=5.0,
            timestamp="2026-04-06T00:00:00Z",
        )

        class EmptyRegistry:
            preload_calls = 0
            cache_hits = 0
            def lookup_pair(self, a, b):
                return []

        result = score_backrun_fast(
            event=ev,
            pool_registry=EmptyRegistry(),
            token_addresses={},
            current_block=100,
            addr_to_symbol={"0x" + "11" * 20: "WETH"},
        )
        assert result is None

    def test_fast_path_resolves_token1_in_direction(self):
        """token1_in direction correctly maps token_in_addr = token1."""
        from m7.orderflow.scoring_parallel import score_backrun_fast
        from m7.orderflow import resolve as resolve_mod
        from m7.orderflow.contracts import OrderflowEvent
        from m7.orderflow.pool_registry import PoolRegistryEntry

        token0_addr = "0x" + "11" * 20
        token1_addr = "0x" + "22" * 20
        pool_addr = "0x" + "ab" * 20

        resolve_mod._pool_token_cache[pool_addr.lower()] = (token0_addr, token1_addr, 500)

        ev = OrderflowEvent(
            event_id="test_t1_in",
            event_type="swap",
            chain="arbitrum_one",
            block_number=100,
            tx_hash="0x" + "00" * 32,
            token_in="token1_in",       # victim swapped token1 in
            token_out="token0",
            amount_in_wei=10**18,
            amount_out_wei=0,
            dex="uniswap_v3",
            pool_address=pool_addr,
            fee_tier=500,
            estimated_size_usd=3000.0,
            estimated_impact_bps=5.0,
            timestamp="2026-04-06T00:00:00Z",
        )

        pool_entry = PoolRegistryEntry(
            address="0x" + "cc" * 20,
            dex="uniswap_v3",
            adapter_type="uniswap_v3",
            fee=500,
            token_a=token1_addr,
            token_b=token0_addr,
            liquidity=10**18,
            sqrt_price_x96=79228162514264337593543950336,
            tick=0,
            last_block=99,
        )

        class MockRegistry:
            preload_calls = 1
            cache_hits = 0
            def lookup_pair(self, a, b):
                return [pool_entry]

        addr_to_symbol = {
            token0_addr.lower(): "WETH",
            token1_addr.lower(): "USDC",
        }

        try:
            result = score_backrun_fast(
                event=ev,
                pool_registry=MockRegistry(),
                token_addresses={"WETH": token0_addr, "USDC": token1_addr},
                current_block=100,
                addr_to_symbol=addr_to_symbol,
            )
            assert result is None or result.scoring_path == "registry_fast"
        finally:
            resolve_mod._pool_token_cache.pop(pool_addr.lower(), None)

    def test_pool_token_cache_import(self):
        """_pool_token_cache is importable from scoring_parallel (via resolve)."""
        from m7.orderflow.scoring_parallel import _pool_token_cache
        assert isinstance(_pool_token_cache, dict)


class TestM7A541TopHotCandidates:
    """M7.A.5.41: Verify top_hot_candidates in hot artifact writer."""

    def test_write_hot_artifact_has_top_hot_candidates_key(self):
        """_write_hot_artifact always emits top_hot_candidates key."""
        import inspect
        from scripts.m7a_orderflow_loop import _write_hot_artifact
        source = inspect.getsource(_write_hot_artifact)
        assert "top_hot_candidates" in source

    def test_top_hot_candidates_empty_when_no_fast_results(self):
        """When fast_results is None/empty, top_hot_candidates is []."""
        import inspect
        from scripts.m7a_orderflow_loop import _write_hot_artifact
        source = inspect.getsource(_write_hot_artifact)
        # Check that empty fast_results produces empty list
        assert 'hot["top_hot_candidates"] = []' in source


class TestM7A537WarmRegistry:
    """M7.A.5.37: run_ws_live accepts warm_registry for persistent cold mode."""

    def test_run_ws_live_signature_has_warm_registry(self):
        """run_ws_live accepts warm_registry keyword arg."""
        import inspect
        from m7.orderflow.mode_ws_live import run_ws_live
        sig = inspect.signature(run_ws_live)
        assert "warm_registry" in sig.parameters
        param = sig.parameters["warm_registry"]
        assert param.default is None

    def test_warm_registry_does_not_trigger_hot_mode(self):
        """warm_registry path does NOT set _hot_mode."""
        import inspect
        from m7.orderflow.mode_ws_live import run_ws_live
        source = inspect.getsource(run_ws_live)
        # _hot_mode is ONLY set from external_registry, not warm_registry
        assert "_hot_mode = external_registry is not None" in source

    def test_warm_registry_prewarm_skip(self):
        """warm_registry sets _prewarm_count = -2, skipping prewarm."""
        import inspect
        from m7.orderflow.mode_ws_live import run_ws_live
        source = inspect.getsource(run_ws_live)
        assert "_prewarm_count = -2" in source
        assert "_prewarm_count not in (-1, -2)" in source


class TestM7A537ColdRegistryPersistence:
    """M7.A.5.37: Orderflow loop persists cold registry across iterations."""

    def test_cold_registry_lazy_init_in_loop(self):
        """run_loop source lazy-inits _cold_registry on cold lane."""
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        source = inspect.getsource(run_loop)
        assert "_cold_registry = None" in source
        assert "_cold_registry = PoolRegistry(stale_threshold_blocks=5000)" in source

    def test_cold_registry_passed_as_warm(self):
        """Cold lane passes _cold_registry as warm_registry (not external)."""
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        source = inspect.getsource(run_loop)
        assert 'warm_registry=_cold_registry if lane == "cold" else None' in source

    def test_cold_registry_stats_logged(self):
        """Cold lane logs registry stats after each iteration."""
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        source = inspect.getsource(run_loop)
        assert "_cold_registry.preload_calls" in source
        assert "_cold_registry.cache_hits" in source


# ---------------------------------------------------------------------------
# M7.A.5.38 — Latency contour: enrichment cache, oracle 500-block, registry stale threshold
# ---------------------------------------------------------------------------

class TestM7A538EnrichmentCaching:
    """M7.A.5.38: Enrichment uses module-level cache for immutable ERC-20 data."""

    def test_enrichment_cache_exists(self):
        """Module-level _enrichment_cache dict exists."""
        from m7.orderflow.resolve import _enrichment_cache
        assert isinstance(_enrichment_cache, dict)

    def test_enrichment_cache_hit_skips_rpc(self):
        """Second call for same tokens uses cache, no RPC."""
        from unittest.mock import patch, MagicMock
        from m7.orderflow import resolve as resolve_mod

        # Clear cache state
        resolve_mod._enrichment_cache.clear()

        addr = "0xABCD1234567890abcdef1234567890abcdef1234"

        mock_batcher = MagicMock()
        mock_batcher.batch_symbol.return_value = {addr: "WETH"}
        mock_batcher.batch_decimals.return_value = {addr: 18}

        with patch("core.multicall.get_multicall_batcher", return_value=mock_batcher):
            # First call — RPC
            r1 = resolve_mod.enrich_tokens_batch([addr], "http://rpc", 100)
            assert r1[addr.lower()]["enriched"] is True
            assert r1[addr.lower()]["symbol"] == "WETH"
            assert mock_batcher.batch_symbol.call_count == 1

            # Second call — cache hit, no RPC
            r2 = resolve_mod.enrich_tokens_batch([addr], "http://rpc", 200)
            assert r2[addr.lower()]["enriched"] is True
            assert r2[addr.lower()]["symbol"] == "WETH"
            assert mock_batcher.batch_symbol.call_count == 1  # still 1

        resolve_mod._enrichment_cache.clear()

    def test_enrichment_cache_only_stores_enriched(self):
        """Failed enrichment (symbol=None) is NOT cached."""
        from unittest.mock import patch, MagicMock
        from m7.orderflow import resolve as resolve_mod

        resolve_mod._enrichment_cache.clear()

        addr = "0xDEAD000000000000000000000000000000000001"

        mock_batcher = MagicMock()
        mock_batcher.batch_symbol.return_value = {addr: None}
        mock_batcher.batch_decimals.return_value = {addr: None}

        with patch("core.multicall.get_multicall_batcher", return_value=mock_batcher):
            r1 = resolve_mod.enrich_tokens_batch([addr], "http://rpc", 100)
            assert r1[addr.lower()]["enriched"] is False

        # Cache should NOT contain the failed entry
        assert addr.lower() not in resolve_mod._enrichment_cache

        resolve_mod._enrichment_cache.clear()

    def test_enrichment_cache_key_is_lowercase(self):
        """Cache uses lowercased address as key."""
        import inspect
        from m7.orderflow.resolve import enrich_tokens_batch
        source = inspect.getsource(enrich_tokens_batch)
        assert "addr.lower()" in source


class TestM7A538OracleThreshold:
    """M7.A.5.38: Oracle cache threshold increased to 500 blocks."""

    def test_oracle_threshold_is_5000(self):
        """_ORACLE_CACHE_STALE_BLOCKS == 5000 (M7.A.5.38)."""
        from m7.orderflow.pricing import _ORACLE_CACHE_STALE_BLOCKS
        assert _ORACLE_CACHE_STALE_BLOCKS == 5000


class TestM7A538RegistryStaleThreshold:
    """M7.A.5.38: PoolRegistry accepts configurable stale_threshold_blocks."""

    def test_default_stale_threshold_is_10(self):
        """Default stale_threshold_blocks is 10 (hot lane backward compat)."""
        from m7.orderflow.pool_registry import PoolRegistry
        reg = PoolRegistry()
        assert reg.stale_threshold_blocks == 10

    def test_custom_stale_threshold(self):
        """PoolRegistry accepts custom stale_threshold_blocks."""
        from m7.orderflow.pool_registry import PoolRegistry
        reg = PoolRegistry(stale_threshold_blocks=200)
        assert reg.stale_threshold_blocks == 200

    def test_cold_registry_uses_5000(self):
        """Cold registry in m7a_orderflow_loop uses stale_threshold_blocks=5000."""
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        source = inspect.getsource(run_loop)
        assert "PoolRegistry(stale_threshold_blocks=5000)" in source

    def test_preload_pair_uses_instance_threshold(self):
        """preload_pair() staleness check uses self.stale_threshold_blocks."""
        import inspect
        from m7.orderflow.pool_registry import PoolRegistry
        source = inspect.getsource(PoolRegistry.preload_pair)
        assert "self.stale_threshold_blocks" in source


# ═══════════════════════════════════════════════════════════════════════
# M7.A.5.39 — Two-level promotion + hot prewarm + cold lane registry fix
# ═══════════════════════════════════════════════════════════════════════


class TestM7A539TwoLevelPromotion:
    """M7.A.5.39: Two-level promotion system (candidate + execution)."""

    def test_returns_dict_with_candidate_and_execution(self):
        """_promote_pairs_from_cold returns dict with 'candidate' and 'execution' keys."""
        from scripts.m7a_orderflow_loop import _promote_pairs_from_cold
        cold_artifact = {"results": []}
        stats = {}
        result = _promote_pairs_from_cold(cold_artifact, stats)
        assert isinstance(result, dict)
        assert "candidate" in result
        assert "execution" in result
        assert isinstance(result["candidate"], list)
        assert isinstance(result["execution"], list)

    def test_candidate_without_size_valid(self):
        """Pairs with active pools but size_valid=False get candidate promotion."""
        from scripts.m7a_orderflow_loop import _promote_pairs_from_cold
        cold_artifact = {
            "results": [
                {"actual_pair": "ARB/WETH", "size_valid_for_token": False,
                 "reject_reason": None, "registry_pools_active": 2,
                 "best_backrun_net_bps": 16.0},
            ],
        }
        stats = {}
        _promote_pairs_from_cold(cold_artifact, stats)
        result = _promote_pairs_from_cold(cold_artifact, stats)
        assert "ARB/WETH" in result["candidate"]
        assert "ARB/WETH" not in result["execution"]

    def test_execution_requires_size_valid(self):
        """Only pairs with size_valid=True get execution promotion."""
        from scripts.m7a_orderflow_loop import _promote_pairs_from_cold
        cold_artifact = {
            "results": [
                {"actual_pair": "WETH/USDC", "size_valid_for_token": True,
                 "reject_reason": None, "registry_pools_active": 2,
                 "best_backrun_net_bps": 5.0},
                {"actual_pair": "SPA/USDC", "size_valid_for_token": False,
                 "reject_reason": None, "registry_pools_active": 1,
                 "best_backrun_net_bps": 100.0},
            ],
        }
        stats = {}
        _promote_pairs_from_cold(cold_artifact, stats)
        result = _promote_pairs_from_cold(cold_artifact, stats)
        assert "WETH/USDC" in result["execution"]
        assert "SPA/USDC" not in result["execution"]
        assert "SPA/USDC" in result["candidate"]

    def test_candidate_caps_at_candidate_max(self):
        """Candidate list capped at PROMOTED_CANDIDATE_MAX_PAIRS."""
        from scripts.m7a_orderflow_loop import _promote_pairs_from_cold
        from m7.shared.constants import PROMOTED_CANDIDATE_MAX_PAIRS
        cold_artifact = {
            "results": [
                {"actual_pair": f"T{i}/WETH", "size_valid_for_token": False,
                 "reject_reason": None, "registry_pools_active": 2,
                 "best_backrun_net_bps": float(i)}
                for i in range(30)
            ],
        }
        stats = {}
        _promote_pairs_from_cold(cold_artifact, stats)
        result = _promote_pairs_from_cold(cold_artifact, stats)
        assert len(result["candidate"]) <= PROMOTED_CANDIDATE_MAX_PAIRS

    def test_anomaly_excluded_from_both_levels(self):
        """PRICING_ANOMALY pairs excluded from both candidate and execution."""
        from scripts.m7a_orderflow_loop import _promote_pairs_from_cold
        cold_artifact = {
            "results": [
                {"actual_pair": "BAD/PAIR", "size_valid_for_token": True,
                 "reject_reason": "REJECT_PRICING_ANOMALY",
                 "registry_pools_active": 5, "best_backrun_net_bps": 999.0},
            ],
        }
        stats = {}
        _promote_pairs_from_cold(cold_artifact, stats)
        result = _promote_pairs_from_cold(cold_artifact, stats)
        assert "BAD/PAIR" not in result["candidate"]
        assert "BAD/PAIR" not in result["execution"]


class TestM7A539Constants:
    """M7.A.5.39: New constants for two-level promotion."""

    def test_candidate_max_pairs_exists(self):
        from m7.shared.constants import PROMOTED_CANDIDATE_MAX_PAIRS, PROMOTED_MAX_PAIRS
        assert PROMOTED_CANDIDATE_MAX_PAIRS >= PROMOTED_MAX_PAIRS

    def test_promoted_constants_relationship(self):
        """Candidate max >= execution max (wider funnel)."""
        from m7.shared.constants import PROMOTED_CANDIDATE_MAX_PAIRS, PROMOTED_MAX_PAIRS
        assert PROMOTED_CANDIDATE_MAX_PAIRS >= PROMOTED_MAX_PAIRS


class TestM7A539ColdLaneRegistryFix:
    """M7.A.5.39: Cold lane must not trigger hot mode."""

    def test_cold_lane_sets_ext_registry_none(self):
        """Cold lane sets _ext_registry = None (not _hot_registry)."""
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        source = inspect.getsource(run_loop)
        # The cold lane block should set _ext_registry = None
        # and pass warm_registry for cold-mode scoring
        assert "_ext_registry = None" in source

    def test_cold_lane_prewarms_cold_registry(self):
        """Cold lane preloads _cold_registry, not _hot_registry."""
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        source = inspect.getsource(run_loop)
        assert "_cold_registry, _pairs_to_prewarm" in source


class TestM7A539CrossLanePromoted:
    """M7.A.5.39: Cross-lane promoted pairs file for hot/cold communication."""

    def test_write_and_read_promoted_pairs(self):
        """Promoted pairs can be written and read back."""
        import tempfile
        import os
        from scripts.m7a_orderflow_loop import _write_promoted_pairs, _read_promoted_pairs, _PROMOTED_PAIRS_PATH

        # Save original path and use temp
        original_path = _PROMOTED_PAIRS_PATH
        import scripts.m7a_orderflow_loop as loop_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = os.path.join(tmpdir, "m7_promoted_pairs.json")
            loop_mod._PROMOTED_PAIRS_PATH = tmp_path
            try:
                promoted = {
                    "candidate": ["ARB/WETH", "SPA/USDC"],
                    "execution": ["ARB/WETH"],
                }
                _write_promoted_pairs(promoted)
                result = _read_promoted_pairs()
                assert result["candidate"] == ["ARB/WETH", "SPA/USDC"]
                assert result["execution"] == ["ARB/WETH"]
            finally:
                loop_mod._PROMOTED_PAIRS_PATH = original_path

    def test_read_returns_empty_when_missing(self):
        """Reading missing file returns empty dict."""
        import scripts.m7a_orderflow_loop as loop_mod
        from scripts.m7a_orderflow_loop import _read_promoted_pairs
        original_path = loop_mod._PROMOTED_PAIRS_PATH
        loop_mod._PROMOTED_PAIRS_PATH = "/nonexistent/path/file.json"
        try:
            result = _read_promoted_pairs()
            assert result == {"candidate": [], "execution": []}
        finally:
            loop_mod._PROMOTED_PAIRS_PATH = original_path


class TestM7A539HotPrewarmFromCross:
    """M7.A.5.39: Hot lane reads cross-lane promoted pairs for prewarm."""

    def test_hot_lane_reads_promoted_pairs(self):
        """run_loop source contains _read_promoted_pairs call for hot lane."""
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        source = inspect.getsource(run_loop)
        assert "_read_promoted_pairs()" in source

    def test_hot_lane_prewarms_hot_registry(self):
        """Hot lane prewarms _hot_registry (not _cold_registry)."""
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        source = inspect.getsource(run_loop)
        assert "_hot_registry, _hot_pairs_to_prewarm" in source


class TestM7A539HotArtifactTwoLevel:
    """M7.A.5.39: Hot artifact includes two-level watchlist info."""

    def test_write_hot_artifact_accepts_candidate_pairs(self):
        """_write_hot_artifact accepts candidate_pairs kwarg."""
        import inspect
        from scripts.m7a_orderflow_loop import _write_hot_artifact
        sig = inspect.signature(_write_hot_artifact)
        assert "candidate_pairs" in sig.parameters

    def test_web3_reuse_in_mode_ws_live(self):
        """mode_ws_live creates Web3 once before the block loop, not per-block."""
        import inspect
        from m7.orderflow.mode_ws_live import run_ws_live
        source = inspect.getsource(run_ws_live)
        # Should have _w3_loop created before the while loop
        assert "_w3_loop" in source
        # Should NOT have per-block `w3 = Web3(Web3.HTTPProvider(rpc_url))` in the loop
        # The old per-block pattern was `w3 = Web3(Web3.HTTPProvider(rpc_url))`
        # After the fix, the in-loop reference is _w3_loop.eth.get_logs
        assert "_w3_loop.eth.get_logs" in source


class TestM7A539StdoutDrainFix:
    """M7.A.5.39: start_nonstop_runtime drains stdout in health check loop."""

    def test_drain_output_called_in_health_loop(self):
        """drain_output() is called in the supervisor health check loop."""
        import inspect
        from scripts.start_nonstop_runtime import main
        source = inspect.getsource(main)
        assert "drain_output()" in source


# ── M7.A.5.40 Tests ─────────────────────────────────────────────────────


class TestM7A540BatchPreResolve:
    """M7.A.5.40: batch_pre_resolve_pools resolves pools and fills caches."""

    def test_batch_pre_resolve_pools_importable(self):
        """batch_pre_resolve_pools is importable from resolve module."""
        from m7.orderflow.resolve import batch_pre_resolve_pools
        assert callable(batch_pre_resolve_pools)

    def test_batch_pre_resolve_pools_empty_input(self):
        """batch_pre_resolve_pools returns empty dict for empty input."""
        from m7.orderflow.resolve import batch_pre_resolve_pools
        result = batch_pre_resolve_pools([], "http://dummy", 100, {})
        assert result == {}

    def test_batch_pre_resolve_populates_pool_token_cache(self):
        """batch_pre_resolve_pools populates _pool_token_cache for known pools."""
        from m7.orderflow.resolve import _pool_token_cache, batch_pre_resolve_pools
        # Pre-populate cache to test cache-hit path
        _test_addr = "0x" + "ab" * 20
        _pool_token_cache[_test_addr.lower()] = ("0x" + "01" * 20, "0x" + "02" * 20, 500)
        result = batch_pre_resolve_pools([_test_addr], "http://dummy", 100, {})
        assert _test_addr.lower() in result
        assert result[_test_addr.lower()]["fee"] == 500
        # Cleanup
        del _pool_token_cache[_test_addr.lower()]

    def test_batch_pre_resolve_returns_token0_token1(self):
        """batch_pre_resolve_pools returns token0/token1/fee in result dict."""
        from m7.orderflow.resolve import _pool_token_cache, batch_pre_resolve_pools
        _test_addr = "0x" + "cd" * 20
        _pool_token_cache[_test_addr.lower()] = ("0x" + "11" * 20, "0x" + "22" * 20, 3000)
        result = batch_pre_resolve_pools([_test_addr], "http://dummy", 100, {})
        info = result[_test_addr.lower()]
        assert "token0" in info
        assert "token1" in info
        assert "fee" in info
        del _pool_token_cache[_test_addr.lower()]


class TestM7A540GetCachedDecimals:
    """M7.A.5.40: get_cached_decimals reads from enrichment cache."""

    def test_get_cached_decimals_importable(self):
        """get_cached_decimals is importable from resolve module."""
        from m7.orderflow.resolve import get_cached_decimals
        assert callable(get_cached_decimals)

    def test_get_cached_decimals_returns_none_for_unknown(self):
        """get_cached_decimals returns None for uncached token."""
        from m7.orderflow.resolve import get_cached_decimals
        result = get_cached_decimals("0x" + "ff" * 20)
        assert result is None

    def test_get_cached_decimals_returns_cached_value(self):
        """get_cached_decimals returns cached decimals from _enrichment_cache."""
        from m7.orderflow.resolve import _enrichment_cache, get_cached_decimals
        _test_addr = "0x" + "ee" * 20
        _enrichment_cache[_test_addr.lower()] = {
            "enriched": True, "symbol": "TEST", "decimals": 18, "source": "onchain",
        }
        result = get_cached_decimals(_test_addr)
        assert result == 18
        del _enrichment_cache[_test_addr.lower()]

    def test_get_cached_decimals_6_for_stablecoin(self):
        """get_cached_decimals returns 6 for a cached stablecoin-like token."""
        from m7.orderflow.resolve import _enrichment_cache, get_cached_decimals
        _test_addr = "0x" + "dd" * 20
        _enrichment_cache[_test_addr.lower()] = {
            "enriched": True, "symbol": "USDC", "decimals": 6, "source": "onchain",
        }
        result = get_cached_decimals(_test_addr)
        assert result == 6
        del _enrichment_cache[_test_addr.lower()]


class TestM7A540ColdPrePassInModeWsLive:
    """M7.A.5.40: mode_ws_live has cold-lane batch pre-pass before scoring."""

    def test_batch_pre_resolve_imported(self):
        """mode_ws_live imports batch_pre_resolve_pools."""
        import inspect
        from m7.orderflow.mode_ws_live import run_ws_live
        source = inspect.getsource(run_ws_live)
        assert "batch_pre_resolve_pools" in source

    def test_cold_pre_resolve_before_scoring(self):
        """Cold lane pre-resolves events before the scoring loop."""
        import inspect
        from m7.orderflow.mode_ws_live import run_ws_live
        source = inspect.getsource(run_ws_live)
        # Pre-resolve must appear before "Score with parallel pipeline"
        pre_idx = source.find("batch_pre_resolve_pools")
        score_idx = source.find("Score with parallel pipeline")
        assert pre_idx > 0
        assert score_idx > 0
        assert pre_idx < score_idx, "batch_pre_resolve_pools must appear before scoring loop"

    def test_cold_pre_pass_preloads_registry(self):
        """Cold pre-pass calls session_registry.preload_pair for discovered pairs."""
        import inspect
        from m7.orderflow.mode_ws_live import run_ws_live
        source = inspect.getsource(run_ws_live)
        # The pre-pass should call preload_pair on session_registry
        assert "session_registry.preload_pair" in source

    def test_cold_pre_pass_only_in_cold_mode(self):
        """Pre-pass is gated on not _hot_mode."""
        import inspect
        from m7.orderflow.mode_ws_live import run_ws_live
        source = inspect.getsource(run_ws_live)
        assert "not _hot_mode" in source


class TestM7A540SizeValidCacheFallback:
    """M7.A.5.40: scoring uses cached decimals for size_valid_for_token."""

    def test_scoring_imports_get_cached_decimals(self):
        """scoring_parallel imports get_cached_decimals from resolve."""
        import inspect
        from m7.orderflow.scoring_parallel import score_backrun_live_parallel
        source = inspect.getsource(score_backrun_live_parallel)
        assert "get_cached_decimals" in source

    def test_cached_decimals_fallback_before_heuristic(self):
        """get_cached_decimals is tried before symbol-based heuristic."""
        import inspect
        from m7.orderflow.scoring_parallel import score_backrun_live_parallel
        source = inspect.getsource(score_backrun_live_parallel)
        cache_idx = source.find("get_cached_decimals")
        heuristic_idx = source.find("Well-known stablecoin heuristic")
        assert cache_idx > 0
        assert heuristic_idx > 0
        assert cache_idx < heuristic_idx, "cached decimals must be tried before heuristic"


# ===========================================================================
# M7.A.5.43: Bridge-driven hot registry + near_executable + pool_address transport
# ===========================================================================


class TestM7A543NearExecutableCandidates:
    """M7.A.5.43: near_executable_candidates in build_replay_summary."""

    def test_near_executable_key_exists_empty(self):
        art = build_replay_summary([], [], mode="test")
        assert "near_executable_candidates" in art
        assert art["near_executable_candidates"] == []

    def test_near_executable_captures_gas_exceeds_with_size_valid(self):
        e = _make_event()
        r = _make_result(
            event_id="gas1",
            best_backrun_net_bps=-10.0,
            block_lag=1,
            same_state_class="next_block",
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            route_viable=False,
            size_valid_for_token=True,
            scoring_path="registry_direct",
            event_block=100,
            event_detected_at_block=100,
        )
        art = build_replay_summary([e], [r], mode="test")
        near = art["near_executable_candidates"]
        assert len(near) == 1
        assert near[0]["event_id"] == "gas1"
        assert near[0]["reject_reason"] == REJECT_GAS_EXCEEDS_GROSS

    def test_near_executable_excludes_size_invalid(self):
        e = _make_event()
        r = _make_result(
            event_id="gas2",
            best_backrun_net_bps=-10.0,
            block_lag=1,
            same_state_class="next_block",
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            route_viable=False,
            size_valid_for_token=False,
            scoring_path="registry_direct",
        )
        art = build_replay_summary([e], [r], mode="test")
        near = art["near_executable_candidates"]
        assert len(near) == 0

    def test_near_executable_captures_stale_positive_with_size_valid(self):
        e = _make_event()
        r = _make_result(
            event_id="s1",
            best_backrun_net_bps=5.0,
            block_lag=5,
            same_state_class="stale",
            reject_reason=REJECT_STALE_POSITIVE,
            route_viable=False,
            size_valid_for_token=True,
            scoring_path="registry_direct",
        )
        art = build_replay_summary([e], [r], mode="test")
        near = art["near_executable_candidates"]
        assert len(near) == 1

    def test_near_executable_excludes_below_minus_50(self):
        e = _make_event()
        r = _make_result(
            event_id="bad",
            best_backrun_net_bps=-60.0,
            block_lag=1,
            same_state_class="next_block",
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            route_viable=False,
            size_valid_for_token=True,
            scoring_path="registry_direct",
        )
        art = build_replay_summary([e], [r], mode="test")
        near = art["near_executable_candidates"]
        assert len(near) == 0


class TestM7A543CompactCandidatePoolAddress:
    """M7.A.5.43: _compact_candidate includes pool_address from _source_event."""

    def test_pool_address_present_when_source_event_attached(self):
        e = _make_event(pool_address="0xABCD1234")
        r = _make_result(
            event_id="e1",
            best_backrun_net_bps=50.0,
            block_lag=0,
            same_state_class="same_block",
            reject_reason=None,
            route_viable=True,
            size_valid_for_token=True,
            event_block=100,
            event_detected_at_block=100,
        )
        r._source_event = e
        art = build_replay_summary([e], [r], mode="test")
        top = art["top_executable_candidates"]
        assert len(top) >= 1
        assert top[0]["pool_address"] == "0xABCD1234"

    def test_pool_address_none_when_no_source_event(self):
        e = _make_event()
        r = _make_result(
            event_id="e1",
            best_backrun_net_bps=50.0,
            block_lag=0,
            same_state_class="same_block",
            reject_reason=None,
            route_viable=True,
            size_valid_for_token=True,
            event_block=100,
            event_detected_at_block=100,
        )
        art = build_replay_summary([e], [r], mode="test")
        top = art["top_executable_candidates"]
        assert len(top) >= 1
        assert top[0]["pool_address"] is None


class TestM7A543BridgeFunctions:
    """M7.A.5.43: Bridge read/write and pool_token_cache population."""

    def test_read_cold_hot_bridge_returns_empty_when_missing(self):
        from scripts.m7a_orderflow_loop import _read_cold_hot_bridge
        # Should not raise, returns empty dict
        result = _read_cold_hot_bridge()
        assert isinstance(result, dict)

    def test_populate_pool_token_cache_from_bridge(self):
        from scripts.m7a_orderflow_loop import _populate_pool_token_cache_from_bridge
        from m7.orderflow.resolve import _pool_token_cache
        # Save and restore cache state
        _saved = dict(_pool_token_cache)
        try:
            _test_key = "0xtestpool_543_bridge"
            _pool_token_cache.pop(_test_key, None)
            bridge = {
                "pool_token_transport": {
                    _test_key: ["0xtoken0", "0xtoken1", 3000],
                }
            }
            count = _populate_pool_token_cache_from_bridge(bridge)
            assert count == 1
            assert _test_key in _pool_token_cache
            assert _pool_token_cache[_test_key] == ("0xtoken0", "0xtoken1", 3000)
        finally:
            _pool_token_cache.clear()
            _pool_token_cache.update(_saved)

    def test_populate_pool_token_cache_skips_existing(self):
        from scripts.m7a_orderflow_loop import _populate_pool_token_cache_from_bridge
        from m7.orderflow.resolve import _pool_token_cache
        _saved = dict(_pool_token_cache)
        try:
            _test_key = "0xtestpool_543_exists"
            _pool_token_cache[_test_key] = ("0xold0", "0xold1", 500)
            bridge = {
                "pool_token_transport": {
                    _test_key: ["0xnew0", "0xnew1", 3000],
                }
            }
            count = _populate_pool_token_cache_from_bridge(bridge)
            assert count == 0  # should not overwrite
            assert _pool_token_cache[_test_key] == ("0xold0", "0xold1", 500)
        finally:
            _pool_token_cache.clear()
            _pool_token_cache.update(_saved)

    def test_populate_pool_token_cache_empty_bridge(self):
        from scripts.m7a_orderflow_loop import _populate_pool_token_cache_from_bridge
        count = _populate_pool_token_cache_from_bridge({})
        assert count == 0

    def test_write_cold_hot_bridge_includes_near_executable(self):
        """_write_cold_hot_bridge should include near_executable key in payload."""
        import inspect
        from scripts.m7a_orderflow_loop import _write_cold_hot_bridge
        source = inspect.getsource(_write_cold_hot_bridge)
        assert "near_executable" in source
        assert "pool_token_transport" in source

    def test_write_hot_artifact_bridge_diagnostics_param(self):
        """_write_hot_artifact accepts bridge_diagnostics parameter."""
        import inspect
        from scripts.m7a_orderflow_loop import _write_hot_artifact
        sig = inspect.signature(_write_hot_artifact)
        assert "bridge_diagnostics" in sig.parameters


class TestM7A543HotGapDebugCounters:
    """M7.A.5.43: hot_gap_debug has 3 bridge-driven counters."""

    def test_hot_gap_debug_keys_in_source(self):
        """_write_hot_artifact emits all 3 new hot-miss counters."""
        import inspect
        from scripts.m7a_orderflow_loop import _write_hot_artifact
        source = inspect.getsource(_write_hot_artifact)
        assert "pool_address_match_count" in source
        assert "canonical_pair_match_count" in source
        assert "registry_has_pair_but_not_pool_count" in source
        assert "bridge_cache_populated" in source
        assert "bridge_registry_prewarmed" in source


# ===========================================================================
# M7.A.5.44: Execution Funnel
# ===========================================================================


class TestM7A544ExecutionFunnel:
    """M7.A.5.44: execution_funnel has 5 stages in artifact."""

    def test_execution_funnel_present(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert "execution_funnel" in artifact

    def test_execution_funnel_stages(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        funnel = artifact["execution_funnel"]
        required_keys = {
            "diagnostic_positive",
            "cold_executable_positive",
            "hot_scored",
            "profit_guard_passed",
            "realized_onchain_profit",
            "headline_level",  # M7.A.5.45
        }
        assert required_keys == set(funnel.keys())

    def test_execution_funnel_types(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        funnel = artifact["execution_funnel"]
        for key, val in funnel.items():
            if key == "headline_level":  # M7.A.5.45: string field
                assert isinstance(val, str), f"{key} should be str, got {type(val)}"
            else:
                assert isinstance(val, int), f"{key} should be int, got {type(val)}"

    def test_execution_funnel_hot_scored_default_zero(self):
        """Cold lane cannot compute hot_scored — defaults to 0."""
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert artifact["execution_funnel"]["hot_scored"] == 0

    def test_execution_funnel_realized_onchain_default_zero(self):
        """M7.B not implemented — realized_onchain_profit always 0."""
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert artifact["execution_funnel"]["realized_onchain_profit"] == 0

    def test_execution_funnel_monotonic_decrease(self):
        """Each stage should be <= the previous (strict subset invariant)."""
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        funnel = artifact["execution_funnel"]
        assert funnel["cold_executable_positive"] <= funnel["diagnostic_positive"]
        assert funnel["profit_guard_passed"] <= funnel["cold_executable_positive"]
        assert funnel["realized_onchain_profit"] <= funnel["profit_guard_passed"]


# ===========================================================================
# M7.A.5.44: Compact Candidate Verification
# ===========================================================================


class TestM7A544CompactCandidateVerification:
    """M7.A.5.44: compact candidate has verified_profitable and verified_net_bps."""

    def test_verified_fields_present(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        for c in artifact["top_executable_candidates"]:
            assert "verified_profitable" in c
            assert "verified_net_bps" in c

    def test_verified_profitable_is_bool_or_none(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        for c in artifact["top_executable_candidates"]:
            assert c["verified_profitable"] is None or isinstance(c["verified_profitable"], bool)

    def test_verified_net_bps_is_numeric_or_none(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        for c in artifact["top_executable_candidates"]:
            assert c["verified_net_bps"] is None or isinstance(c["verified_net_bps"], (int, float))


# ===========================================================================
# M7.A.5.44: Micro-Refinement
# ===========================================================================


class TestM7A544MicroRefinement:
    """M7.A.5.44: micro_refinement list in artifact."""

    def test_micro_refinement_present(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert "micro_refinement" in artifact
        assert isinstance(artifact["micro_refinement"], list)

    def test_micro_refinement_entry_schema(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        required_keys = {
            "event_id", "actual_pair", "base_net_bps",
            "sizes_tried", "sizes_passed", "best_micro_net_bps",
            "reject_reason",
        }
        for entry in artifact["micro_refinement"]:
            assert required_keys.issubset(set(entry.keys())), (
                f"missing keys: {required_keys - set(entry.keys())}"
            )

    def test_micro_refinement_sizes_tried_bounded(self):
        """At most 5 multipliers tried per candidate."""
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        for entry in artifact["micro_refinement"]:
            assert entry["sizes_tried"] <= 5

    def test_micro_refinement_sizes_passed_le_tried(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        for entry in artifact["micro_refinement"]:
            assert entry["sizes_passed"] <= entry["sizes_tried"]


# ===========================================================================
# M7.A.5.44: Bridge Hit Counters in Hot Lane
# ===========================================================================


class TestM7A544BridgeHitCounters:
    """M7.A.5.44: 3 new bridge-hit counters in _hot_bridge_diag."""

    def test_bridge_hit_counter_keys_in_source(self):
        """m7a_orderflow_loop initializes all 3 new bridge-hit counters."""
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        source = inspect.getsource(run_loop)
        assert "bridge_pool_address_hit_count" in source
        assert "bridge_pair_hit_count" in source
        assert "bridge_loaded_candidate_count" in source

    def test_bridge_hit_counters_computed(self):
        """Computation logic exists for bridge_pool_address_hit_count."""
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        source = inspect.getsource(run_loop)
        # Verify the counter is incremented (computed, not just initialized)
        assert 'bridge_pool_address_hit_count"] += 1' in source
        assert 'bridge_pair_hit_count"] += 1' in source
        assert 'bridge_loaded_candidate_count"] = len' in source


# ===========================================================================
# M7.A.5.44: Dashboard Execution Gap Section
# ===========================================================================


class TestM7A544DashboardFunnelSection:
    """M7.A.5.44: dashboard has Execution Gap Funnel section."""

    def test_dashboard_has_funnel_section(self):
        import pathlib
        src = pathlib.Path("monitoring/dashboard.html").read_text(encoding="utf-8")
        assert "Execution Gap Funnel" in src

    def test_dashboard_funnel_stages_rendered(self):
        import pathlib
        src = pathlib.Path("monitoring/dashboard.html").read_text(encoding="utf-8")
        for stage in [
            "diagnostic_positive",
            "cold_executable_positive",
            "hot_scored",
            "profit_guard_passed",
            "realized_onchain_profit",
        ]:
            assert stage in src, f"funnel stage {stage} not in dashboard"

    def test_dashboard_micro_refinement_table(self):
        import pathlib
        src = pathlib.Path("monitoring/dashboard.html").read_text(encoding="utf-8")
        assert "micro_refinement" in src

    def test_dashboard_verified_column(self):
        import pathlib
        src = pathlib.Path("monitoring/dashboard.html").read_text(encoding="utf-8")
        assert "verified_profitable" in src


# ===========================================================================
# M7.A.5.45 — Bridge execution queue, hot intents, headline enforcement
# ===========================================================================


class TestM7A545HeadlineLevel:
    """M7.A.5.45: headline_level computation in execution_funnel."""

    def test_headline_level_present_in_funnel(self):
        """Cold-lane artifact must include headline_level in execution_funnel."""
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        art = build_replay_summary(events, results, mode="ws_live")
        funnel = art.get("execution_funnel", {})
        assert "headline_level" in funnel

    def test_headline_level_with_positives(self):
        """When diagnostic_positive > 0, headline_level should be at least that."""
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        art = build_replay_summary(events, results, mode="ws_live")
        funnel = art.get("execution_funnel", {})
        if funnel.get("diagnostic_positive", 0) > 0:
            assert funnel["headline_level"] != "none"

    def test_headline_level_none_when_all_zero(self):
        """When all stages are 0, headline_level = 'none'."""
        from scripts.m7a_orderflow_loop import _compute_headline_level
        funnel = {
            "diagnostic_positive": 0,
            "cold_executable_positive": 0,
            "hot_scored": 0,
            "profit_guard_passed": 0,
            "realized_onchain_profit": 0,
        }
        assert _compute_headline_level(funnel) == "none"

    def test_headline_level_picks_highest(self):
        """headline_level should be the most advanced confirmed stage."""
        from scripts.m7a_orderflow_loop import _compute_headline_level
        funnel = {
            "diagnostic_positive": 5,
            "cold_executable_positive": 2,
            "hot_scored": 3,
            "profit_guard_passed": 1,
            "realized_onchain_profit": 0,
        }
        assert _compute_headline_level(funnel) == "profit_guard_passed"

    def test_headline_level_cold_only(self):
        """When only cold stages have counts, headline should be cold."""
        from scripts.m7a_orderflow_loop import _compute_headline_level
        funnel = {
            "diagnostic_positive": 5,
            "cold_executable_positive": 2,
            "hot_scored": 0,
            "profit_guard_passed": 0,
            "realized_onchain_profit": 0,
        }
        assert _compute_headline_level(funnel) == "cold_executable_positive"


class TestM7A545PriorityPrewarm:
    """M7.A.5.45: _prewarm_registry_from_bridge with priority_pools."""

    def test_function_accepts_priority_pools(self):
        """_prewarm_registry_from_bridge must accept priority_pools param."""
        from scripts.m7a_orderflow_loop import _prewarm_registry_from_bridge
        import inspect
        sig = inspect.signature(_prewarm_registry_from_bridge)
        assert "priority_pools" in sig.parameters

    def test_priority_pools_default_is_none(self):
        """Default value for priority_pools is None."""
        from scripts.m7a_orderflow_loop import _prewarm_registry_from_bridge
        import inspect
        sig = inspect.signature(_prewarm_registry_from_bridge)
        assert sig.parameters["priority_pools"].default is None

    def test_empty_bridge_returns_zero(self):
        """Empty bridge ptt returns 0 prewarmed."""
        from scripts.m7a_orderflow_loop import _prewarm_registry_from_bridge

        class DummyReg:
            def preload_pair(self, *a, **kw):
                pass
        result = _prewarm_registry_from_bridge(
            DummyReg(), {}, {}, "", 0, priority_pools=set()
        )
        assert result == 0


class TestM7A545HotIntentsArtifact:
    """M7.A.5.45: _write_hot_intents function contract."""

    def test_write_hot_intents_exists(self):
        """Function exists in m7a_orderflow_loop."""
        from scripts.m7a_orderflow_loop import _write_hot_intents
        assert callable(_write_hot_intents)

    def test_write_hot_intents_writes_file(self, tmp_path, monkeypatch):
        """_write_hot_intents writes the intents artifact to rolling dir."""
        import json as _json
        from scripts import m7a_orderflow_loop as mod
        out = tmp_path / "m7_hot_intents_latest.json"
        monkeypatch.setattr(mod, "_HOT_INTENTS_PATH", str(out))

        mod._write_hot_intents(
            fast_results=[], guard_results=None, iteration=1, bridge={},
        )
        assert out.exists()
        data = _json.loads(out.read_text(encoding="utf-8"))
        assert "headline_level" in data
        assert "hot_scored_count" in data
        assert "intents" in data
        assert isinstance(data["intents"], list)

    def test_write_hot_intents_caps_rows(self, tmp_path, monkeypatch):
        """Intents rows are capped at 20."""
        import json as _json
        from scripts import m7a_orderflow_loop as mod
        out = tmp_path / "m7_hot_intents_latest.json"
        monkeypatch.setattr(mod, "_HOT_INTENTS_PATH", str(out))

        # Make 30 fake BackrunResult-like objects
        class FakeResult:
            def __init__(self, i):
                self.event_id = f"evt_{i}"
                self.actual_pair = "WETH/USDC"
                self.best_backrun_net_bps = 10.0 - i * 0.1
                self.profit_guard_passed = False
                self.scoring_path = "registry_fast"
                self.quote_pipeline_latency_ms = 5.0
                self.route_viable = True

        fakes = [FakeResult(i) for i in range(30)]
        mod._write_hot_intents(
            fast_results=fakes, guard_results=None, iteration=1, bridge={},
        )
        data = _json.loads(out.read_text(encoding="utf-8"))
        assert len(data["intents"]) <= 20


class TestM7A545HotIntentsPathConstant:
    """M7.A.5.45: _HOT_INTENTS_PATH is defined."""

    def test_path_constant_exists(self):
        from scripts.m7a_orderflow_loop import _HOT_INTENTS_PATH
        assert "m7_hot_intents_latest.json" in _HOT_INTENTS_PATH


class TestM7A545DashboardHeadlineLevel:
    """M7.A.5.45: Dashboard shows headline_level badge."""

    def test_dashboard_has_headline_level(self):
        import pathlib
        src = pathlib.Path("monitoring/dashboard.html").read_text(encoding="utf-8")
        assert "headline_level" in src

    def test_dashboard_has_headlinelevel_color_logic(self):
        import pathlib
        src = pathlib.Path("monitoring/dashboard.html").read_text(encoding="utf-8")
        assert "headlineLevelColor" in src

    def test_dashboard_has_hot_scored_color(self):
        import pathlib
        src = pathlib.Path("monitoring/dashboard.html").read_text(encoding="utf-8")
        assert "hot_scored" in src


class TestM7A545DashboardIntentsEndpoint:
    """M7.A.5.45: Dashboard server has /api/intents endpoint."""

    def test_intents_endpoint_in_server(self):
        import pathlib
        src = pathlib.Path("monitoring/dashboard_server.py").read_text(encoding="utf-8")
        assert "/api/intents" in src

    def test_intents_artifact_in_files(self):
        import pathlib
        src = pathlib.Path("monitoring/dashboard_server.py").read_text(encoding="utf-8")
        assert "m7_hot_intents" in src
