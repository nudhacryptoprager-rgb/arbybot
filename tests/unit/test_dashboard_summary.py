"""Unit tests for monitoring/dashboard_server.build_summary_payload (soak17).

Reviewer contract: /api/summary primary view must come from the *current*
supervisor session only — derived from rollup.session.session_*_total
when available, or from delta vs reviewer_soak_baseline_latest.json.
Lifetime *_total counters belong in a separate ``historical_cumulative``
block and MUST NOT pollute the primary funnel.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from monitoring.dashboard_server import (
    DASHBOARD_HTML,
    build_m7_current_payload,
    build_summary_payload,
)


NOW = datetime(2026, 4, 27, 8, 0, 0, tzinfo=timezone.utc)


def _make_rollup(
    *,
    session_id: str = "sess_a",
    last_updated_offset_s: int = 5,
    events_total: int = 1000,
    submit_ready_total: int = 7,
    sim_attempted_total: int = 50,
    sim_passed_total: int = 20,
    session_events: int = 30,
    session_fast_path_scored: int = 12,
):
    last_updated = (NOW - timedelta(seconds=last_updated_offset_s)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return {
        "chain": "base",
        "last_updated": last_updated,
        "simulation_backend": "rpc_fork",
        "events_seen_total": events_total,
        "fast_score_attempted_total": events_total,
        "fast_path_scored_total": 200,
        "fast_path_positive_total": 8,
        "route_viable_total": 8,
        "profit_guard_passed_total": 8,
        "sim_attempted_total": sim_attempted_total,
        "sim_passed_total": sim_passed_total,
        "submit_ready_total": submit_ready_total,
        "roundtrip_attempted_total": 5,
        "roundtrip_success_total": 5,
        "roundtrip_profitable_total": 0,
        "session": {
            "session_id": session_id,
            "session_started_at": "2026-04-27T07:55:00Z",
            "session_events_seen_total": session_events,
            "session_fast_path_scored_total": session_fast_path_scored,
            "session_ws_recv_error_total": 1,
            "session_ws_reconnect_total": 1,
            "last_exit_reason": "ok",
        },
    }


def _make_baseline(
    *,
    session_id: str = "sess_a",
    events_total: int = 950,
    submit_ready_total: int = 7,  # equal to current → delta=0
    sim_attempted_total: int = 45,
    sim_passed_total: int = 18,
):
    return {
        "events_seen_total": events_total,
        "fast_score_attempted_total": events_total,
        "fast_path_scored_total": 190,
        "fast_path_positive_total": 7,
        "route_viable_total": 7,
        "profit_guard_passed_total": 7,
        "sim_attempted_total": sim_attempted_total,
        "sim_passed_total": sim_passed_total,
        "submit_ready_total": submit_ready_total,
        "roundtrip_attempted_total": 5,
        "roundtrip_success_total": 5,
        "roundtrip_profitable_total": 0,
        "session": {"session_id": session_id},
    }


def test_summary_has_two_block_contract():
    payload = build_summary_payload(
        rollup=_make_rollup(),
        hot={},
        orderflow={},
        baseline=_make_baseline(),
        profile="production",
        now_utc=NOW,
    )
    assert payload["schema_version"] == "summary_v2"
    assert "current_scan" in payload
    assert "historical_cumulative" in payload
    assert "gate_funnel" in payload["current_scan"]


def test_current_funnel_uses_session_not_lifetime_for_events():
    rollup = _make_rollup(events_total=1000, session_events=30)
    baseline = _make_baseline(events_total=950)
    payload = build_summary_payload(
        rollup=rollup,
        hot={},
        orderflow={},
        baseline=baseline,
        profile="production",
        now_utc=NOW,
    )
    cs_funnel = payload["current_scan"]["gate_funnel"]
    # session_events_seen_total takes precedence (30, not 1000 nor delta 50)
    assert cs_funnel["events_seen"] == 30
    # historical block still exposes the raw lifetime total
    assert payload["historical_cumulative"]["events_seen_total"] == 1000


def test_current_submit_ready_is_baseline_delta_not_lifetime():
    """submit_ready has no session_*_total counterpart — must be a delta."""
    rollup = _make_rollup(submit_ready_total=7)
    baseline = _make_baseline(submit_ready_total=7)  # delta = 0
    payload = build_summary_payload(
        rollup=rollup,
        hot={},
        orderflow={},
        baseline=baseline,
        profile="production",
        now_utc=NOW,
    )
    cs_funnel = payload["current_scan"]["gate_funnel"]
    # CRITICAL: must be 0 (delta), not 7 (lifetime). This is the exact
    # bug the reviewer flagged: historical submit_ready=1 was bleeding
    # into the "current" funnel.
    assert cs_funnel["submit_ready"] == 0
    # But historical block still shows 7
    assert payload["historical_cumulative"]["submit_ready_total"] == 7


def test_current_sim_passed_is_delta():
    rollup = _make_rollup(sim_passed_total=20)
    baseline = _make_baseline(sim_passed_total=18)
    payload = build_summary_payload(
        rollup=rollup,
        hot={},
        orderflow={},
        baseline=baseline,
        profile="production",
        now_utc=NOW,
    )
    assert payload["current_scan"]["gate_funnel"]["sim_passed"] == 2
    assert payload["historical_cumulative"]["sim_passed_total"] == 20


def test_freshness_marks_stale_when_age_exceeds_threshold():
    rollup = _make_rollup(last_updated_offset_s=300)  # 5 min old > 120s
    payload = build_summary_payload(
        rollup=rollup,
        hot={},
        orderflow={},
        baseline=_make_baseline(),
        profile="production",
        now_utc=NOW,
    )
    cs = payload["current_scan"]
    assert cs["is_fresh"] is False
    assert cs["staleness_reason"] is not None
    assert "STALE" in cs["staleness_reason"]
    assert cs["age_seconds"] >= 300


def test_freshness_marks_fresh_when_recent():
    rollup = _make_rollup(last_updated_offset_s=5)
    payload = build_summary_payload(
        rollup=rollup,
        hot={},
        orderflow={},
        baseline=_make_baseline(),
        profile="production",
        now_utc=NOW,
    )
    cs = payload["current_scan"]
    assert cs["is_fresh"] is True
    assert cs["staleness_reason"] is None
    assert cs["age_seconds"] <= 10


def test_session_id_mismatch_baseline_flagged():
    rollup = _make_rollup(session_id="sess_NEW")
    baseline = _make_baseline(session_id="sess_OLD")
    payload = build_summary_payload(
        rollup=rollup,
        hot={},
        orderflow={},
        baseline=baseline,
        profile="production",
        now_utc=NOW,
    )
    cs = payload["current_scan"]
    assert cs["session_id"] == "sess_NEW"
    assert cs["baseline_session_id"] == "sess_OLD"
    assert cs["session_id_match_baseline"] is False


def test_session_id_match_baseline_true_when_equal():
    payload = build_summary_payload(
        rollup=_make_rollup(session_id="sess_a"),
        hot={},
        orderflow={},
        baseline=_make_baseline(session_id="sess_a"),
        profile="production",
        now_utc=NOW,
    )
    assert payload["current_scan"]["session_id_match_baseline"] is True


def test_no_baseline_yields_delta_equal_to_current_total():
    """When baseline is missing, deltas degrade to current totals — but
    the block separation MUST still hold (no leakage into 'session' fields)."""
    rollup = _make_rollup(submit_ready_total=7)
    payload = build_summary_payload(
        rollup=rollup,
        hot={},
        orderflow={},
        baseline=None,
        profile="production",
        now_utc=NOW,
    )
    cs_funnel = payload["current_scan"]["gate_funnel"]
    # Without baseline, delta = current_total - 0 = 7. Still flows through
    # the delta path, not from cumulative_total directly. This is the
    # acceptable degenerate case at first-ever supervisor start.
    assert cs_funnel["submit_ready"] == 7


def test_missing_last_updated_marks_stale():
    rollup = _make_rollup()
    rollup.pop("last_updated", None)
    payload = build_summary_payload(
        rollup=rollup,
        hot={},
        orderflow={},
        baseline=_make_baseline(),
        profile="production",
        now_utc=NOW,
    )
    cs = payload["current_scan"]
    assert cs["is_fresh"] is False
    assert cs["staleness_reason"] == "MISSING_LAST_UPDATED"


def test_profile_propagated_into_payload():
    payload = build_summary_payload(
        rollup=_make_rollup(),
        hot={},
        orderflow={},
        baseline=_make_baseline(),
        profile="discovery",
        now_utc=NOW,
    )
    assert payload["profile"] == "discovery"
    assert payload["current_scan"]["profile"] == "discovery"


def test_legacy_gate_funnel_marked_deprecated():
    """Backward-compat: legacy top-level gate_funnel still present but
    flagged so any old client knows to migrate."""
    payload = build_summary_payload(
        rollup=_make_rollup(),
        hot={},
        orderflow={},
        baseline=_make_baseline(),
        profile="production",
        now_utc=NOW,
    )
    assert payload["gate_funnel"].get("_deprecated") is True


def test_historical_block_contains_all_total_fields():
    payload = build_summary_payload(
        rollup=_make_rollup(),
        hot={},
        orderflow={},
        baseline=_make_baseline(),
        profile="production",
        now_utc=NOW,
    )
    hc = payload["historical_cumulative"]
    required = {
        "events_seen_total",
        "fast_path_scored_total",
        "sim_attempted_total",
        "sim_passed_total",
        "submit_ready_total",
        "roundtrip_attempted_total",
        "roundtrip_success_total",
        "roundtrip_profitable_total",
    }
    assert required.issubset(hc.keys())
    assert "roundtrip_profit_bps" in hc


# soak18 step 1: BASELINE_NOT_REFRESHED
def test_baseline_not_refreshed_marks_stale():
    """When the supervisor restarts and snapshots a baseline whose
    last_updated equals the current rollup, the lane has NOT yet
    written a fresh rollup. Primary view must mark stale even though
    age_seconds is below the freshness threshold."""
    rollup = _make_rollup(last_updated_offset_s=5)
    baseline = _make_baseline()
    baseline["last_updated"] = rollup["last_updated"]  # exact match
    payload = build_summary_payload(
        rollup=rollup, hot={}, orderflow={}, baseline=baseline,
        profile="production", now_utc=NOW,
    )
    cs = payload["current_scan"]
    assert cs["is_fresh"] is False
    assert cs["staleness_reason"] == "BASELINE_NOT_REFRESHED"


def test_baseline_refreshed_after_first_write_marks_fresh():
    """As soon as the lane writes one rollup past baseline, the primary
    view becomes fresh."""
    rollup = _make_rollup(last_updated_offset_s=5)
    baseline = _make_baseline()
    # Baseline snapped 30s before current rollup.
    baseline["last_updated"] = (
        NOW - timedelta(seconds=35)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = build_summary_payload(
        rollup=rollup, hot={}, orderflow={}, baseline=baseline,
        profile="production", now_utc=NOW,
    )
    cs = payload["current_scan"]
    assert cs["is_fresh"] is True
    assert cs["staleness_reason"] is None


# soak18 step 2: submit_ready never negative even with snapshot drift
def test_current_submit_ready_never_negative_when_baseline_above_current():
    """Snapshot drift can produce baseline_total > current_total. The
    primary funnel must clamp to 0, never expose a negative count."""
    rollup = _make_rollup(submit_ready_total=3)
    baseline = _make_baseline(submit_ready_total=10)  # baseline higher
    payload = build_summary_payload(
        rollup=rollup, hot={}, orderflow={}, baseline=baseline,
        profile="production", now_utc=NOW,
    )
    cs_funnel = payload["current_scan"]["gate_funnel"]
    assert cs_funnel["submit_ready"] == 0  # clamped
    assert cs_funnel["sim_passed"] >= 0
    assert cs_funnel["roundtrip_attempted"] >= 0


# soak18 step 3: empty / missing baseline session_id
def test_baseline_with_empty_session_id_yields_match_false():
    rollup = _make_rollup(session_id="sess_a")
    baseline = _make_baseline()
    baseline["session"] = {"session_id": ""}  # empty string
    payload = build_summary_payload(
        rollup=rollup, hot={}, orderflow={}, baseline=baseline,
        profile="production", now_utc=NOW,
    )
    cs = payload["current_scan"]
    assert cs["session_id_match_baseline"] is False
    assert cs["baseline_session_id"] == ""


def test_baseline_without_session_block_yields_match_false():
    rollup = _make_rollup(session_id="sess_a")
    baseline = _make_baseline()
    baseline.pop("session", None)
    payload = build_summary_payload(
        rollup=rollup, hot={}, orderflow={}, baseline=baseline,
        profile="production", now_utc=NOW,
    )
    cs = payload["current_scan"]
    assert cs["session_id_match_baseline"] is False
    assert cs["baseline_session_id"] is None


# soak18 step 6: ARBY_DASHBOARD_FRESHNESS_S env tunable
def test_freshness_threshold_env_overrides_default(monkeypatch):
    """Reload the module with a custom env so FRESHNESS_THRESHOLD_S
    rebinds. Verify build_summary_payload picks up the new threshold."""
    import importlib

    import monitoring.dashboard_server as ds

    monkeypatch.setenv("ARBY_DASHBOARD_FRESHNESS_S", "30")
    importlib.reload(ds)
    try:
        assert ds.FRESHNESS_THRESHOLD_S == 30
        rollup = _make_rollup(last_updated_offset_s=60)  # > 30
        payload = ds.build_summary_payload(
            rollup=rollup, hot={}, orderflow={}, baseline=_make_baseline(),
            profile="production", now_utc=NOW,
        )
        cs = payload["current_scan"]
        assert cs["is_fresh"] is False
        assert "STALE" in (cs["staleness_reason"] or "")
    finally:
        # Restore default for downstream tests.
        monkeypatch.delenv("ARBY_DASHBOARD_FRESHNESS_S", raising=False)
        importlib.reload(ds)


def test_freshness_threshold_env_invalid_falls_back(monkeypatch):
    import importlib

    import monitoring.dashboard_server as ds

    monkeypatch.setenv("ARBY_DASHBOARD_FRESHNESS_S", "notanumber")
    importlib.reload(ds)
    try:
        assert ds.FRESHNESS_THRESHOLD_S == 120
    finally:
        monkeypatch.delenv("ARBY_DASHBOARD_FRESHNESS_S", raising=False)
        importlib.reload(ds)


# soak18 step 7: integration test through real HTTPServer
def test_api_summary_via_http_server(monkeypatch, tmp_path):
    """Spin a real HTTPServer with DashboardHandler against fixture
    rolling artifacts. Verifies the JSON-shape contract end-to-end."""
    import json as _json
    import threading
    import urllib.request
    from http.server import HTTPServer

    import monitoring.dashboard_server as ds

    rolling = tmp_path / "_rolling"
    rolling.mkdir()
    rollup = _make_rollup(last_updated_offset_s=5)
    # Anchor freshness vs wall-clock now so test stays stable.
    rollup["last_updated"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    baseline = _make_baseline()
    baseline["last_updated"] = (
        datetime.now(timezone.utc) - timedelta(seconds=120)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    (rolling / "m7_hot_rollup_latest.json").write_text(_json.dumps(rollup))
    (rolling / "reviewer_soak_baseline_latest.json").write_text(
        _json.dumps(baseline)
    )

    monkeypatch.setattr(ds, "ROLLING_DIR", rolling)
    monkeypatch.setattr(ds, "ARTIFACT_FILES", {
        k: rolling / v.name for k, v in ds.ARTIFACT_FILES.items()
    })
    monkeypatch.setattr(ds, "DISCOVERY_ARTIFACT_FILES", {
        k: rolling / v.name for k, v in ds.DISCOVERY_ARTIFACT_FILES.items()
    })
    monkeypatch.setattr(ds, "BASELINE_FILES", {
        "production": rolling / "reviewer_soak_baseline_latest.json",
        "discovery": rolling / "reviewer_soak_baseline_latest_discovery.json",
    })

    server = HTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/summary", timeout=5
        ) as resp:
            assert resp.status == 200
            payload = _json.loads(resp.read().decode("utf-8"))
        assert payload["schema_version"] == "summary_v2"
        assert "current_scan" in payload
        assert "historical_cumulative" in payload
        assert payload["current_scan"]["is_fresh"] is True
        assert payload["current_scan"]["session_id_match_baseline"] is True

        # Profile selector
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/summary?profile=discovery", timeout=5
        ) as resp:
            disc = _json.loads(resp.read().decode("utf-8"))
        assert disc["profile"] == "discovery"

        # Unknown route is 404
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/nonexistent", timeout=5
            )
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=2)


# soak19 step 5: discovery-specific freshness threshold
def test_freshness_threshold_discovery_env_independent(monkeypatch):
    """ARBY_DASHBOARD_FRESHNESS_S_DISCOVERY must override only the
    discovery profile; production keeps its own threshold."""
    import importlib

    import monitoring.dashboard_server as ds

    monkeypatch.setenv("ARBY_DASHBOARD_FRESHNESS_S", "120")
    monkeypatch.setenv("ARBY_DASHBOARD_FRESHNESS_S_DISCOVERY", "300")
    importlib.reload(ds)
    try:
        assert ds.FRESHNESS_THRESHOLD_S == 120
        assert ds.FRESHNESS_THRESHOLD_S_DISCOVERY == 300
        # Rollup 200s old: stale for production (>120), fresh for
        # discovery (<300).
        rollup = _make_rollup(last_updated_offset_s=200)
        baseline = _make_baseline()
        # Distinct baseline.last_updated to avoid BASELINE_NOT_REFRESHED.
        baseline["last_updated"] = (
            NOW - timedelta(seconds=400)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        prod = ds.build_summary_payload(
            rollup=rollup, hot={}, orderflow={}, baseline=baseline,
            profile="production", now_utc=NOW,
        )
        disc = ds.build_summary_payload(
            rollup=rollup, hot={}, orderflow={}, baseline=baseline,
            profile="discovery", now_utc=NOW,
        )
        assert prod["current_scan"]["is_fresh"] is False
        assert "STALE" in (prod["current_scan"]["staleness_reason"] or "")
        assert disc["current_scan"]["is_fresh"] is True
        assert disc["current_scan"]["staleness_reason"] is None
    finally:
        monkeypatch.delenv("ARBY_DASHBOARD_FRESHNESS_S", raising=False)
        monkeypatch.delenv("ARBY_DASHBOARD_FRESHNESS_S_DISCOVERY", raising=False)
        importlib.reload(ds)


# soak19 step 6: legacy top-level keys carry _deprecated markers
def test_legacy_top_level_keys_marked_deprecated():
    payload = build_summary_payload(
        rollup=_make_rollup(),
        hot={"reject_buckets": {"GUARD_X": 5}},
        orderflow={},
        baseline=_make_baseline(),
        profile="production",
        now_utc=NOW,
    )
    # Meta key advertises every deprecated top-level field.
    deprecated = payload.get("_deprecated_top_level_keys")
    assert isinstance(deprecated, list)
    expected = {
        "scope", "top_spreads", "gate_funnel",
        "reject_buckets", "current_session_id", "last_exit_reason",
    }
    assert expected.issubset(set(deprecated))
    # Dict-shaped legacy blocks carry inline _deprecated:true.
    assert payload["scope"].get("_deprecated") is True
    assert payload["gate_funnel"].get("_deprecated") is True
    assert payload["reject_buckets"].get("_deprecated") is True
    # current_scan / historical_cumulative MUST NOT carry the marker.
    assert payload["current_scan"].get("_deprecated") is None
    assert payload["historical_cumulative"].get("_deprecated") is None




# ===========================================================================
# Reviewer (post-soak19) step 6: universe_breadth in /api/summary
# ===========================================================================


def test_universe_breadth_default_zero_when_artifacts_empty():
    payload = build_summary_payload(
        rollup=_make_rollup(),
        hot={},
        orderflow={},
        baseline=_make_baseline(),
        profile="production",
        now_utc=NOW,
    )
    breadth = payload["current_scan"]["universe_breadth"]
    expected_keys = {
        "intent_pairs",
        "pools_discovered_total",
        "pools_active_total",
        "ptt_total",
        "bridge_focused_pool_count",
        "bridge_pool_hit_total",
        "registry_hit_for_event_pool_total",
        "hot_seen_unresolved_pool_count",
        "candidate_source_breakdown",
    }
    assert expected_keys.issubset(set(breadth.keys()))
    assert breadth["intent_pairs"] == 0
    assert breadth["pools_active_total"] == 0
    assert breadth["ptt_total"] == 0


def test_universe_breadth_populated_from_orderflow_and_bridge():
    rollup = _make_rollup()
    rollup["bridge_focused_pool_count_last"] = 48
    rollup["bridge_pool_hit_total"] = 3210
    rollup["hot_seen_unresolved_pool_count"] = 7
    rollup["registry_hit_for_event_pool_total"] = 4500
    orderflow = {
        "registry_session_stats": {
            "unique_pairs_queried": 15,
            "pools_discovered": 429,
            "pools_active": 280,
        }
    }
    bridge = {
        "candidate_source_breakdown": {
            "cold_exec": 12,
            "near_exec": 4,
            "stale_positive": 5,
            "recent_active": 3,
            "hot_seen_backfill": 0,
            "ptt_total": 133,
        }
    }
    payload = build_summary_payload(
        rollup=rollup,
        hot={},
        orderflow=orderflow,
        baseline=_make_baseline(),
        profile="production",
        now_utc=NOW,
        bridge=bridge,
    )
    breadth = payload["current_scan"]["universe_breadth"]
    assert breadth["intent_pairs"] == 15
    assert breadth["pools_discovered_total"] == 429
    assert breadth["pools_active_total"] == 280
    assert breadth["ptt_total"] == 133
    assert breadth["bridge_focused_pool_count"] == 48
    assert breadth["bridge_pool_hit_total"] == 3210
    assert breadth["registry_hit_for_event_pool_total"] == 4500
    assert breadth["hot_seen_unresolved_pool_count"] == 7
    csb = breadth["candidate_source_breakdown"]
    assert csb["cold_exec"] == 12
    assert csb["stale_positive"] == 5
    # ptt_total is promoted to a top-level field, not duplicated here.
    assert "ptt_total" not in csb


def test_live_deltas_block_present():
    """Reviewer post-2h-soak step #8: live_deltas must surface fresh facts."""
    rollup = _make_rollup()
    rollup["scorer_sim_divergence_samples_total"] = 4
    rollup["scorer_sim_divergence_samples_recent"] = [{"event_id": "x"}]
    rollup["pre_sim_skip_samples_total"] = 8
    rollup["pre_sim_skip_samples_recent"] = [{"reason": "MISSING_SIZE_METADATA"}]
    rollup["submit_blocker_histogram"] = {"SCORER_SIM_DIVERGENCE": 4}
    rollup["simulation_error_histogram"] = {"PRE_SIM_SKIP:MISSING_SIZE_METADATA": 8}
    rollup["external_provider_blocker_total"] = 0
    baseline = _make_baseline()
    baseline["submit_blocker_histogram"] = {"SCORER_SIM_DIVERGENCE": 1}
    baseline["simulation_error_histogram"] = {"PRE_SIM_SKIP:MISSING_SIZE_METADATA": 3}
    payload = build_summary_payload(
        rollup=rollup,
        hot={},
        orderflow={},
        baseline=baseline,
        profile="production",
        now_utc=NOW,
    )
    ld = payload["current_scan"]["live_deltas"]
    assert ld["scorer_sim_divergence_samples_total"] == 4
    assert ld["scorer_sim_divergence_samples_recent_count"] == 1
    assert ld["pre_sim_skip_samples_total"] == 8
    assert ld["pre_sim_skip_samples_recent_count"] == 1
    assert ld["submit_blocker_histogram_delta"]["SCORER_SIM_DIVERGENCE"] == 3
    assert ld["simulation_error_histogram_delta"]["PRE_SIM_SKIP:MISSING_SIZE_METADATA"] == 5
    assert ld["scorer_sim_divergence_submit_blocker_delta"] == 3
    assert ld["pre_sim_skip_delta_total"] == 5
    # Backward-compatible fields remain cumulative for older clients.
    assert ld["submit_blocker_histogram"]["SCORER_SIM_DIVERGENCE"] == 4
    assert ld["simulation_error_histogram"]["PRE_SIM_SKIP:MISSING_SIZE_METADATA"] == 8
    assert ld["external_provider_blocker_total"] == 0
    assert "fresh_funnel" in ld
    assert "is_fresh" in ld


