"""Unit tests for new infra telemetry fields in M9 artifact schema.

Validates that build_artifact accepts and correctly serialises:
  - quote_backend, quote_workers
  - provider_throttle_snapshot / http_429_count
  - ws_freshness
"""
from __future__ import annotations

import pytest

from m9.graph_arb.artifacts import build_artifact
from m9.graph_arb.models import GraphTopology


# ---------------------------------------------------------------------------
# Minimal stubs for build_artifact call
# ---------------------------------------------------------------------------

def _make_topology() -> GraphTopology:
    return GraphTopology(
        token_count=3,
        edge_count=6,
        route_count=2,
        hub_tokens=["USDC"],
        dead_end_tokens=[],
        missing_edges_for_3cycle=[],
        adjacency_summary={},
    )


def _base_kwargs() -> dict:
    return dict(
        chain="base",
        duration_minutes=1.0,
        cycle_results=[],
        topology=_make_topology(),
        sizes_usd=(1000.0,),
        run_timestamp="2025-01-01T00:00:00Z",
        started_at_mono=0.0,
        elapsed_s=60.0,
    )


# ---------------------------------------------------------------------------
# Tests: infra_telemetry block always present
# ---------------------------------------------------------------------------

class TestInfraTelemetryDefaults:

    def test_infra_telemetry_key_present(self):
        art = build_artifact(**_base_kwargs())
        assert "infra_telemetry" in art

    def test_default_quote_backend_is_direct_http(self):
        art = build_artifact(**_base_kwargs())
        assert art["infra_telemetry"]["quote_backend"] == "direct_http"

    def test_default_quote_workers_is_4(self):
        art = build_artifact(**_base_kwargs())
        assert art["infra_telemetry"]["quote_workers"] == 4

    def test_default_http_429_count_is_0(self):
        art = build_artifact(**_base_kwargs())
        assert art["infra_telemetry"]["http_429_count"] == 0

    def test_default_provider_throttle_snapshot_is_none(self):
        art = build_artifact(**_base_kwargs())
        assert art["infra_telemetry"]["provider_throttle_snapshot"] is None

    def test_ws_freshness_absent_when_not_provided(self):
        art = build_artifact(**_base_kwargs())
        assert "ws_freshness" not in art["infra_telemetry"]


# ---------------------------------------------------------------------------
# Tests: explicit infra telemetry values are preserved
# ---------------------------------------------------------------------------

class TestInfraTelemetryExplicit:

    def test_raw_http_backend_stored(self):
        art = build_artifact(**_base_kwargs(), quote_backend="raw_http")
        assert art["infra_telemetry"]["quote_backend"] == "raw_http"

    def test_anvil_fork_backend_stored(self):
        art = build_artifact(**_base_kwargs(), quote_backend="anvil_fork")
        assert art["infra_telemetry"]["quote_backend"] == "anvil_fork"

    def test_quote_workers_stored(self):
        art = build_artifact(**_base_kwargs(), quote_workers=1)
        assert art["infra_telemetry"]["quote_workers"] == 1

    def test_provider_throttle_snapshot_stored(self):
        snap = {
            "calls": {
                "total_429": 42,
                "total_408": 3,
                "total_ok": 100,
                "breaker_open": False,
                "cooldown_remaining_s": 0.0,
            }
        }
        art = build_artifact(**_base_kwargs(), provider_throttle_snapshot=snap)
        assert art["infra_telemetry"]["provider_throttle_snapshot"] == snap
        # http_429_count derived from calls bucket
        assert art["infra_telemetry"]["http_429_count"] == 42

    def test_http_429_count_zero_when_no_429s(self):
        snap = {"calls": {"total_429": 0, "total_ok": 50}}
        art = build_artifact(**_base_kwargs(), provider_throttle_snapshot=snap)
        assert art["infra_telemetry"]["http_429_count"] == 0

    def test_http_429_count_missing_calls_key(self):
        """If snapshot has no 'calls' key, http_429_count defaults to 0."""
        snap = {"logs": {"total_429": 5}}
        art = build_artifact(**_base_kwargs(), provider_throttle_snapshot=snap)
        assert art["infra_telemetry"]["http_429_count"] == 0

    def test_ws_freshness_stored(self):
        ws = {
            "connected": True,
            "latest_block": 1234567,
            "block_age_s": 2.3,
            "stale": False,
            "error": None,
        }
        art = build_artifact(**_base_kwargs(), ws_freshness=ws)
        assert art["infra_telemetry"]["ws_freshness"] == ws

    def test_ws_freshness_none_not_stored(self):
        art = build_artifact(**_base_kwargs(), ws_freshness=None)
        assert "ws_freshness" not in art["infra_telemetry"]


