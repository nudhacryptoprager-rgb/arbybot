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
            "quote_size_truth": {"econ_rpc_quote_attempts": 10, "econ_gate_attempts": 10},
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
            "quote_size_truth": {
                "econ_rpc_quote_attempts": 5,
                "econ_gate_attempts": 362,
            },
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
    # Patch 3: freshness gate now additively surfaces MISSING blockers when
    # artifacts lack timestamps. Use membership instead of exact equality.
    assert "UPSTREAM_M8_2_NOT_READY" in report["upstream_blockers"]
    assert "UPSTREAM_M8_3_NOT_READY" in report["upstream_blockers"]
    assert "SUBGRAPH_READY_LOW" in report["m8_2_upstream"]["blockers"]
    assert report["m9_goal_status"] == "NOT_EVALUATED"


def test_build_acceptance_report_freshness_gate_stale_blocks():
    """Patch 3: stale cross-artifact timestamps -> freshness BLOCKED +
    goal_status BLOCKED with explicit freshness blockers surfaced."""
    from datetime import datetime, timedelta, timezone

    # Fresh reference clock; all artifacts older than their thresholds.
    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
    stale_shadow = (now - timedelta(hours=48)).isoformat().replace("+00:00", "Z")
    stale_bridge = (now - timedelta(hours=8)).isoformat().replace("+00:00", "Z")
    stale_m8_3 = (now - timedelta(hours=8)).isoformat().replace("+00:00", "Z")
    report = build_acceptance_report(
        sniper={
            "status": "ACTIVE",
            "generated_at_utc": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            "metrics": {},
            "recent_events": [],
        },
        anchor={"metrics": {}},
        expansion={"metrics": {}},
        bridge={
            "generated_at_utc": stale_bridge,
            "active_routes": [],
            "bridge_source_metrics": {
                "graph_ready_from_m8": 1,
                "sniper_generated_at_utc": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            },
        },
        shadow={
            "generated_at_utc": stale_shadow,
            "cycles_found": 10,
            "cycles_quoteable": 0,
            "cycles_positive_gross": 0,
        },
        rca=None,
        m8_2_report={"goal_status": "REACHED", "handoff_ready": True},
    )
    fg = report["freshness_gate"]
    assert fg["freshness_status"] == "BLOCKED"
    assert "SHADOW_STALE" in fg["blockers"]
    assert "BRIDGE_STALE" in fg["blockers"]
    assert report["goal_status"] == "BLOCKED"
    # Freshness blockers must be surfaced into upstream_blockers.
    for b in fg["blockers"]:
        assert b in report["upstream_blockers"]


def test_build_acceptance_report_freshness_gate_mixed_window_blocks():
    """Patch 3: mixed runtime windows (timestamps far apart) -> BLOCKED."""
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": []},
        anchor={"metrics": {}},
        expansion={"metrics": {}},
        bridge={
            "generated_at_utc": "2026-07-09T11:00:00Z",
            "active_routes": [],
            "bridge_source_metrics": {
                "graph_ready_from_m8": 1,
                "sniper_generated_at_utc": "2026-07-09T11:00:00Z",
            },
        },
        shadow={
            "generated_at_utc": "2026-07-09T11:05:00Z",
            "cycles_found": 10,
            "cycles_quoteable": 10,
            "cycles_positive_gross": 0,
        },
        rca=None,
        m8_2_report={
            "goal_status": "REACHED",
            "handoff_ready": True,
            "generated_at_utc": "2026-07-08T10:00:00Z",  # >30min off
        },
    )
    fg = report["freshness_gate"]
    assert fg["freshness_status"] == "BLOCKED"
    assert "MIXED_RUNTIME_WINDOW" in fg["blockers"]


