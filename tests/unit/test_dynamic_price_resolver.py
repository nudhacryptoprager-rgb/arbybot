"""E5: Tests for drift-free USD price resolver.

Contract: resolve_token_usd_price() must prefer dynamic_anchors over YAML
config, over STABLE_USD_PRICES, over the stale DEFAULT table. Callers that
set allow_default_fallback=False must see None for non-stable tokens that
lack a live source.
"""

from __future__ import annotations

import pytest


class TestStableResolution:
    def test_usdc_is_stable(self):
        from strategy.quotes import resolve_token_usd_price
        assert resolve_token_usd_price("USDC") == 1.0

    def test_usdt_is_stable(self):
        from strategy.quotes import resolve_token_usd_price
        assert resolve_token_usd_price("USDT") == 1.0

    def test_usdbc_case_insensitive(self):
        from strategy.quotes import resolve_token_usd_price
        # ci-lookup inside STABLE_USD_PRICES
        assert resolve_token_usd_price("usdbc") == 1.0


class TestConfigOverridesDefault:
    def test_config_wins_over_default_table(self):
        from strategy.quotes import resolve_token_usd_price
        cfg = {"tokens_usd_price": {"WETH": 3100.0}}
        assert resolve_token_usd_price("WETH", config=cfg) == 3100.0

    def test_case_insensitive_config_lookup(self):
        from strategy.quotes import resolve_token_usd_price
        cfg = {"tokens_usd_price": {"weth": 3200.0}}
        assert resolve_token_usd_price("WETH", config=cfg) == 3200.0


class TestStrictMode:
    def test_strict_returns_none_for_unknown(self):
        """allow_default_fallback=False must skip the stale DEFAULT table."""
        from strategy.quotes import resolve_token_usd_price
        assert (
            resolve_token_usd_price("AERO", allow_default_fallback=False) is None
        )

    def test_strict_still_returns_stable(self):
        from strategy.quotes import resolve_token_usd_price
        assert (
            resolve_token_usd_price("USDC", allow_default_fallback=False) == 1.0
        )


class TestFallbackEmitsWarning:
    def test_stale_fallback_logs_warning(self, caplog):
        import logging
        from strategy.quotes import resolve_token_usd_price

        with caplog.at_level(logging.WARNING, logger="strategy.quotes"):
            price = resolve_token_usd_price("WETH")  # no config, no anchor
        assert price is not None  # falls through to stale DEFAULT
        assert any("STALE_PRICE_FALLBACK" in rec.message for rec in caplog.records)


class TestEmptyInputs:
    def test_empty_symbol_returns_none(self):
        from strategy.quotes import resolve_token_usd_price
        assert resolve_token_usd_price("") is None

    def test_unknown_symbol_strict_returns_none(self):
        from strategy.quotes import resolve_token_usd_price
        assert (
            resolve_token_usd_price("NOSUCHTOKEN", allow_default_fallback=False)
            is None
        )
