"""M7.E1.51 slice-4 — tests for replay_v3_state_drift harness."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _u256_hex(val: int) -> str:
    return f"{val & ((1 << 256) - 1):064x}"


def _i256_hex(val: int) -> str:
    if val < 0:
        val = (1 << 256) + val
    return _u256_hex(val)


def _build_swap_log(pool: str, *, block: int, log_index: int, sqrt: int, liq: int, tick: int) -> dict:
    data = (
        _i256_hex(0)  # amount0
        + _i256_hex(0)  # amount1
        + _u256_hex(sqrt)
        + _u256_hex(liq)
        + _i256_hex(tick)
    )
    return {
        "address": pool,
        "blockNumber": block,
        "logIndex": log_index,
        "data": "0x" + data,
        "transactionHash": "0x" + "33" * 32,
    }


@pytest.fixture
def harness():
    """Load scripts/replay_v3_state_drift.py as a module by file path."""
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "replay_v3_state_drift.py"
    spec = importlib.util.spec_from_file_location("replay_v3_state_drift", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_perfect_match_pass(harness):
    pool = "0xpool" + "0" * 36
    sqrt = 79228162514264337593543950336  # 1.0 in Q96
    liq = 1_000_000
    bundle = {
        "chain": "base",
        "logs": [_build_swap_log(pool, block=10, log_index=0, sqrt=sqrt, liq=liq, tick=0)],
        "ground_truth": {pool: {"block_number": 10, "sqrt_price_x96": sqrt, "tick": 0, "liquidity": liq}},
    }
    out = harness.replay_drift(bundle)
    assert out["verdict"] == "PASS"
    assert out["pools_matched"] == 1
    assert out["pools_drift"] == 0
    assert out["drift_pools_pct"] == 0.0
    assert out["max_sqrt_price_drift_bps"] == 0.0


def test_missing_pool_in_state_fails(harness):
    bundle = {
        "chain": "base",
        "logs": [],
        "ground_truth": {
            "0xmissing" + "0" * 34: {"block_number": 1, "sqrt_price_x96": 1, "tick": 0, "liquidity": 1}
        },
    }
    out = harness.replay_drift(bundle)
    assert out["verdict"] == "FAIL"
    assert out["pools_drift"] == 1


def test_drift_above_threshold_fails(harness):
    pool = "0xdrift" + "0" * 35
    sqrt = 1_000_000
    bundle = {
        "chain": "base",
        "logs": [_build_swap_log(pool, block=1, log_index=0, sqrt=sqrt, liq=1, tick=0)],
        # ground truth claims a different sqrt -> bps drift
        "ground_truth": {pool: {"block_number": 1, "sqrt_price_x96": 1_010_000, "tick": 0, "liquidity": 1}},
    }
    out = harness.replay_drift(bundle)
    assert out["verdict"] == "FAIL"
    assert out["max_sqrt_price_drift_bps"] > 5.0


def test_latest_log_per_pool_used(harness):
    pool = "0xlatest" + "0" * 34
    bundle = {
        "chain": "base",
        "logs": [
            _build_swap_log(pool, block=1, log_index=0, sqrt=111, liq=1, tick=0),
            _build_swap_log(pool, block=2, log_index=0, sqrt=222, liq=2, tick=1),
        ],
        "ground_truth": {pool: {"block_number": 2, "sqrt_price_x96": 222, "tick": 1, "liquidity": 2}},
    }
    out = harness.replay_drift(bundle)
    assert out["verdict"] == "PASS"


def test_empty_truth_pass(harness):
    out = harness.replay_drift({"chain": "base", "logs": [], "ground_truth": {}})
    assert out["verdict"] == "PASS"
    assert out["pools_total"] == 0