def test_live_deltas_histogram_delta_filters_stale_cumulative_blockers():
    """Cumulative blocker histograms must not masquerade as fresh deltas."""
    rollup = _make_rollup()
    baseline = _make_baseline()
    stale_submit = {"SCORER_SIM_DIVERGENCE:2424.7584->-9988.8760": 3}
    stale_sim = {"PRE_SIM_SKIP:MISSING_SIZE_METADATA": 9}
    rollup["submit_blocker_histogram"] = dict(stale_submit)
    baseline["submit_blocker_histogram"] = dict(stale_submit)
    rollup["simulation_error_histogram"] = dict(stale_sim)
    baseline["simulation_error_histogram"] = dict(stale_sim)

    payload = build_summary_payload(
        rollup=rollup,
        hot={},
        orderflow={},
        baseline=baseline,
        profile="production",
        now_utc=NOW,
    )
    ld = payload["current_scan"]["live_deltas"]

    assert ld["submit_blocker_histogram"]["SCORER_SIM_DIVERGENCE:2424.7584->-9988.8760"] == 3
    assert ld["submit_blocker_histogram_delta"] == {}
    assert ld["simulation_error_histogram_delta"] == {}
    assert ld["scorer_sim_divergence_submit_blocker_delta"] == 0
    assert ld["pre_sim_skip_delta_total"] == 0


