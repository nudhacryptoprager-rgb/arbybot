"""E1.77 unit tests: MAV+lag wiring into cold scorer rank key,
bridge identity normalization, heatmap staleness, pending-sim helper."""
from __future__ import annotations

import os
from typing import Any, Dict


def _entry_with_curve(net_bps: float = 100.0, size_usd: float = 50.0,
                     secs: int = 30, divergence: float = 80.0) -> Dict[str, Any]:
    return {
        "pool_address": "0x" + "a" * 40,
        "net_bps": net_bps,
        "size_usd_estimate": size_usd,
        "depth_curve": [
            {"size_usd": 10.0, "expected_profit_usd": 0.10},
            {"size_usd": 25.0, "expected_profit_usd": 0.30},
            {"size_usd": 50.0, "expected_profit_usd": 0.55},
            {"size_usd": 100.0, "expected_profit_usd": 0.45},
        ],
        "seconds_since_last_swap": secs,
        "price_divergence_bps": divergence,
    }


def test_rank_key_lag_boost_amplifies_stale_divergence():
    """E1.77: an entry with same MAV but more lag/divergence ranks higher.

    `lag_score` is intentionally larger when the pool is stale + price has
    diverged — that's the arb-opportunity signal.  The rank key multiplies
    the base profit by ``1 + lag/100`` so a stale pool outranks a fresh one
    when both carry the same depth curve.
    """
    from m7.orderflow.cold_immediate_sim import _entry_rank_key

    fresh = _entry_with_curve(net_bps=100.0, size_usd=50.0, secs=5,
                              divergence=10.0)
    stale = _entry_with_curve(net_bps=100.0, size_usd=50.0, secs=600,
                              divergence=80.0)
    fresh["pool_address"] = "0x" + "1" * 40
    stale["pool_address"] = "0x" + "2" * 40
    rk_fresh = _entry_rank_key(fresh)
    rk_stale = _entry_rank_key(stale)
    assert rk_stale > rk_fresh, (rk_fresh, rk_stale)


def test_rank_key_stashes_mav_lag_fields_inplace():
    """The rank key must enrich the entry with mav_usd/best_size_usd/lag_score."""
    from m7.orderflow.cold_immediate_sim import _entry_rank_key

    e = _entry_with_curve()
    _entry_rank_key(e)
    assert "mav_usd" in e
    assert "best_size_usd" in e
    assert "lag_score" in e
    assert e["mav_usd"] >= 0.0
    assert e["best_size_usd"] >= 0.0
    assert 0.0 <= e["lag_score"] <= 100.0


def test_rank_key_falls_back_to_expected_profit_when_no_curve():
    from m7.orderflow.cold_immediate_sim import _entry_rank_key

    e = {"pool_address": "0xabc", "net_bps": 50.0, "size_usd_estimate": 100.0}
    rk = _entry_rank_key(e)
    # expected_profit_usd = 100 * 50/10000 = 0.5 (×lag boost ≥1.0)
    assert rk >= 0.5


def test_rank_key_pure_bps_fallback():
    from m7.orderflow.cold_immediate_sim import _entry_rank_key

    e = {"pool_address": "0xabc", "net_bps": 200.0}
    rk = _entry_rank_key(e)
    assert rk > 0.0
    assert rk < 0.01  # scaled tiny


