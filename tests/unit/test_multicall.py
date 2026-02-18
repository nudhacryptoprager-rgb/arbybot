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


class TestMulticallCallTypes:
    """Test call_types tracking for Roadmap M5_0 multicall contract."""
    
    def test_call_types_initialized(self):
        """Call types should include all expected fields: slot0, liquidity, token0, token1, decimals, symbol, fee."""
        batcher = MulticallBatcher("http://localhost:8545", 12345)
        expected_types = ["slot0", "liquidity", "token0", "token1", "decimals", "symbol", "fee"]
        for call_type in expected_types:
            assert call_type in batcher.call_types, f"Missing call_type: {call_type}"
            assert batcher.call_types[call_type] == 0
    
    def test_call_types_in_stats(self):
        """Stats should include call_types for artifact tracking."""
        batcher = MulticallBatcher("http://localhost:8545", 12345)
        stats = batcher.get_stats()
        assert "call_types" in stats, "Stats should include call_types"
        assert isinstance(stats["call_types"], dict)


class TestMulticallRequestedFields:
    """Test requested_fields aggregation for Roadmap M5_0 contract verification."""
    
    def setup_method(self):
        """Clear batchers before each test."""
        clear_batchers()
    
    def teardown_method(self):
        """Clear batchers after each test."""
        clear_batchers()
    
    def test_requested_fields_from_aggregate_stats(self):
        """Aggregate stats should include requested_fields for artifact verification."""
        from core.multicall import get_aggregate_multicall_stats
        
        # Create a batcher and simulate some calls
        batcher = get_multicall_batcher("http://localhost:8545", 12345)
        # Manually increment call_types to simulate actual batching
        batcher.call_types["slot0"] = 10
        batcher.call_types["liquidity"] = 10
        batcher.call_types["token0"] = 5
        batcher.call_types["token1"] = 5
        batcher.call_types["fee"] = 5
        
        stats = get_aggregate_multicall_stats()
        assert "requested_fields" in stats, "Aggregate stats should include requested_fields"
        
        # v2.2.1 Fix Step 7: requested_fields should include all batched types
        rf = stats["requested_fields"]
        assert "slot0" in rf, "slot0 should be in requested_fields"
        assert "liquidity" in rf, "liquidity should be in requested_fields"
        assert "token0" in rf, "token0 should be in requested_fields after v2.2.1"
        assert "token1" in rf, "token1 should be in requested_fields after v2.2.1"
        assert "fee" in rf, "fee should be in requested_fields after v2.2.1"