def test_dashboard_root_serves_m7_only_view():
    """Root dashboard should be the M7 operator surface, not the legacy mixed dashboard."""
    assert DASHBOARD_HTML.name == "dashboard_m7.html"


def test_m7_current_stream_uses_orderflow_candidates_when_sim_samples_absent():
    """Active stream must not depend on sim_output_samples only."""
    now = datetime(2026, 5, 5, 22, 2, 0, tzinfo=timezone.utc)
    rollup = {
        "last_updated": "2026-05-05T22:01:30Z",
        "submit_ready_total": 13,
        "roundtrip_profitable_total": 13,
        "production_readiness": {
            "kill_switch_active": False,
            "live_submit_blocked_reason": "REAL_SUBMIT_NOT_IMPLEMENTED",
        },
    }
    orderflow = {
        "timestamp": "2026-05-05T22:01:12Z",
        "top_executable_candidates": [{
            "event_id": "live_swap_1",
            "actual_pair": "AAA/WETH",
            "net_bps": 1084.0247,
            "route_viable": True,
            "profit_guard_passed": True,
            "pool_address": "0xa6d44d25f22115e7b88646c5acaf0370753eb1e9",
            "best_buy_venue": "aerodrome",
            "best_sell_venue": "uniswap_v3",
            "best_buy_fee": 0,
            "best_sell_fee": 10000,
            "amount_in_wei": 1_000_000_000_000_000_000,
            "net_pnl_wei": 108_402_467_413_561_023,
            "total_gas_bps": 0.002,
            "gate_trace": {"profit_guard_passed": True},
        }],
        "micro_refinement": [{
            "event_id": "live_swap_1",
            "best_submit_size": 750_000_000_000_000_000,
            "verified_net_bps_after_refinement": 1083.8767,
        }],
    }

    payload = build_m7_current_payload(
        rollup=rollup,
        hot={},
        orderflow=orderflow,
        bridge={},
        profile="production",
        now_utc=now,
    )

    assert payload["is_fresh"] is True
    assert payload["submit_ready_total"] == 13
    assert len(payload["opportunities"]) == 1
    opp = payload["opportunities"][0]
    assert opp["pair"] == "AAA/WETH"
    assert opp["source"] == "cold_executable"
    assert opp["amount_in_optimal_wei"] == "750000000000000000"
    assert opp["net_spread_bps"] == 1083.8767
    assert opp["expected_profit_wei"] == "108402467413561023"
    assert opp["gate_status"] == "PROFIT_GUARD_PASSED"


