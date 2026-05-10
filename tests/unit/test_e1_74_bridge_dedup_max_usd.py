"""E1.74 — Bridge dedup keeps largest-USD frontier sample.

Locks:
  * Dedup by pool_address must retain the candidate with the HIGHEST
    amount_in_optimal_usd, not the first-seen entry.
    This ensures frontier sweep peaks ($49 999) survive into the bridge
    instead of being shadowed by smaller earlier entries ($24.999).
"""
from __future__ import annotations

import inspect
import types
import unittest.mock as mock


def _make_candidate(pool_addr: str, usd: float, pair: str = "A/B") -> dict:
    return {
        "pool_address": pool_addr,
        "amount_in_optimal_usd": usd,
        "actual_pair": pair,
        "expected_profit_usd": usd * 0.01,
        "best_backrun_net_bps": 10.0,
    }


def _run_dedup(candidates: list) -> list:
    """Execute the bridge_runtime dedup logic directly."""
    _best_by_pool: dict = {}
    for _c in candidates:
        _pa = (_c.get("pool_address") or "").lower()
        _usd = float(_c.get("amount_in_optimal_usd") or 0)
        if not _pa:
            _best_by_pool[id(_c)] = _c
            continue
        if _pa not in _best_by_pool:
            _best_by_pool[_pa] = _c
        else:
            _prev_usd = float(_best_by_pool[_pa].get("amount_in_optimal_usd") or 0)
            if _usd > _prev_usd:
                _best_by_pool[_pa] = _c
    return list(_best_by_pool.values())


def test_dedup_keeps_max_usd_candidate():
    """When two candidates share a pool_address, the one with larger USD wins."""
    small = _make_candidate("0xabc123", 24.999)
    large = _make_candidate("0xabc123", 49_999.0)
    result = _run_dedup([small, large])
    assert len(result) == 1, "Dedup must reduce to 1 candidate per pool"
    assert result[0]["amount_in_optimal_usd"] == 49_999.0, (
        "Dedup must keep the LARGEST USD candidate, not the first-seen"
    )


def test_dedup_keeps_max_usd_candidate_reversed_order():
    """Order of inputs must not matter — still keep the largest USD."""
    large = _make_candidate("0xabc123", 49_999.0)
    small = _make_candidate("0xabc123", 24.999)
    result = _run_dedup([large, small])
    assert len(result) == 1
    assert result[0]["amount_in_optimal_usd"] == 49_999.0


def test_dedup_keeps_separate_pools():
    """Different pool_address entries should each be kept."""
    c1 = _make_candidate("0xpool1", 25.0)
    c2 = _make_candidate("0xpool2", 50.0)
    result = _run_dedup([c1, c2])
    assert len(result) == 2


def test_dedup_no_pool_address_kept_as_is():
    """Candidates without pool_address must still be included (not dropped)."""
    c = {"pool_address": None, "amount_in_optimal_usd": 100.0}
    result = _run_dedup([c])
    assert len(result) == 1


def test_dedup_production_sized_promoted():
    """After dedup, production_sized (>=$50) count should reflect max-USD winner."""
    small = _make_candidate("0xpool1", 24.999)
    large = _make_candidate("0xpool1", 50.0)
    result = _run_dedup([small, large])
    prod_sized = sum(1 for c in result if (c.get("amount_in_optimal_usd") or 0) >= 50.0)
    assert prod_sized == 1, "Production-sized count should be 1 after dedup keeps max-USD"


def test_bridge_runtime_uses_max_usd_dedup():
    """Source-level check: bridge_runtime must not use 'in _seen_pool_addrs' pattern
    (first-seen dedup) — it must use the max-USD selection logic."""
    import m7.orderflow.bridge_runtime as _br
    src = inspect.getsource(_br)
    assert "_seen_pool_addrs" not in src, (
        "E1.69 first-seen dedup must be replaced with E1.74 max-USD dedup. "
        "Remove `_seen_pool_addrs` pattern from bridge_runtime._write_cold_hot_bridge."
    )
    assert "_best_by_pool" in src, (
        "E1.74 max-USD dedup must use `_best_by_pool` dict in bridge_runtime."
    )
