# PATH: strategy/quote_metrics.py
"""
Quote-level metrics initialization and finalization.

Extracted from strategy.quotes to formalize the counts/quoter_matrix contract.
The actual per-quote counter increments remain inline in collect_quotes.
"""

from __future__ import annotations

from typing import Any, Dict, List


def init_quote_counts() -> Dict[str, Any]:
    """Return the canonical initial counts dict for collect_quotes."""
    return {
        "quotes_fetched": 0,
        "pool_missing": 0,
        "pool_disabled": 0,
        "runtime_disabled": 0,
        "liquidity_zero": 0,
        "quarantined": 0,
        "v3_slot0_failed": 0,
        "ve33_quote_failed": 0,
        "price_calc_failed": 0,
        "no_onchain_price": 0,
        "no_usd_price": 0,
        "algebra_needs_quoter": 0,
        "quoter_v2_failed": 0,
        "quoter_v2_skipped": 0,  # R32: pools where quoter_v2 was skipped (repeated failures)
    }


def init_quoter_matrix() -> Dict[str, Dict[str, int]]:
    """Return an empty quoter_matrix dict."""
    return {}


def finalize_quote_counts(
    counts: Dict[str, Any],
    failed_pool_addresses: List[Dict[str, str]],
    pool_missing_keys: List[str],
    quoter_matrix: Dict[str, Dict[str, int]],
) -> None:
    """Attach collected metadata to counts dict (in-place) before return."""
    counts["failed_pool_addresses"] = failed_pool_addresses
    counts["pool_missing_keys"] = pool_missing_keys[:20]
    counts["pool_missing_keys_total"] = len(pool_missing_keys)
    counts["quoter_matrix"] = quoter_matrix
