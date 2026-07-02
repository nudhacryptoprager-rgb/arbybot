"""Tests for Uniswap v4 poolId resolver."""
from __future__ import annotations

from unittest.mock import patch

from m8.discovery.pool_hints import PoolHint
from m8.discovery.uniswap_v4_pool_resolver import (
    V4_MISLABEL_V3_POOL,
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


@patch("m8.discovery.uniswap_v4_pool_resolver.verify_v4_pool_id_exists", return_value=(False, "V4_SLOT0_EMPTY"))
@patch("m8.discovery.uniswap_v4_pool_resolver.verify_v4_pool_id", return_value=(False, "V4_SLOT0_EMPTY"))
@patch("m8.discovery.uniswap_v4_pool_resolver.verify_factory_pool", return_value=(True, "factory_getPool"))
def test_v4_slot0_empty_falls_back_to_v3_factory(_factory, _full, _exists):
    """When V4 StateView slot0 is empty, try V3 factory lookup using token pair.

    DexScreener may label V3 pools as V4 (labels_or_raw_dex_v4). The V4 poolId
    (66-char bytes32) won't match any StateView entry, but the underlying pool
    is a real V3 pool findable via factory.getPool(token0, token1, fee).
    """
    hint = _v4_hint()
    ok, bucket, detail = resolve_v4_pool_existence(hint, chain="base")
    assert ok is True
    assert bucket == V4_MISLABEL_V3_POOL
    assert detail == "factory_getPool"
    _factory.assert_called_once()


@patch("m8.discovery.uniswap_v4_pool_resolver.verify_v4_pool_id_exists", return_value=(False, "V4_SLOT0_EMPTY"))
@patch("m8.discovery.uniswap_v4_pool_resolver.verify_v4_pool_id", return_value=(False, "V4_SLOT0_EMPTY"))
@patch("m8.discovery.uniswap_v4_pool_resolver.verify_factory_pool", return_value=(True, "factory_getPool"))
def test_v4_fallback_extracts_fee_from_raw_pair(_factory, _full, _exists):
    """V3 factory fallback extracts feeTier from raw pair data."""
    hint = _v4_hint()
    resolve_v4_pool_existence(hint, chain="base")
    called_hint = _factory.call_args[0][0]
    assert called_hint.fee == 3000
    assert called_hint.dex_id == "uniswap_v3"


@patch("m8.discovery.uniswap_v4_pool_resolver.verify_v4_pool_id_exists", return_value=(False, "V4_SLOT0_EMPTY"))
@patch("m8.discovery.uniswap_v4_pool_resolver.verify_v4_pool_id", return_value=(False, "V4_SLOT0_EMPTY"))
@patch("m8.discovery.uniswap_v4_pool_resolver.verify_factory_pool", return_value=(False, "FACTORY_NO_POOL"))
def test_v4_fallback_no_tokens_skips_factory(_factory, _full, _exists):
    """When V4 hint has no token addresses, V3 factory fallback is skipped."""
    hint = _v4_hint()
    hint.token0_addr = ""
    hint.token1_addr = ""
    ok, bucket, _detail = resolve_v4_pool_existence(hint, chain="base")
    assert ok is False
    assert bucket == V4_POOLID_NOT_RESOLVED
    _factory.assert_not_called()