def test_m7_current_stream_falls_back_to_hot_candidates():
    now = datetime(2026, 5, 5, 22, 2, 0, tzinfo=timezone.utc)
    payload = build_m7_current_payload(
        rollup={"last_updated": "2026-05-05T22:01:30Z", "production_readiness": {}},
        hot={
            "top_hot_candidates": [{
                "event_id": "hot_1",
                "actual_pair": "PENGACHU/WETH",
                "net_bps": -2.15,
                "route_viable": False,
                "reject_reason": "GAS_EXCEEDS_GROSS",
                "pool_address": "0x5d2091e0b3e0b516e0f3abd75242e9287c253499",
            }]
        },
        orderflow={},
        bridge={},
        profile="production",
        now_utc=now,
    )

    assert len(payload["opportunities"]) == 1
    assert payload["opportunities"][0]["source"] == "hot_recent"
    assert payload["opportunities"][0]["gate_status"] == "GAS_EXCEEDS_GROSS"


# ===========================================================================
# M7 dashboard USD display contract
# ===========================================================================


def test_m7_current_usd_values_are_derived_from_artifact_notional():
    now = datetime(2026, 5, 6, 8, 0, 0, tzinfo=timezone.utc)
    payload = build_m7_current_payload(
        rollup={"last_updated": "2026-05-06T07:59:55Z", "production_readiness": {}},
        hot={},
        orderflow={
            "top_executable_candidates": [{
                "event_id": "usd_1",
                "pair": "AAA/WETH",
                "net_bps": 100,
                "size_usd_estimate": 1000,
                "amount_in_wei": 1_000_000_000_000_000_000,
                "total_gas_bps": 4,
                "slippage_bps": 2,
            }],
            "micro_refinement": [{
                "event_id": "usd_1",
                "best_submit_size": 500_000_000_000_000_000,
            }],
        },
        bridge={},
        profile="production",
        now_utc=now,
    )

    opp = payload["opportunities"][0]
    assert opp["amount_in_optimal_usd"] == 500.0
    assert opp["expected_profit_usd"] == 5.0
    assert opp["gas_usd"] == 0.2
    assert opp["slippage_usd"] == 0.1
    assert opp["usd_basis"] == "artifact_usd_fields"
    assert payload["usd_coverage"]["profit_usd_available"] == 1
    assert payload["usd_coverage"]["conversion_contract"] == (
        "dynamic_artifact_usd_only_no_price_hardcode"
    )


