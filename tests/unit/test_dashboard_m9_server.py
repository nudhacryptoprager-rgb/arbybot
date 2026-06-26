"""Schema tests for M9 dashboard server API payload builder.

Validates that build_m9_current_payload() returns the required keys and
sensible values when provided with either an empty artifact or a representative
M9 rolling artifact fixture.  No HTTP server is spun up; we test the payload
builder function directly.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)


def _minimal_m9_artifact(**overrides) -> dict:
    """Build a minimal m9_graph_latest.json dict for testing."""
    base = {
        "schema_family": "m9_graph_arb",
        "schema_revision": "m9.1",
        "generated_at_utc": "2026-05-22T11:59:00Z",
        "run_timestamp": "2026-05-22T11:59:00Z",
        "chain": "base",
        "cycles_found": 1100,
        "cycles_positive_gross": 0,
        "cycles_quoteable": 900,
        "qsr": 0.82,
        "quote_rpc_error_rate": 0.03,
        "quote_revert_rate": 0.15,
        "economics_gate_status": "BLOCKED_NO_POSITIVE_GROSS",
        "economics_blocker_class": "PROVIDER_QUALITY_BLOCKED",
        "sweeps_completed": 4,
        "duration_minutes": 5.0,
        "elapsed_s": 300.0,
        "requested_duration_minutes": 5.0,
        "topology_gate": "CYCLES_FOUND",
        "gate_acceptance": False,
        "strategy_gate_acceptance": False,
        "funnel_a": {
            "raw_hints": 91,
            "pairs_probed": 7,
            "dexes_probed": 5,
            "verified_tokens": 8,
            "verified_pools": 46,
            "active_routes": 51,
        },
        "economics_metrics": {
            "p50_gross_bps": -8.5,
            "p90_gross_bps": -4.2,
        },
        "risk_metrics": {
            "risk_gate": "NOT_STARTED",
            "honeypot_checked": 0,
            "transfer_tax_checked": 0,
            "unsafe_rejected": 0,
        },
        "graph_topology": {"token_count": 8, "edge_count": 102, "route_count": 51},
        "top_cycles": [],
        "top_opportunities": [],
        "run_context": {"chain": "base", "execution_mode": "paper"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests: build_m9_current_payload()
# ---------------------------------------------------------------------------

class TestBuildM9CurrentPayload:
    """Tests for monitoring.dashboard_server.build_m9_current_payload()."""

    def test_empty_artifact_returns_required_keys(self):
        from monitoring.dashboard_server import build_m9_current_payload
        payload = build_m9_current_payload(
            artifact={},
            now_utc=_now(),
            file_age_s=None,
        )
        required = {
            "schema_family", "schema_revision", "now_utc", "artifact_exists",
            "artifact_age_s", "m9_summary", "scan_status", "coverage",
            "funnel", "economics", "risk_metrics", "top_opportunities",
            "m8_1_inventory", "m8_sniper", "scan_scope",
        }
        missing = required - set(payload.keys())
        assert not missing, f"Missing payload keys: {missing}"

    def test_artifact_not_exists_when_empty(self):
        from monitoring.dashboard_server import build_m9_current_payload
        payload = build_m9_current_payload(artifact={}, now_utc=_now())
        assert payload["artifact_exists"] is False

    def test_artifact_exists_when_populated(self):
        from monitoring.dashboard_server import build_m9_current_payload
        a = _minimal_m9_artifact()
        payload = build_m9_current_payload(artifact=a, now_utc=_now(), file_age_s=30)
        assert payload["artifact_exists"] is True
        assert payload["artifact_age_s"] == 30

    def test_scan_status_from_artifact(self):
        from monitoring.dashboard_server import build_m9_current_payload
        a = _minimal_m9_artifact()
        payload = build_m9_current_payload(artifact=a, now_utc=_now())
        assert payload["scan_status"] == "BLOCKED_NO_POSITIVE_GROSS"

    def test_scan_status_unknown_when_empty(self):
        from monitoring.dashboard_server import build_m9_current_payload
        payload = build_m9_current_payload(artifact={}, now_utc=_now())
        assert payload["scan_status"] == "UNKNOWN"

    def test_m9_summary_fields(self):
        from monitoring.dashboard_server import build_m9_current_payload
        a = _minimal_m9_artifact()
        payload = build_m9_current_payload(artifact=a, now_utc=_now())
        s = payload["m9_summary"]
        assert s["cycles_found"] == 1100
        assert s["sweeps_completed"] == 4
        assert s["topology_gate"] == "CYCLES_FOUND"
        assert s["chain"] == "base"

    def test_coverage_edge_count(self):
        from monitoring.dashboard_server import build_m9_current_payload
        a = _minimal_m9_artifact()
        payload = build_m9_current_payload(artifact=a, now_utc=_now())
        cov = payload["coverage"]
        assert cov["edge_count"] == 102
        assert cov["active_routes"] == 51
        assert cov["pairs_probed"] == 7

    def test_economics_blocker_class(self):
        from monitoring.dashboard_server import build_m9_current_payload
        a = _minimal_m9_artifact()
        payload = build_m9_current_payload(artifact=a, now_utc=_now())
        assert payload["economics"]["economics_blocker_class"] == "PROVIDER_QUALITY_BLOCKED"

    def test_economics_qsr(self):
        from monitoring.dashboard_server import build_m9_current_payload
        a = _minimal_m9_artifact()
        payload = build_m9_current_payload(artifact=a, now_utc=_now())
        assert payload["economics"]["qsr"] == pytest.approx(0.82, abs=1e-6)

    def test_risk_metrics_forwarded(self):
        from monitoring.dashboard_server import build_m9_current_payload
        a = _minimal_m9_artifact()
        payload = build_m9_current_payload(artifact=a, now_utc=_now())
        rm = payload["risk_metrics"]
        assert rm["risk_gate"] == "NOT_STARTED"

    def test_top_opportunities_forwarded(self):
        from monitoring.dashboard_server import build_m9_current_payload
        opp = {
            "dex": "uniswap_v3", "factory": "EFFICIENT_BASELINE",
            "pool": "0xabc", "pool_path": ["0xabc", "0xdef", "0xghi"],
            "pair": "USDC/WETH/USDT",
            "market_size_usd": 1000.0, "dynamic_size_usd": None,
            "spread_bps": 12.5, "spread_usd": 1.25, "profit_usd": 1.25,
            "main_blocker": None,
        }
        a = _minimal_m9_artifact(top_opportunities=[opp])
        payload = build_m9_current_payload(artifact=a, now_utc=_now())
        assert len(payload["top_opportunities"]) == 1
        assert payload["top_opportunities"][0]["spread_bps"] == 12.5

    def test_m8_1_inventory_empty_artifact(self):
        from monitoring.dashboard_server import build_m9_current_payload
        payload = build_m9_current_payload(
            artifact={}, m8_1_artifact={}, now_utc=_now()
        )
        inv = payload["m8_1_inventory"]
        assert "pool_count" in inv
        assert "pair_count" in inv

    def test_m8_sniper_empty(self):
        from monitoring.dashboard_server import build_m9_current_payload
        payload = build_m9_current_payload(artifact={}, now_utc=_now())
        assert "m8_sniper" in payload
        assert "new_pools_found" in payload["m8_sniper"]

    def test_schema_family_constant(self):
        from monitoring.dashboard_server import build_m9_current_payload
        payload = build_m9_current_payload(artifact={}, now_utc=_now())
        assert payload["schema_family"] == "m9_dashboard"
        assert payload["schema_revision"] == "m9_dashboard.6"

    def test_operator_control_plane_present(self):
        from monitoring.dashboard_server import build_m9_current_payload, build_m9_operator_control_plane

        a = _minimal_m9_artifact(
            cycles_quoteable=851,
            cycles_positive_gross=0,
            qsr_liveness=0.0,
            qsr_econ=0.0,
            cycles_quoteable_by_length={"2": 10, "3": 9, "4": 0},
            scan_scope={
                "cycles_before_quarantine": 124,
                "cycles_after_quarantine": 34,
                "quarantine_exclusion_breakdown": {"hard_exclude_total": 9},
            },
        )
        acceptance = {
            "operator_verdict": {
                "verdict_labels": ["M8_2_GRAPH_HANDOFF_REACHED", "M9_QUOTE_LIVENESS_PARTIAL"],
                "economics_claim_allowed": False,
                "forbidden_claims": ["positive_gross"],
            },
            "quote_liveness_metrics": {"quote_liveness_status": "PARTIAL"},
        }
        payload = build_m9_current_payload(
            artifact=a,
            acceptance_report=acceptance,
            now_utc=_now(),
            file_age_s=30,
        )
        ocp = payload["operator_control_plane"]
        assert ocp["do_not_claim"]["active"] is True
        assert "2" in ocp["cycle_length_health"]
        assert ocp["quarantine_impact"]["cycles_before"] == 124

        ocp2 = build_m9_operator_control_plane(artifact=a, acceptance_report=acceptance)
        assert ocp2["do_not_claim"]["active"] is True
        assert "QUOTEABLE_NOT_ECONOMIC" in ocp2.get("operator_warnings", [])

    def test_stale_verdict_when_artifact_old(self):
        """Stale artifact must expose STALE live verdict, not PASS."""
        from monitoring.dashboard_server import build_m9_current_payload
        a = _minimal_m9_artifact(
            runtime_gates={"all_pass": True},
            duration_fulfilled=True,
        )
        payload = build_m9_current_payload(artifact=a, now_utc=_now(), file_age_s=1800)
        iq = payload["infra_quality"]
        assert iq["run_status"] == "stale"
        assert iq["runtime_gates_live_verdict"] == "STALE"
        assert iq["staleness_reason"] is not None
        assert "1800" in iq["staleness_reason"]

    def test_pass_verdict_when_fresh(self):
        """Fresh completed artifact with all_pass must show live verdict PASS."""
        from monitoring.dashboard_server import build_m9_current_payload
        a = _minimal_m9_artifact(
            runtime_gates={"all_pass": True},
            duration_fulfilled=True,
        )
        payload = build_m9_current_payload(artifact=a, now_utc=_now(), file_age_s=30)
        iq = payload["infra_quality"]
        assert iq["run_status"] == "completed"
        assert iq["runtime_gates_live_verdict"] == "PASS"
        assert iq["staleness_reason"] is None

    def test_top_opportunities_split(self):
        """top_opportunities (quoteable) and top_failed_opportunities are split."""
        from monitoring.dashboard_server import build_m9_current_payload
        opp_neg = {
            "dex": "aerodrome_v2", "factory": "EFFICIENT_BASELINE",
            "pool": "0xaaa", "pool_path": ["0xaaa", "0xbbb", "0xccc"],
            "pair": "WETH/USDC/AERO",
            "market_size_usd": 100.0, "dynamic_size_usd": None,
            "spread_bps": -15.2, "spread_usd": -0.015, "profit_usd": -0.015,
            "main_blocker": "NEGATIVE_GROSS",
        }
        opp_failed = {
            "dex": "uniswap_v3", "factory": "UNKNOWN",
            "pool": "0xddd", "pool_path": ["0xddd", "0xeee", "0xfff"],
            "pair": "USDC/WETH/USDT",
            "market_size_usd": 100.0, "dynamic_size_usd": None,
            "spread_bps": 0.0, "spread_usd": None, "profit_usd": None,
            "main_blocker": "CYCLE_QUOTE_FAILED",
        }
        a = _minimal_m9_artifact(top_opportunities=[opp_neg, opp_failed])
        payload = build_m9_current_payload(artifact=a, now_utc=_now(), file_age_s=10)
        assert len(payload["top_opportunities"]) == 1
        assert payload["top_opportunities"][0]["spread_bps"] == pytest.approx(-15.2)
        assert len(payload["top_failed_opportunities"]) == 1
        assert payload["top_failed_opportunities"][0]["main_blocker"] == "CYCLE_QUOTE_FAILED"

    def test_m8_1_artifact_age_s(self):
        """m8_1_inventory.artifact_age_s is computed from generated_at_utc."""
        from monitoring.dashboard_server import build_m9_current_payload
        # Artifact is 60 minutes old relative to now_utc
        old_ts = "2026-05-22T11:00:00Z"  # _now() = 12:00:00
        m8_1 = {"generated_at_utc": old_ts, "pool_count": 5}
        payload = build_m9_current_payload(artifact={}, m8_1_artifact=m8_1, now_utc=_now())
        inv = payload["m8_1_inventory"]
        assert inv["artifact_age_s"] == 3600  # 60 min = 3600 s
        assert inv["is_stale"] is False  # 3600 < 86400

    def test_m8_1_artifact_stale_flag(self):
        """m8_1_inventory.is_stale is True when artifact is older than 24 h."""
        from monitoring.dashboard_server import build_m9_current_payload
        old_ts = "2026-05-21T11:00:00Z"  # 25 h before _now() → clearly stale
        m8_1 = {"generated_at_utc": old_ts}
        payload = build_m9_current_payload(artifact={}, m8_1_artifact=m8_1, now_utc=_now())
        assert payload["m8_1_inventory"]["is_stale"] is True

    def test_prequote_min_bps_exposed(self):
        """prequote_min_bps in infra_telemetry is forwarded to infra_quality."""
        from monitoring.dashboard_server import build_m9_current_payload
        a = _minimal_m9_artifact(
            infra_telemetry={"prequote_min_bps": -9999.0}
        )
        payload = build_m9_current_payload(artifact=a, now_utc=_now(), file_age_s=5)
        assert payload["infra_quality"]["prequote_min_bps"] == pytest.approx(-9999.0)

    def test_top_failed_opportunities_key_always_present(self):
        """top_failed_opportunities key must always be present even when empty."""
        from monitoring.dashboard_server import build_m9_current_payload
        payload = build_m9_current_payload(artifact={}, now_utc=_now())
        assert "top_failed_opportunities" in payload
        assert isinstance(payload["top_failed_opportunities"], list)

    def test_start_pipeline_control_plane_embedded(self):
        from monitoring.dashboard_server import build_m9_current_payload
        payload = build_m9_current_payload(artifact={}, now_utc=_now())
        assert "start_pipeline" in payload
        sp = payload["start_pipeline"]
        assert sp["schema_family"] == "start_pipeline_control_plane"
        assert "checkpoint_progress" in sp

    def test_build_pipeline_control_plane_idle(self):
        from monitoring.dashboard_server import build_pipeline_control_plane
        payload = build_pipeline_control_plane(now_utc=_now())
        assert payload["schema_family"] == "start_pipeline_control_plane"
        assert "step_markers" in payload

    def test_build_pipeline_control_plane_stale_heartbeat(self):
        import json
        import tempfile
        from pathlib import Path

        from monitoring.dashboard_server import (
            PIPELINE_CURRENT_PATH,
            build_pipeline_control_plane,
        )

        stale_ts = "2020-01-01T00:00:00+00:00"
        doc = {
            "mode": "time_to_mirror",
            "step": "m8_2_radar_two_phase",
            "pid": 12345,
            "started_at": stale_ts,
            "last_heartbeat": stale_ts,
            "status": "running",
            "heartbeat_stale_s": 60,
            "checkpoint_progress": {"done_count": 0, "failed_count": 0},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "start_pipeline_current.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            orig = PIPELINE_CURRENT_PATH
            try:
                import monitoring.dashboard_server as ds

                ds.PIPELINE_CURRENT_PATH = path
                payload = build_pipeline_control_plane(now_utc=_now())
                assert payload["stale"] is True
                assert payload["stale_reason"] is not None
                assert "heartbeat_silent" in payload["stale_reason"]
            finally:
                ds.PIPELINE_CURRENT_PATH = orig
