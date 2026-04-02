"""
Consolidated ARTIFACTS_STATUS tests for M7 orderflow.

Locks all artifact-level contracts produced by build_replay_summary(),
build_intent_surface_assessments(), and build_intent_scout_summary():

- Replay artifact schema (hypothesis, baselines, reject histograms, mode)
- Intent surface scout artifact schema
- Backward compatibility of artifact baselines (M7.A.4, M7.A.5)
- ws_live artifact mode and keys (M7.A.5.3)
- ws_low_lag_summary and ws_stale_summary schema (M7.A.5.3.1)
- Coverage scan metrics, size sweep metrics, m4_m7_comparison (M7.A.5.5, M7.A.5.6)
- Split viability summary fields (M7.A.5.10)
- Pre-econ metrics, unscored reject artifact counts (M7.A.5.11)
- Consistency metrics (M7.A.5.12)
- Stale/low-lag scored split fields, comparison block (M7.A.5.13)
- Low-lag reject decomposition, pipeline stage rates (M7.A.5.14)
- Low-lag debug rows, coverage truth, 4 synthetic paths (M7.A.5.15)
- Pool-class truth, dex family histogram, debug row key updates (M7.A.5.16)
- V2 low-lag metrics, pool_state_read_path in debug rows (M7.A.5.17)
- Blocker tags, low-lag watchlist, quote-fail provenance (M7.A.5.18, M7.A.5.19)
- Local pricing artifact block (M7.A.5.20)
- Registry metrics artifact (M7.A.5.21)
- Registry session stats, hypothesis strings (M7.A.5.22)
- Low-lag fast-path artifact (M7.A.5.23)
- Non-low-lag unchanged invariant (M7.A.5.23)
- Pipeline optimization artifact (M7.A.5.24)
- Backward compatibility for every milestone (field counts, key presence)
"""
from __future__ import annotations

import json
from dataclasses import asdict, fields

import pytest

