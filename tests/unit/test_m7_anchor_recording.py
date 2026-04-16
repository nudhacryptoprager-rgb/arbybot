"""N5: Tests for M7 anchor accumulation hook.

record_m7_anchor_sample() is the entry point M7 hot-loop uses to feed live
pool quotes into the dynamic_anchors cache. Before N5 only M4 populated
anchors via strategy/quotes.py, leaving data/cache/dynamic_anchors.json
empty during M7-only soaks.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_anchor_manager():
    """Reset singleton before/after each test so tests don't leak state."""
    from strategy.dynamic_anchors import reset_anchor_manager
    reset_anchor_manager()
    yield
    reset_anchor_manager()


class TestRecordingSuccess:
    def test_basic_record_returns_true(self):
        from strategy.dynamic_anchors import record_m7_anchor_sample
        # 1 WETH (1e18) → 2000 USDC (2000e6) => price 2000 usd/weth
        assert record_m7_anchor_sample(
            chain_key="base",
            symbol_in="WETH",
            symbol_out="USDC",
            amount_in_wei=10**18,
            amount_out_wei=2000 * 10**6,
            decimals_in=18,
            decimals_out=6,
            dex_id="uniswap_v3",
            fee_tier=500,
            block=29_000_000,
        ) is True

    def test_price_normalization_is_decimals_aware(self):
        from strategy.dynamic_anchors import (
            record_m7_anchor_sample,
            get_anchor_manager,
        )
        # Need >= min_samples (default 3) to get a dynamic median.
        for _ in range(3):
            ok = record_m7_anchor_sample(
                chain_key="base",
                symbol_in="WETH",
                symbol_out="USDC",
                amount_in_wei=10**18,
                amount_out_wei=2000 * 10**6,
                decimals_in=18,
                decimals_out=6,
                dex_id="uniswap_v3",
                fee_tier=500,
                block=1,
            )
            assert ok
        mgr = get_anchor_manager("base")
        price, source = mgr.get_anchor("WETH/USDC")
        assert source == "dynamic"
        # Median of three identical samples = 2000.
        assert price is not None
        assert 1990.0 < price < 2010.0


class TestInvalidInputs:
    def test_missing_symbols_returns_false(self):
        from strategy.dynamic_anchors import record_m7_anchor_sample
        assert record_m7_anchor_sample(
            "base", None, "USDC", 10**18, 10**6, 18, 6
        ) is False
        assert record_m7_anchor_sample(
            "base", "WETH", "", 10**18, 10**6, 18, 6
        ) is False

    def test_zero_amounts_returns_false(self):
        from strategy.dynamic_anchors import record_m7_anchor_sample
        assert record_m7_anchor_sample(
            "base", "WETH", "USDC", 0, 10**6, 18, 6
        ) is False
        assert record_m7_anchor_sample(
            "base", "WETH", "USDC", 10**18, 0, 18, 6
        ) is False

    def test_missing_decimals_returns_false(self):
        from strategy.dynamic_anchors import record_m7_anchor_sample
        assert record_m7_anchor_sample(
            "base", "WETH", "USDC", 10**18, 10**6, None, 6
        ) is False
        assert record_m7_anchor_sample(
            "base", "WETH", "USDC", 10**18, 10**6, 18, None
        ) is False

    def test_anomalous_price_rejected(self):
        """is_valid_anchor_price bounds: a 1 WETH → 32 wei AERO is nonsense."""
        from strategy.dynamic_anchors import record_m7_anchor_sample
        assert record_m7_anchor_sample(
            "base",
            "WETH",
            "AERO",
            10**18,
            32,  # the E1.28 soak bug
            18,
            18,
        ) is False


class TestUsdResolverIntegration:
    def test_recorded_weth_is_usable_by_resolver(self):
        from strategy.dynamic_anchors import (
            record_m7_anchor_sample,
            get_token_usd_from_anchors,
        )
        for _ in range(3):
            ok = record_m7_anchor_sample(
                chain_key="base",
                symbol_in="WETH",
                symbol_out="USDC",
                amount_in_wei=10**18,
                amount_out_wei=2050 * 10**6,
                decimals_in=18,
                decimals_out=6,
                dex_id="uniswap_v3",
                fee_tier=500,
                block=1,
            )
            assert ok
        usd = get_token_usd_from_anchors("WETH", chain_key="base")
        assert usd is not None
        assert 2040.0 < usd < 2060.0
