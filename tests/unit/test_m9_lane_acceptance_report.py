"""Unit tests for m9_lane_acceptance_report script."""
from __future__ import annotations

from scripts.m9_lane_acceptance_report import build_acceptance_report


def test_build_acceptance_report_blockers_when_m8_not_ready():
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {"snipe_candidates_total": 11}, "recent_events": [{}] * 11},
        anchor={"status": "PASS", "metrics": {"stable_anchor_passes_total": 100, "qsr": 1.0}},
        expansion={"metrics": {"routes_admitted": 50, "multi_venue_tokens": 3}},
        bridge={
            "active_routes": [{"dex_id": "balancer_vault", "cross_mechanic": True}],
            "bridge_source_metrics": {
                "m8_new_pools_input": 11,
                "token_verified_count": 0,
                "graph_ready_from_m8": 0,
                "graph_ready_total": 100,
                "m8_funnel_reject_histogram": {"TOKEN_SYMBOL_MISSING": 11},
            },
        },
        shadow={
            "cycles_found": 100,
            "cycles_quoteable": 10,
            "cycles_positive_gross": 0,
            "cross_mechanic_cycles": 0,
            "qsr": 0.1,
            "active_economics_profile": "production_conservative",
        },
        rca=None,
    )
    assert "M8_DIRECT_INGESTION_NOT_READY" in report["bridge_upstream_warnings"]
    assert "NO_POSITIVE_GROSS" in report["m9_blockers"]
    assert "M8_DIRECT_INGESTION_NOT_READY" not in report["m9_blockers"]
    assert report["goal_status"] == "BLOCKED"
    assert report["funnel_layers"][1]["m8_funnel_reject_histogram"]["TOKEN_SYMBOL_MISSING"] == 11


def test_build_acceptance_report_diagnostic_no_positive_gross_blocker():
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": [{}] * 11},
        anchor={"status": "PASS", "metrics": {"stable_anchor_passes_total": 100, "qsr": 1.0}},
        expansion={"metrics": {"routes_admitted": 50, "multi_venue_tokens": 3, "handoff_ready": True}},
        bridge={
            "active_routes": [{"dex_id": "uniswap_v3"}],
            "bridge_source_metrics": {
                "graph_ready_from_m8": 10,
                "graph_ready_from_expansion": 10,
            },
        },
        shadow={
            "cycles_found": 100,
            "cycles_quoteable": 4,
            "cycles_positive_gross": 0,
            "diagnostic_lane_status": "DIAGNOSTIC_NO_POSITIVE_GROSS",
            "qsr": 0.5,
        },
        rca=None,
        m8_2_report={"handoff_ready": True, "goal_status": "REACHED"},
    )
    assert "DIAGNOSTIC_NO_POSITIVE_GROSS" in report["m9_quote_validation_blockers"]
    assert "NO_POSITIVE_GROSS" not in report["m9_quote_validation_blockers"]


def test_build_acceptance_report_m8_2_summary_from_artifact_summary():
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": []},
        anchor={"metrics": {}},
        expansion={
            "summary": {
                "routes_admitted_count": 595,
                "connector_routes_count": 59,
                "subgraph_ready_tokens": 1,
                "verified_second_pool_count": 7,
                "multi_venue_tokens": 3,
                "hint_tokens_matched": 283,
                "external_hints_enabled": True,
                "m8_tokens_in": 272,
            }
        },
        bridge={"active_routes": [], "bridge_source_metrics": {}},
        shadow=None,
        rca=None,
    )
    layer = next(
        x for x in report["funnel_layers"] if x["layer"] == "M8_2_expansion"
    )
    assert layer["routes_admitted"] == 595
    assert layer["connector_routes_count"] == 59
    assert layer["subgraph_ready_tokens"] == 1
    assert layer["verified_second_pool_count"] == 7
    assert layer["external_hints_enabled"] is True


