"""E1.42 Iter 4 — factory_enumeration cold-collector wiring tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from discovery.factory_enumeration import (
    EnumerationCache,
    FactoryPoolRecord,
    default_cache_path,
    enumerate_factory_pools,
    populate_cache_from_pool_index,
)


class _StubIndex:
    """Duck-typed PoolIndex for testing."""

    def __init__(self, by_chain):
        self._by_chain = by_chain

    def get_pools(self, chain):
        return self._by_chain.get(chain, [])


def _mk_pool(**overrides):
    base = dict(
        chain="base",
        dex="uniswap_v3",
        factory_address="0xFACTORY",
        address="0xPOOL",
        token0="0xT0",
        token1="0xT1",
        fee_tier=500,
        adapter_type="uniswap_v3",
        tick_spacing=10,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_default_cache_path_uses_canonical_location(tmp_path):
    p = default_cache_path("base", root=tmp_path / "cache")
    assert str(p).replace("\\", "/").endswith("/base.json")
    assert "base.json" in str(p)


def test_populate_writes_records(tmp_path):
    idx = _StubIndex({"base": [_mk_pool(), _mk_pool(address="0xPOOL2", fee_tier=3000)]})
    cache_path = tmp_path / "base.json"
    n = populate_cache_from_pool_index(
        chain="base", pool_index=idx, cache_path=cache_path
    )
    assert n == 2
    assert cache_path.is_file()
    cache = EnumerationCache.read(cache_path)
    assert cache.chain == "base"
    assert len(cache.records) == 2
    addrs = {r.pool_address for r in cache.records}
    assert addrs == {"0xPOOL", "0xPOOL2"}


def test_populate_idempotent_replaces(tmp_path):
    cache_path = tmp_path / "base.json"
    idx_v1 = _StubIndex({"base": [_mk_pool()]})
    populate_cache_from_pool_index(chain="base", pool_index=idx_v1, cache_path=cache_path)
    idx_v2 = _StubIndex(
        {"base": [_mk_pool(address="0xNEW1"), _mk_pool(address="0xNEW2")]}
    )
    n = populate_cache_from_pool_index(chain="base", pool_index=idx_v2, cache_path=cache_path)
    assert n == 2
    cache = EnumerationCache.read(cache_path)
    addrs = {r.pool_address for r in cache.records}
    assert addrs == {"0xNEW1", "0xNEW2"}


def test_populate_skips_records_without_pool_address(tmp_path):
    idx = _StubIndex({"base": [_mk_pool(address=""), _mk_pool(address="0xKEEP")]})
    cache_path = tmp_path / "base.json"
    n = populate_cache_from_pool_index(chain="base", pool_index=idx, cache_path=cache_path)
    assert n == 1


def test_populate_handles_index_failure_gracefully(tmp_path):
    class _Broken:
        def get_pools(self, chain):
            raise RuntimeError("boom")

    cache_path = tmp_path / "base.json"
    n = populate_cache_from_pool_index(
        chain="base", pool_index=_Broken(), cache_path=cache_path
    )
    assert n == 0
    cache = EnumerationCache.read(cache_path)
    assert cache.records == []


def test_populated_cache_readable_by_enumerate_factory_pools(tmp_path):
    idx = _StubIndex(
        {"base": [_mk_pool(), _mk_pool(dex="pancakeswap_v3", address="0xPCS")]}
    )
    cache_path = tmp_path / "base.json"
    populate_cache_from_pool_index(chain="base", pool_index=idx, cache_path=cache_path)
    pools_uni = enumerate_factory_pools(
        chain="base", dex="uniswap_v3", cache_path=cache_path
    )
    assert len(pools_uni) == 1
    assert pools_uni[0].dex == "uniswap_v3"
    pools_pcs = enumerate_factory_pools(
        chain="base", dex="pancakeswap_v3", cache_path=cache_path
    )
    assert len(pools_pcs) == 1
