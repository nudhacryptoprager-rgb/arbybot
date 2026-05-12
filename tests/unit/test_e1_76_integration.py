"""E1.76 integration tests: bridge wiring, dashboard heatmap endpoint, strict pass gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


# -----------------------------------------------------------------------------
# Pass-gate strict mode (E1.76 step 10)
# -----------------------------------------------------------------------------

def _write_artifacts(rolling_dir: Path, *, best_amount: float, prod_total: int = 1) -> None:
    rolling_dir.mkdir(parents=True, exist_ok=True)
    bridge = {
        "production_sized_candidate_total": prod_total,
        "cold_executable": [
            {
                "amount_in_optimal_usd": best_amount,
                "expected_profit_usd": 1.0,
                "pair": "USDC/WETH",
            }
        ],
        # E1.83 fix #2/#6: strict-mode factory_enriched_guard requires loaded truth.
        "factory_truth_loaded": True,
        "factory_enriched_pairs": 1,
        "factory_truth_age_s": 60.0,
        # E1.83 NEW: strict-mode deep_sweep_guard requires deep_pair_scored_total > 0
        # when factory_enriched_pairs > 0.
        "deep_pair_scored_total": 1,
    }
    rollup = {
        "production_sized_candidate_total": prod_total,
        "current_session_delta": {
            "roundtrip_profitable_total": 5,
            "submit_ready_total": 5,
        },
        "windows_seen": 100,
        "session_ws_failed_429_windows": 0,
    }
    (rolling_dir / "m7_cold_hot_bridge.json").write_text(
        json.dumps(bridge), encoding="utf-8"
    )
    (rolling_dir / "m7_hot_rollup_latest.json").write_text(
        json.dumps(rollup), encoding="utf-8"
    )


def _run_gate(rolling_dir: Path, *extra_args: str) -> tuple[int, dict]:
    env = os.environ.copy()
    env["ARBY_GATE_ROLLING_DIR"] = str(rolling_dir)
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "post_soak_pass_gate.py"), *extra_args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    try:
        report = json.loads(proc.stdout)
    except Exception:
        report = {}
    return proc.returncode, report


def test_strict_flag_rejects_dust_below_50():
    with tempfile.TemporaryDirectory() as td:
        rolling = Path(td) / "_rolling"
        _write_artifacts(rolling, best_amount=49.995)
        rc_default, rep_default = _run_gate(rolling)
        rc_strict, rep_strict = _run_gate(rolling, "--strict")
    # Default: dust tolerance applied -> best_amount_in_usd PASS.
    assert rep_default["checks"]["best_amount_in_usd"]["pass"] is True
    # Strict: zero tolerance -> FAIL on $49.995 < $50.
    assert rep_strict["checks"]["best_amount_in_usd"]["pass"] is False
    assert rep_strict["strict"] is True
    assert rc_strict == 1


def test_strict_flag_accepts_exact_50_or_above():
    with tempfile.TemporaryDirectory() as td:
        rolling = Path(td) / "_rolling"
        _write_artifacts(rolling, best_amount=50.0)
        rc, rep = _run_gate(rolling, "--strict")
    assert rep["checks"]["best_amount_in_usd"]["pass"] is True
    assert rc == 0


# -----------------------------------------------------------------------------
# Bridge wiring (E1.76 steps 1, 6, 8)
# -----------------------------------------------------------------------------

def test_bridge_runtime_pair_pool_matrix_block_present():
    """The bridge_runtime module must reference pair_pool_matrix wiring."""
    src = (REPO_ROOT / "m7" / "orderflow" / "bridge_runtime.py").read_text(encoding="utf-8")
    assert "pair_pool_matrix" in src
    assert "build_pair_pool_matrix" in src
    assert "ARBY_PAIR_POOL_MATRIX_ENABLE" in src
    assert "flashblocks_pending_ready" in src
    assert "defillama_volume_scout" in src or "DEFILLAMA_VOLUME_SCOUT" in src


# -----------------------------------------------------------------------------
# Dashboard heatmap endpoint (E1.76 step 9)
# -----------------------------------------------------------------------------

def test_dashboard_has_pair_family_heatmap_endpoint():
    src = (REPO_ROOT / "monitoring" / "dashboard_server.py").read_text(encoding="utf-8")
    assert "/api/m7/pair_family_heatmap" in src
    assert "_serve_pair_family_heatmap" in src
    assert "depth_ladder" in src or "build_depth_ladder" in src


def test_dashboard_heatmap_builder_logic_uses_matrix_and_curves():
    """Sanity-check the in-process heatmap-row construction without HTTP."""
    from m7.orderflow.depth_ladder import build_depth_ladder, mav_estimate_usd, lag_score
    from m7.scouts.pair_pool_matrix import build_pair_pool_matrix

    pools = [
        {"symbol": "WETH-USDC", "pool_address": "0x1", "project": "uniswap-v3",
         "tvl_usd": 1_000.0, "volume_24h_usd": 100.0, "fee_tier": 500},
        {"symbol": "WETH-USDC", "pool_address": "0x2", "project": "aerodrome-v1",
         "tvl_usd": 500.0, "volume_24h_usd": 50.0},
    ]
    matrix = build_pair_pool_matrix(pools)
    assert matrix["summary"]["pair_count"] == 1
    family = matrix["pairs"][0]
    curve = [
        {"size_usd": 10, "expected_profit_usd": 0.1},
        {"size_usd": 100, "expected_profit_usd": 1.0},
    ]
    mav = mav_estimate_usd(curve)
    ladder = build_depth_ladder(curve)
    score = lag_score(seconds_since_last_swap=120, price_divergence_bps=15)
    row = {
        "pair": family["pair"],
        "pool_count": family["pool_count"],
        "dex_count": family["dex_count"],
        "tvl_total_usd": family["tvl_total_usd"],
        "best_pool": family["best_pool"],
        "depth_ladder": ladder,
        "mav_usd": mav["mav_usd"],
        "best_size_usd": mav["best_size_usd"],
        "lag_score": score,
    }
    assert row["pair"] == "USDC/WETH"
    assert row["pool_count"] == 2
    assert row["dex_count"] == 2
    assert row["mav_usd"] == 1.0
    assert row["best_size_usd"] == 100.0
    assert 0.0 < row["lag_score"] <= 100.0
