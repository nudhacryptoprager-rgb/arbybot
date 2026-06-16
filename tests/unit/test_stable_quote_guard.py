"""Tests for stable quote guard."""
from __future__ import annotations

from m9.graph_arb.stable_quote_guard import (
    REJECT_TOXIC_STABLE_POOL,
    anchor_value_ratio_warning,
    reject_toxic_stable_quote,
)
from m8_1.stable_anchor.quote_probe import QuoteResult
from m9.graph_arb.models import GraphEdge


def test_reject_toxic_stable_usdc_usdbc():
    toxic = reject_toxic_stable_quote(
        amount_in=180_000_000,
        amount_out=1_010_433,
        token_in_decimals=6,
        token_out_decimals=6,
        token_in_sym="USDC",
        token_out_sym="USDbC",
    )
    assert toxic == REJECT_TOXIC_STABLE_POOL


def test_reject_toxic_skips_healthy_stable_swap():
    toxic = reject_toxic_stable_quote(
        amount_in=180_000_000,
        amount_out=179_500_000,
        token_in_decimals=6,
        token_out_decimals=6,
        token_in_sym="USDC",
        token_out_sym="USDbC",
    )
    assert toxic is None


def test_anchor_value_ratio_warning_on_weth_usdc_toxic():
    edge = GraphEdge(
        token_in_sym="USDC",
        token_out_sym="WETH",
        token_in_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        token_out_addr="0x4200000000000000000000000000000000000006",
        token_in_decimals=6,
        token_out_decimals=18,
        route_id="bal_usdc_weth",
        dex_id="balancer_vault",
        adapter_type="balancer_stable",
        fee=0,
        tick_spacing=None,
        quoter_addr="0x" + "a" * 40,
        pool_address="0x" + "b" * 40,
        fee_bps=1.0,
        factory_class="EFFICIENT_BASELINE",
        pair_id="USDC_WETH",
        factory_verified=True,
    )
    leg = QuoteResult(
        route_id="bal_usdc_weth",
        size_usd=180.0,
        amount_in=180_000_000,
        amount_out=66_518_283,
        ok=True,
        reject_reason=None,
        gas_estimate=None,
        raw_error=None,
    )
    assert anchor_value_ratio_warning(edge, leg) is True
