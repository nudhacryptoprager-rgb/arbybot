# PATH: tests/unit/test_multicall.py
"""Unit tests for core/multicall.py module."""

import pytest

from core.multicall import (
    MulticallBatcher,
    get_multicall_batcher,
    clear_batchers,
    MULTICALL3_ADDRESS,
    V3_SLOT0_SELECTOR,
)


class TestMulticallConstants:
    """Test multicall constants are valid."""
    
    def test_multicall3_address_format(self):
        """Multicall3 address should be valid checksummed address."""
        assert MULTICALL3_ADDRESS.startswith("0x")
        assert len(MULTICALL3_ADDRESS) == 42
    
    def test_slot0_selector_format(self):
        """Slot0 selector should be 4 bytes."""
        assert V3_SLOT0_SELECTOR.startswith("0x")
        assert len(V3_SLOT0_SELECTOR) == 10  # 0x + 8 hex chars


class TestMulticallBatcher:
    """Test MulticallBatcher functionality."""
    
    def test_batcher_initialization(self):
        """Batcher initializes with correct attributes."""
        batcher = MulticallBatcher("http://localhost:8545", 12345)
        assert batcher.rpc_url == "http://localhost:8545"
        assert batcher.block_num == 12345
        assert batcher.stats["calls_made"] == 0
    
    def test_empty_batch_returns_empty(self):
        """Empty pool list returns empty dict."""
        batcher = MulticallBatcher("http://localhost:8545", 12345)
        result = batcher.batch_slot0([])
        assert result == {}
    
    def test_stats_tracking(self):
        """Stats are tracked correctly."""
        batcher = MulticallBatcher("http://localhost:8545", 12345)
        stats = batcher.get_stats()
        assert "calls_made" in stats
        assert "calls_batched" in stats
        assert "rpc_calls" in stats


class TestMulticallSingleton:
    """Test singleton batcher pattern."""
    
    def setup_method(self):
        """Clear batchers before each test."""
        clear_batchers()
    
    def teardown_method(self):
        """Clear batchers after each test."""
        clear_batchers()
    
    def test_singleton_same_params(self):
        """Same RPC + block returns same batcher."""
        b1 = get_multicall_batcher("http://localhost:8545", 100)
        b2 = get_multicall_batcher("http://localhost:8545", 100)
        assert b1 is b2
    
    def test_singleton_different_block(self):
        """Different block returns different batcher."""
        b1 = get_multicall_batcher("http://localhost:8545", 100)
        b2 = get_multicall_batcher("http://localhost:8545", 200)
        assert b1 is not b2
    
    def test_singleton_different_rpc(self):
        """Different RPC returns different batcher."""
        b1 = get_multicall_batcher("http://localhost:8545", 100)
        b2 = get_multicall_batcher("http://other:8545", 100)
        assert b1 is not b2