def test_build_acceptance_report_freshness_gate_aligned_passes(monkeypatch, tmp_path):
    """Patch 3: aligned fresh timestamps -> freshness PASS, no freshness blockers."""
    from datetime import datetime, timezone

    aligned = "2026-07-09T11:49:48Z"
    # Pin "now" to 1 min after the artifact timestamps so all are FRESH.
    now_fixed = datetime(2026, 7, 9, 11, 50, 48, tzinfo=timezone.utc)
    import scripts.m9_lane_acceptance_report as mod

    monkeypatch.setattr(mod, "_now_utc", lambda: now_fixed)

    # Use a fresh inline M8.3 registry so the default rolling registry (which
    # is days old relative to ``now_fixed``) does not force STALE.
    fresh_registry = tmp_path / "registry.json"
    fresh_registry.write_text(
        '{"schema_version":"m8_3_token_metadata_registry_v2","tokens":{},'
        '"route_coverage":{"cycle_participating_routes":{"legs_total":10,'
        '"economics_grade_known_rate":0.98}},"generated_at_utc":"'
        + aligned
        + '"}',
        encoding="utf-8",
    )

    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "generated_at_utc": aligned, "metrics": {}, "recent_events": []},
        anchor={"metrics": {}},
        expansion={"metrics": {}},
        bridge={
            "generated_at_utc": aligned,
            "active_routes": [],
            "bridge_source_metrics": {
                "graph_ready_from_m8": 1,
                "sniper_generated_at_utc": aligned,
            },
        },
        shadow={
            "generated_at_utc": aligned,
            "cycles_found": 10,
            "cycles_quoteable": 10,
            "cycles_positive_gross": 0,
        },
        rca=None,
        m8_2_report={"goal_status": "REACHED", "handoff_ready": True, "generated_at_utc": aligned},
        capacity_metrics={"generated_at_utc": aligned},
        m8_3_registry_path=str(fresh_registry),
    )
    fg = report["freshness_gate"]
    assert fg["freshness_status"] == "PASS"
    assert fg["blockers"] == []
    # No freshness-derived blockers should leak into upstream_blockers.
    assert not any(
        b.endswith("_STALE")
        or b == "MIXED_RUNTIME_WINDOW"
        or b.endswith("_TIMESTAMP_MISSING")
        for b in report["upstream_blockers"]
    )


def test_build_acceptance_report_freshness_gate_missing_timestamp_blocks(tmp_path):
    """Patch 3: missing timestamps must NOT crash; must produce explicit
    MISSING blockers instead of silently passing."""
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        '{"schema_version":"m8_3_token_metadata_registry_v2","tokens":{},'
        '"route_coverage":{"cycle_participating_routes":{"legs_total":10,'
        '"economics_grade_known_rate":0.98}},"generated_at_utc":"2026-07-09T11:49:48Z"}',
        encoding="utf-8",
    )
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": []},  # no ts
        anchor={"metrics": {}},
        expansion={"metrics": {}},
        bridge={"active_routes": [], "bridge_source_metrics": {"graph_ready_from_m8": 1}},  # no ts
        shadow={"cycles_found": 10, "cycles_quoteable": 10, "cycles_positive_gross": 0},  # no ts
        rca=None,
        m8_2_report={"goal_status": "REACHED", "handoff_ready": True},  # no ts
        m8_3_registry_path=str(registry_path),
    )
    fg = report["freshness_gate"]
    assert fg["freshness_status"] == "BLOCKED"
    assert any(b.endswith("_TIMESTAMP_MISSING") for b in fg["blockers"])
    assert report["goal_status"] == "BLOCKED"


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


