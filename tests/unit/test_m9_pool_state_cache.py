"""Unit tests for PoolStateCache (m9/graph_arb/pool_state_cache.py)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from m9.graph_arb.pool_state_cache import PoolState, PoolStateCache


def _make_state(addr="0xaaaa", sqrt_price=2**96, tick=0, liq=1000, block=100):
    return PoolState(
        pool_addr=addr,
        sqrt_price_x96=sqrt_price,
        tick=tick,
        liquidity=liq,
        block_number=block,
        fetched_at_mono=time.monotonic(),
    )


class TestPoolState:
    def test_is_empty_zero_liquidity(self):
        s = _make_state(liq=0)
        assert s.is_empty()

    def test_is_empty_zero_price(self):
        s = _make_state(sqrt_price=0)
        assert s.is_empty()

    def test_not_empty(self):
        s = _make_state(liq=100, sqrt_price=2**96)
        assert not s.is_empty()

    def test_age_s_increases(self):
        s = _make_state()
        time.sleep(0.05)
        assert s.age_s() >= 0.0

    def test_to_from_dict_roundtrip(self):
        s = _make_state(addr="0xbeef", block=999, liq=42)
        d = s.to_dict()
        assert "fetched_at_mono" not in d
        s2 = PoolState.from_dict(d, fetched_at_mono=time.monotonic())
        assert s2.pool_addr == "0xbeef"
        assert s2.block_number == 999
        assert s2.liquidity == 42


class TestPoolStateCache:
    def test_put_and_get_fresh(self):
        cache = PoolStateCache(ttl_s=2.0)
        state = _make_state("0x1234")
        cache.put(state)
        result = cache.get("0x1234")
        assert result is not None
        assert result.pool_addr == "0x1234"

    def test_get_none_for_unknown(self):
        cache = PoolStateCache()
        assert cache.get("0xdeadbeef") is None

    def test_case_normalisation(self):
        cache = PoolStateCache()
        state = _make_state("0xABCD")  # uppercase
        cache.put(state)
        assert cache.get("0xabcd") is not None
        assert cache.get("0xABCD") is not None

    def test_ttl_expiry(self):
        cache = PoolStateCache(ttl_s=0.05)
        state = _make_state("0x5555")
        cache.put(state)
        assert cache.get("0x5555") is not None
        time.sleep(0.1)
        assert cache.get("0x5555") is None

    def test_stale_or_missing_returns_stale(self):
        cache = PoolStateCache(ttl_s=0.05)
        state = _make_state("0xaabb")
        cache.put(state)
        time.sleep(0.1)
        stale = cache.stale_or_missing(["0xaabb", "0xccdd"])
        assert "0xaabb" in stale
        assert "0xccdd" in stale

    def test_stale_or_missing_excludes_fresh(self):
        cache = PoolStateCache(ttl_s=10.0)
        state = _make_state("0xffff")
        cache.put(state)
        stale = cache.stale_or_missing(["0xffff", "0x0000"])
        assert "0xffff" not in stale
        assert "0x0000" in stale

    def test_put_many(self):
        cache = PoolStateCache()
        states = [_make_state(f"0x{i:04x}") for i in range(5)]
        cache.put_many(states)
        assert cache.size() == 5
        assert cache.fresh_count() == 5

    def test_clear(self):
        cache = PoolStateCache()
        cache.put_many([_make_state(f"0x{i:04x}") for i in range(3)])
        cache.clear()
        assert cache.size() == 0

    def test_summary_keys(self):
        cache = PoolStateCache()
        s = cache.summary()
        assert "total" in s
        assert "fresh" in s
        assert "ttl_s" in s

    def test_save_and_load(self, tmp_path):
        cache = PoolStateCache(ttl_s=10.0)
        cache.put_many([_make_state(f"0x{i:04x}", block=i) for i in range(5)])
        path = str(tmp_path / "test_cache.json")
        cache.save(path)
        assert Path(path).exists()

        # Load into fresh cache
        cache2 = PoolStateCache(ttl_s=10.0)
        n = cache2.load(path)
        assert n == 5

    def test_load_nonexistent_returns_zero(self):
        cache = PoolStateCache()
        assert cache.load("/nonexistent/path/does_not_exist.json") == 0

    def test_save_excludes_stale(self, tmp_path):
        cache = PoolStateCache(ttl_s=0.05)
        cache.put(_make_state("0x1111"))
        time.sleep(0.1)  # let it expire
        path = str(tmp_path / "stale_cache.json")
        cache.save(path)
        data = json.loads(Path(path).read_text())
        assert data["entries"] == []
