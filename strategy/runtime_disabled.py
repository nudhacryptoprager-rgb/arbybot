"""
strategy/runtime_disabled.py - Runtime auto-disable for consistently failing pools.

This module provides a mechanism for the bot to automatically disable pools
that consistently fail (SUSPECT_LIQUIDITY, PRICE_SANITY_FAILED, LIQUIDITY_ZERO)
without manual YAML changes.

The runtime-disabled list is persisted in data/cache/runtime_disabled_pools.json
and is checked in addition to the static disabled_pools in YAML config.

v3.2.0 CONTRACT:
================
- Runtime-disabled pools are checked BEFORE config disabled_pools
- Pools can be auto-disabled after N consecutive failures
- Pools auto-re-enable after TTL expires AND a successful quote
- LIQUIDITY_ZERO pools are immediately disabled (no threshold)
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

RUNTIME_DISABLED_CONFIG = {
    # Cache file path (relative to workspace root)
    "cache_file": "data/cache/runtime_disabled_pools.json",
    
    # Auto-disable threshold (consecutive failures)
    "failure_threshold": 3,
    
    # TTL for runtime-disabled pools (seconds)
    "ttl_seconds": 3600,  # 1 hour
    
    # Error codes that trigger auto-disable
    "auto_disable_errors": [
        "SUSPECT_LIQUIDITY",
        "PRICE_SANITY_FAILED",
        "LIQUIDITY_ZERO",
    ],
    
    # Errors that immediately disable (no threshold)
    "immediate_disable_errors": [
        "LIQUIDITY_ZERO",
    ],
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class RuntimeDisabledEntry:
    """Entry for a runtime-disabled pool."""
    pool_key: str  # e.g. "sushiswap_v3_WETH_USDC_100"
    reason: str  # Error code (e.g. "SUSPECT_LIQUIDITY")
    disabled_at: float  # Unix timestamp
    failure_count: int = 1
    last_error_details: dict = field(default_factory=dict)
    
    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if this entry has expired (can attempt re-enable)."""
        return time.time() > (self.disabled_at + ttl_seconds)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "RuntimeDisabledEntry":
        return cls(
            pool_key=data["pool_key"],
            reason=data["reason"],
            disabled_at=data["disabled_at"],
            failure_count=data.get("failure_count", 1),
            last_error_details=data.get("last_error_details", {}),
        )


# =============================================================================
# RUNTIME DISABLED MANAGER
# =============================================================================