# ---------------------------------------------------------------------------
# Tests: backward compat — existing callers without infra params still work
# ---------------------------------------------------------------------------

def test_build_artifact_no_infra_params_no_error():
    """Callers that do not pass infra params must not break."""
    art = build_artifact(**_base_kwargs())
    assert art["schema_family"] == "m9_graph_arb"
    assert "infra_telemetry" in art


def test_build_artifact_all_infra_params():
    """Callers that pass all infra params get a fully populated block."""
    snap = {"calls": {"total_429": 10, "total_ok": 200}}
    ws = {"connected": True, "latest_block": 99, "block_age_s": 1.0, "stale": False, "error": None}
    art = build_artifact(
        **_base_kwargs(),
        quote_backend="raw_http",
        quote_workers=2,
        provider_throttle_snapshot=snap,
        ws_freshness=ws,
    )
    it = art["infra_telemetry"]
    assert it["quote_backend"] == "raw_http"
    assert it["quote_workers"] == 2
    assert it["http_429_count"] == 10
    assert it["provider_throttle_snapshot"] == snap
    assert it["ws_freshness"] == ws


# ---------------------------------------------------------------------------
# Tests: ws_monitor module is importable and snapshot() returns dict
# ---------------------------------------------------------------------------

def test_ws_monitor_importable():
    from m9.graph_arb.ws_monitor import WsMonitor, start_ws_monitor
    assert callable(start_ws_monitor)
    monitor = WsMonitor()
    snap = monitor.snapshot()
    assert isinstance(snap, dict)
    assert "connected" in snap
    assert snap["connected"] is False  # not started


def test_ws_monitor_snapshot_not_stale_when_no_data():
    from m9.graph_arb.ws_monitor import WsMonitor
    monitor = WsMonitor()
    snap = monitor.snapshot()
    assert snap["block_age_s"] is None  # no data yet
    assert snap["stale"] is False  # can't be stale with no data


# ---------------------------------------------------------------------------
# Tests: quoter backend constants are stable
# ---------------------------------------------------------------------------

def test_quoter_backend_constants():
    from m9.graph_arb.quoter import (
        BACKEND_DIRECT_HTTP,
        BACKEND_RAW_HTTP,
        BACKEND_ANVIL_FORK,
        _VALID_BACKENDS,
    )
    assert BACKEND_DIRECT_HTTP == "direct_http"
    assert BACKEND_RAW_HTTP == "raw_http"
    assert BACKEND_ANVIL_FORK == "anvil_fork"
    assert "direct_http" in _VALID_BACKENDS
    assert "raw_http" in _VALID_BACKENDS
    assert "anvil_fork" in _VALID_BACKENDS


def test_schedule_cycle_quotes_accepts_backend_params():
    """schedule_cycle_quotes signature must accept max_workers, quote_backend, rpc_url."""
    import inspect
    from m9.graph_arb.quoter import schedule_cycle_quotes
    sig = inspect.signature(schedule_cycle_quotes)
    params = sig.parameters
    assert "max_workers" in params
    assert "quote_backend" in params
    assert "rpc_url" in params