def test_m7_current_does_not_invent_usd_without_dynamic_basis():
    now = datetime(2026, 5, 6, 8, 0, 0, tzinfo=timezone.utc)
    payload = build_m7_current_payload(
        rollup={"last_updated": "2026-05-06T07:59:55Z", "production_readiness": {}},
        hot={},
        orderflow={
            "top_executable_candidates": [{
                "event_id": "no_usd",
                "pair": "BBB/WETH",
                "net_bps": 1050,
                "amount_in_wei": 1_000_000_000_000_000_000,
                "net_pnl_wei": 105_000_000_000_000_000,
            }],
        },
        bridge={},
        profile="production",
        now_utc=now,
    )

    opp = payload["opportunities"][0]
    assert opp["amount_in_optimal_usd"] is None
    assert opp["expected_profit_usd"] is None
    assert opp["gas_usd"] is None
    assert opp["usd_basis"] == "unavailable"
    assert payload["usd_coverage"]["profit_usd_available"] == 0
    assert payload["metric_audit"]["synthetic_amount_1e18_rows"] == 1


def test_m7_current_excludes_stale_orderflow_candidates_from_live_stream():
    now = datetime(2026, 5, 6, 8, 0, 0, tzinfo=timezone.utc)
    payload = build_m7_current_payload(
        rollup={"last_updated": "2026-05-06T07:59:55Z", "production_readiness": {}},
        hot={},
        orderflow={
            "timestamp": "2026-05-06T07:30:00Z",
            "top_executable_candidates": [{
                "event_id": "stale",
                "pair": "OLD/WETH",
                "net_bps": 100,
            }],
        },
        bridge={
            "timestamp": "2026-05-06T07:59:40Z",
            "cold_executable": [{
                "event_id": "fresh",
                "pair": "NEW/WETH",
                "net_bps": 50,
                "size_usd_estimate": 100,
            }],
        },
        profile="production",
        now_utc=now,
    )

    assert payload["candidate_sources"]["orderflow"]["is_fresh"] is False
    assert payload["candidate_sources"]["bridge"]["is_fresh"] is True
    assert [row["event_id"] for row in payload["opportunities"]] == ["fresh"]


def test_m7_current_metric_audit_flags_zero_delta_with_nonzero_totals():
    now = datetime(2026, 5, 6, 8, 0, 0, tzinfo=timezone.utc)
    payload = build_m7_current_payload(
        rollup={
            "last_updated": "2026-05-06T07:59:55Z",
            "submit_ready_total": 13,
            "roundtrip_profitable_total": 13,
            "rate_metrics": {
                "rate_basis": "current_worker_session_delta",
                "submit_ready_delta": 0,
                "roundtrip_profitable_delta": 0,
            },
            "session": {
                "rate_baseline": {
                    "submit_ready_total": 13,
                    "roundtrip_profitable_total": 13,
                }
            },
            "production_readiness": {},
        },
        hot={},
        orderflow={},
        bridge={},
        profile="production",
        now_utc=now,
    )

    audit = payload["metric_audit"]
    assert audit["rate_metrics_basis"] == "current_worker_session_delta"
    assert audit["rate_baseline_present"] is True
    assert audit["rate_metrics_zero_delta_with_nonzero_totals"] is True


# ===========================================================================
# Reviewer Step 2: rate_metrics baseline fix — submit_ready_delta
# ===========================================================================

