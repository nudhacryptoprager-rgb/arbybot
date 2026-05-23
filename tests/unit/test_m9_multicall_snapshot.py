"""Unit tests for multicall_snapshot.py (Step 3)."""
from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from m9.graph_arb.pool_state_cache import PoolState, PoolStateCache
from m9.graph_arb.multicall_snapshot import snapshot_pool_states, _batch_fetch


POOL_A = "0xaaaa000000000000000000000000000000000001"
POOL_B = "0xbbbb000000000000000000000000000000000002"


def _make_state(addr, sqrt_price=2**96, tick=0, liq=1000, block=100):
    return PoolState(
        pool_addr=addr.lower(),
        sqrt_price_x96=sqrt_price,
        tick=tick,
        liquidity=liq,
        block_number=block,
        fetched_at_mono=time.monotonic(),
    )


class TestSnapshotPoolStates:
    """Tests that use ARBY_SKIP_RPC=1 to skip actual RPC calls."""

    def test_returns_cached_when_fresh(self):
        cache = PoolStateCache(ttl_s=10.0)
        state = _make_state(POOL_A)
        cache.put(state)

        os.environ["ARBY_SKIP_RPC"] = "1"
        try:
            result = snapshot_pool_states(
                [POOL_A], rpc_url="http://dummy", cache=cache
            )
        finally:
            os.environ.pop("ARBY_SKIP_RPC", None)

        assert result.get(POOL_A.lower()) is not None

    def test_returns_none_for_uncached_when_skip_rpc(self):
        cache = PoolStateCache()
        os.environ["ARBY_SKIP_RPC"] = "1"
        try:
            result = snapshot_pool_states(
                [POOL_A], rpc_url="http://dummy", cache=cache
            )
        finally:
            os.environ.pop("ARBY_SKIP_RPC", None)

        assert result.get(POOL_A.lower()) is None

    def test_empty_pool_list(self):
        result = snapshot_pool_states([], rpc_url="http://dummy")
        assert result == {}

    def test_no_rpc_returns_only_cached(self):
        cache = PoolStateCache(ttl_s=10.0)
        state = _make_state(POOL_A)
        cache.put(state)

        result = snapshot_pool_states([POOL_A, POOL_B], rpc_url=None, cache=cache)
        assert result.get(POOL_A.lower()) is not None
        assert result.get(POOL_B.lower()) is None

    def test_addresses_normalised_to_lowercase(self):
        cache = PoolStateCache(ttl_s=10.0)
        cache.put(_make_state(POOL_A.lower()))

        os.environ["ARBY_SKIP_RPC"] = "1"
        try:
            result = snapshot_pool_states(
                [POOL_A.upper()], rpc_url="http://dummy", cache=cache
            )
        finally:
            os.environ.pop("ARBY_SKIP_RPC", None)

        assert POOL_A.lower() in result

    def test_updates_cache_with_fetched(self):
        """Mock MulticallBatcher to verify cache is updated."""
        cache = PoolStateCache(ttl_s=10.0)

        mock_instance = MagicMock()
        mock_instance.batch_slot0.return_value = {
            POOL_A: (2**96, 100, 0)  # (sqrt_price, tick, _unused)
        }
        mock_instance.batch_liquidity.return_value = {POOL_A: 50_000}

        # return_value=mock_instance so MulticallBatcher(...) returns mock_instance
        with patch("m9.graph_arb.multicall_snapshot.MulticallBatcher", return_value=mock_instance):
            with patch("m9.graph_arb.multicall_snapshot._SKIP_RPC", False):
                result = snapshot_pool_states([POOL_A], rpc_url="http://rpc", cache=cache)

        assert result.get(POOL_A.lower()) is not None
        cached = cache.get(POOL_A.lower())
        assert cached is not None
        assert cached.sqrt_price_x96 == 2**96
        assert cached.liquidity == 50_000

    def test_multicall_batcher_failure_returns_none(self):
        """If MulticallBatcher returns empty results, snapshot should return None gracefully."""
        cache = PoolStateCache()

        mock_instance = MagicMock()
        mock_instance.batch_slot0.return_value = {}
        mock_instance.batch_liquidity.return_value = {}

        with patch("m9.graph_arb.multicall_snapshot.MulticallBatcher", return_value=mock_instance):
            with patch("m9.graph_arb.multicall_snapshot._SKIP_RPC", False):
                result = snapshot_pool_states([POOL_A], rpc_url="http://rpc", cache=cache)

        assert result.get(POOL_A.lower()) is None

    def test_import_error_returns_none(self):
        """If MulticallBatcher import fails, should return None gracefully."""
        with patch.dict("sys.modules", {"core.multicall": None}):
            result = _batch_fetch([POOL_A], rpc_url="http://rpc", block_num=None)
        assert result.get(POOL_A.lower()) is None


class TestWsMonitorWaitForNewBlock:
    """Tests for the wait_for_new_block() method on WsMonitor."""

    def test_returns_false_when_not_connected(self):
        from m9.graph_arb.ws_monitor import WsMonitor
        monitor = WsMonitor()
        result = monitor.wait_for_new_block(timeout_s=0.05)
        assert result is False

    def test_returns_true_when_block_arrives(self):
        from m9.graph_arb.ws_monitor import WsMonitor
        import threading

        monitor = WsMonitor()
        # Manually set connected state
        with monitor._lock:
            monitor._connected = True
            monitor._latest_block = 100

        def _deliver_block():
            time.sleep(0.05)
            with monitor._lock:
                monitor._latest_block = 101
            monitor._new_block_event.set()

        t = threading.Thread(target=_deliver_block, daemon=True)
        t.start()
        result = monitor.wait_for_new_block(timeout_s=1.0)
        t.join(timeout=2.0)
        assert result is True

    def test_timeout_returns_false(self):
        from m9.graph_arb.ws_monitor import WsMonitor

        monitor = WsMonitor()
        with monitor._lock:
            monitor._connected = True
            monitor._latest_block = 100
        # No block delivered → should timeout
        result = monitor.wait_for_new_block(timeout_s=0.05)
        assert result is False
