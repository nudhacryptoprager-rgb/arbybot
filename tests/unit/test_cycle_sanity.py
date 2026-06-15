"""Cycle sanity gate tests."""
from __future__ import annotations

from m8_1.stable_anchor.quote_probe import QuoteResult
from m9.graph_arb.cycle_sanity import (
    REJECT_AMOUNT_CONTINUITY_VIOLATION,
    REJECT_STABLE_VALUE_RATIO_OUTLIER,
    check_cycle_leg_sanity,
    stable_value_ratio_outlier,
)
from m9.graph_arb.models import GraphCycle, GraphEdge


def _leg(amount_in: int, amount_out: int, *, ok: bool = True) -> QuoteResult:
    return QuoteResult(
        route_id="x",
        size_usd=25.0,
        amount_in=amount_in,
        amount_out=amount_out,
        ok=ok,
        reject_reason=None,
        gas_estimate=None,
        raw_error=None,
    )


def _edge(**kwargs) -> GraphEdge:
    defaults = dict(
        token_in_sym="USDC",
        token_out_sym="USDbC",
        token_in_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        token_out_addr="0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",
        token_in_decimals=6,
        token_out_decimals=6,
        route_id="curve_usdc_usdbc",
        dex_id="curve_stable",
        adapter_type="curve_stable",
        fee=0,
        tick_spacing=None,
        quoter_addr="0x" + "1" * 40,
        pool_address="0x" + "2" * 40,
        fee_bps=1.0,
        factory_class="EFFICIENT_BASELINE",
        pair_id="USDC_USDBC",
        factory_verified=True,
    )
    defaults.update(kwargs)
    return GraphEdge(**defaults)


def test_stable_value_ratio_outlier_on_usdc_usdbc():
    edge = _edge()
    leg = _leg(25_000_000, 1_010_498)
    assert stable_value_ratio_outlier(edge, leg) is True


def _three_leg_cycle(**edge_overrides) -> GraphCycle:
    e0 = _edge(pool_address="0x" + "2" * 40, **edge_overrides.get("e0", {}))
    e1 = _edge(
        token_in_sym="USDbC",
        token_out_sym="WETH",
        token_in_addr="0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",
        token_out_addr="0x4200000000000000000000000000000000000006",
        token_in_decimals=6,
        token_out_decimals=18,
        pool_address="0x" + "3" * 40,
        route_id="maverick_usdbc_weth",
        adapter_type="maverick_v2",
        dex_id="maverick_v2",
        pair_id="USDBC_WETH",
        **edge_overrides.get("e1", {}),
    )
    e2 = _edge(
        token_in_sym="WETH",
        token_out_sym="USDC",
        token_in_addr="0x4200000000000000000000000000000000000006",
        token_out_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        token_in_decimals=18,
        token_out_decimals=6,
        pool_address="0x" + "4" * 40,
        route_id="uni_weth_usdc",
        adapter_type="uniswap_v3",
        dex_id="uniswap_v3",
        pair_id="WETH_USDC",
        **edge_overrides.get("e2", {}),
    )
    return GraphCycle(edges=(e0, e1, e2))


def test_amount_continuity_violation_detected():
    cycle = _three_leg_cycle()
    legs = [
        _leg(25_000_000, 24_900_000),
        _leg(10**15, 8),
    ]
    assert check_cycle_leg_sanity(cycle, legs) == REJECT_AMOUNT_CONTINUITY_VIOLATION


def test_stable_ratio_blocks_economics():
    cycle = _three_leg_cycle()
    legs = [
        _leg(25_000_000, 1_010_498),
        _leg(1_010_498, 8),
    ]
    assert check_cycle_leg_sanity(cycle, legs) == REJECT_STABLE_VALUE_RATIO_OUTLIER


def test_stable_ratio_skipped_below_min_notional():
    edge = _edge()
    leg = _leg(1_000, 999)  # 0.001 USDC in — micro probe
    assert stable_value_ratio_outlier(edge, leg) is False


def test_stable_ratio_still_flags_at_meaningful_notional():
    edge = _edge()
    leg = _leg(25_000_000, 1_010_498)  # $25 in
    assert stable_value_ratio_outlier(edge, leg) is True
