"""Tests for M9 depth probe TTL cache."""
from __future__ import annotations

from m9.graph_arb.depth_cache import DepthProbeCache, block_bucket, depth_cache_key


def test_depth_cache_key_stable():
    key = depth_cache_key(
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "a" * 40,
        token_in="0x" + "b" * 40,
        token_out="0x" + "c" * 40,
        block_number=1234567,
    )
    assert key.startswith("base:uniswap_v3:")
    assert block_bucket(1234567) == block_bucket(1234590)


def test_depth_cache_hit_and_expire():
    cache = DepthProbeCache(ttl_s=30.0)
    key = "k1"
    cache.set(key, {"depth": 1.0})
    assert cache.get(key) == {"depth": 1.0}
    cache._store[key] = (0.0, {"depth": 1.0})
    assert cache.get(key) is None