def test_rate_metrics_submit_ready_delta_not_zero_after_fresh_baseline():
    """After a fresh session start with cold_immediate_submit_ready_total=13
    carried from prior run, a new window that adds 1 more must show
    submit_ready_delta >= 1, never 0 when new candidates arrived."""
    from m7.orderflow.hot_runtime_artifacts import _compute_rate_metrics

    rollup = {
        "roundtrip_attempted_total": 81,
        "roundtrip_profitable_total": 13,
        "submit_ready_total": 14,          # 13 baseline + 1 new
        "cold_immediate_submit_ready_total": 14,
        "windows_events_without_fast_score_total": 5,
        "session": {
            "session_id": "fresh_sess",
            "session_started_at": "2026-05-06T08:00:00Z",
            "session_elapsed_minutes": 10.0,
            "session_windows_seen": 20,
            "rate_baseline": {
                "roundtrip_attempted_total": 81,
                "roundtrip_profitable_total": 13,
                "windows_events_without_fast_score_total": 5,
                "submit_ready_total": 13,           # ← baseline from prior run
                "cold_immediate_submit_ready_total": 13,
            },
        },
    }
    rm = _compute_rate_metrics(rollup)
    # Fresh session has 1 new submit_ready beyond baseline
    assert rm["submit_ready_delta"] == 1, (
        f"Expected submit_ready_delta=1, got {rm['submit_ready_delta']}"
    )
    assert rm["cold_immediate_submit_ready_delta"] == 1


def test_rate_metrics_submit_ready_delta_zero_when_no_new_candidates():
    """When no new candidates arrived in this session (all 13 from prior run),
    submit_ready_delta must be 0."""
    from m7.orderflow.hot_runtime_artifacts import _compute_rate_metrics

    rollup = {
        "roundtrip_attempted_total": 81,
        "roundtrip_profitable_total": 13,
        "submit_ready_total": 13,
        "cold_immediate_submit_ready_total": 13,
        "windows_events_without_fast_score_total": 5,
        "session": {
            "session_id": "fresh_sess",
            "session_started_at": "2026-05-06T08:00:00Z",
            "session_elapsed_minutes": 10.0,
            "session_windows_seen": 20,
            "rate_baseline": {
                "roundtrip_attempted_total": 81,
                "roundtrip_profitable_total": 13,
                "windows_events_without_fast_score_total": 5,
                "submit_ready_total": 13,
                "cold_immediate_submit_ready_total": 13,
            },
        },
    }
    rm = _compute_rate_metrics(rollup)
    assert rm["submit_ready_delta"] == 0
    assert rm["cold_immediate_submit_ready_delta"] == 0


def test_rate_metrics_baseline_auto_seeds_submit_ready_fields():
    """When no rate_baseline exists yet (first window of brand-new session),
    _compute_rate_metrics must auto-seed submit_ready_total and
    cold_immediate_submit_ready_total into the baseline so subsequent
    windows compute correct deltas."""
    from m7.orderflow.hot_runtime_artifacts import _compute_rate_metrics

    rollup = {
        "roundtrip_attempted_total": 81,
        "roundtrip_profitable_total": 13,
        "submit_ready_total": 13,
        "cold_immediate_submit_ready_total": 13,
        "windows_events_without_fast_score_total": 0,
        "session": {
            "session_id": "brand_new",
            "session_elapsed_minutes": 1.0,
            "session_windows_seen": 1,
            # No rate_baseline — will be auto-created
        },
    }
    rm = _compute_rate_metrics(rollup)
    # Auto-seeded baseline = current totals → deltas = 0 on first window
    assert rm["submit_ready_delta"] == 0
    assert rm["cold_immediate_submit_ready_delta"] == 0
    # Baseline is now persisted in session
    seeded = rollup["session"]["rate_baseline"]
    assert seeded["submit_ready_total"] == 13
    assert seeded["cold_immediate_submit_ready_total"] == 13


# ===========================================================================
# Reviewer Steps 4-5, 8: ws_health + execution_funnel in /api/m7/current
# ===========================================================================

def test_m7_current_has_ws_health_block():
    """ws_health block must be present with expected keys."""
    now = datetime(2026, 5, 6, 8, 0, 0, tzinfo=timezone.utc)
    rollup = {
        "last_updated": "2026-05-06T07:59:55Z",
        "windows_seen": 41,
        "session_ws_connected_windows": 24,
        "session_ws_failed_429_windows": 16,
        "session_ws_failed_windows": 17,
        "session_ws_fallback_windows": 0,
        "last_ws_connection_status": "connected",
        "last_ws_provider": "drpc",
        "production_readiness": {},
    }
    payload = build_m7_current_payload(
        rollup=rollup, hot={}, orderflow={}, bridge={},
        profile="production", now_utc=now,
    )
    wsh = payload.get("ws_health")
    assert wsh is not None, "ws_health block must be present"
    assert wsh["connected_windows"] == 24
    assert wsh["failed_429_windows"] == 16
    assert wsh["total_windows"] == 41
    assert wsh["last_status"] == "connected"
    assert wsh["last_provider"] == "drpc"
    # pct_429 = 16/41 * 100 ≈ 39.0
    assert wsh["pct_429"] is not None
    assert wsh["pct_429"] > 30.0


def test_m7_current_ws_health_pct_429_zero_when_no_failures():
    """When no 429s, pct_429 must be 0.0, not None."""
    now = datetime(2026, 5, 6, 8, 0, 0, tzinfo=timezone.utc)
    rollup = {
        "last_updated": "2026-05-06T07:59:55Z",
        "windows_seen": 20,
        "session_ws_connected_windows": 20,
        "session_ws_failed_429_windows": 0,
        "session_ws_failed_windows": 0,
        "production_readiness": {},
    }
    payload = build_m7_current_payload(
        rollup=rollup, hot={}, orderflow={}, bridge={},
        profile="production", now_utc=now,
    )
    assert payload["ws_health"]["pct_429"] == 0.0


def test_m7_current_has_execution_funnel_block():
    """execution_funnel must separate paper / canary / live_receipt / live_pnl."""
    now = datetime(2026, 5, 6, 8, 0, 0, tzinfo=timezone.utc)
    rollup = {
        "last_updated": "2026-05-06T07:59:55Z",
        "submit_ready_total": 13,
        "canary_rehearsal": {"canary_dry_run_submitted": 3},
        "production_readiness": {},
    }
    payload = build_m7_current_payload(
        rollup=rollup, hot={}, orderflow={}, bridge={},
        profile="production", now_utc=now,
        live_submit={"receipt_ok_total": 0},
        live_pnl={"pnl_ok_total": 0},
    )
    ef = payload.get("execution_funnel")
    assert ef is not None, "execution_funnel block must be present"
    assert ef["paper_submit_ready"] == 13
    assert ef["canary_ready"] == 3
    assert ef["live_receipt_ok"] == 0
    assert ef["live_pnl_ok"] == 0