class RuntimeDisabledManager:
    """
    Manages runtime-disabled pools with persistence.
    
    Usage:
        manager = get_runtime_disabled_manager()
        
        # Check if pool is disabled
        if manager.is_disabled(pool_key):
            # skip quoting
            
        # Record failure (may trigger auto-disable)
        manager.record_failure(pool_key, "SUSPECT_LIQUIDITY")
        
        # Record success (may re-enable if expired)
        manager.record_success(pool_key)
    """
    
    _instance: Optional["RuntimeDisabledManager"] = None
    
    def __init__(self, config: dict | None = None, cache_path: str | None = None):
        self.config = config or RUNTIME_DISABLED_CONFIG
        self.cache_path = cache_path or self.config["cache_file"]
        self._entries: dict[str, RuntimeDisabledEntry] = {}
        self._failure_counts: dict[str, int] = {}  # Track consecutive failures
        self._stats = {
            "auto_disabled_count": 0,
            "re_enabled_count": 0,
            "cache_loaded": False,
        }
        self._load_cache()
    
    def _load_cache(self) -> None:
        """Load runtime-disabled entries from cache file."""
        if not os.path.exists(self.cache_path):
            logger.debug("Runtime-disabled cache not found: %s", self.cache_path)
            return
        
        try:
            with open(self.cache_path, "r") as f:
                data = json.load(f)
            
            entries = data.get("entries", [])
            for entry_data in entries:
                entry = RuntimeDisabledEntry.from_dict(entry_data)
                self._entries[entry.pool_key] = entry
            
            self._stats["cache_loaded"] = True
            logger.info("Loaded %d runtime-disabled entries from cache", len(self._entries))
        except Exception as e:
            logger.warning("Failed to load runtime-disabled cache: %s", e)
    
    def _save_cache(self) -> None:
        """Persist runtime-disabled entries to cache file.
        
        v3.2.2: Uses atomic write (temp file + replace) to prevent corruption
        if the process crashes during write.
        """
        import tempfile
        try:
            # Ensure directory exists
            cache_dir = os.path.dirname(self.cache_path)
            os.makedirs(cache_dir, exist_ok=True)
            
            data = {
                "schema_version": "1.0.0",
                "updated_at": time.time(),
                "entries": [e.to_dict() for e in self._entries.values()],
            }
            
            # v3.2.2: Atomic write - write to temp file then replace
            # This prevents corruption if process crashes during write
            fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f, indent=2)
                # Atomic replace (on Windows, need to delete first if exists)
                if os.path.exists(self.cache_path):
                    os.replace(tmp_path, self.cache_path)
                else:
                    os.rename(tmp_path, self.cache_path)
            except Exception:
                # Clean up temp file on failure
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
            
            logger.debug("Saved %d runtime-disabled entries to cache", len(self._entries))
        except Exception as e:
            logger.warning("Failed to save runtime-disabled cache: %s", e)
    
    def is_disabled(self, pool_key: str) -> Optional[dict]:
        """
        Check if a pool is runtime-disabled.
        
        Args:
            pool_key: Pool key (e.g. "sushiswap_v3_WETH_USDC_100")
            
        Returns:
            Dict with reason/details if disabled, None otherwise
        """
        entry = self._entries.get(pool_key)
        if entry is None:
            return None
        
        # Check if expired (can attempt re-enable)
        ttl = self.config.get("ttl_seconds", 3600)
        if entry.is_expired(ttl):
            remaining_seconds = 0
        else:
            remaining_seconds = int(entry.disabled_at + ttl - time.time())
        
        return {
            "reason": f"RUNTIME_DISABLED:{entry.reason}",
            "disabled_at": entry.disabled_at,
            "failure_count": entry.failure_count,
            "expired": entry.is_expired(ttl),
            "remaining_seconds": remaining_seconds,
        }
    
    def record_failure(
        self,
        pool_key: str,
        error_code: str,
        details: dict | None = None,
    ) -> bool:
        """
        Record a failure for a pool.
        
        May trigger auto-disable if threshold reached.
        
        Args:
            pool_key: Pool key
            error_code: Error code (e.g. "SUSPECT_LIQUIDITY")
            details: Optional error details
            
        Returns:
            True if this failure caused auto-disable
        """
        auto_disable_errors = self.config.get("auto_disable_errors", [])
        immediate_errors = self.config.get("immediate_disable_errors", [])
        
        # Only track auto-disable errors
        if error_code not in auto_disable_errors:
            return False
        
        # Increment failure count
        self._failure_counts[pool_key] = self._failure_counts.get(pool_key, 0) + 1
        count = self._failure_counts[pool_key]
        
        # Check if should auto-disable
        threshold = self.config.get("failure_threshold", 3)
        should_disable = (
            error_code in immediate_errors or
            count >= threshold
        )
        
        if should_disable:
            self._entries[pool_key] = RuntimeDisabledEntry(
                pool_key=pool_key,
                reason=error_code,
                disabled_at=time.time(),
                failure_count=count,
                last_error_details=details or {},
            )
            self._stats["auto_disabled_count"] += 1
            self._save_cache()
            
            logger.warning(
                "AUTO-DISABLED: %s reason=%s failures=%d",
                pool_key, error_code, count
            )
            return True
        
        return False
    
    def record_success(self, pool_key: str) -> bool:
        """
        Record a successful quote for a pool.
        
        If the pool is runtime-disabled but expired, this will re-enable it.
        Also resets failure count.
        
        Args:
            pool_key: Pool key
            
        Returns:
            True if this success re-enabled the pool
        """
        # Reset failure count
        self._failure_counts[pool_key] = 0
        
        # Check if pool is runtime-disabled and expired
        entry = self._entries.get(pool_key)
        if entry is None:
            return False
        
        ttl = self.config.get("ttl_seconds", 3600)
        if entry.is_expired(ttl):
            # Re-enable
            del self._entries[pool_key]
            self._stats["re_enabled_count"] += 1
            self._save_cache()
            
            logger.info(
                "RE-ENABLED: %s (was disabled for %s, TTL expired)",
                pool_key, entry.reason
            )
            return True
        
        return False
    
    def get_all_disabled(self) -> list[dict]:
        """Get all runtime-disabled pools."""
        return [
            {"pool_key": k, **self.is_disabled(k)}
            for k in self._entries.keys()
        ]
    
    def get_stats(self) -> dict:
        """Get manager statistics."""
        return {
            **self._stats,
            "currently_disabled": len(self._entries),
            "failure_counts": dict(self._failure_counts),
        }
    
    def clear_all(self) -> None:
        """Clear all runtime-disabled entries (for testing/reset)."""
        self._entries.clear()
        self._failure_counts.clear()
        self._save_cache()
        logger.info("Cleared all runtime-disabled entries")


