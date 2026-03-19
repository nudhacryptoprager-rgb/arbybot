"""
Unit tests for chain-scoped cache behavior.

Tests that:
- Chain-scoped cache paths include chain_key suffix
- Legacy cache paths used when chain_key is None or 'unknown'
- Chain switching saves current state and loads from new chain's cache
- Cross-chain isolation: data from chain A not visible to chain B

v3.2.11: Initial implementation
v3.2.12: Added content assertions and conftest.py autouse isolation
"""
import json
from pathlib import Path
from unittest import mock

import pytest


class TestQuarantineChainScoped:
    """Tests for strategy/quarantine.py chain-scoped persistence."""
    
    def test_cache_path_suffix_arbitrum(self, tmp_path):
        """Chain-scoped path must include chain_key suffix (arbitrum)."""
        # Note: conftest.py redirects paths to tmp_path, so we test returned path contains suffix
        from strategy.quarantine import _get_quarantine_cache_path
        
        path = _get_quarantine_cache_path("arbitrum_one")
        assert "arbitrum_one" in str(path)
    
    def test_cache_path_suffix_linea(self, tmp_path):
        """Chain-scoped path must include chain_key suffix (linea)."""
        from strategy.quarantine import _get_quarantine_cache_path
        
        path = _get_quarantine_cache_path("linea")
        assert "linea" in str(path)
    
    def test_cache_path_legacy_none(self, tmp_path):
        """Legacy path used when chain_key is None (no chain_key suffix)."""
        from strategy.quarantine import _get_quarantine_cache_path
        
        path = _get_quarantine_cache_path(None)
        # Legacy path should NOT contain any chain_key suffix like "_arbitrum_one"
        assert "quarantine" in str(path).lower()
        assert "_arbitrum" not in str(path)
        assert "_linea" not in str(path)
    
    def test_cache_path_legacy_unknown(self, tmp_path):
        """Legacy path used when chain_key is 'unknown' (no chain suffix)."""
        from strategy.quarantine import _get_quarantine_cache_path
        
        path = _get_quarantine_cache_path("unknown")
        # 'unknown' should NOT produce a path with "_unknown" suffix
        # It should use the same legacy path as None
        # v3.2.14: Check only filename, not full path (tmp_path may contain test name)
        assert "_unknown" not in path.name, f"Filename should not contain _unknown: {path.name}"
    
    def test_manager_record_and_flush_chain_a(self, tmp_path):
        """Manager records and flushes to chain-scoped file."""
        from strategy.quarantine import (
            get_quarantine_manager,
            flush_quarantine_manager,
            _get_quarantine_cache_path,
        )
        
        # Record failure for chain A
        mgr = get_quarantine_manager(chain_key="arbitrum_one")
        mgr.record_failure(
            dex_id="test_dex",
            pair="WETH/USDC",
            fee=3000,
            error_code="TEST_ERROR",
        )
        
        # Flush and verify file content
        flush_quarantine_manager(chain_key="arbitrum_one")
        
        cache_path = _get_quarantine_cache_path("arbitrum_one")
        assert cache_path.exists(), f"Cache file should exist at {cache_path}"
        
        content = json.loads(cache_path.read_text())
        assert "records" in content
        assert len(content["records"]) > 0
        # Verify chain_key in metadata
        assert content.get("chain_key") == "arbitrum_one"
    
    def test_chain_switch_isolates_data(self, tmp_path):
        """Switching chain_key isolates data: chain B should not see chain A records."""
        from strategy.quarantine import (
            get_quarantine_manager,
            reset_quarantine_manager,
            flush_quarantine_manager,
            _get_quarantine_cache_path,
        )
        
        # Record failure for chain A
        reset_quarantine_manager()
        mgr_a = get_quarantine_manager(chain_key="arbitrum_one")
        mgr_a.record_failure(
            dex_id="dex_chain_a",
            pair="WETH/USDC",
            fee=500,
            error_code="CHAIN_A_ERROR",
        )
        flush_quarantine_manager(chain_key="arbitrum_one")
        
        # Switch to chain B - should have empty records (no cache file for B)
        reset_quarantine_manager()
        mgr_b = get_quarantine_manager(chain_key="linea")
        
        # Chain B should not have chain A's records
        assert len(mgr_b._records) == 0, "Chain B should start with empty records"
        
        # Verify chain A's cache file exists with data
        cache_a = _get_quarantine_cache_path("arbitrum_one")
        assert cache_a.exists()
        content_a = json.loads(cache_a.read_text())
        assert len(content_a["records"]) > 0
        
        # Verify chain B's cache file doesn't exist yet
        cache_b = _get_quarantine_cache_path("linea")
        assert not cache_b.exists() or json.loads(cache_b.read_text()).get("records", {}) == {}

    def test_zombie_quarantine_reset_on_load(self, tmp_path):
        """R28.22: Non-quarantined records must have consecutive_failures reset on load.
        
        Prevents zombie re-quarantine where stale high-failure records
        from previous sessions cause immediate re-quarantine on first failure.
        """
        import time as _time
        from strategy.quarantine import (
            QuarantineManager,
            QuarantineKey,
            FailureRecord,
            save_quarantine_state,
            load_quarantine_state,
            _get_quarantine_cache_path,
        )

        # Create a manager with a record that has high failures but NOT quarantined
        mgr = QuarantineManager()
        key = QuarantineKey("test_dex", "WETH/USDC", 3000, None)
        mgr._records[key] = FailureRecord(
            consecutive_failures=5,  # Above threshold
            total_failures=10,
            last_failure_time=_time.time() - 600,  # 10 min ago
            last_error_code="QUOTE_REVERT",
            quarantined_until=0.0,  # NOT quarantined (expired or reset)
            quarantine_count=2,
        )

        # Save to disk
        save_quarantine_state(mgr, chain_key="test_zombie")

        # Load into fresh manager
        mgr2 = QuarantineManager()
        load_quarantine_state(mgr2, chain_key="test_zombie")

        loaded_record = mgr2._records.get(key)
        assert loaded_record is not None, "Record should be loaded"
        assert loaded_record.consecutive_failures == 0, (
            f"consecutive_failures should be reset to 0 for non-quarantined records, "
            f"got {loaded_record.consecutive_failures}"
        )
        # total_failures should be preserved (historical stat)
        assert loaded_record.total_failures == 10

        # Cleanup
        cache_path = _get_quarantine_cache_path("test_zombie")
        if cache_path.exists():
            cache_path.unlink()


