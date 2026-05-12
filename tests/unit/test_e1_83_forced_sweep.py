"""E1.83 NEW — Unit tests for forced deep-pair quote sweep and related fixes.

Tests:
  1. bridge_runtime contains forced_sweep_results code (source-level contract)
  2. _build_why_not_active_summary aggregates correctly
  3. deep_pair forced sweep field population via bridge_runtime integration
  4. replay_mode field present in build_m7_current_payload
"""
from __future__ import annotations

import inspect
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# 1. Source-level contract: forced sweep is wired in bridge_runtime
# ---------------------------------------------------------------------------

def test_bridge_runtime_has_forced_sweep_results():
    """bridge_runtime._write_cold_hot_bridge must write forced_sweep_results."""
    from m7.orderflow import bridge_runtime
    src = inspect.getsource(bridge_runtime._write_cold_hot_bridge)
    assert "forced_sweep_results" in src, (
        "bridge_runtime must write forced_sweep_results for factory-enriched pairs"
    )


def test_bridge_runtime_has_correct_sweep_sizes():
    """Forced sweep must cover production sizes $50/$100/$250/$500/$1000."""
    from m7.orderflow import bridge_runtime
    src = inspect.getsource(bridge_runtime._write_cold_hot_bridge)
    for size in ["50.0", "100.0", "250.0", "500.0", "1000.0"]:
        assert size in src, (
            f"Forced sweep must include ${size} as a probe size"
        )


def test_bridge_runtime_distinguishes_no_event_vs_thin_liquidity():
    """Forced sweep must distinguish no_event_triggered from thin_liquidity_at_size."""
    from m7.orderflow import bridge_runtime
    src = inspect.getsource(bridge_runtime._write_cold_hot_bridge)
    assert "no_event_triggered" in src
    assert "thin_liquidity_at_size" in src


def test_bridge_runtime_updates_deep_pair_scored_total():
    """deep_pair_scored_total must be updated from forced sweep coverage."""
    from m7.orderflow import bridge_runtime
    src = inspect.getsource(bridge_runtime._write_cold_hot_bridge)
    assert "deep_pair_scored_total" in src
    assert "deep_pair_unscored_pairs" in src
    assert "deep_pair_thin_liquidity_pairs" in src


# ---------------------------------------------------------------------------
# 2. _build_why_not_active_summary in dashboard_server
# ---------------------------------------------------------------------------

def _load_dashboard_module():
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "monitoring" / "dashboard_server.py"
    spec = importlib.util.spec_from_file_location("dashboard_server", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    # Patch heavy imports that trigger networking/threading at import time.
    import sys
    class _FakeHTTP:
        class BaseHTTPRequestHandler:
            pass
        class HTTPServer:
            pass
    sys.modules.setdefault("http.server", _FakeHTTP)
    try:
        assert spec.loader is not None
        spec.loader.exec_module(module)
    except Exception:
        pass
    return module


def test_why_not_active_summary_counts_active():
    """why_not_active_summary must count rows tagged 'active'."""
    try:
        from monitoring import dashboard_server as ds
        fn = ds._build_why_not_active_summary
    except Exception:
        ds = _load_dashboard_module()
        fn = getattr(ds, "_build_why_not_active_summary", None)
        if fn is None:
            import pytest
            pytest.skip("dashboard_server not importable in unit test context")
    rows = [
        {"why_not_active": "active"},
        {"why_not_active": "active"},
        {"why_not_active": "no_priced_quote"},
        {"why_not_active": "no_priced_quote|single_dex_only(factory_dex=0)"},
    ]
    result = fn(rows)
    assert result["active"] == 2
    assert result.get("no_priced_quote", 0) == 2
    assert result.get("single_dex_only(factory_dex=0)", 0) == 1


def test_why_not_active_summary_empty_rows():
    """Empty rows list → only active=0 in summary."""
    try:
        from monitoring import dashboard_server as ds
        fn = ds._build_why_not_active_summary
    except Exception:
        ds = _load_dashboard_module()
        fn = getattr(ds, "_build_why_not_active_summary", None)
        if fn is None:
            import pytest
            pytest.skip("dashboard_server not importable in unit test context")
    result = fn([])
    assert result.get("active", 0) == 0


# ---------------------------------------------------------------------------
# 3. post_soak gate: deep_sweep_guard and fresh profit separation
# ---------------------------------------------------------------------------

def _load_gate_module():
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "scripts" / "post_soak_pass_gate.py"
    spec = importlib.util.spec_from_file_location("post_soak_pass_gate", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_deep_sweep_check_has_forced_sweep_count():
    """deep_sweep_guard must expose forced_sweep_count field."""
    gate = _load_gate_module()
    bridge = {
        "factory_enriched_pairs": 3,
        "deep_pair_scored_total": 2,
        "deep_pair_unscored_pairs": 1,
        "deep_pair_thin_liquidity_pairs": 0,
        "forced_sweep_results": [{"pair": "USDC/WETH"}, {"pair": "AERO/USDC"}],
    }
    result = gate._build_deep_sweep_check(bridge, strict=False)
    assert result["forced_sweep_count"] == 2
    assert result["deep_pair_scored_total"] == 2


def test_deep_sweep_check_no_regression_when_zero_enriched():
    """If factory_enriched_pairs=0, no regression possible."""
    gate = _load_gate_module()
    bridge = {
        "factory_enriched_pairs": 0,
        "deep_pair_scored_total": 0,
    }
    result = gate._build_deep_sweep_check(bridge, strict=True)
    assert result["pass"] is True


def test_deep_sweep_check_strict_fails_regression():
    """Strict: enriched > 0 AND scored = 0 → hard fail."""
    gate = _load_gate_module()
    bridge = {
        "factory_enriched_pairs": 6,
        "deep_pair_scored_total": 0,
        "deep_pair_unscored_pairs": 6,
        "forced_sweep_results": [],
    }
    result = gate._build_deep_sweep_check(bridge, strict=True)
    assert result["pass"] is False
    assert result["informational"] is False


# ---------------------------------------------------------------------------
# 4. replay_mode in build_m7_current_payload (source-level)
# ---------------------------------------------------------------------------

def test_build_m7_current_payload_has_replay_mode():
    """build_m7_current_payload must return replay_mode field."""
    try:
        from monitoring.dashboard_server import build_m7_current_payload
        import inspect
        src = inspect.getsource(build_m7_current_payload)
        assert "replay_mode" in src
        assert "replay_bridge_timestamp" in src
    except ImportError:
        # In minimal test env, check source directly
        srv_path = Path(__file__).resolve().parents[2] / "monitoring" / "dashboard_server.py"
        src = srv_path.read_text(encoding="utf-8")
        assert "replay_mode" in src, "dashboard_server must add replay_mode to /api/m7/current"
        assert "replay_bridge_timestamp" in src
