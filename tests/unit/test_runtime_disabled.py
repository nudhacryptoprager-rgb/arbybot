"""
Tests for strategy/runtime_disabled.py - Runtime auto-disable mechanism.

v3.2.0: Implements automatic pool disabling based on persistent failures.
v3.2.1: Fixed test isolation - all tests use temp cache paths, no pollution of data/cache/.
"""

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from strategy.runtime_disabled import (
    RuntimeDisabledManager,
    RuntimeDisabledEntry,
    is_runtime_disabled,
    auto_disable_pool,
    record_quote_success,
    get_runtime_disabled_manager,
    clear_runtime_disabled_manager,
)


# =============================================================================
# TEST ISOLATION FIXTURE
# =============================================================================

@pytest.fixture(autouse=True)
def isolated_runtime_cache(tmp_path):
    """
    Ensure all runtime_disabled tests use an isolated temp cache.
    
    This fixture:
    1. Clears any existing global manager
    2. Creates a new manager with a temp cache path
    3. Yields for the test
    4. Cleans up after
    
    This prevents tests from polluting data/cache/runtime_disabled_pools.json.
    """
    clear_runtime_disabled_manager()
    temp_cache = tmp_path / "runtime_disabled_test.json"
    # Force new manager with temp cache - this sets the global singleton
    get_runtime_disabled_manager(cache_path=str(temp_cache), force_new=True)
    yield str(temp_cache)
    # Cleanup - clear the manager state and singleton
    clear_runtime_disabled_manager()


class TestRuntimeDisabledEntry:
    """Tests for RuntimeDisabledEntry dataclass."""

    def test_entry_creation(self):
        """Test basic entry creation."""
        entry = RuntimeDisabledEntry(
            pool_key="uniswap_v3_WETH_USDC_500",
            reason="LIQUIDITY_ZERO",
            disabled_at=1700000000.0,
            failure_count=3,
            last_error_details={"pool_address": "0x123"},
        )
        assert entry.pool_key == "uniswap_v3_WETH_USDC_500"
        assert entry.reason == "LIQUIDITY_ZERO"
        assert entry.failure_count == 3

    def test_entry_to_dict(self):
        """Test entry serialization to dict."""
        entry = RuntimeDisabledEntry(
            pool_key="test_pool",
            reason="SUSPECT_LIQUIDITY",
            disabled_at=1700000000.0,
            failure_count=5,
            last_error_details={"reason": "test"},
        )
        d = entry.to_dict()
        assert d["pool_key"] == "test_pool"
        assert d["reason"] == "SUSPECT_LIQUIDITY"
        assert d["failure_count"] == 5
        assert d["last_error_details"]["reason"] == "test"

    def test_entry_from_dict(self):
        """Test entry deserialization from dict."""
        data = {
            "pool_key": "sushi_v3_ARB_USDC_100",
            "reason": "LIQUIDITY_ZERO",
            "disabled_at": 1700000000.0,
            "failure_count": 1,
            "last_error_details": {"auto": True},
        }
        entry = RuntimeDisabledEntry.from_dict(data)
        assert entry.pool_key == "sushi_v3_ARB_USDC_100"
        assert entry.reason == "LIQUIDITY_ZERO"
        assert entry.failure_count == 1


