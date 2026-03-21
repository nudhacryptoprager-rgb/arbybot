# PATH: tests/unit/test_quoter_v2_skip_cache.py
"""
Contract tests for the R32 quoter_v2 skip cache in strategy/quotes.py.

Verifies:
- After QUOTER_V2_SKIP_THRESHOLD failures, _should_skip returns True
- After TTL expires, skip cache resets
- On success, skip cache resets
"""

from strategy.quotes import (
    QUOTER_V2_SKIP_THRESHOLD,
    QUOTER_V2_SKIP_TTL_SECONDS,
    _quoter_v2_fail_counts,
    _quoter_v2_skip_since,
    _record_quoter_v2_failure,
    _record_quoter_v2_success,
    _should_skip_quoter_v2,
)


def _cleanup():
    _quoter_v2_fail_counts.clear()
    _quoter_v2_skip_since.clear()


class TestQuoterV2SkipCache:
    def test_no_skip_initially(self):
        _cleanup()
        assert _should_skip_quoter_v2("pool_xyz") is False

    def test_skip_after_threshold(self):
        _cleanup()
        for _ in range(QUOTER_V2_SKIP_THRESHOLD):
            _record_quoter_v2_failure("pool_fail")
        assert _should_skip_quoter_v2("pool_fail") is True

    def test_below_threshold_no_skip(self):
        _cleanup()
        for _ in range(QUOTER_V2_SKIP_THRESHOLD - 1):
            _record_quoter_v2_failure("pool_almost")
        assert _should_skip_quoter_v2("pool_almost") is False

    def test_reset_on_success(self):
        _cleanup()
        for _ in range(QUOTER_V2_SKIP_THRESHOLD):
            _record_quoter_v2_failure("pool_reset")
        assert _should_skip_quoter_v2("pool_reset") is True
        _record_quoter_v2_success("pool_reset")
        assert _should_skip_quoter_v2("pool_reset") is False

    def test_ttl_expiry(self):
        _cleanup()
        for _ in range(QUOTER_V2_SKIP_THRESHOLD):
            _record_quoter_v2_failure("pool_ttl")
        # Force TTL expiry
        _quoter_v2_skip_since["pool_ttl"] -= QUOTER_V2_SKIP_TTL_SECONDS + 1
        assert _should_skip_quoter_v2("pool_ttl") is False
        # Cache should be cleaned up after TTL check
        assert "pool_ttl" not in _quoter_v2_fail_counts

    def test_different_pools_independent(self):
        _cleanup()
        for _ in range(QUOTER_V2_SKIP_THRESHOLD):
            _record_quoter_v2_failure("pool_a")
        _record_quoter_v2_failure("pool_b")
        assert _should_skip_quoter_v2("pool_a") is True
        assert _should_skip_quoter_v2("pool_b") is False

    def test_constants(self):
        assert QUOTER_V2_SKIP_THRESHOLD >= 2, "Threshold should be at least 2"
        assert QUOTER_V2_SKIP_TTL_SECONDS >= 60, "TTL should be at least 60s"
