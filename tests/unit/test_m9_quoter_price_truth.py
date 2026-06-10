"""Tests for quoter price/decimals truth gate."""
from __future__ import annotations

from unittest.mock import MagicMock

from m9.graph_arb.models import GraphCycle, GraphEdge
from m9.graph_arb.quoter import (
    STATUS_UNKNOWN_PRICE,
    quote_cycle_sync,
)
from m9.graph_arb.token_price_fetcher import build_dual_key_price_map


def _two_pool_cycle(addr: str, sym: str, decimals: int) -> GraphCycle:
    e1 = GraphEdge(
        token_in_sym=sym,
        token_out_sym="USDC",
        token_in_addr=addr,
        token_out_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        token_in_decimals=decimals,
        token_out_decimals=6,
        route_id="r1",
        dex_id="uniswap_v3",
        adapter_type="uniswap_v3",
        fee=500,
        tick_spacing=None,
        quoter_addr="0x3d4e44eb1374240ce5f1b871ab261cd16335b76a",
        pool_address="0x" + "a" * 40,
        fee_bps=5.0,
        factory_class="EFFICIENT",
        pair_id="X_USDC",
    )
    e2 = GraphEdge(
        token_in_sym="USDC",
        token_out_sym=sym,
        token_in_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        token_out_addr=addr,
        token_in_decimals=6,
        token_out_decimals=decimals,
        route_id="r2",
        dex_id="uniswap_v3",
        adapter_type="uniswap_v3",
        fee=500,
        tick_spacing=None,
        quoter_addr="0x3d4e44eb1374240ce5f1b871ab261cd16335b76a",
        pool_address="0x" + "b" * 40,
        fee_bps=5.0,
        factory_class="EFFICIENT",
        pair_id="USDC_X",
    )
    return GraphCycle(edges=(e1, e2))


def test_unknown_price_rejects_instead_of_default_one():
    cycle = _two_pool_cycle(
        "0x4200000000000000000000000000000000000006",
        "0x420000",
        18,
    )
    result = quote_cycle_sync(cycle, 10.0, MagicMock(), token_price_usd={})
    assert result.status == STATUS_UNKNOWN_PRICE


def test_address_keyed_price_sizes_weth_correctly():
    cycle = _two_pool_cycle(
        "0x4200000000000000000000000000000000000006",
        "0x420000",
        18,
    )
    prices = build_dual_key_price_map({"WETH": 2500.0})
    result = quote_cycle_sync(cycle, 2500.0, MagicMock(), token_price_usd=prices)
    assert result.amount_in == 10 ** 18