def test_build_acceptance_report_quote_blockers():
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": [{}]},
        anchor={"metrics": {}},
        expansion={"metrics": {}},
        bridge={
            "active_routes": [],
            "bridge_source_metrics": {
                "graph_ready_from_m8": 8,
                "m8_stale": True,
                "sniper_age_seconds": 7200,
                "routes_rejected_not_m8_derived": 12,
            },
        },
        shadow={
            "cycles_found": 362,
            "cycles_quoteable": 0,
            "cycles_positive_gross": 0,
            "qsr": 0.0,
            "qsr_econ": 0.0,
            "depth_aware_known_rate": 0.0,
            "cross_mechanic_cycles": 106,
            "cross_mechanic_cycles_found": 106,
            "cross_mechanic_cycles_quoteable": 0,
            "cycles_with_m8_pool": 0,
            "phantom_quote_diagnostics": {"phantom_count": 10},
            "cycle_reject_histogram": {"OVERSIZED_VS_DEPTH": 261},
        },
        rca={"by_reject_reason": {"QUOTE_REVERT": 50}},
    )
    assert "NO_QUOTEABLE_CYCLES" in report["m9_blockers"]
    assert "QSR_ZERO" in report["m9_blockers"]
    assert "QSR_ECON_ZERO" in report["m9_blockers"]
    assert "DEPTH_UNKNOWN" in report["m9_blockers"]
    assert "QUOTE_REVERT" in report["m9_blockers"]
    assert "CYCLES_WITH_M8_POOL_ZERO" in report["m9_blockers"]
    assert "PHANTOM_QUOTE_PRESENT" in report["m9_blockers"]
    assert "NO_CROSS_MECHANIC_CYCLES_QUOTEABLE" in report["m9_blockers"]
    assert "M8_ARTIFACT_STALE" in report["bridge_upstream_warnings"]
    assert "M8_EXPLORATION_ROUTES_PARTITIONED" not in report["m9_blockers"]


def test_m9_report_upstream_m8_2_not_ready(tmp_path):
    m8_2 = {
        "goal_status": "BLOCKED",
        "blockers": ["SUBGRAPH_READY_LOW"],
        "metrics": {"subgraph_ready_tokens": 1},
    }
    bad_registry = tmp_path / "m8_3_blocked.json"
    bad_registry.write_text(
        '{"schema_version":"m8_3_token_metadata_registry_v2","tokens":{},'
        '"route_coverage":{"cycle_participating_routes":{"legs_total":10,'
        '"economics_grade_known_rate":0.5}}}',
        encoding="utf-8",
    )
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": []},
        anchor=None,
        expansion={"summary": {"subgraph_ready_tokens": 1}},
        bridge={
            "active_routes": [],
            "bridge_source_metrics": {
                "productive_curve_quoteable_routes": 1,
                "missing_distinct_pricing_lanes": [],
                "depth_known_rate": 0.9,
                "routes_decimals_unknown": 0,
            },
        },
        shadow=None,
        rca=None,
        m8_2_report=m8_2,
        m8_3_registry_path=str(bad_registry),
    )
    assert report["upstream_blockers"] == [
        "UPSTREAM_M8_2_NOT_READY",
        "UPSTREAM_M8_3_NOT_READY",
    ]
    assert "SUBGRAPH_READY_LOW" in report["m8_2_upstream"]["blockers"]
    assert report["m9_goal_status"] == "NOT_EVALUATED"


def test_build_acceptance_report_quote_liveness_qsr_liveness_consistency():
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": [{}]},
        anchor={"metrics": {}},
        expansion={"metrics": {}},
        bridge={"active_routes": [], "bridge_source_metrics": {"graph_ready_from_m8": 1}},
        shadow={
            "cycles_found": 368,
            "cycles_quoteable": 368,
            "cycles_positive_gross": 0,
            "qsr": 1.0,
            "qsr_liveness": 0.0,
            "qsr_econ": 0.0,
            "cycles_quoteable_by_length": {"2": 8},
            "discovery_cycles_by_length": {"2": 20, "3": 60, "4": 48},
        },
        rca=None,
        m8_2_report={
            "goal_status": "REACHED",
            "handoff_ready": True,
            "handoff_lane": "graph_topology",
        },
    )
    qlm = report["quote_liveness_metrics"]
    assert qlm["quote_liveness_status"] == "PROVEN"
    assert qlm["qsr_liveness_consistency"]["consistent"] is False
    assert qlm["economics_status"] == "NOT_PROVEN"
    shadow_layer = next(x for x in report["funnel_layers"] if x["layer"] == "M9_shadow")
    assert shadow_layer["qsr_liveness"] == 0.0


def test_build_acceptance_report_value_ratio_rca_blocker():
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": [{}]},
        anchor={"metrics": {}},
        expansion={"metrics": {}},
        bridge={"active_routes": [], "bridge_source_metrics": {"graph_ready_from_m8": 1}},
        shadow={
            "cycles_found": 455,
            "cycles_quoteable": 97,
            "cycles_positive_gross": 0,
            "qsr": 0.92,
            "qsr_econ": 0.92,
            "economics_metrics": {
                "toxic_route_rate": 1.0,
                "toxic_route_denominator": 97,
            },
            "discovery_cycles_by_length": {"2": 30, "3": 96, "4": 568},
            "cycles_quoteable_by_length": {"2": 20, "3": 77, "4": 0},
        },
        rca={"summary": {"stable_value_ratio_outlier_legs": 10}},
        m8_2_report={"goal_status": "REACHED", "handoff_ready": True},
    )
    assert "VALUE_RATIO_RCA_NOT_CLEAN" in report["m9_blockers"]
    assert "FOUR_LEG_PRODUCTIVE_COVERAGE_ZERO" in report["m9_blockers"]