def test_lane_report_skip_shadow_upstream_bundle_validated(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    aligned = "2026-07-23T20:10:00Z"
    now_fixed = datetime(2026, 7, 23, 20, 11, 0, tzinfo=timezone.utc)
    import scripts.m9_lane_acceptance_report as mod

    monkeypatch.setattr(mod, "_now_utc", lambda: now_fixed)

    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        '{"schema_version":"m8_3_token_metadata_registry_v2","tokens":{},'
        '"route_coverage":{"cycle_participating_routes":{"legs_total":10,'
        '"economics_grade_known_rate":0.98}},"generated_at_utc":"'
        + aligned
        + '"}',
        encoding="utf-8",
    )
    report = build_acceptance_report(
        sniper={
            "status": "ACTIVE",
            "generated_at_utc": aligned,
            "metrics": {},
            "recent_events": [{}],
        },
        anchor={
            "generated_at_utc": aligned,
            "metrics": {"stable_anchor_passes_total": 100},
        },
        expansion={
            "generated_at_utc": aligned,
            "summary": {"routes_admitted_count": 50, "handoff_ready": True},
            "metrics": {"routes_admitted": 50},
        },
        bridge={
            "generated_at_utc": aligned,
            "active_routes": [{"dex_id": "uniswap_v3"}],
            "bridge_source_metrics": {
                "graph_ready_from_m8": 5,
                "graph_ready_from_expansion": 10,
                "graph_ready_total": 15,
                "sniper_generated_at_utc": aligned,
            },
        },
        shadow=None,
        rca=None,
        m8_2_report={
            "generated_at_utc": aligned,
            "goal_status": "REACHED",
            "handoff_ready": True,
        },
        m8_3_registry_path=str(registry_path),
        skip_shadow=True,
    )
    assert report["skip_shadow"] is True
    assert report["m9_shadow_acceptance_status"] == "SKIPPED"
    assert report["upstream_bundle_status"] == "UPSTREAM_BUNDLE_VALIDATED"
    assert report["goal_status"] == "UPSTREAM_BUNDLE_VALIDATED"
    assert "SHADOW_STALE" not in report["blockers"]


def test_lane_report_shadow_accepted_goal_reached(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    from monitoring.sniper_artifacts import make_sniper_artifact

    aligned = "2026-07-23T20:10:00Z"
    now_fixed = datetime(2026, 7, 23, 20, 11, 0, tzinfo=timezone.utc)
    import scripts.m9_lane_acceptance_report as mod

    monkeypatch.setattr(mod, "_now_utc", lambda: now_fixed)

    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        '{"schema_version":"m8_3_token_metadata_registry_v2","tokens":{},'
        '"route_coverage":{"cycle_participating_routes":{"legs_total":10,'
        '"economics_grade_known_rate":0.98}},"generated_at_utc":"'
        + aligned
        + '"}',
        encoding="utf-8",
    )
    sniper = make_sniper_artifact(
        status="ACTIVE",
        recent_events=[{"pool": "0x" + "1" * 40}, {"pool": "0x" + "2" * 40}],
        metrics={"pool_creation_events_seen": 5},
    )
    sniper["generated_at_utc"] = aligned
    sniper["m8_health"] = {"goal_status": "REACHED"}
    report = build_acceptance_report(
        sniper=sniper,
        anchor={"generated_at_utc": aligned, "metrics": {"stable_anchor_passes_total": 100}},
        expansion={
            "generated_at_utc": aligned,
            "summary": {"routes_admitted_count": 50, "handoff_ready": True},
            "metrics": {"routes_admitted": 50},
        },
        bridge={
            "generated_at_utc": aligned,
            "active_routes": [{"dex_id": "uniswap_v3", "cross_mechanic": True}],
            "bridge_source_metrics": {
                "graph_ready_from_m8": 5,
                "graph_ready_from_expansion": 10,
                "graph_ready_total": 15,
                "sniper_generated_at_utc": aligned,
                "productive_curve_quoteable_routes": 2,
                "missing_distinct_pricing_lanes": [],
                "depth_known_rate": 0.9,
                "m8_3_authority_applied": True,
            },
        },
        shadow={
            "generated_at_utc": aligned,
            "cycles_found": 10,
            "cycles_quoteable": 10,
            "cycles_positive_gross": 3,
            "cycles_with_m8_pool": 5,
            "cross_mechanic_cycles_found": 4,
            "cross_mechanic_cycles_quoteable": 2,
            "qsr": 0.5,
        },
        rca=None,
        m8_2_report={
            "generated_at_utc": aligned,
            "goal_status": "REACHED",
            "handoff_ready": True,
        },
        m8_3_registry_path=str(registry_path),
        capacity_metrics={"generated_at_utc": aligned},
        skip_shadow=False,
    )
    assert report["m9_shadow_acceptance_status"] == "M9_SHADOW_ACCEPTED"
    assert report["m9_goal_status"] == "REACHED"
    assert report["goal_status"] == "REACHED"
    assert report["blockers"] == []


