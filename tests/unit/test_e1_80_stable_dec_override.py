"""E1.80 Iter 9 — _STABLE_DEC_OVERRIDE applies on the primary in-stable path."""
from __future__ import annotations

import pytest

from m7.orderflow.scoring_parallel import _quote_implied_size_usd


def test_usdc_in_with_cache_miss_uses_override():
    # 100 USDC at 6 decimals = 100 * 10**6 wei. With cache miss (decimals_in=None)
    # the primary path historically defaulted to 18 → 100 / 10**12 = 1e-10 → 0.0.
    # E1.80 Iter 9: override should kick in, yielding 100.0.
    val = _quote_implied_size_usd(
        amount_in_wei=100 * 10**6,
        decimals_in=None,
        symbol_in="USDC",
        amount_out_wei=None,
        decimals_out=None,
        symbol_out="WETH",
        eth_price_usd=4500.0,
    )
    assert val == pytest.approx(100.0)


def test_usdt_in_with_cache_miss_uses_override():
    val = _quote_implied_size_usd(
        amount_in_wei=50 * 10**6,
        decimals_in=None,
        symbol_in="USDT",
        amount_out_wei=None,
        decimals_out=None,
        symbol_out="WETH",
        eth_price_usd=4500.0,
    )
    assert val == pytest.approx(50.0)


def test_dai_in_with_cache_miss_keeps_18_decimals():
    # DAI is 18 decimals — override map must preserve that.
    val = _quote_implied_size_usd(
        amount_in_wei=25 * 10**18,
        decimals_in=None,
        symbol_in="DAI",
        amount_out_wei=None,
        decimals_out=None,
        symbol_out="WETH",
        eth_price_usd=4500.0,
    )
    assert val == pytest.approx(25.0)


def test_explicit_decimals_still_take_precedence():
    # If the cache hit (decimals_in provided), we must trust it even if it
    # disagrees with the override (defensive — operator override / tooling).
    val = _quote_implied_size_usd(
        amount_in_wei=100 * 10**6,
        decimals_in=6,
        symbol_in="USDC",
        amount_out_wei=None,
        decimals_out=None,
        symbol_out="WETH",
        eth_price_usd=4500.0,
    )
    assert val == pytest.approx(100.0)


def test_unknown_symbol_falls_back_to_18():
    # Unknown / non-stable in_sym + no eth_price + no out leg → None expected,
    # but specifically: the override map must not silently treat it as 6.
    val = _quote_implied_size_usd(
        amount_in_wei=10**18,
        decimals_in=None,
        symbol_in="MYSTERY_TOKEN",
        amount_out_wei=None,
        decimals_out=None,
        symbol_out=None,
        eth_price_usd=None,
    )
    assert val is None
