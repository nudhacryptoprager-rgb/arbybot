"""Tests for Uniswap v4 poolId resolver."""
from __future__ import annotations

from unittest.mock import patch

from m8.discovery.pool_hints import PoolHint
from m8.discovery.uniswap_v4_pool_resolver import (
    V4_POOLID_EXISTS,
    V4_POOLID_NOT_RESOLVED,
    resolve_v4_pool_existence,
)


def _v4_hint() -> PoolHint:
    return PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v4",
        pool_address="0x" + "f" * 64,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
        focus_token="0x" + "1" * 40,
        raw={"pair": {"feeTier": 3000}},
    )


@patch("m8.discovery.uniswap_v4_pool_resolver.verify_v4_pool_id_exists", return_value=(True, "v4_stateview"))
def test_resolve_v4_slot0_exists(mock_exists):
    ok, bucket, _detail = resolve_v4_pool_existence(_v4_hint(), chain="base")
    assert ok is True
    assert bucket == V4_POOLID_EXISTS
    mock_exists.assert_called_once()


@patch("m8.discovery.uniswap_v4_pool_resolver.verify_v4_pool_id_exists", return_value=(False, "V4_SLOT0_EMPTY"))
@patch("m8.discovery.uniswap_v4_pool_resolver.verify_v4_pool_id", return_value=(False, "V4_ZERO_LIQUIDITY"))
@patch("m8.discovery.uniswap_v4_pool_resolver.verify_factory_pool", return_value=(False, "FACTORY_NO_POOL"))
def test_resolve_v4_not_resolved(_factory, _full, _exists):
    ok, bucket, _detail = resolve_v4_pool_existence(_v4_hint(), chain="base")
    assert ok is False
    assert bucket == V4_POOLID_NOT_RESOLVED