def test_lane_report_quote_validation_failure_blocks_release(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    aligned = "2026-07-23T20:10:00Z"
    now_fixed = datetime(2026, 7, 23, 20, 11, 0, tzinfo=timezone.utc)
    import scripts.m9_lane_acceptance_report as mod

    monkeypatch.setattr(mod, "_now_utc", lambda: now_fixed)

    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        '{"schema_version":"m8_3_token_metadata_registry_v2","tokens":{},'
        '"route_coverage":{"cycle_participating_routes":{"legs_total":10,'
        '"economics_grade_known_rate":0.98}},"generated_at_utc":"'
        + aligned
        + '"}',
        encoding="utf-8",
    )
    report = build_acceptance_report(
        sniper={
            "status": "ACTIVE",
            "generated_at_utc": aligned,
            "metrics": {},
            "recent_events": [{}],
        },
        anchor={"generated_at_utc": aligned, "metrics": {"stable_anchor_passes_total": 100}},
        expansion={
            "generated_at_utc": aligned,
            "summary": {"routes_admitted_count": 50, "handoff_ready": True},
            "metrics": {"routes_admitted": 50},
        },
        bridge={
            "generated_at_utc": aligned,
            "active_routes": [{"dex_id": "uniswap_v3"}],
            "bridge_source_metrics": {
                "graph_ready_from_m8": 5,
                "graph_ready_from_expansion": 10,
                "graph_ready_total": 15,
                "sniper_generated_at_utc": aligned,
            },
        },
        shadow={
            "generated_at_utc": aligned,
            "cycles_found": 0,
            "cycles_quoteable": 0,
            "cycles_positive_gross": 0,
        },
        rca=None,
        m8_2_report={
            "generated_at_utc": aligned,
            "goal_status": "REACHED",
            "handoff_ready": True,
        },
        m8_3_registry_path=str(registry_path),
        skip_shadow=False,
    )
    assert "UPSTREAM_OK_BUT_NO_CYCLES" in report["m9_quote_validation_blockers"]
    assert "UPSTREAM_OK_BUT_NO_CYCLES" in report["blockers"]
    assert report["m9_shadow_acceptance_status"] == "BLOCKED"
    assert report["goal_status"] == "BLOCKED"


def test_m9_blockers_admission_before_quote_not_market_negative():
    from scripts.m9_lane_acceptance_report import _m9_economics_blockers

    blockers = _m9_economics_blockers(
        shadow={
            "qsr": 1.0,
            "qsr_econ": None,
            "economics_blocker_class": "DEPTH_ADMISSION_BLOCKED_BEFORE_ECONOMIC_QUOTE",
            "quote_size_truth": {
                "econ_gate_attempts": 2441,
                "econ_rpc_quote_attempts": 0,
            },
            "scan_scope": {
                "shadow_lane_mode": "broad_graph_diagnostic",
                "capacity_valid_cycle_ids": ["cap_a", "cap_b"],
            },
        },
        rca=None,
        shadow_cycles_found=2441,
        shadow_cycles_quoteable=0,
        shadow_cycles_with_m8=0,
        bridge={"fresh_long_tail_quote_ready_tokens": 0},
        capacity_metrics={"cycles_at_production_floor": 2, "cycles_total": 10},
    )
    assert "CODE_OR_POLICY_ADMISSION_BLOCKED_BEFORE_ECONOMIC_QUOTE" in blockers
    assert "NO_POSITIVE_GROSS" not in blockers
    assert "BROAD_GRAPH_DIAGNOSTIC_NOT_LONG_TAIL_ECONOMICS" in blockers
    assert "CAPACITY_VALID_CYCLES_NOT_QUOTED_IN_SHADOW" in blockers