def test_build_acceptance_report_operator_verdict():
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": [{}]},
        anchor={"metrics": {}},
        expansion={"metrics": {}},
        bridge={"active_routes": [], "bridge_source_metrics": {"graph_ready_from_m8": 1}},
        shadow={
            "cycles_found": 929,
            "cycles_quoteable": 851,
            "cycles_positive_gross": 0,
            "qsr": 1.0,
            "qsr_liveness": 0.0,
            "qsr_econ": 0.0,
            "cycles_quoteable_by_length": {"2": 10, "3": 9, "4": 0},
            "quote_lane_rca": {
                "amount_continuity_violations": 2,
                "stable_value_ratio_outlier_legs": 1,
            },
        },
        rca={"economics_status": "NOT_PROVEN"},
        m8_2_report={
            "goal_status": "REACHED",
            "handoff_ready": True,
            "handoff_lane": "graph_topology",
        },
    )
    ov = report["operator_verdict"]
    assert ov["M8_2_HANDOFF"] == "REACHED"
    assert ov["M9_QUOTE_LIVENESS"] == "M9_QUOTE_LIVENESS_PROVEN"
    assert ov["M9_ECONOMICS"] == "M9_ECONOMICS_BLOCKED_BY_AMOUNT_CONTINUITY_AND_VALUE_RATIO_RCA"
    assert ov["M9_FRESH_M8_PARTICIPATION"] == "FRESH_M8_PARTICIPATION_NOT_PROVEN"
    assert "fresh_m8_participation" in ov["forbidden_claims"]
    assert ov["economics_claim_allowed"] is False
    assert "positive_gross" in ov["forbidden_claims"]
    assert report["schema_version"] == "m9_lane_acceptance_report.6"


def test_m8_3_upstream_blocked_when_registry_not_ready(tmp_path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        '{"schema_version":"m8_3_token_metadata_registry_v1","tokens":{},'
        '"route_coverage":{"cycle_participating_routes":{"legs_total":10,'
        '"economics_grade_known_rate":0.5}}}',
        encoding="utf-8",
    )
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": []},
        anchor={"metrics": {}},
        expansion={"metrics": {}},
        bridge={
            "active_routes": [],
            "bridge_source_metrics": {
                "graph_ready_from_m8": 1,
                "m8_3_registry_applied": {"applied_legs": 10},
            },
        },
        shadow=None,
        rca=None,
        m8_2_report={"goal_status": "REACHED", "handoff_ready": True},
        m8_3_registry_path=str(registry_path),
    )
    assert "UPSTREAM_M8_3_NOT_READY" in report["upstream_blockers"]
    assert "DECIMALS_ENRICHMENT_REQUIRED" not in report["m9_blockers"]


def test_lane_report_flags_bridge_not_consuming_expansion():
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": []},
        anchor={"metrics": {}},
        expansion={"metrics": {}},
        bridge={
            "active_routes": [{"route_id": "r1"}],
            "bridge_source_metrics": {"graph_ready_from_expansion": 0},
        },
        shadow=None,
        rca=None,
        m8_2_report={
            "goal_status": "REACHED",
            "handoff_ready": True,
            "handoff_lane": "mirror_2leg",
        },
    )
    assert "M9_BRIDGE_NOT_CONSUMING_M8_2_HANDOFF_EXPANSION" in report["upstream_blockers"]


def test_lane_report_shadow_bridge_stale_or_mismatch():
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": []},
        anchor={"metrics": {}},
        expansion={"metrics": {}},
        bridge={
            "generated_at_utc": "2026-06-22T10:00:00Z",
            "active_routes": [{"route_id": "r1"}] * 70,
            "bridge_source_metrics": {"graph_ready_from_m8": 1},
        },
        shadow={
            "generated_at_utc": "2026-06-16T10:00:00Z",
            "cycles_found": 100,
            "cycles_quoteable": 0,
            "bridge_active_routes_at_run": 70,
        },
        rca=None,
        m8_2_report={"goal_status": "REACHED", "handoff_ready": True},
    )
    assert "SHADOW_BRIDGE_STALE_OR_MISMATCH" in report["m9_blockers"]
