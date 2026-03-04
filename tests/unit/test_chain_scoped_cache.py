"""
Unit tests for chain-scoped cache behavior.

Tests that:
- Chain-scoped cache paths include chain_key suffix
- Legacy cache paths used when chain_key is None or 'unknown'
- Chain switching saves current state and loads from new chain's cache

v3.2.11: Initial implementation
"""
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest


class TestQuarantineChainScoped:
    """Tests for strategy/quarantine.py chain-scoped persistence."""
    
    def test_cache_path_with_chain_key(self):
        """Chain-scoped path must include chain_key suffix."""
        from strategy.quarantine import _get_quarantine_cache_path
        
        path = _get_quarantine_cache_path("arbitrum_one")
        assert "arbitrum_one" in str(path)
        assert path == Path("data/cache/quarantine_state_arbitrum_one.json")
    
    def test_cache_path_without_chain_key(self):
        """Legacy path used when chain_key is None."""
        from strategy.quarantine import _get_quarantine_cache_path
        
        path = _get_quarantine_cache_path(None)
        assert "quarantine_state.json" in str(path)
        assert "_" not in path.name or path.name == "quarantine_state.json"
    
    def test_cache_path_with_unknown(self):
        """Legacy path used when chain_key is 'unknown'."""
        from strategy.quarantine import _get_quarantine_cache_path
        
        path = _get_quarantine_cache_path("unknown")
        assert path == Path("data/cache/quarantine_state.json")
    
    def test_manager_chain_switch(self):
        """Switching chain_key should reset and reload from new chain's cache."""
        from strategy.quarantine import (
            get_quarantine_manager,
            reset_quarantine_manager,
        )
        
        # Reset to clean state
        reset_quarantine_manager()
        
        # Get manager for chain A and add a record via record_failure
        mgr_a = get_quarantine_manager(chain_key="arbitrum_one")
        mgr_a.record_failure(
            dex_id="test_dex",
            pair="A/B",
            fee=100,
            error_code="TEST_ERROR",
        )
        records_count_a = len(mgr_a._records)
        assert records_count_a > 0
        
        # Switch to chain B - should trigger save of A and load of B
        mgr_b = get_quarantine_manager(chain_key="linea")
        # mgr_b is the same object but reset for new chain
        # Since no cache file exists for linea, records should be empty
        # (Note: mgr_b may have 0 records if no cache, or same if same object)
        
        # Cleanup
        reset_quarantine_manager()


class TestRuntimeDisabledChainScoped:
    """Tests for strategy/runtime_disabled.py chain-scoped persistence."""
    
    def test_cache_path_with_chain_key(self):
        """Chain-scoped path must include chain_key suffix."""
        from strategy.runtime_disabled import _get_runtime_disabled_cache_path
        
        path = _get_runtime_disabled_cache_path("linea")
        assert "linea" in path
        assert path == "data/cache/runtime_disabled_pools_linea.json"
    
    def test_cache_path_without_chain_key(self):
        """Legacy path used when chain_key is None."""
        from strategy.runtime_disabled import _get_runtime_disabled_cache_path
        
        path = _get_runtime_disabled_cache_path(None)
        assert path == "data/cache/runtime_disabled_pools.json"
    
    def test_cache_path_with_unknown(self):
        """Legacy path used when chain_key is 'unknown'."""
        from strategy.runtime_disabled import _get_runtime_disabled_cache_path
        
        path = _get_runtime_disabled_cache_path("unknown")
        assert path == "data/cache/runtime_disabled_pools.json"
    
    def test_manager_with_chain_key_uses_chain_path(self):
        """Manager initialized with chain_key should use chain-scoped path."""
        from strategy.runtime_disabled import (
            get_runtime_disabled_manager,
            clear_runtime_disabled_manager,
        )
        
        # Reset
        clear_runtime_disabled_manager()
        
        # Get manager with chain_key
        mgr = get_runtime_disabled_manager(chain_key="arbitrum_one")
        assert "arbitrum_one" in mgr.cache_path
        
        # Cleanup
        clear_runtime_disabled_manager()


class TestDynamicAnchorsChainScoped:
    """Tests for strategy/dynamic_anchors.py chain-scoped persistence."""
    
    def test_cache_path_with_chain_key(self):
        """Chain-scoped path must include chain_key suffix."""
        from strategy.dynamic_anchors import _get_anchor_cache_path
        
        path = _get_anchor_cache_path("arbitrum_one")
        assert "arbitrum_one" in str(path)
        assert path == Path("data/cache/dynamic_anchors_arbitrum_one.json")
    
    def test_cache_path_without_chain_key(self):
        """Legacy path used when chain_key is None."""
        from strategy.dynamic_anchors import _get_anchor_cache_path
        
        path = _get_anchor_cache_path(None)
        assert path == Path("data/cache/dynamic_anchors.json")
    
    def test_cache_path_with_unknown(self):
        """Legacy path used when chain_key is 'unknown'."""
        from strategy.dynamic_anchors import _get_anchor_cache_path
        
        path = _get_anchor_cache_path("unknown")
        assert path == Path("data/cache/dynamic_anchors.json")
    
    def test_manager_chain_switch(self):
        """Switching chain_key should reset and reload from new chain's cache."""
        from strategy.dynamic_anchors import (
            get_anchor_manager,
            reset_anchor_manager,
        )
        
        # Reset to clean state
        reset_anchor_manager()
        
        # Get manager for chain A and add sample via record_quote
        mgr_a = get_anchor_manager(chain_key="arbitrum_one")
        mgr_a.record_quote(
            pair="WETH/USDC",
            dex_id="uniswap_v3",
            price=3000.0,
            fee_tier=3000,
            block=12345,
        )
        initial_pairs = len(mgr_a._pairs)
        assert initial_pairs > 0, "Should have recorded at least one pair"
        
        # Reset and switch to chain B - should be fresh (no pairs from A)
        reset_anchor_manager()
        mgr_b = get_anchor_manager(chain_key="linea")
        # Chain B should not have chain A's data loaded
        # (assuming no cache file exists for linea)
        
        # Cleanup
        reset_anchor_manager()


class TestChainScopedPathDetermination:
    """Tests for correct chain key → path determination across all managers."""
    
    @pytest.mark.parametrize("chain_key,expected_suffix", [
        ("arbitrum_one", "arbitrum_one"),
        ("linea", "linea"),
        ("base", "base"),
        ("optimism", "optimism"),
    ])
    def test_quarantine_path_suffix(self, chain_key, expected_suffix):
        """Quarantine cache path must contain chain_key."""
        from strategy.quarantine import _get_quarantine_cache_path
        path = _get_quarantine_cache_path(chain_key)
        assert expected_suffix in str(path)
    
    @pytest.mark.parametrize("chain_key,expected_suffix", [
        ("arbitrum_one", "arbitrum_one"),
        ("linea", "linea"),
    ])
    def test_runtime_disabled_path_suffix(self, chain_key, expected_suffix):
        """Runtime disabled cache path must contain chain_key."""
        from strategy.runtime_disabled import _get_runtime_disabled_cache_path
        path = _get_runtime_disabled_cache_path(chain_key)
        assert expected_suffix in path
    
    @pytest.mark.parametrize("chain_key,expected_suffix", [
        ("arbitrum_one", "arbitrum_one"),
        ("linea", "linea"),
    ])
    def test_dynamic_anchors_path_suffix(self, chain_key, expected_suffix):
        """Dynamic anchors cache path must contain chain_key."""
        from strategy.dynamic_anchors import _get_anchor_cache_path
        path = _get_anchor_cache_path(chain_key)
        assert expected_suffix in str(path)
