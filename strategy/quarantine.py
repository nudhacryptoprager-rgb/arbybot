"""
strategy/quarantine.py - Automatic quarantine for consistently failing pools.

Team Lead:
"Quarantine pravylo: yakshcho QUOTE_REVERT stabil'nyi na konkretnii 
(dex, pair, fee, quoter) — avtomatychno quarantine na N khvylyn/tsykliv."

This module tracks failure patterns and quarantines pools that consistently fail.

v2.2.0 CANONICAL SOURCE:
========================
This is the canonical runtime quarantine manager for quote collection.
Used by strategy/quotes.py via get_quarantine_manager().

The discovery/quarantine.py module provides a separate cycle-based system
for registry/universe pruning. The two serve different purposes:
- strategy/quarantine.py: Runtime, time-based (this file)
- discovery/quarantine.py: Registry, cycle-based

For all runtime quote filtering, import from this module:
    from strategy.quarantine import get_quarantine_manager
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# QUARANTINE CONFIGURATION
# =============================================================================

# Quarantine thresholds
QUARANTINE_CONFIG = {
    # How many consecutive failures before quarantine
    "failure_threshold": 3,
    
    # How long to quarantine (seconds)
    "quarantine_duration_seconds": 300,  # 5 minutes
    
    # How many cycles before quarantine (alternative)
    "quarantine_cycles": 10,
    
    # Error codes that trigger quarantine tracking
    "trackable_errors": [
        "QUOTE_REVERT",
        "QUOTE_TIMEOUT",
        "RPC_ERROR",
        "PRICE_SANITY_FAILED",  # v2.3.2: Auto-quarantine price sanity failures (Step 7)
    ],
    
    # Error codes that immediately quarantine (no threshold)
    "immediate_quarantine_errors": [
        "CONTRACT_NOT_FOUND",
        "INVALID_POOL",
    ],
}


# =============================================================================
# QUARANTINE KEY
# =============================================================================

@dataclass
class QuarantineKey:
    """
    Unique key for quarantine tracking.
    
    Identifies a specific (dex, pair, fee, quoter) combination.
    """
    dex_id: str
    pair: str
    fee: int
    quoter_address: str | None = None
    
    def __hash__(self) -> int:
        return hash((self.dex_id, self.pair, self.fee, self.quoter_address or ""))
    
    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, QuarantineKey):
            return False
        return (
            self.dex_id == other.dex_id and
            self.pair == other.pair and
            self.fee == other.fee and
            self.quoter_address == other.quoter_address
        )
    
    def __str__(self) -> str:
        return f"{self.dex_id}:{self.pair}:{self.fee}"


# =============================================================================
# FAILURE TRACKER
# =============================================================================

@dataclass
class FailureRecord:
    """Record of failures for a specific key."""
    consecutive_failures: int = 0
    total_failures: int = 0
    last_failure_time: float = 0.0
    last_error_code: str = ""
    last_error_details: dict = field(default_factory=dict)
    quarantined_until: float = 0.0
    quarantine_count: int = 0


class QuarantineManager:
    """
    Manages quarantine state for pools.
    
    Tracks failure patterns and quarantines pools that consistently fail.
    """
    
    def __init__(self, config: dict | None = None):
        self.config = config or QUARANTINE_CONFIG
        self._records: dict[QuarantineKey, FailureRecord] = {}
        self._stats = {
            "total_quarantines": 0,
            "active_quarantines": 0,
            "failures_tracked": 0,
        }
    
    def record_failure(
        self,
        dex_id: str,
        pair: str,
        fee: int,
        error_code: str,
        quoter_address: str | None = None,
        details: dict | None = None,
    ) -> bool:
        """
        Record a failure and potentially quarantine.
        
        Args:
            dex_id: DEX identifier
            pair: Trading pair
            fee: Fee tier
            error_code: Error code from the failure
            quoter_address: Optional quoter contract address
            details: Optional error details
        
        Returns:
            True if this failure resulted in quarantine
        """
        key = QuarantineKey(dex_id, pair, fee, quoter_address)
        now = time.time()
        
        # Get or create record
        if key not in self._records:
            self._records[key] = FailureRecord()
        
        record = self._records[key]
        
        # Update failure stats
        record.consecutive_failures += 1
        record.total_failures += 1
        record.last_failure_time = now
        record.last_error_code = error_code
        record.last_error_details = details or {}
        
        self._stats["failures_tracked"] += 1
        
        # Check if should quarantine
        should_quarantine = False
        
        # Immediate quarantine for certain errors
        if error_code in self.config.get("immediate_quarantine_errors", []):
            should_quarantine = True
            logger.warning(
                f"Immediate quarantine for {key}: {error_code}",
                extra={"context": details}
            )
        
        # Threshold-based quarantine
        elif error_code in self.config.get("trackable_errors", []):
            threshold = self.config.get("failure_threshold", 3)
            if record.consecutive_failures >= threshold:
                should_quarantine = True
                logger.warning(
                    f"Threshold quarantine for {key}: "
                    f"{record.consecutive_failures} consecutive failures",
                    extra={"context": details}
                )
        
        # Apply quarantine
        if should_quarantine:
            duration = self.config.get("quarantine_duration_seconds", 300)
            record.quarantined_until = now + duration
            record.quarantine_count += 1
            self._stats["total_quarantines"] += 1
            self._stats["active_quarantines"] += 1
            
            logger.info(
                f"Quarantined {key} for {duration}s (count: {record.quarantine_count})"
            )
        
        return should_quarantine
    
    def record_success(
        self,
        dex_id: str,
        pair: str,
        fee: int,
        quoter_address: str | None = None,
    ) -> None:
        """
        Record a success, resetting consecutive failure count.
        
        Args:
            dex_id: DEX identifier
            pair: Trading pair
            fee: Fee tier
            quoter_address: Optional quoter contract address
        """
        key = QuarantineKey(dex_id, pair, fee, quoter_address)
        
        if key in self._records:
            self._records[key].consecutive_failures = 0
    
    def is_quarantined(
        self,
        dex_id: str,
        pair: str,
        fee: int,
        quoter_address: str | None = None,
    ) -> bool:
        """
        Check if a pool is currently quarantined.
        
        Args:
            dex_id: DEX identifier
            pair: Trading pair
            fee: Fee tier
            quoter_address: Optional quoter contract address
        
        Returns:
            True if quarantined
        """
        key = QuarantineKey(dex_id, pair, fee, quoter_address)
        
        if key not in self._records:
            return False
        
        record = self._records[key]
        now = time.time()
        
        # Check if quarantine expired
        if record.quarantined_until > 0 and record.quarantined_until <= now:
            # Quarantine expired
            record.quarantined_until = 0.0
            record.consecutive_failures = 0  # Reset on expiry
            self._stats["active_quarantines"] = max(0, self._stats["active_quarantines"] - 1)
            logger.info(f"Quarantine expired for {key}")
            return False
        
        return record.quarantined_until > now
    
    def get_quarantine_remaining(
        self,
        dex_id: str,
        pair: str,
        fee: int,
        quoter_address: str | None = None,
    ) -> float:
        """
        Get remaining quarantine time in seconds.
        
        Returns 0 if not quarantined.
        """
        key = QuarantineKey(dex_id, pair, fee, quoter_address)
        
        if key not in self._records:
            return 0.0
        
        record = self._records[key]
        remaining = record.quarantined_until - time.time()
        return max(0.0, remaining)
    
    def get_record(
        self,
        dex_id: str,
        pair: str,
        fee: int,
        quoter_address: str | None = None,
    ) -> FailureRecord | None:
        """Get failure record for a key."""
        key = QuarantineKey(dex_id, pair, fee, quoter_address)
        return self._records.get(key)
    
    def get_all_quarantined(self) -> list[tuple[QuarantineKey, float]]:
        """Get all currently quarantined keys with remaining time."""
        now = time.time()
        result = []
        
        for key, record in self._records.items():
            if record.quarantined_until > now:
                remaining = record.quarantined_until - now
                result.append((key, remaining))
        
        return result
    
    def get_stats(self) -> dict:
        """Get quarantine statistics."""
        # Update active count
        now = time.time()
        active = sum(
            1 for r in self._records.values()
            if r.quarantined_until > now
        )
        self._stats["active_quarantines"] = active
        
        return {
            **self._stats,
            "tracked_keys": len(self._records),
        }
    
    def clear(self) -> None:
        """Clear all quarantine state."""
        self._records.clear()
        self._stats = {
            "total_quarantines": 0,
            "active_quarantines": 0,
            "failures_tracked": 0,
        }
    
    def to_dict(self) -> dict:
        """Export state for persistence/debugging."""
        return {
            "stats": self.get_stats(),
            "quarantined": [
                {
                    "key": str(key),
                    "dex_id": key.dex_id,
                    "pair": key.pair,
                    "fee": key.fee,
                    "remaining_seconds": remaining,
                }
                for key, remaining in self.get_all_quarantined()
            ],
            "records": {
                str(key): {
                    "consecutive_failures": record.consecutive_failures,
                    "total_failures": record.total_failures,
                    "last_error_code": record.last_error_code,
                    "quarantine_count": record.quarantine_count,
                }
                for key, record in self._records.items()
            },
        }


# =============================================================================
# PERSISTENCE (v2.2.0)
# =============================================================================

import json
from pathlib import Path

QUARANTINE_CACHE_PATH = Path("data/cache/quarantine_state.json")


def save_quarantine_state(manager: "QuarantineManager") -> bool:
    """
    Save quarantine state to disk cache.
    
    Returns True if saved successfully.
    """
    try:
        QUARANTINE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "version": "2.2.0",
            "saved_at": time.time(),
            "records": {}
        }
        for key, record in manager._records.items():
            state["records"][str(key)] = {
                "dex_id": key.dex_id,
                "pair": key.pair,
                "fee": key.fee,
                "quoter_address": key.quoter_address,
                "consecutive_failures": record.consecutive_failures,
                "total_failures": record.total_failures,
                "last_failure_time": record.last_failure_time,
                "last_error_code": record.last_error_code,
                "quarantined_until": record.quarantined_until,
                "quarantine_count": record.quarantine_count,
            }
        QUARANTINE_CACHE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        logger.debug("Quarantine state saved to %s", QUARANTINE_CACHE_PATH)
        return True
    except Exception as e:
        logger.warning("Failed to save quarantine state: %s", e)
        return False


def load_quarantine_state(manager: "QuarantineManager") -> bool:
    """
    Load quarantine state from disk cache.
    
    Returns True if loaded successfully.
    """
    try:
        if not QUARANTINE_CACHE_PATH.exists():
            return False
        
        state = json.loads(QUARANTINE_CACHE_PATH.read_text(encoding="utf-8"))
        now = time.time()
        loaded_count = 0
        
        for key_str, data in state.get("records", {}).items():
            # Skip expired quarantines
            quarantined_until = data.get("quarantined_until", 0.0)
            if quarantined_until > 0 and quarantined_until <= now:
                continue  # Expired
            
            key = QuarantineKey(
                dex_id=data["dex_id"],
                pair=data["pair"],
                fee=data["fee"],
                quoter_address=data.get("quoter_address"),
            )
            record = FailureRecord(
                consecutive_failures=data.get("consecutive_failures", 0),
                total_failures=data.get("total_failures", 0),
                last_failure_time=data.get("last_failure_time", 0.0),
                last_error_code=data.get("last_error_code", ""),
                quarantined_until=quarantined_until,
                quarantine_count=data.get("quarantine_count", 0),
            )
            manager._records[key] = record
            loaded_count += 1
        
        logger.info("Loaded %d quarantine records from cache", loaded_count)
        return loaded_count > 0
    except Exception as e:
        logger.warning("Failed to load quarantine state: %s", e)
        return False


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_quarantine_manager: QuarantineManager | None = None


def get_quarantine_manager() -> QuarantineManager:
    """Get the singleton quarantine manager (loads from cache if exists)."""
    global _quarantine_manager
    if _quarantine_manager is None:
        _quarantine_manager = QuarantineManager()
        load_quarantine_state(_quarantine_manager)
    return _quarantine_manager


def reset_quarantine_manager() -> None:
    """Reset the singleton (for testing)."""
    global _quarantine_manager
    if _quarantine_manager is not None:
        _quarantine_manager.clear()
    _quarantine_manager = None


def flush_quarantine_manager() -> bool:
    """Save current quarantine state to disk."""
    global _quarantine_manager
    if _quarantine_manager is not None:
        return save_quarantine_state(_quarantine_manager)
    return False