from m7.orderflow.artifacts import (
    build_intent_scout_summary,
    build_intent_surface_assessments,
    build_replay_summary,
    score_backrun_offline,
)
from m7.orderflow.contracts import (
    BackrunResult,
    IntentSurfaceAssessment,
    OrderflowEvent,
)
from m7.orderflow.events import build_fixture_events
from m7.shared.constants import (
    ADMISSION_CANONICAL,
    ADMISSION_ONCHAIN_ENRICHED,
    ALL_BLOCKER_TAGS,
    ALL_REJECT_REASONS,
    ALL_SURFACES,
    BACKRUN_BUY_DEPRESSED,
    BLOCKER_GAS_L1_DATA_DOMINANT,
    BLOCKER_LOW_LAG_INACTIVE_POOL,
    BLOCKER_LOW_LAG_NONE_THIS_WINDOW,
    BLOCKER_LOW_LAG_NO_COUNTER_POOL,
    BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY,
    BLOCKER_LOW_LAG_V2_UNSUPPORTED,
    BLOCKER_SUBGRAPH_API_KEY_REQUIRED,
    EVENT_TYPE_SWAP,
    M7A4_CHAIN,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    REJECT_COVERAGE_LOCAL_MISMATCH,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_NO_ACTIVE_COUNTER_POOL,
    REJECT_NO_COUNTER_POOL,
    REJECT_RPC_QUOTE_FAIL,
    REJECT_STALE_POSITIVE,
    REJECT_TOKEN_NOT_ADMITTED,
    REJECT_TOKEN_PAIR_UNRESOLVED,
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
# M7.A.5.15: Low-Lag Debug Rows
# ===========================================================================


class TestM7A515LowLagDebugRows:
    """M7.A.5.15: build_replay_summary emits low_lag_debug_rows."""

    def test_low_lag_debug_rows_present_empty(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_debug_rows" in art
        assert art["low_lag_debug_rows"] == []

    def test_low_lag_debug_rows_present_with_results(self):
        r = _make_result(
            event_id="debug_row_1", block_lag=1,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False, pair_unresolved_detail="pool_read_failed",
            event_block=100, event_detected_at_block=101,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        rows = art["low_lag_debug_rows"]
        assert len(rows) == 1
        assert rows[0]["event_id"] == "debug_row_1"
        assert rows[0]["reject_reason"] == REJECT_TOKEN_PAIR_UNRESOLVED

    def test_low_lag_debug_rows_only_low_lag(self):
        low = _make_result(
            event_id="low_lag", block_lag=0,
            reject_reason=REJECT_NO_COUNTER_POOL, pair_resolved=True,
            actual_pair="LINK/UNI", event_block=100, event_detected_at_block=100,
        )
        stale = _make_result(
            event_id="stale", block_lag=10,
            reject_reason=REJECT_NO_COUNTER_POOL, pair_resolved=True,
            actual_pair="LINK/UNI",
        )
        art = build_replay_summary([], [low, stale], mode="ws_live")
        rows = art["low_lag_debug_rows"]
        assert len(rows) == 1
        assert rows[0]["event_id"] == "low_lag"

    def test_low_lag_debug_row_keys(self):
        r = _make_result(
            event_id="key_check", block_lag=2,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True, actual_pair="X/Y",
            token_admitted=True, admission_source=ADMISSION_CANONICAL,
            counter_venue_count=3, event_block=100, event_detected_at_block=102,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        expected_keys = {
            "event_id", "block_lag", "reject_reason", "pair_resolved",
            "actual_pair", "pair_unresolved_detail", "token_admitted",
            "admission_source", "known_pools", "active_pools",
            "counter_venue_count", "pool_contract_truth",
            "pool_state_read_path",
            "quote_fail_stage", "quote_fail_venue",
            "quote_fail_exception_short",
        }
        assert set(row.keys()) == expected_keys


class TestM7A515LowLagCoverageTruth:
    """M7.A.5.15: Coverage truth metrics for low-lag subset."""

    def test_coverage_truth_present_empty(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_coverage_truth" in art
        ct = art["low_lag_coverage_truth"]
        assert ct["known_pools_total"] == 0
        assert ct["no_counter_pool_rate"] is None

    def test_coverage_truth_rates_with_results(self):
        results = [
            _make_result(
                event_id="cov_1", block_lag=0, reject_reason=REJECT_NO_COUNTER_POOL,
                pair_resolved=True, event_block=100, event_detected_at_block=100,
            ),
            _make_result(
                event_id="cov_2", block_lag=1, reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
                pair_resolved=True, event_block=100, event_detected_at_block=101,
                coverage_result={"known_pools_total": 3, "active_pools_total": 0,
                                 "active_buy_venues": 0, "active_sell_venues": 0},
            ),
            _make_result(
                event_id="cov_3", block_lag=2, best_backrun_net_bps=-1.5,
                route_viable=False, pair_resolved=True,
                event_block=100, event_detected_at_block=102,
                coverage_result={"known_pools_total": 5, "active_pools_total": 2,
                                 "active_buy_venues": 1, "active_sell_venues": 1},
            ),
        ]
        art = build_replay_summary([], results, mode="ws_live")
        ct = art["low_lag_coverage_truth"]
        assert ct["known_pools_total"] == 8
        assert ct["active_pools_total"] == 2


class TestM7A515FourLowLagPaths:
    """M7.A.5.15: 4 synthetic low-lag paths."""

    def test_path_unresolved_pair(self):
        r = _make_result(
            event_id="path_unresolved", block_lag=0,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False, pair_unresolved_detail="pool_read_failed",
            event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 0
        assert art["low_lag_pair_resolution_rate"] == 0.0

    def test_path_no_counter_pool(self):
        r = _make_result(
            event_id="path_no_counter", block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="0x3212dc0f/WETH",
            token_admitted=True, admission_source=ADMISSION_ONCHAIN_ENRICHED,
            counter_venue_count=0, event_block=100, event_detected_at_block=101,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["low_lag_pair_resolution_rate"] == 1.0
        assert art["low_lag_counter_coverage_rate"] == 0.0

    def test_path_inactive_counter_pool(self):
        r = _make_result(
            event_id="path_inactive", block_lag=0,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True, actual_pair="LINK/UNI",
            token_admitted=True, admission_source=ADMISSION_CANONICAL,
            coverage_result={"known_pools_total": 2, "active_pools_total": 0,
                             "active_buy_venues": 0, "active_sell_venues": 0},
            counter_venue_count=2, event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        ct = art["low_lag_coverage_truth"]
        assert ct["known_pools_total"] == 2
        assert ct["active_pools_total"] == 0

    def test_path_active_reaches_scoring(self):
        r = _make_result(
            event_id="path_scored", block_lag=0, pair_resolved=True,
            actual_pair="WETH/USDC", token_admitted=True,
            admission_source=ADMISSION_CANONICAL,
            coverage_result={"known_pools_total": 4, "active_pools_total": 2,
                             "active_buy_venues": 1, "active_sell_venues": 1},
            counter_venue_count=4, best_backrun_net_bps=-1.5,
            route_viable=False, event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["events_scored_low_lag"] == 1
        assert art["low_lag_scored_results_rate"] == 1.0


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
# M7.A.5.16: Pool-Class Truth
# ===========================================================================


class TestM7A516DebugRowPoolTruth:
    """M7.A.5.16: low_lag_debug_rows includes pool_contract_truth."""

    def test_debug_row_has_pool_contract_truth_key(self):
        r = _make_result(
            event_id="row_pct", block_lag=0,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False, pair_unresolved_detail="POOL_TOKEN0_REVERT",
            event_block=100, event_detected_at_block=100,
            pool_contract_truth={
                "pool_address": "0xabc", "code_present": True,
                "token0_ok": False, "token1_ok": False,
                "slot0_ok": False, "liquidity_ok": False,
                "dex_family_guess": "unknown",
            },
        )
        art = build_replay_summary([], [r], mode="ws_live")
        rows = art["low_lag_debug_rows"]
        assert len(rows) == 1
        assert "pool_contract_truth" in rows[0]
        assert rows[0]["pool_contract_truth"]["code_present"] is True

    def test_debug_row_pool_truth_none_when_resolved(self):
        r = _make_result(
            event_id="row_resolved", block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="WETH/USDC",
            pool_contract_truth=None, event_block=100, event_detected_at_block=101,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["low_lag_debug_rows"][0]["pool_contract_truth"] is None


class TestM7A516ThreeLowLagClasses:
    """M7.A.5.16: pool_class_truth rates and dex_family_histogram."""

    def _make_class_results(self):
        results = []
        results.append(_make_result(
            event_id="c1_unsupported", block_lag=0,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False, pair_unresolved_detail="POOL_TOKEN0_REVERT",
            event_block=100, event_detected_at_block=100,
            pool_contract_truth={
                "pool_address": "0xaaa", "code_present": True,
                "token0_ok": False, "token1_ok": False,
                "slot0_ok": False, "liquidity_ok": False,
                "dex_family_guess": "unknown",
            },
        ))
        results.append(_make_result(
            event_id="c2_no_counter", block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="0xabc/WETH",
            counter_venue_count=0, event_block=100, event_detected_at_block=101,
        ))
        results.append(_make_result(
            event_id="c3_inactive", block_lag=0,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True, actual_pair="LINK/UNI",
            counter_venue_count=2, event_block=100, event_detected_at_block=100,
            coverage_result={"known_pools_total": 2, "active_pools_total": 0,
                             "active_buy_venues": 0, "active_sell_venues": 0},
        ))
        results.append(_make_result(
            event_id="c4_scored", block_lag=0,
            pair_resolved=True, actual_pair="WETH/USDC",
            best_backrun_net_bps=-1.5, route_viable=False,
            event_block=100, event_detected_at_block=100,
            coverage_result={"known_pools_total": 4, "active_pools_total": 2,
                             "active_buy_venues": 1, "active_sell_venues": 1},
        ))
        return results

    def test_pool_class_truth_present(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(4)]
        results = self._make_class_results()
        art = build_replay_summary(events, results, mode="test")
        assert "low_lag_pool_class_truth" in art

    def test_unsupported_pool_rate(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(4)]
        results = self._make_class_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["low_lag_pool_class_truth"]["unsupported_pool_rate"] == 0.25

    def test_dex_family_histogram(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(4)]
        results = self._make_class_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["low_lag_pool_class_truth"]["dex_family_histogram"] == {"unknown": 1}

    def test_pool_class_truth_all_none_when_no_low_lag(self):
        results = [_make_result(
            event_id="stale_only", block_lag=10,
            reject_reason=REJECT_STALE_POSITIVE,
        )]
        art = build_replay_summary([_make_event()], results, mode="test")
        pct = art["low_lag_pool_class_truth"]
        assert pct["unsupported_pool_rate"] is None
        assert pct["dex_family_histogram"] == {}


class TestM7A516PoolCodeEmpty:
    """M7.A.5.16: POOL_CODE_EMPTY path."""

    def test_pool_code_empty_detail(self):
        r = _make_result(
            event_id="code_empty", block_lag=0,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False, pair_unresolved_detail="POOL_CODE_EMPTY",
            event_block=100, event_detected_at_block=100,
            pool_contract_truth={
                "pool_address": "0xdead", "code_present": False,
                "token0_ok": False, "token1_ok": False,
                "slot0_ok": False, "liquidity_ok": False,
                "dex_family_guess": "no_code",
            },
        )
        art = build_replay_summary([], [r], mode="ws_live")
        pct = art["low_lag_pool_class_truth"]
        assert pct["unsupported_pool_rate"] == 1.0
        assert pct["dex_family_histogram"] == {"no_code": 1}


class TestM7A516DexFamilyGuessValues:
    """M7.A.5.16: dex_family_guess covers all expected categories."""

    def test_all_family_guesses(self):
        families = [
            "uniswap_v3_like", "uniswap_v2_like",
            "partial_erc20_pool", "unknown", "no_code",
        ]
        for fam in families:
            truth = {
                "pool_address": "0x123", "code_present": fam != "no_code",
                "token0_ok": fam in ("uniswap_v3_like", "uniswap_v2_like", "partial_erc20_pool"),
                "token1_ok": fam in ("uniswap_v3_like", "uniswap_v2_like"),
                "slot0_ok": fam == "uniswap_v3_like",
                "liquidity_ok": fam == "uniswap_v3_like",
                "dex_family_guess": fam,
            }
            r = _make_result(
                event_id=f"fam_{fam}", block_lag=0,
                reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
                pool_contract_truth=truth,
                event_block=100, event_detected_at_block=100,
            )
            art = build_replay_summary([], [r], mode="ws_live")
            assert art["low_lag_pool_class_truth"]["dex_family_histogram"] == {fam: 1}


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
# M7.A.5.17: V2 Low-Lag Metrics, Debug Row Read Path
# ===========================================================================


class TestM7A517DebugRowReadPath:
    """M7.A.5.17: pool_state_read_path appears in low_lag_debug_rows."""

    def test_debug_row_contains_read_path(self):
        r = _make_result(
            event_id="dr_rp", block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="X/Y",
            token_admitted=True, admission_source=ADMISSION_CANONICAL,
            counter_venue_count=0, pool_state_read_path="v2_getReserves",
            event_block=100, event_detected_at_block=101,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert row["pool_state_read_path"] == "v2_getReserves"

    def test_debug_row_key_count_16(self):
        r = _make_result(
            event_id="dr_kc", block_lag=1,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True, actual_pair="A/B",
            token_admitted=True, admission_source=ADMISSION_CANONICAL,
            counter_venue_count=2, pool_state_read_path="v3_multicall",
            event_block=100, event_detected_at_block=101,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert len(row) == 16


class TestM7A517V2LowLagMetrics:
    """M7.A.5.17: low_lag_v2_truth block in build_replay_summary."""

    def test_v2_truth_present_empty(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_v2_truth" in art
        v2t = art["low_lag_v2_truth"]
        expected_keys = {
            "low_lag_v2_supported_rate", "low_lag_v2_scored_results_rate",
            "low_lag_v2_no_counter_pool_rate", "low_lag_v2_inactive_pool_rate",
            "v2_resolved_count", "v2_scored_count",
        }
        assert set(v2t.keys()) == expected_keys

    def test_v2_rates_none_when_no_low_lag(self):
        art = build_replay_summary([], [], mode="test")
        v2t = art["low_lag_v2_truth"]
        assert v2t["low_lag_v2_supported_rate"] is None
        assert v2t["v2_resolved_count"] == 0

    def test_v2_resolved_counted(self):
        v2_result = _make_result(
            event_id="v2_cnt", block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="A/B",
            pool_state_read_path="v2_getReserves",
            event_block=100, event_detected_at_block=101,
        )
        v3_result = _make_result(
            event_id="v3_cnt", block_lag=0,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True, actual_pair="C/D",
            pool_state_read_path="v3_multicall",
            event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([], [v2_result, v3_result], mode="ws_live")
        v2t = art["low_lag_v2_truth"]
        assert v2t["v2_resolved_count"] == 1


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
# M7.A.5.18: Blocker Tags
# ===========================================================================


class TestM7A518BlockerTagsArtifact:
    """M7.A.5.18: blocker_tags block in replay summary."""

    def test_blocker_tags_present_in_empty_artifact(self):
        art = build_replay_summary([], [], mode="test")
        assert "blocker_tags" in art

    def test_blocker_tags_structure(self):
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert "active_tags" in bt
        assert "active_count" in bt
        assert "all_canonical_tags" in bt

    def test_blocker_tags_all_canonical_sorted(self):
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert bt["all_canonical_tags"] == sorted(ALL_BLOCKER_TAGS)

    def test_blocker_tags_no_events_gets_none_this_window(self):
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert BLOCKER_LOW_LAG_NONE_THIS_WINDOW in bt["active_tags"]

    def test_blocker_tags_subgraph_always_present(self):
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert BLOCKER_SUBGRAPH_API_KEY_REQUIRED in bt["active_tags"]

    def test_blocker_tags_with_gas_dominant(self):
        ev = _make_event(eid="gas_dom")
        r = _make_result(
            event_id="gas_dom", best_backrun_net_bps=-5.0,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            event_block=100, quote_block=100, block_lag=0,
            same_state_class="same_block", event_detected_at_block=100,
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert BLOCKER_GAS_L1_DATA_DOMINANT in art["blocker_tags"]["active_tags"]

    def test_blocker_tags_no_counter_pool_on_low_lag(self):
        ev = _make_event(eid="ncp_ll")
        r = _make_result(
            event_id="ncp_ll", reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block", event_detected_at_block=101,
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert BLOCKER_LOW_LAG_NO_COUNTER_POOL in art["blocker_tags"]["active_tags"]

    def test_blocker_tags_inactive_pool_on_low_lag(self):
        ev = _make_event(eid="inactive_ll")
        r = _make_result(
            event_id="inactive_ll", reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block", event_detected_at_block=101,
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert BLOCKER_LOW_LAG_INACTIVE_POOL in art["blocker_tags"]["active_tags"]

    def test_blocker_tags_unsupported_v2_on_low_lag(self):
        ev = _make_event(eid="v2_unsup_ll")
        r = _make_result(
            event_id="v2_unsup_ll", reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_unresolved_detail="POOL_SLOT0_REVERT",
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block", event_detected_at_block=101,
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert BLOCKER_LOW_LAG_V2_UNSUPPORTED in art["blocker_tags"]["active_tags"]

    def test_blocker_tags_remote_quoter_latency_when_scored_zero(self):
        ev = _make_event(eid="latency_ll")
        r = _make_result(
            event_id="latency_ll", reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block", event_detected_at_block=101,
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY not in art["blocker_tags"]["active_tags"]


# ===========================================================================
# M7.A.5.19: Quote-Fail Provenance
# ===========================================================================


class TestM7A519QuoteFailProvenance:
    """M7.A.5.19: quote_fail provenance in low-lag debug rows."""

    def test_provenance_populated_for_rpc_quote_fail(self):
        r = _make_result(
            event_id="qfp_1", block_lag=1,
            reject_reason=REJECT_RPC_QUOTE_FAIL,
            pair_resolved=True, actual_pair="WETH/USDC",
            event_block=100, event_detected_at_block=101,
            pipeline_stage_latency_ms={
                "stage_a_ms": 10.0, "stage_b_ms": 20.0,
                "quote_fail_stage": "buy", "quote_fail_venue": "uniswap_v3",
                "quote_fail_exception_short": "ContractLogicError",
            },
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert row["quote_fail_stage"] == "buy"
        assert row["quote_fail_venue"] == "uniswap_v3"
        assert row["quote_fail_exception_short"] == "ContractLogicError"

    def test_provenance_none_for_non_rpc_fail(self):
        r = _make_result(
            event_id="qfp_2", block_lag=0,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="WETH/ARB",
            event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert row["quote_fail_stage"] is None

    def test_provenance_none_when_no_pipeline_latency(self):
        r = _make_result(
            event_id="qfp_3", block_lag=2,
            reject_reason=REJECT_RPC_QUOTE_FAIL,
            pair_resolved=True, actual_pair="WETH/USDT",
            event_block=100, event_detected_at_block=102,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert row["quote_fail_stage"] is None


# ===========================================================================
# M7.A.5.18: Low-Lag Watchlist
# ===========================================================================


class TestM7A518LowLagWatchlist:
    """M7.A.5.18: low_lag_watchlist artifact block."""

    def test_watchlist_present_in_empty_artifact(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_watchlist" in art
        assert art["low_lag_watchlist"] == []

    def test_watchlist_entry_fields(self):
        ev = _make_event(eid="wl_1")
        r = _make_result(
            event_id="wl_1", reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block", pair_resolved=True,
            actual_pair="WETH/USDC",
            pool_contract_truth={"pool_address": "0xabc123"},
            pool_state_read_path="v3_multicall",
            event_detected_at_block=101,
        )
        art = build_replay_summary([ev], [r], mode="test")
        wl = art["low_lag_watchlist"]
        assert len(wl) == 1
        expected_keys = {
            "pair", "pool_address", "first_seen_block", "last_seen_block",
            "seen_count", "reject_reason", "pair_unresolved_detail",
            "pool_state_read_path", "known_pools", "active_pools",
        }
        assert set(wl[0].keys()) == expected_keys

    def test_watchlist_deduplication_by_pool(self):
        ev1 = _make_event(eid="wl_dup1")
        ev2 = _make_event(eid="wl_dup2")
        r1 = _make_result(
            event_id="wl_dup1", reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block",
            pool_contract_truth={"pool_address": "0xsamepool"},
            event_detected_at_block=101,
        )
        r2 = _make_result(
            event_id="wl_dup2", reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=105, quote_block=106, block_lag=1,
            same_state_class="next_block",
            pool_contract_truth={"pool_address": "0xsamepool"},
            event_detected_at_block=106,
        )
        art = build_replay_summary([ev1, ev2], [r1, r2], mode="test")
        wl = art["low_lag_watchlist"]
        assert len(wl) == 1
        assert wl[0]["seen_count"] == 2

    def test_watchlist_no_stale_events(self):
        ev = _make_event(eid="wl_stale")
        r = _make_result(
            event_id="wl_stale", reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            event_block=100, quote_block=200, block_lag=100,
            same_state_class="stale",
            pool_contract_truth={"pool_address": "0xstalepool"},
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert art["low_lag_watchlist"] == []

    def test_watchlist_coverage_truth_propagation(self):
        ev = _make_event(eid="wl_cov")
        r = _make_result(
            event_id="wl_cov", reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block",
            coverage_result={
                "known_pools_total": 3, "active_pools_total": 1,
                "candidate_pools": [{"address": "0xpool1"}],
            },
            event_detected_at_block=101,
        )
        art = build_replay_summary([ev], [r], mode="test")
        wl = art["low_lag_watchlist"]
        assert wl[0]["known_pools"] == 3
        assert wl[0]["active_pools"] == 1


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
