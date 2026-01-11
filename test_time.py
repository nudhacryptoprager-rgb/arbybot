"""
tests/unit/test_time.py - Tests for core/time.py

Tests for freshness rules and block pinning.
"""

import pytest
import time

from core.time import (
    BlockPin,
    now_ms,
    now_utc,
    is_quote_fresh,
    is_block_fresh,
    check_freshness,
    FreshnessCheck,
    ScanClock,
    ms_to_seconds,
    seconds_to_ms,
)
from core.constants import DEFAULT_MAX_BLOCK_AGE, DEFAULT_MAX_QUOTE_AGE_MS


class TestTimeUtilities:
    """Test time utility functions."""
    
    def test_now_ms_returns_int(self):
        """now_ms returns integer milliseconds."""
        result = now_ms()
        assert isinstance(result, int)
        assert result > 0
    
    def test_now_ms_increases(self):
        """now_ms increases over time."""
        t1 = now_ms()
        time.sleep(0.01)  # 10ms
        t2 = now_ms()
        assert t2 > t1
    
    def test_now_utc_returns_datetime(self):
        """now_utc returns datetime."""
        from datetime import datetime, timezone
        result = now_utc()
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
    
    def ms_to_seconds(ms: int) -> int:
        """Convert milliseconds to seconds (integer division, truncates)."""
        return ms // 1000
    
    def test_seconds_to_ms(self):
        """Convert seconds to milliseconds."""
        assert seconds_to_ms(1) == 1000
        assert seconds_to_ms(0) == 0
        assert seconds_to_ms(2) == 2000


class TestBlockPin:
    """Test BlockPin dataclass."""
    
    def test_block_pin_creation(self):
        """Create BlockPin."""
        pin = BlockPin(
            block_number=12345678,
            block_timestamp=1704326400,
            pinned_at_ms=now_ms(),
            chain_id=42161,
        )
        assert pin.block_number == 12345678
        assert pin.chain_id == 42161
    
    def test_block_pin_age(self):
        """BlockPin tracks age."""
        old_time = now_ms() - 1000  # 1 second ago
        pin = BlockPin(
            block_number=100,
            block_timestamp=1704326400,
            pinned_at_ms=old_time,
            chain_id=1,
        )
        age = pin.age_ms
        assert age >= 1000
        assert age < 2000  # Should be ~1000ms
    
    def test_block_pin_is_stale_fresh(self):
        """Fresh BlockPin is not stale."""
        pin = BlockPin(
            block_number=100,
            block_timestamp=1704326400,
            pinned_at_ms=now_ms(),
            chain_id=1,
        )
        assert not pin.is_stale
    
    def test_block_pin_is_stale_old(self):
        """Old BlockPin is stale."""
        old_time = now_ms() - 3000  # 3 seconds ago (> DEFAULT_MAX_QUOTE_AGE_MS)
        pin = BlockPin(
            block_number=100,
            block_timestamp=1704326400,
            pinned_at_ms=old_time,
            chain_id=1,
        )
        assert pin.is_stale


class TestQuoteFreshness:
    """Test quote freshness functions."""
    
    def test_is_quote_fresh_recent(self):
        """Recent quote is fresh."""
        recent = now_ms() - 500  # 500ms ago
        assert is_quote_fresh(recent) is True
    
    def test_is_quote_fresh_old(self):
        """Old quote is not fresh."""
        old = now_ms() - 3000  # 3 seconds ago
        assert is_quote_fresh(old) is False
    
    def test_is_quote_fresh_custom_threshold(self):
        """Custom freshness threshold."""
        quote_time = now_ms() - 500
        # 500ms is fresh with 1000ms threshold
        assert is_quote_fresh(quote_time, max_age_ms=1000) is True
        # 500ms is not fresh with 400ms threshold
        assert is_quote_fresh(quote_time, max_age_ms=400) is False


class TestBlockFreshness:
    """Test block freshness functions."""
    
    def test_is_block_fresh_recent(self):
        """Recent block is fresh."""
        assert is_block_fresh(
            quote_block=100,
            current_block=101,
            max_block_age=3,
        ) is True
    
    def test_is_block_fresh_old(self):
        """Old block is not fresh."""
        assert is_block_fresh(
            quote_block=100,
            current_block=105,
            max_block_age=3,
        ) is False
    
    def test_is_block_fresh_exact_threshold(self):
        """Block at exact threshold is fresh."""
        assert is_block_fresh(
            quote_block=100,
            current_block=103,
            max_block_age=3,
        ) is True


class TestFreshnessCheck:
    """Test comprehensive freshness check."""
    
    def test_check_freshness_fresh(self):
        """Fresh quote passes all checks."""
        result = check_freshness(
            quote_timestamp_ms=now_ms() - 500,
            quote_block=100,
            current_block=101,
        )
        assert result.is_fresh is True
        assert result.reason is None
    
    def test_check_freshness_stale_time(self):
        """Stale time is detected."""
        result = check_freshness(
            quote_timestamp_ms=now_ms() - 3000,
            quote_block=100,
            current_block=101,
        )
        assert result.is_fresh is False
        assert "too old" in result.reason.lower()
        assert "ms" in result.reason
    
    def test_check_freshness_stale_block(self):
        """Stale block is detected."""
        result = check_freshness(
            quote_timestamp_ms=now_ms() - 100,  # Time is fresh
            quote_block=100,
            current_block=110,  # Block is stale
        )
        assert result.is_fresh is False
        assert "block" in result.reason.lower()
    
    def test_freshness_check_class_methods(self):
        """Test FreshnessCheck class methods."""
        fresh = FreshnessCheck.fresh(quote_age_ms=100, block_age=1)
        assert fresh.is_fresh is True
        
        stale_time = FreshnessCheck.stale_time(
            quote_age_ms=3000, block_age=1, max_age_ms=2000
        )
        assert stale_time.is_fresh is False
        assert "3000ms" in stale_time.reason
        
        stale_block = FreshnessCheck.stale_block(
            quote_age_ms=100, block_age=5, max_block_age=3
        )
        assert stale_block.is_fresh is False


class TestScanClock:
    """Test ScanClock for scan cycle management."""
    
    def test_scan_clock_creation(self):
        """Create ScanClock."""
        clock = ScanClock(chain_id=42161)
        assert clock.chain_id == 42161
        assert clock.block_pin is None
    
    def test_scan_clock_elapsed(self):
        """ScanClock tracks elapsed time."""
        clock = ScanClock(chain_id=1)
        time.sleep(0.1)  # 100ms
        elapsed = clock.elapsed_ms
        assert elapsed >= 100
        assert elapsed < 200
    
    def test_scan_clock_pin_block(self):
        """ScanClock can pin a block."""
        clock = ScanClock(chain_id=42161)
        
        assert not clock.is_block_pinned()
        
        pin = clock.pin_block(
            block_number=12345678,
            block_timestamp=1704326400,
        )
        
        assert clock.is_block_pinned()
        assert pin.block_number == 12345678
        assert clock.block_pin == pin
    
    def test_scan_clock_pin_stale(self):
        """ScanClock detects stale pin."""
        clock = ScanClock(chain_id=1)
        
        # No pin = stale
        assert clock.is_pin_stale()
        
        # Fresh pin = not stale
        clock.pin_block(100, 1704326400)
        assert not clock.is_pin_stale()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
