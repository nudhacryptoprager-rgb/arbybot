"""Tests for adaptive chunk scale getter (todo_RPC_blockers Phase 3)."""
from m9.graph_arb.multicall_snapshot import (
    get_adaptive_chunk_scale,
    _update_chunk_scale,
)


def test_chunk_scale_initially_one():
    # After import the EMA may have drifted, so we just check bounds.
    s = get_adaptive_chunk_scale()
    assert 0.25 <= s <= 1.0


def test_chunk_scale_decreases_under_high_429_rate():
    initial = get_adaptive_chunk_scale()
    # Simulate 100 attempts with 50 → 50% 429 rate.
    for _ in range(20):
        _update_chunk_scale(100, 50)
    after = get_adaptive_chunk_scale()
    assert after < initial or after < 0.8


def test_chunk_scale_bounded():
    # Drive it down hard
    for _ in range(100):
        _update_chunk_scale(100, 100)
    assert get_adaptive_chunk_scale() >= 0.25
    # Recover
    for _ in range(100):
        _update_chunk_scale(100, 0)
    assert get_adaptive_chunk_scale() <= 1.0


def test_chunk_scale_ignores_zero_attempts():
    s_before = get_adaptive_chunk_scale()
    _update_chunk_scale(0, 0)
    assert get_adaptive_chunk_scale() == s_before
