"""Tests for hint refresh completed_indices checkpoint semantics."""
from __future__ import annotations


def _contiguous_frontier(done: set[int]) -> int:
    i = 0
    while i in done:
        i += 1
    return i


def test_contiguous_frontier_with_out_of_order_completion():
    done = {0, 2, 3}
    assert _contiguous_frontier(done) == 1
    done.add(1)
    assert _contiguous_frontier(done) == 4


def test_pending_indices_excludes_completed():
    tokens_total = 5
    completed = {0, 2, 4}
    pending = [i for i in range(tokens_total) if i not in completed]
    assert pending == [1, 3]
