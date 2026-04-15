# PATH: tests/unit/test_rpc_rate_limiter.py
"""Tests for core.rpc_rate_limiter — token-bucket RPC throttle."""
import os
import time
import threading


def test_acquire_does_not_block_under_limit():
    """Acquiring fewer tokens than burst should not sleep."""
    os.environ["ARBY_RPC_THROTTLE"] = "1"
    from core.rpc_rate_limiter import TokenBucketRateLimiter

    rl = TokenBucketRateLimiter(rps=100, burst=20)
    t0 = time.monotonic()
    for _ in range(20):
        rl.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5, f"Should not block for burst-size tokens, took {elapsed:.2f}s"
    stats = rl.stats()
    assert stats["total_acquired"] == 20
    assert stats["total_waits"] == 0


def test_acquire_throttles_beyond_burst():
    """Acquiring more than burst should introduce sleeps."""
    from core.rpc_rate_limiter import TokenBucketRateLimiter

    rl = TokenBucketRateLimiter(rps=50, burst=5)
    # Drain burst
    for _ in range(5):
        rl.acquire()
    # Next 5 should require waiting (~100ms total for rps=50)
    t0 = time.monotonic()
    for _ in range(5):
        rl.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.05, f"Should throttle beyond burst, took {elapsed:.4f}s"
    stats = rl.stats()
    assert stats["total_acquired"] == 10
    assert stats["total_waits"] > 0


def test_disabled_via_env(monkeypatch):
    """ARBY_RPC_THROTTLE=0 disables throttling entirely."""
    import core.rpc_rate_limiter as mod
    # Save original and test disabled
    monkeypatch.setattr(mod, "_ENABLED", False)
    t0 = time.monotonic()
    mod.rpc_throttle.acquire(100)  # should be instant when disabled
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1
    # monkeypatch restores automatically


def test_thread_safety():
    """Multiple threads should not corrupt the token count."""
    from core.rpc_rate_limiter import TokenBucketRateLimiter

    rl = TokenBucketRateLimiter(rps=200, burst=50)
    errors = []

    def worker():
        try:
            for _ in range(20):
                rl.acquire()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors, f"Thread errors: {errors}"
    assert rl.stats()["total_acquired"] == 100


def test_stats_structure():
    """Stats dict should have expected keys."""
    from core.rpc_rate_limiter import TokenBucketRateLimiter

    rl = TokenBucketRateLimiter(rps=50, burst=10)
    s = rl.stats()
    assert "rps_limit" in s
    assert "burst" in s
    assert "total_acquired" in s
    assert "total_waits" in s
    assert "total_waited_ms" in s
    assert "enabled" in s
    assert s["rps_limit"] == 50
    assert s["burst"] == 10
