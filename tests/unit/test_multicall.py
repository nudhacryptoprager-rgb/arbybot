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
        batcher.call_types["decimals"] = 3  # v2.2.0: Also batch decimals
        
        stats = get_aggregate_multicall_stats()
        assert "requested_fields" in stats, "Aggregate stats should include requested_fields"
        
        # v2.2.0: requested_fields should include all batched types per Roadmap M5_0
        rf = stats["requested_fields"]
        assert "slot0" in rf, "slot0 should be in requested_fields"
        assert "liquidity" in rf, "liquidity should be in requested_fields"
        assert "token0" in rf, "token0 should be in requested_fields"
        assert "token1" in rf, "token1 should be in requested_fields"
        assert "fee" in rf, "fee should be in requested_fields"
        assert "decimals" in rf, "decimals should be in requested_fields (v2.2.0 Fix Step 5)"
    
    def test_requested_fields_roadmap_contract(self):
        """Roadmap M5_0 requires: slot0, liquidity, token0, token1, decimals in requested_fields."""
        from core.multicall import get_aggregate_multicall_stats
        
        batcher = get_multicall_batcher("http://localhost:8545", 99999)
        # Simulate full prefetch as done in strategy/quotes.py
        batcher.call_types["slot0"] = 33
        batcher.call_types["liquidity"] = 33
        batcher.call_types["token0"] = 33
        batcher.call_types["token1"] = 33
        batcher.call_types["fee"] = 33
        batcher.call_types["decimals"] = 10  # Unique tokens
        
        stats = get_aggregate_multicall_stats()
        rf = set(stats["requested_fields"])
        
        # Roadmap M5_0 required fields
        required = {"slot0", "liquidity", "token0", "token1", "decimals"}
        assert required.issubset(rf), f"Missing required fields: {required - rf}"


class TestMulticallFieldSuccessRates:
    """Test v2.3.0 field_success_rates contract for per-field observability."""
    
    def setup_method(self):
        """Clear batchers before each test."""
        clear_batchers()
    
    def teardown_method(self):
        """Clear batchers after each test."""
        clear_batchers()
    
    def test_call_success_fail_initialized(self):
        """Batcher should have call_success and call_fail dicts initialized."""
        batcher = MulticallBatcher("http://localhost:8545", 12345)
        assert hasattr(batcher, "call_success"), "Missing call_success dict"
        assert hasattr(batcher, "call_fail"), "Missing call_fail dict"
        # All fields should be initialized to 0
        expected_fields = ["slot0", "liquidity", "token0", "token1", "decimals", "fee"]
        for field in expected_fields:
            assert field in batcher.call_success, f"Missing call_success[{field}]"
            assert field in batcher.call_fail, f"Missing call_fail[{field}]"
            assert batcher.call_success[field] == 0
            assert batcher.call_fail[field] == 0
    
    def test_call_success_fail_in_stats(self):
        """Stats should include call_success and call_fail for artifact tracking."""
        batcher = MulticallBatcher("http://localhost:8545", 12345)
        stats = batcher.get_stats()
        assert "call_success" in stats, "Stats should include call_success"
        assert "call_fail" in stats, "Stats should include call_fail"
    
    def test_aggregate_field_success_fail(self):
        """Aggregate stats should include field_success and field_fail."""
        from core.multicall import get_aggregate_multicall_stats
        
        batcher = get_multicall_batcher("http://localhost:8545", 12346)
        # Simulate some calls with success/fail
        batcher.call_types["slot0"] = 10
        batcher.call_success["slot0"] = 8
        batcher.call_fail["slot0"] = 2
        batcher.call_types["liquidity"] = 10
        batcher.call_success["liquidity"] = 10
        batcher.call_fail["liquidity"] = 0
        
        stats = get_aggregate_multicall_stats()
        assert "field_success" in stats, "Aggregate stats should include field_success"
        assert "field_fail" in stats, "Aggregate stats should include field_fail"
        assert stats["field_success"]["slot0"] == 8
        assert stats["field_fail"]["slot0"] == 2
        assert stats["field_success"]["liquidity"] == 10
    
    def test_aggregate_field_success_rates(self):
        """Aggregate stats should include field_success_rates with correct calculation."""
        from core.multicall import get_aggregate_multicall_stats
        
        batcher = get_multicall_batcher("http://localhost:8545", 12347)
        # Simulate some calls
        batcher.call_types["slot0"] = 10
        batcher.call_success["slot0"] = 8
        batcher.call_fail["slot0"] = 2
        batcher.call_types["liquidity"] = 10
        batcher.call_success["liquidity"] = 10
        
        stats = get_aggregate_multicall_stats()
        assert "field_success_rates" in stats, "Aggregate stats should include field_success_rates"
        # slot0: 8/10 = 0.8
        assert stats["field_success_rates"]["slot0"] == 0.8
        # liquidity: 10/10 = 1.0
        assert stats["field_success_rates"]["liquidity"] == 1.0
    
    def test_field_success_rates_not_zero_when_calls_made(self):
        """When calls are made and succeed, field_success_rates should be > 0."""
        from core.multicall import get_aggregate_multicall_stats
        
        batcher = get_multicall_batcher("http://localhost:8545", 12348)
        # Simulate token0/token1/fee/decimals calls with success
        fields = ["token0", "token1", "fee", "decimals"]
        for field in fields:
            batcher.call_types[field] = 5
            batcher.call_success[field] = 5  # All success
        
        stats = get_aggregate_multicall_stats()
        fsr = stats["field_success_rates"]
        for field in fields:
            assert fsr.get(field, 0) > 0, f"field_success_rates[{field}] should be > 0 when calls succeed"
            assert fsr[field] == 1.0, f"field_success_rates[{field}] should be 1.0 when all calls succeed"