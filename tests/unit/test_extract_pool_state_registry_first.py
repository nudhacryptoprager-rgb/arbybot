"""M7.E1.51 slice-3b — registry-first lookup in extract_pool_state_for_sim."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from m7.orderflow.pool_price_state import (
    PoolPriceStateRegistry,
    get_registry,
    reset_registry_for_tests,
)
from m7.orderflow import resolve


def _u256_hex(val: int) -> str:
    return f"{val & ((1 << 256) - 1):064x}"


def _build_swap_log(pool: str, *, sqrt: int, liq: int, tick: int) -> dict:
    data = (
        _u256_hex(0)
        + _u256_hex(0)
        + _u256_hex(sqrt)
        + _u256_hex(liq)
        + _u256_hex(tick)
    )
    return {
        "address": pool,
        "blockNumber": 1000,
        "logIndex": 0,
        "data": "0x" + data,
        "transactionHash": "0x" + "44" * 32,
    }


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()
    os.environ.pop("ARBY_REGISTRY_FIRST_POOL_STATE", None)


def test_default_behavior_unchanged_uses_multicall():
    # No env, no chain -> legacy path (multicall)
    pool = "0xpool" + "0" * 36
    expected = {pool.lower(): {"sqrt_price_x96": 1, "tick": 0, "liquidity": 1}}
    with patch("core.multicall.get_multicall_batcher") as m:
        m.return_value.batch_full_pool_data.return_value = expected
        out = resolve.extract_pool_state_for_sim([pool], "http://x", 100)
    assert out == expected
    m.return_value.batch_full_pool_data.assert_called_once()


def test_env_off_chain_provided_still_uses_multicall():
    pool = "0xpool" + "0" * 36
    os.environ["ARBY_REGISTRY_FIRST_POOL_STATE"] = "0"
    get_registry().update_from_v3_log("base", _build_swap_log(pool, sqrt=999, liq=999, tick=5))
    with patch("core.multicall.get_multicall_batcher") as m:
        m.return_value.batch_full_pool_data.return_value = {pool.lower(): {"x": 1}}
        out = resolve.extract_pool_state_for_sim([pool], "http://x", 100, chain="base")
    m.return_value.batch_full_pool_data.assert_called_once()


def test_registry_hit_skips_multicall():
    pool = "0xPooLAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1234"
    os.environ["ARBY_REGISTRY_FIRST_POOL_STATE"] = "1"
    get_registry().update_from_v3_log("base", _build_swap_log(pool, sqrt=12345, liq=678, tick=-3))
    with patch("core.multicall.get_multicall_batcher") as m:
        out = resolve.extract_pool_state_for_sim([pool], "http://x", 100, chain="base")
    m.assert_not_called()
    assert out[pool.lower()]["sqrt_price_x96"] == 12345
    assert out[pool.lower()]["tick"] == -3
    assert out[pool.lower()]["liquidity"] == 678
    assert out[pool.lower()]["source"] == "local_registry"


def test_registry_miss_falls_back_to_multicall():
    pool = "0xcold" + "0" * 36
    os.environ["ARBY_REGISTRY_FIRST_POOL_STATE"] = "1"
    fallback = {pool.lower(): {"sqrt_price_x96": 7, "tick": 0, "liquidity": 1}}
    with patch("core.multicall.get_multicall_batcher") as m:
        m.return_value.batch_full_pool_data.return_value = fallback
        out = resolve.extract_pool_state_for_sim([pool], "http://x", 100, chain="base")
    m.return_value.batch_full_pool_data.assert_called_once()
    args, _ = m.return_value.batch_full_pool_data.call_args
    assert args[0] == [pool]
    assert out[pool.lower()]["sqrt_price_x96"] == 7


def test_partial_hit_only_misses_go_to_multicall():
    hot = "0xHot1" + "0" * 36
    cold = "0xCold" + "0" * 35
    os.environ["ARBY_REGISTRY_FIRST_POOL_STATE"] = "1"
    get_registry().update_from_v3_log("base", _build_swap_log(hot, sqrt=111, liq=222, tick=1))
    with patch("core.multicall.get_multicall_batcher") as m:
        m.return_value.batch_full_pool_data.return_value = {
            cold.lower(): {"sqrt_price_x96": 999, "tick": 9, "liquidity": 9}
        }
        out = resolve.extract_pool_state_for_sim([hot, cold], "http://x", 100, chain="base")
    args, _ = m.return_value.batch_full_pool_data.call_args
    assert args[0] == [cold]  # only cold pool went to multicall
    assert out[hot.lower()]["source"] == "local_registry"
    assert out[hot.lower()]["sqrt_price_x96"] == 111
    assert out[cold.lower()]["sqrt_price_x96"] == 999


def test_empty_input_short_circuits():
    os.environ["ARBY_REGISTRY_FIRST_POOL_STATE"] = "1"
    with patch("core.multicall.get_multicall_batcher") as m:
        out = resolve.extract_pool_state_for_sim([], "http://x", 100, chain="base")
    assert out == {}
    m.assert_not_called()


def test_multicall_failure_returns_none_for_cold():
    pool = "0xcold" + "0" * 36
    os.environ["ARBY_REGISTRY_FIRST_POOL_STATE"] = "1"
    with patch("core.multicall.get_multicall_batcher") as m:
        m.return_value.batch_full_pool_data.side_effect = RuntimeError("rpc down")
        out = resolve.extract_pool_state_for_sim([pool], "http://x", 100, chain="base")
    assert out.get(pool.lower()) is None