# =============================================================================
# SINGLETON
# =============================================================================

_manager_instance: Optional[RuntimeDisabledManager] = None


def get_runtime_disabled_manager(
    config: dict | None = None,
    cache_path: str | None = None,
    force_new: bool = False,
) -> RuntimeDisabledManager:
    """
    Get the singleton RuntimeDisabledManager.
    
    Args:
        config: Optional config override
        cache_path: Optional cache path override
        force_new: Force create new instance (for testing)
        
    Returns:
        RuntimeDisabledManager instance
    """
    global _manager_instance
    
    if force_new or _manager_instance is None:
        _manager_instance = RuntimeDisabledManager(config, cache_path)
    
    return _manager_instance


def clear_runtime_disabled_manager() -> None:
    """
    Clear the singleton RuntimeDisabledManager (for testing).
    
    This resets the manager state and clears the global instance.
    """
    global _manager_instance
    if _manager_instance is not None:
        _manager_instance._entries.clear()
        _manager_instance._failure_counts.clear()
    _manager_instance = None


# =============================================================================
# INTEGRATION HELPERS
# =============================================================================

def is_runtime_disabled(pool_key: str) -> Optional[dict]:
    """
    Check if a pool is runtime-disabled.
    
    This is a convenience function for use in strategy/quotes.py.
    
    Args:
        pool_key: Pool key (e.g. "sushiswap_v3_WETH_USDC_100")
        
    Returns:
        Dict with reason/details if disabled, None otherwise
    """
    manager = get_runtime_disabled_manager()
    return manager.is_disabled(pool_key)


def auto_disable_pool(
    pool_key: str,
    error_code: str,
    details: dict | None = None,
) -> bool:
    """
    Record a failure that may trigger auto-disable.
    
    This is a convenience function for use in strategy/quotes.py.
    
    Args:
        pool_key: Pool key
        error_code: Error code (e.g. "SUSPECT_LIQUIDITY", "LIQUIDITY_ZERO")
        details: Optional error details
        
    Returns:
        True if pool was auto-disabled
    """
    manager = get_runtime_disabled_manager()
    return manager.record_failure(pool_key, error_code, details)


def record_quote_success(pool_key: str) -> bool:
    """
    Record a successful quote for a pool.
    
    This is a convenience function for use in strategy/quotes.py.
    
    Args:
        pool_key: Pool key
        
    Returns:
        True if pool was re-enabled
    """
    manager = get_runtime_disabled_manager()
    return manager.record_success(pool_key)