def test_m7_current_execution_funnel_zeros_when_no_artifacts():
    """execution_funnel fields default to 0 when artifacts absent."""
    now = datetime(2026, 5, 6, 8, 0, 0, tzinfo=timezone.utc)
    payload = build_m7_current_payload(
        rollup={"last_updated": "2026-05-06T07:59:55Z", "production_readiness": {}},
        hot={}, orderflow={}, bridge={},
        profile="production", now_utc=now,
    )
    ef = payload["execution_funnel"]
    assert ef["paper_submit_ready"] == 0
    assert ef["canary_ready"] == 0
    assert ef["live_receipt_ok"] == 0
    assert ef["live_pnl_ok"] == 0


# E1.65 dashboard fix tests
def test_bridge_priced_candidate_shows_usd(monkeypatch):
    """Fix step 2+3: bridge cold_executable with size_usd_estimate > 0 must produce
    amount_usd_available > 0 in /api/m7/current, even if hot rows have no USD."""
    from monitoring.dashboard_server import build_m7_current_payload, _m7_usd_coverage
    now = datetime(2026, 5, 8, 12, 10, 0, tzinfo=timezone.utc)
    # Bridge has a fresh timestamp and a priced candidate (USDe/USDC from soak)
    bridge = {
        "timestamp": "2026-05-08T12:09:00Z",
        "cold_executable": [
            {
                "event_id": "live_swap_1",
                "actual_pair": "USDe/USDC",
                "net_bps": 787.4,
                "route_viable": True,
                "size_valid_for_token": True,
                "size_usd_estimate": 1.07957,
                "amount_in_optimal_usd": 1.07957,
                "expected_profit_usd": 0.08499,
                "usd_basis_source": "token_out_stable_fallback",
                "amount_in_wei": "1000000000000000000",
            }
        ],
    }
    payload = build_m7_current_payload(
        rollup={"last_updated": now.isoformat(), "production_readiness": {}},
        hot={}, orderflow={}, bridge=bridge,
        profile="production", now_utc=now,
    )
    rows = payload["opportunities"]
    usd_cov = payload["usd_coverage"]
    assert usd_cov["amount_usd_available"] >= 1, (
        f"Expected amount_usd_available >= 1, got {usd_cov}"
    )
    assert usd_cov["profit_usd_available"] >= 1, (
        f"Expected profit_usd_available >= 1, got {usd_cov}"
    )
    # Row must carry usd_basis_source
    priced = [r for r in rows if (r.get("amount_in_optimal_usd") or 0) > 0]
    assert len(priced) >= 1, f"No priced rows, got {rows}"
    assert priced[0].get("usd_basis_source") == "token_out_stable_fallback"


def test_candidate_size_usd_zero_returns_none():
    """Fix step 2: size_usd_estimate=0.0 must yield None from _candidate_size_usd,
    so dashboard does not claim USD coverage for unpriced fast-path rows."""
    from monitoring.dashboard_server import _candidate_size_usd
    assert _candidate_size_usd({"size_usd_estimate": 0.0, "amount_in_wei": "1000"}, None) is None
    assert _candidate_size_usd({"amount_in_optimal_usd": 0.0}, None) is None
    assert _candidate_size_usd({"size_usd_estimate": 1.5}, None) == 1.5
    assert _candidate_size_usd({}, None) is None


def test_bridge_freshness_uses_mtime_fallback():
    """Fix step 1: _artifact_timestamp uses mtime when it is newer."""
    from monitoring.dashboard_server import _artifact_timestamp
    assert _artifact_timestamp({"_file_mtime_utc": "2026-05-08T12:05:00Z"}) == "2026-05-08T12:05:00Z"
    # Cold bridge files may be rewritten with an unchanged internal timestamp.
    assert _artifact_timestamp({"timestamp": "2026-05-08T12:03:00Z",
                                 "_file_mtime_utc": "2026-05-08T12:05:00Z"}) == "2026-05-08T12:05:00Z"
    assert _artifact_timestamp({"last_updated": "2026-05-08T12:08:00Z",
                                 "_file_mtime_utc": "2026-05-08T12:05:00Z"}) == "2026-05-08T12:08:00Z"


# E1.65 steps 1-10: size bucket / depth verdict / production sizing tests
def test_size_category_buckets():
    """Steps 1-2: _size_category returns correct bucket for each range."""
    from monitoring.dashboard_server import _size_category
    assert _size_category(None) == "unknown"
    assert _size_category(0.0) == "dust"
    assert _size_category(0.099) == "dust"
    assert _size_category(1.0) == "micro"
    assert _size_category(5.5) == "micro"
    assert _size_category(10.0) == "small"
    assert _size_category(99.9) == "small"
    assert _size_category(100.0) == "medium"
    assert _size_category(1000.0) == "medium"


def test_profit_at_buckets_linear_estimate():
    """Step 3: _profit_at_buckets extrapolates linearly from current size."""
    from monitoring.dashboard_server import _profit_at_buckets
    # $1.08 size, $0.085 profit → profit_per_usd ≈ 0.07870
    result = _profit_at_buckets(1.08, 0.085)
    assert result is not None
    assert "$0.01" in result
    assert "$10.00" in result
    assert result["$1.00"] == round(0.085 / 1.08 * 1.0, 6)
    assert result["$10.00"] == round(0.085 / 1.08 * 10.0, 6)
    # None input returns None
    assert _profit_at_buckets(None, 0.085) is None
    assert _profit_at_buckets(1.0, None) is None
    assert _profit_at_buckets(0.0, 0.085) is None


def test_depth_verdict_classification():
    """Steps 7-8: _depth_verdict returns correct verdict string."""
    from monitoring.dashboard_server import _depth_verdict
    assert _depth_verdict(None, 100) == "depth_unknown"
    assert _depth_verdict(0.0, 100) == "depth_unknown"
    assert _depth_verdict(0.5, 100) == "dust_only"
    assert _depth_verdict(1.07, 787) == "micro_unverified"
    assert _depth_verdict(9.99, 100) == "micro_unverified"
    assert _depth_verdict(10.0, 100) == "viable_probe_needed"
    assert _depth_verdict(100.0, 50) == "viable_probe_needed"


def test_usd_basis_dust_profit_only_tag():
    """Step 4: usd_basis must be prefixed with DUST_PROFIT_ONLY when size < $1 and profit > 0."""
    from monitoring.dashboard_server import _candidate_usd_basis
    # Sub-$1 with profit → DUST_PROFIT_ONLY tag
    basis = _candidate_usd_basis(
        {"size_usd_estimate": 0.1, "expected_profit_usd": 0.032},
        size_usd=0.1, profit_usd=0.032, gas_usd=None
    )
    assert basis.startswith("DUST_PROFIT_ONLY:"), f"Expected DUST_PROFIT_ONLY prefix, got {basis!r}"
    # >= $1 with profit → NO dust tag
    basis_micro = _candidate_usd_basis(
        {"size_usd_estimate": 1.08, "expected_profit_usd": 0.085},
        size_usd=1.08, profit_usd=0.085, gas_usd=None
    )
    assert not basis_micro.startswith("DUST_PROFIT_ONLY:"), f"Should not have DUST tag, got {basis_micro!r}"
    # unavailable when all None
    assert _candidate_usd_basis({}, None, None, None) == "unavailable"