def test_bridge_identity_normalization_fills_pair_dex_fee():
    """Bridge writer must populate pair/pool_in/pool_out/dex/fee/source."""
    import json
    from pathlib import Path
    import tempfile

    # Stage a fake artifact dict + write bridge to tempdir.
    from m7.orderflow import bridge_runtime, runtime_io

    artifact = {
        "top_executable_candidates": [
            {
                "pool_address": "0x" + "1" * 40,
                "actual_pair": "FUN/USDC",
                "fee_tier": 3000,
                "amount_in_optimal_usd": 12.5,
                "net_bps": 80.0,
            },
            {
                "pool_address": "0x" + "2" * 40,
                "token_in_symbol": "WETH",
                "token_out_symbol": "USDC",
                "best_buy_fee": 500,
                "amount_in_optimal_usd": 0.05,
                "net_bps": 250.0,
                "dex_name": "uniswap_v3",
            },
        ],
    }
    with tempfile.TemporaryDirectory() as td:
        # Redirect bridge path
        orig = runtime_io._COLD_HOT_BRIDGE_PATH
        new_path = os.path.join(td, "bridge.json")
        runtime_io._COLD_HOT_BRIDGE_PATH = new_path
        try:
            bridge_runtime._write_cold_hot_bridge(artifact, {})
            with open(new_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        finally:
            runtime_io._COLD_HOT_BRIDGE_PATH = orig

    cold = payload["cold_executable"]
    assert len(cold) == 2
    for c in cold:
        assert c.get("pair"), f"pair missing for {c}"
        assert c.get("pool_in")
        assert c.get("pool_out")
        assert c.get("dex")
        assert c.get("fee") is not None
        assert c.get("source") == "cold_bridge"
    # Pair preserved/derived correctly.
    pairs = sorted(c["pair"] for c in cold)
    assert "FUN/USDC" in pairs
    assert "WETH/USDC" in pairs


def test_pending_sim_helpers_env_gated():
    """pending_sim_enabled is OFF by default; pending_eth_call returns None."""
    from chains import flashblocks_http

    saved = {
        k: os.environ.pop(k, None)
        for k in ("ARBY_FLASHBLOCKS_HTTP_LANE", "ARBY_PENDING_SIM_ENABLE")
    }
    try:
        assert flashblocks_http.pending_sim_enabled() is False
        # OFF -> returns None even with a working transport
        called = []

        def fake_post(url, payload, t):
            called.append(payload)
            return {"jsonrpc": "2.0", "id": 1, "result": "0xdeadbeef"}

        out = flashblocks_http.pending_eth_call(
            rpc_url="http://x", to="0xabc", data="0x00", http_post=fake_post
        )
        assert out is None
        assert called == []  # transport never invoked when disabled
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_pending_sim_helpers_when_enabled():
    """When both flags are ON, pending_eth_call invokes transport and returns result."""
    from chains import flashblocks_http

    saved = {
        k: os.environ.get(k)
        for k in ("ARBY_FLASHBLOCKS_HTTP_LANE", "ARBY_PENDING_SIM_ENABLE")
    }
    try:
        os.environ["ARBY_FLASHBLOCKS_HTTP_LANE"] = "1"
        os.environ["ARBY_PENDING_SIM_ENABLE"] = "1"
        assert flashblocks_http.pending_sim_enabled() is True
        captured = []

        def fake_post(url, payload, t):
            captured.append(payload)
            return {"jsonrpc": "2.0", "id": 1, "result": "0x42"}

        out = flashblocks_http.pending_eth_call(
            rpc_url="http://x", to="0xpool", data="0xfeed", http_post=fake_post
        )
        assert out == "0x42"
        assert captured and captured[0]["method"] == "eth_call"
        # Block tag is "pending" by default.
        params = captured[0]["params"]
        assert params[1] == "pending"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_default_cold_ws_timeout_is_240():
    """E1.77 step 7: default cold-ws-timeout lowered 900→240."""
    import argparse
    import importlib

    mod = importlib.import_module("scripts.start_nonstop_runtime")
    # Locate the build_arg_parser by inspecting source for default value.
    import inspect

    src = inspect.getsource(mod)
    assert 'm7-cold-ws-timeout", type=int, default=240' in src, (
        "default --m7-cold-ws-timeout must be 240 in E1.77"
    )


def test_heatmap_response_includes_staleness(monkeypatch):
    """Dashboard heatmap response must expose staleness fields."""
    # Smoke test: directly invoke the staleness-builder logic via reading the
    # source — we don't spin up the full HTTP server in unit tests.
    import inspect
    from monitoring import dashboard_server

    src = inspect.getsource(dashboard_server.DashboardHandler._serve_pair_family_heatmap)
    for key in (
        '"bridge_age_s"',
        '"matrix_age_s"',
        '"pool_age_s"',
        '"price_age_s"',
        '"volume_age_s"',
        '"scout_age_s"',
        '"staleness"',
    ):
        assert key in src, f"heatmap missing staleness key {key}"