class TestRuntimeDisabledChainScoped:
    """Tests for strategy/runtime_disabled.py chain-scoped persistence."""
    
    def test_cache_path_suffix(self, tmp_path):
        """Chain-scoped path must include chain_key suffix."""
        from strategy.runtime_disabled import _get_runtime_disabled_cache_path
        
        path = _get_runtime_disabled_cache_path("linea")
        assert "linea" in path
    
    def test_cache_path_legacy_none(self, tmp_path):
        """Legacy path used when chain_key is None (no chain suffix)."""
        from strategy.runtime_disabled import _get_runtime_disabled_cache_path
        
        path = _get_runtime_disabled_cache_path(None)
        # Legacy path should NOT contain chain_key suffix
        assert "runtime_disabled" in path.lower()
        assert "_arbitrum" not in path
        assert "_linea" not in path
    
    def test_manager_uses_chain_path(self, tmp_path):
        """Manager initialized with chain_key should use chain-scoped path."""
        from strategy.runtime_disabled import (
            get_runtime_disabled_manager,
            clear_runtime_disabled_manager,
        )
        
        clear_runtime_disabled_manager()
        mgr = get_runtime_disabled_manager(chain_key="arbitrum_one")
        assert "arbitrum_one" in mgr.cache_path
    
    def test_record_failure_persists_to_chain_file(self, tmp_path):
        """record_failure should persist to chain-scoped file."""
        from strategy.runtime_disabled import (
            get_runtime_disabled_manager,
            clear_runtime_disabled_manager,
            _get_runtime_disabled_cache_path,
        )
        
        clear_runtime_disabled_manager()
        # Use config with auto_disable_errors so record_failure has effect
        config = {
            "auto_disable_errors": ["ZERO_LIQUIDITY"],
            "failure_threshold": 2,
        }
        mgr = get_runtime_disabled_manager(config=config, chain_key="arbitrum_one")
        
        # Record failures to trigger auto-disable (use correct API: pool_key, error_code)
        for _ in range(3):  # Hit threshold
            mgr.record_failure(
                pool_key="test_dex:TEST/POOL:3000",
                error_code="ZERO_LIQUIDITY",
            )
        
        # Verify file exists and has content
        cache_path = _get_runtime_disabled_cache_path("arbitrum_one")
        assert Path(cache_path).exists(), f"Cache file should exist at {cache_path}"
        
        content = json.loads(Path(cache_path).read_text())
        # File should have some structure (entries or failure_counts)
        assert "entries" in content or "failure_counts" in content or len(content) > 0
    
    def test_chain_switch_isolates_data(self, tmp_path):
        """Switching chain_key isolates data: chain B should not see chain A entries."""
        from strategy.runtime_disabled import (
            get_runtime_disabled_manager,
            clear_runtime_disabled_manager,
        )
        
        # Record failure for chain A
        clear_runtime_disabled_manager()
        config = {
            "auto_disable_errors": ["TEST_ERROR"],
            "failure_threshold": 2,
        }
        mgr_a = get_runtime_disabled_manager(config=config, chain_key="arbitrum_one")
        for _ in range(3):
            mgr_a.record_failure(
                pool_key="dex_a:A/B:500",
                error_code="TEST_ERROR",
            )
        
        # Switch to chain B
        clear_runtime_disabled_manager()
        mgr_b = get_runtime_disabled_manager(chain_key="linea")
        
        # Chain B should not have chain A's entries
        assert len(mgr_b._entries) == 0, "Chain B should start with empty entries"