def test_usd_coverage_production_research_split():
    """Steps 5-6: usd_coverage must split production_profitable vs research_profitable."""
    from monitoring.dashboard_server import build_m7_current_payload, MIN_EXECUTABLE_SIZE_USD
    now = datetime(2026, 5, 8, 12, 10, 0, tzinfo=timezone.utc)
    bridge = {
        "timestamp": "2026-05-08T12:09:00Z",
        "cold_executable": [
            # dust size ($0.10)
            {
                "event_id": "fun_usdc_1",
                "actual_pair": "FUN/USDC",
                "net_bps": 320.0,
                "route_viable": True,
                "size_usd_estimate": 0.0998,
                "amount_in_optimal_usd": 0.0998,
                "expected_profit_usd": 0.032,
                "usd_basis_source": "token_out_stable_fallback",
            },
            # micro size ($1.08)
            {
                "event_id": "usde_usdc_1",
                "actual_pair": "USDe/USDC",
                "net_bps": 787.4,
                "route_viable": True,
                "size_usd_estimate": 1.07957,
                "amount_in_optimal_usd": 1.07957,
                "expected_profit_usd": 0.085,
                "usd_basis_source": "token_out_stable_fallback",
            },
        ],
    }
    payload = build_m7_current_payload(
        rollup={"last_updated": now.isoformat(), "production_readiness": {}},
        hot={}, orderflow={}, bridge=bridge,
        profile="production", now_utc=now,
    )
    usd_cov = payload["usd_coverage"]
    # Neither candidate >= MIN_EXECUTABLE_SIZE_USD ($10) → production_profitable = 0
    assert usd_cov["production_profitable_total"] == 0, (
        f"Expected 0 production profitable, got {usd_cov}"
    )
    # Both have profit > 0 but below threshold → research_profitable = 2
    assert usd_cov["research_profitable_total"] == 2, (
        f"Expected 2 research profitable, got {usd_cov}"
    )
    # dust_only_total: FUN/USDC size=$0.0998 < $1
    assert usd_cov["dust_only_total"] >= 1, f"Expected at least 1 dust row, got {usd_cov}"
    # min_executable_size_usd present
    assert usd_cov["min_executable_size_usd"] == MIN_EXECUTABLE_SIZE_USD


def test_row_has_size_classification_fields():
    """Steps 1-8: opportunity rows must carry size_category, is_production_sized,
    depth_verdict, and profit_size_buckets_est."""
    from monitoring.dashboard_server import build_m7_current_payload
    now = datetime(2026, 5, 8, 12, 10, 0, tzinfo=timezone.utc)
    bridge = {
        "timestamp": "2026-05-08T12:09:00Z",
        "cold_executable": [{
            "event_id": "fun_test",
            "actual_pair": "FUN/USDC",
            "net_bps": 320.0,
            "route_viable": True,
            "size_usd_estimate": 0.0998,
            "amount_in_optimal_usd": 0.0998,
            "expected_profit_usd": 0.032,
        }],
    }
    payload = build_m7_current_payload(
        rollup={"last_updated": now.isoformat(), "production_readiness": {}},
        hot={}, orderflow={}, bridge=bridge,
        profile="production", now_utc=now,
    )
    row = payload["opportunities"][0]
    assert row["size_category"] == "dust"  # 0.0998 < $1
    assert row["is_production_sized"] is False  # < MIN_EXECUTABLE_SIZE_USD ($10)
    assert row["depth_verdict"] == "dust_only"
    assert row["profit_size_buckets_est"] is not None
    assert "$10.00" in row["profit_size_buckets_est"]


# ------------------------------------------------------------------ E1.66 --
# pipeline_ready / production_profit_ready / production_sized_profitable_total
# ARBY_MIN_PRODUCTION_SIZE_USD = $50 (serious gate).
# ------------------------------------------------------------------ E1.66 --

class TestM7A566UsdCoverageE166:
    """E1.66: production_sized_profitable_total, pipeline_ready, production_profit_ready."""

    def _make_payload(self, cold_exec):
        from monitoring.dashboard_server import build_m7_current_payload
        now = datetime(2026, 5, 8, 12, 10, 0, tzinfo=timezone.utc)
        bridge = {"timestamp": "2026-05-08T12:09:00Z", "cold_executable": cold_exec}
        return build_m7_current_payload(
            rollup={"last_updated": now.isoformat(), "production_readiness": {}},
            hot={}, orderflow={}, bridge=bridge,
            profile="production", now_utc=now,
        )

    def test_pipeline_ready_true_when_candidates_present(self):
        payload = self._make_payload([{
            "event_id": "e1", "actual_pair": "FUN/USDC",
            "size_usd_estimate": 0.10, "expected_profit_usd": 0.01,
        }])
        assert payload["usd_coverage"]["pipeline_ready"] is True

    def test_pipeline_ready_false_when_no_candidates(self):
        payload = self._make_payload([])
        assert payload["usd_coverage"]["pipeline_ready"] is False

    def test_production_profit_ready_false_when_only_research(self):
        """$10 size → production_profitable=1 but not serious ($50) → prod_profit_ready=False."""
        payload = self._make_payload([{
            "event_id": "e1", "actual_pair": "WETH/USDC",
            "size_usd_estimate": 15.0, "expected_profit_usd": 0.5,
        }])
        cov = payload["usd_coverage"]
        assert cov["production_profitable_total"] == 1
        assert cov["production_sized_profitable_total"] == 0
        assert cov["production_profit_ready"] is False

    def test_production_profit_ready_true_when_serious_size(self):
        """$60 size >= $50 (MIN_PRODUCTION_SIZE_USD) → production_profit_ready=True."""
        payload = self._make_payload([{
            "event_id": "e1", "actual_pair": "WETH/USDC",
            "size_usd_estimate": 60.0, "expected_profit_usd": 1.5,
        }])
        cov = payload["usd_coverage"]
        assert cov["production_sized_profitable_total"] == 1
        assert cov["production_profit_ready"] is True

    def test_is_serious_production_sized_field_on_rows(self):
        """Row dict must carry is_serious_production_sized."""
        payload = self._make_payload([{
            "event_id": "e1", "actual_pair": "WETH/USDC",
            "size_usd_estimate": 60.0, "expected_profit_usd": 1.5,
        }])
        row = payload["opportunities"][0]
        assert row.get("is_serious_production_sized") is True

    def test_min_production_size_usd_in_coverage(self):
        """usd_coverage must expose min_production_size_usd for clients."""
        from monitoring.dashboard_server import MIN_PRODUCTION_SIZE_USD
        payload = self._make_payload([])
        assert payload["usd_coverage"]["min_production_size_usd"] == MIN_PRODUCTION_SIZE_USD