class TestRuntimeDisabledManager:
    """Tests for RuntimeDisabledManager."""

    # NOTE: setup/teardown handled by autouse fixture 'isolated_runtime_cache'

    def test_singleton_pattern(self):
        """Test manager singleton pattern."""
        mgr1 = get_runtime_disabled_manager()
        mgr2 = get_runtime_disabled_manager()
        assert mgr1 is mgr2

    def test_record_failure_below_threshold(self):
        """Test that failures below threshold don't disable pool."""
        mgr = get_runtime_disabled_manager()
        
        # Use unique pool key to avoid cross-test contamination
        pool_key = "threshold_test_pool_below"
        
        # Record 2 failures (default threshold is 3)
        mgr.record_failure(pool_key, "SUSPECT_LIQUIDITY")
        mgr.record_failure(pool_key, "SUSPECT_LIQUIDITY")
        
        # Pool should not be disabled yet
        assert mgr.is_disabled(pool_key) is None

    def test_record_failure_at_threshold(self):
        """Test that failures at threshold disable pool."""
        mgr = get_runtime_disabled_manager()
        
        # Record 3 failures (default threshold)
        mgr.record_failure("test_pool", "SUSPECT_LIQUIDITY")
        mgr.record_failure("test_pool", "SUSPECT_LIQUIDITY")
        mgr.record_failure("test_pool", "SUSPECT_LIQUIDITY")
        
        # Pool should now be disabled
        assert mgr.is_disabled("test_pool") is not None

    def test_liquidity_zero_immediate_disable(self):
        """Test that LIQUIDITY_ZERO causes immediate disable."""
        mgr = get_runtime_disabled_manager()
        
        # Single LIQUIDITY_ZERO should disable immediately
        mgr.record_failure("test_pool", "LIQUIDITY_ZERO")
        
        assert mgr.is_disabled("test_pool") is not None

    def test_success_resets_failure_count(self):
        """Test that success resets failure count."""
        mgr = get_runtime_disabled_manager()
        
        # Record 2 failures - pool should not be disabled yet (threshold is 3)
        mgr.record_failure("reset_test_pool", "SUSPECT_LIQUIDITY")
        mgr.record_failure("reset_test_pool", "SUSPECT_LIQUIDITY")
        assert mgr.is_disabled("reset_test_pool") is None
        
        # Record success - this resets failure count
        mgr.record_success("reset_test_pool")
        
        # Record 2 more failures - should not disable (count was reset)
        mgr.record_failure("reset_test_pool", "SUSPECT_LIQUIDITY")
        mgr.record_failure("reset_test_pool", "SUSPECT_LIQUIDITY")
        
        # Still below threshold after reset
        assert mgr.is_disabled("reset_test_pool") is None

    def test_ttl_expiration(self):
        """Test that disabled pools expire after TTL."""
        mgr = get_runtime_disabled_manager()
        # Override config for testing
        mgr.config = dict(mgr.config)
        mgr.config["ttl_seconds"] = 1
        
        # Disable pool
        mgr.record_failure("test_pool", "LIQUIDITY_ZERO")
        info = mgr.is_disabled("test_pool")
        assert info is not None
        assert info.get("expired") is False
        
        # Wait for TTL to expire
        time.sleep(1.1)
        
        # Pool should show as expired
        info = mgr.is_disabled("test_pool")
        assert info is not None
        assert info.get("expired") is True

    def test_get_disabled_info_returns_remaining(self):
        """Test that is_disabled returns remaining seconds."""
        mgr = get_runtime_disabled_manager()
        # Override config for testing
        mgr.config = dict(mgr.config)
        mgr.config["ttl_seconds"] = 3600
        
        mgr.record_failure("test_pool", "LIQUIDITY_ZERO")
        
        info = mgr.is_disabled("test_pool")
        assert info is not None
        assert "remaining_seconds" in info
        assert info["remaining_seconds"] > 0
        assert info["remaining_seconds"] <= 3600

    def test_persistence_to_file(self):
        """Test that disabled state persists to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = os.path.join(tmpdir, "runtime_disabled.json")
            
            # Create manager with custom cache path
            mgr = RuntimeDisabledManager(cache_path=cache_file)
            
            # Disable a pool
            mgr.record_failure("persistent_pool", "LIQUIDITY_ZERO")
            
            # Force save
            mgr._save_cache()
            
            # Verify file exists and contains data
            assert os.path.exists(cache_file)
            with open(cache_file) as f:
                data = json.load(f)
            assert "entries" in data
            assert any(p["pool_key"] == "persistent_pool" for p in data["entries"])

    def test_persistence_load_on_init(self):
        """Test that disabled state loads from file on init."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = os.path.join(tmpdir, "runtime_disabled.json")
            
            # Create initial state
            initial_data = {
                "schema_version": "1.0.0",
                "updated_at": time.time(),
                "entries": [
                    {
                        "pool_key": "preexisting_pool",
                        "reason": "LIQUIDITY_ZERO",
                        "disabled_at": time.time(),
                        "failure_count": 1,
                        "last_error_details": {},
                    }
                ],
            }
            with open(cache_file, "w") as f:
                json.dump(initial_data, f)
            
            # Create manager - should load existing state
            mgr = RuntimeDisabledManager(cache_path=cache_file)
            
            assert mgr.is_disabled("preexisting_pool") is not None


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    # NOTE: setup/teardown handled by autouse fixture 'isolated_runtime_cache'

    def test_is_runtime_disabled_not_disabled(self):
        """Test is_runtime_disabled returns None for non-disabled pool."""
        info = is_runtime_disabled("not_disabled_pool")
        assert info is None

    def test_auto_disable_pool_immediate(self):
        """Test auto_disable_pool with immediate disable error."""
        auto_disable_pool("immediate_pool", "LIQUIDITY_ZERO", {"test": True})
        
        info = is_runtime_disabled("immediate_pool")
        assert info is not None
        assert "LIQUIDITY_ZERO" in info["reason"]  # reason is prefixed with RUNTIME_DISABLED:

    def test_auto_disable_pool_threshold(self):
        """Test auto_disable_pool with threshold-based disable."""
        # Record failures up to threshold
        for _ in range(3):
            auto_disable_pool("threshold_pool", "SUSPECT_LIQUIDITY", {})
        
        info = is_runtime_disabled("threshold_pool")
        assert info is not None

    def test_record_quote_success_clears_failures(self):
        """Test record_quote_success clears failure count."""
        # Record some failures
        auto_disable_pool("success_pool", "SUSPECT_LIQUIDITY", {})
        auto_disable_pool("success_pool", "SUSPECT_LIQUIDITY", {})
        
        # Record success
        record_quote_success("success_pool")
        
        # One more failure should not disable
        auto_disable_pool("success_pool", "SUSPECT_LIQUIDITY", {})
        
        info = is_runtime_disabled("success_pool")
        assert info is None


