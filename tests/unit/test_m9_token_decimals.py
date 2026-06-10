"""Tests for address-first token decimals resolver."""
from __future__ import annotations

from m9.graph_arb.token_decimals import (
    enrich_route_decimals,
    resolve_decimals_for_address,
)
from m9.graph_arb.token_price_fetcher import build_dual_key_price_map, resolve_token_price_usd
from m9.graph_arb.size_truth import economic_size_floor_usd, split_liveness_econ_sizes


def test_usdbc_address_resolves_six_decimals():
    addr = "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"
    dec = resolve_decimals_for_address(addr, symbol="0xd9aaec")
    assert dec == 6


def test_known_address_beats_polluted_override():
    addr = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    dec = resolve_decimals_for_address(addr, override=18, symbol="0x833589")
    assert dec == 6


def test_truncated_hex_symbol_does_not_default_to_eighteen():
    addr = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    dec = resolve_decimals_for_address(addr, symbol="0x833589")
    assert dec == 6


def test_enrich_route_decimals_sets_both_legs():
    route = {
        "token0": "0xd9aaec",
        "token1": "0x420000",
        "token0_addr": "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",
        "token1_addr": "0x4200000000000000000000000000000000000006",
    }
    enrich_route_decimals(route)
    assert route["token0_decimals"] == 6
    assert route["token1_decimals"] == 18


def test_address_first_price_lookup():
    prices = build_dual_key_price_map({"WETH": 3500.0, "USDC": 1.0})
    assert resolve_token_price_usd(
        "0x4200000000000000000000000000000000000006", "0x420000", prices
    ) == 3500.0
    assert resolve_token_price_usd("0x420000", "0x420000", prices) == 3500.0
    assert resolve_token_price_usd(
        "", "0x833589", prices
    ) == 1.0


def test_economic_size_floor_sane_minimum():
    floor = economic_size_floor_usd(gas_usd=0.05, l1_fee_usd=0.01, target_net_bps=10.0)
    assert floor >= 25.0


def test_split_liveness_econ_sizes():
    liveness, econ = split_liveness_econ_sizes([0.25, 1.0, 25.0, 100.0], econ_floor_usd=25.0)
    assert 0.25 in liveness and 1.0 in liveness
    assert 25.0 in econ and 100.0 in econ
