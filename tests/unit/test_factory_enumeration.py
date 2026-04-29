"""Tests for ``discovery.factory_enumeration`` scaffold.

Reviewer post-2h-soak step #6: lock the cache schema and the offline
``enumerate_factory_pools`` contract. These tests intentionally do NOT
exercise live RPC paths — those land in a follow-up iteration on top of
this scaffold.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from discovery.factory_enumeration import (
    CACHE_SCHEMA_VERSION,
    EnumerationCache,
    FactoryPoolRecord,
    enumerate_factory_pools,
)


def _rec(**overrides) -> FactoryPoolRecord:
    base = dict(
        chain="base",
        dex="uniswap_v3",
        factory_address="0x1F98431c8aD98523631AE4a59f267346ea31F984",
        pool_address="0xPOOL",
        token0_address="0xA",
        token1_address="0xB",
        fee_tier=500,
        adapter_type="v3",
        tick_spacing=10,
        discovered_at="2026-04-29T00:00:00Z",
    )
    base.update(overrides)
    return FactoryPoolRecord(**base)


class TestFactoryPoolRecord:
    def test_record_is_frozen_dataclass(self):
        r = _rec()
        with pytest.raises(Exception):
            r.fee_tier = 999  # type: ignore[misc]

    def test_record_round_trips_through_dict(self):
        r = _rec()
        from dataclasses import asdict
        d = asdict(r)
        r2 = FactoryPoolRecord(**d)
        assert r2 == r


class TestEnumerationCache:
    def test_add_rejects_wrong_chain(self):
        cache = EnumerationCache(chain="base")
        with pytest.raises(ValueError):
            cache.add(_rec(chain="arbitrum_one"))

    def test_to_json_includes_schema_version_and_count(self):
        cache = EnumerationCache(chain="base")
        cache.add(_rec(pool_address="0xP1"))
        cache.add(_rec(pool_address="0xP2", fee_tier=3000, dex="aerodrome_v3"))
        payload = cache.to_json()
        assert payload["schema_version"] == CACHE_SCHEMA_VERSION
        assert payload["chain"] == "base"
        assert payload["record_count"] == 2
        assert len(payload["records"]) == 2

    def test_write_then_read_round_trip(self, tmp_path: Path):
        cache = EnumerationCache(chain="base")
        cache.add(_rec(pool_address="0xP1"))
        cache.add(_rec(pool_address="0xP2", fee_tier=3000))
        target = tmp_path / "base.json"
        cache.write(target)
        assert target.is_file()

        loaded = EnumerationCache.read(target)
        assert loaded.chain == "base"
        assert len(loaded.records) == 2
        assert loaded.records[0].pool_address == "0xP1"

    def test_read_rejects_unknown_schema(self, tmp_path: Path):
        target = tmp_path / "base.json"
        target.write_text(
            json.dumps({"schema_version": "factory_enum_vXX", "chain": "base", "records": []}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            EnumerationCache.read(target)

    def test_read_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            EnumerationCache.read(tmp_path / "nope.json")

    def test_filter_by_dex_and_fee(self):
        cache = EnumerationCache(chain="base")
        cache.add(_rec(pool_address="0xP1", dex="uniswap_v3", fee_tier=500))
        cache.add(_rec(pool_address="0xP2", dex="uniswap_v3", fee_tier=3000))
        cache.add(_rec(pool_address="0xP3", dex="aerodrome_v3", fee_tier=500))
        assert len(cache.filter(dex="uniswap_v3")) == 2
        assert len(cache.filter(fee_tier=500)) == 2
        assert len(cache.filter(dex="uniswap_v3", fee_tier=3000)) == 1


class TestEnumerateFactoryPoolsOffline:
    def test_returns_empty_when_cache_missing(self, tmp_path: Path):
        out = enumerate_factory_pools(
            chain="base", dex="uniswap_v3", cache_path=tmp_path / "missing.json"
        )
        assert out == []

    def test_no_cache_path_is_safe(self):
        # Calling without a cache must never touch RPC and must return [].
        out = enumerate_factory_pools(chain="base", dex="uniswap_v3")
        assert out == []

    def test_returns_filtered_records_when_cache_exists(self, tmp_path: Path):
        cache = EnumerationCache(chain="base")
        cache.add(_rec(pool_address="0xP1", dex="uniswap_v3"))
        cache.add(_rec(pool_address="0xP2", dex="aerodrome_v3"))
        target = tmp_path / "base.json"
        cache.write(target)

        out = enumerate_factory_pools(chain="base", dex="uniswap_v3", cache_path=target)
        assert len(out) == 1
        assert out[0].dex == "uniswap_v3"

    def test_chain_mismatch_returns_empty(self, tmp_path: Path):
        cache = EnumerationCache(chain="base")
        cache.add(_rec(pool_address="0xP1"))
        target = tmp_path / "base.json"
        cache.write(target)

        out = enumerate_factory_pools(
            chain="arbitrum_one", dex="uniswap_v3", cache_path=target
        )
        assert out == []