class TestDynamicAnchorsChainScoped:
    """Tests for strategy/dynamic_anchors.py chain-scoped persistence."""
    
    def test_cache_path_suffix(self, tmp_path):
        """Chain-scoped path must include chain_key suffix."""
        from strategy.dynamic_anchors import _get_anchor_cache_path
        
        path = _get_anchor_cache_path("arbitrum_one")
        assert "arbitrum_one" in str(path)
    
    def test_cache_path_legacy_none(self, tmp_path):
        """Legacy path used when chain_key is None (no chain suffix)."""
        from strategy.dynamic_anchors import _get_anchor_cache_path
        
        path = _get_anchor_cache_path(None)
        # Legacy path should NOT contain chain_key suffixes
        assert "dynamic_anchors" in str(path).lower()
        assert "_arbitrum" not in str(path)
        assert "_linea" not in str(path)
    
    def test_record_quote_and_flush(self, tmp_path):
        """record_quote should persist to chain-scoped file on flush."""
        from strategy.dynamic_anchors import (
            get_anchor_manager,
            reset_anchor_manager,
            _get_anchor_cache_path,
        )
        
        reset_anchor_manager()
        mgr = get_anchor_manager(chain_key="arbitrum_one")
        
        # Record a quote
        mgr.record_quote(
            pair="WETH/USDC",
            dex_id="uniswap_v3",
            price=3000.0,
            fee_tier=3000,
            block=12345678,
        )
        
        # Flush to disk
        mgr.flush()
        
        # Verify file exists and has content
        cache_path = _get_anchor_cache_path("arbitrum_one")
        assert cache_path.exists(), f"Cache file should exist at {cache_path}"
        
        content = json.loads(cache_path.read_text())
        assert "pairs" in content
        assert len(content["pairs"]) > 0
        # Cache file should exist with valid structure (chain_key in metadata is optional)
    
    def test_chain_switch_isolates_data(self, tmp_path):
        """Switching chain_key isolates data: chain B should not see chain A samples."""
        from strategy.dynamic_anchors import (
            get_anchor_manager,
            reset_anchor_manager,
            _get_anchor_cache_path,
        )
        
        # Record for chain A and flush
        reset_anchor_manager()
        mgr_a = get_anchor_manager(chain_key="arbitrum_one")
        mgr_a.record_quote(
            pair="ARB/USDC",
            dex_id="uniswap_v3",
            price=1.5,
            fee_tier=3000,
            block=12345678,
        )
        mgr_a.flush()
        
        # Verify chain A cache has data
        cache_a = _get_anchor_cache_path("arbitrum_one")
        assert cache_a.exists()
        content_a = json.loads(cache_a.read_text())
        assert len(content_a.get("pairs", {})) > 0
        
        # Switch to chain B - should have empty pairs
        reset_anchor_manager()
        mgr_b = get_anchor_manager(chain_key="linea")
        
        # Chain B should not have chain A's data loaded
        assert len(mgr_b._pairs) == 0, "Chain B should start with empty pairs"


class TestChainScopedPathDetermination:
    """Tests for correct chain key → path determination across all managers."""
    
    @pytest.mark.parametrize("chain_key,expected_suffix", [
        ("arbitrum_one", "arbitrum_one"),
        ("linea", "linea"),
        ("base", "base"),
        ("optimism", "optimism"),
    ])
    def test_quarantine_path_suffix(self, chain_key, expected_suffix, tmp_path):
        """Quarantine cache path must contain chain_key."""
        from strategy.quarantine import _get_quarantine_cache_path
        path = _get_quarantine_cache_path(chain_key)
        assert expected_suffix in str(path)
    
    @pytest.mark.parametrize("chain_key,expected_suffix", [
        ("arbitrum_one", "arbitrum_one"),
        ("linea", "linea"),
    ])
    def test_runtime_disabled_path_suffix(self, chain_key, expected_suffix, tmp_path):
        """Runtime disabled cache path must contain chain_key."""
        from strategy.runtime_disabled import _get_runtime_disabled_cache_path
        path = _get_runtime_disabled_cache_path(chain_key)
        assert expected_suffix in path
    
    @pytest.mark.parametrize("chain_key,expected_suffix", [
        ("arbitrum_one", "arbitrum_one"),
        ("linea", "linea"),
    ])
    def test_dynamic_anchors_path_suffix(self, chain_key, expected_suffix, tmp_path):
        """Dynamic anchors cache path must contain chain_key."""
        from strategy.dynamic_anchors import _get_anchor_cache_path
        path = _get_anchor_cache_path(chain_key)
        assert expected_suffix in str(path)
    
    @pytest.mark.parametrize("chain_key,expected_suffix", [
        ("arbitrum_one", "arbitrum_one"),
        ("linea", "linea"),
    ])
    def test_pool_resolver_path_suffix(self, chain_key, expected_suffix, tmp_path):
        """v3.2.16: Pool resolver cache path must contain chain_key."""
        from discovery.pool_resolver import _get_cache_path
        path = _get_cache_path(chain_key)
        assert expected_suffix in str(path)
