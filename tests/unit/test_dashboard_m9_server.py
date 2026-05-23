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
        assert payload["schema_revision"] == "m9_dashboard.2"