class TestIntegrationWithQuotes:
    """Integration tests for quotes.py integration."""

    # NOTE: setup/teardown handled by autouse fixture 'isolated_runtime_cache'

    def test_disabled_pool_skipped_in_quoting(self):
        """Test that runtime-disabled pools are skipped in quoting.
        
        This is a behavioral test - we verify the is_runtime_disabled
        function returns the correct format for quotes.py integration.
        """
        # Disable a pool
        auto_disable_pool("skip_pool", "LIQUIDITY_ZERO", {"pool_address": "0x123"})
        
        # Verify the returned info has the expected structure
        info = is_runtime_disabled("skip_pool")
        assert info is not None
        assert "reason" in info
        assert "remaining_seconds" in info
        assert "expired" in info
        assert info["expired"] is False

    def test_expired_pool_returns_expired_flag(self):
        """Test that expired pools return expired=True."""
        mgr = get_runtime_disabled_manager()
        # Override config for testing
        mgr.config = dict(mgr.config)
        mgr.config["ttl_seconds"] = 0.1  # Very short TTL
        
        mgr.record_failure("expire_pool", "LIQUIDITY_ZERO")
        
        # Wait for expiration
        time.sleep(0.2)
        
        info = mgr.is_disabled("expire_pool")
        # After expiration, expired flag should be True
        assert info is not None
        assert info.get("expired", False) is True


class TestEdgeCases:
    """Edge case and error handling tests."""

    # NOTE: setup/teardown handled by autouse fixture 'isolated_runtime_cache'

    def test_empty_pool_key(self):
        """Test handling of empty pool key."""
        # Should not crash with empty key
        info = is_runtime_disabled("")
        assert info is None

    def test_none_error_code(self):
        """Test handling of None error code."""
        # Should handle gracefully
        auto_disable_pool("none_error_pool", None, {})
        
        # Should not be disabled (no error code)
        info = is_runtime_disabled("none_error_pool")
        assert info is None

    def test_concurrent_access(self):
        """Test thread safety with concurrent access."""
        import threading
        
        results = []
        
        def worker(pool_id):
            for _ in range(10):
                auto_disable_pool(f"concurrent_{pool_id}", "SUSPECT_LIQUIDITY", {})
                is_runtime_disabled(f"concurrent_{pool_id}")
                record_quote_success(f"concurrent_{pool_id}")
            results.append(True)
        
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(results) == 5


# =============================================================================
# TEST ISOLATION GUARD
# =============================================================================

class TestCachePollutionGuard:
    """
    Guard test to verify that no tests pollute the production cache.
    
    This test verifies that data/cache/runtime_disabled_pools.json
    does not contain test-specific pool keys after running the test suite.
    
    If this test fails, it means the autouse fixture is not working correctly.
    """

    def test_production_cache_not_polluted(self):
        """
        Verify data/cache/runtime_disabled_pools.json is not polluted by tests.
        
        Test keys that should NEVER appear in production cache:
        - test_pool, threshold_pool, immediate_pool, expire_pool, skip_pool
        - concurrent_*, none_error_pool, reset_test_pool, etc.
        """
        cache_path = Path("data/cache/runtime_disabled_pools.json")
        
        if not cache_path.exists():
            # No cache file - no pollution
            return
        
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            # Invalid JSON - not our concern here
            return
        
        entries = data.get("entries", [])
        test_patterns = [
            "test_pool", "threshold_pool", "immediate_pool", "expire_pool",
            "skip_pool", "concurrent_", "none_error_pool", "reset_test_pool",
            "success_pool", "preexisting_pool", "persistent_pool",
            "threshold_test_pool",
        ]
        
        polluted_keys = []
        for entry in entries:
            pool_key = entry.get("pool_key", "")
            for pattern in test_patterns:
                if pattern in pool_key:
                    polluted_keys.append(pool_key)
                    break
        
        assert not polluted_keys, (
            f"Production cache polluted with test keys: {polluted_keys}. "
            f"The autouse fixture 'isolated_runtime_cache' should prevent this."
        )
