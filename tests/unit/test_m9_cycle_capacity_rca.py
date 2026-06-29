"""Unit tests for M9 cycle capacity bottleneck RCA and shadow gate."""
from __future__ import annotations

from m9.graph_arb.cycle_capacity import (
    shadow_gate_blocked,
    spread_lifetime_allowed,
    top_bottleneck_legs,
)
from m9.graph_arb.models import GraphEdge, GraphCycle


def _edge(route_id: str, depth, *, sym_in="A", sym_out="B", pool_suffix="2"):
    usdc = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    weth = "0x4200000000000000000000000000000000000006"
    if sym_in == "A":
        tin, tout, ain, aout = sym_in, sym_out, usdc, weth
    else:
        tin, tout, ain, aout = sym_in, sym_out, weth, usdc
    return GraphEdge(
        token_in_sym=tin,
        token_out_sym=tout,
        token_in_addr=ain,
        token_out_addr=aout,
        token_in_decimals=6,
        token_out_decimals=18,
        route_id=route_id,
        dex_id="uniswap_v3",
        adapter_type="uniswap_v3",
        fee=500,
        tick_spacing=10,
        quoter_addr="0x" + "1" * 40,
        pool_address="0x" + pool_suffix * 40,
        fee_bps=5.0,
        factory_class="uniswap_v3",
        pair_id="pair",
        effective_depth_usd=depth,
    )


def test_shadow_gate_blocked_when_zero_cycles_total():
    blocked, reason = shadow_gate_blocked(
        {
            "cycles_by_profile": {
                "production_conservative": {"cycles_at_floor": 0},
                "diagnostic_near_econ": {"cycles_at_floor": 0},
            },
            "cycles_at_production_floor": 0,
        }
    )
    assert blocked is True
    assert "ZERO_CYCLES_TOTAL" in reason


def test_shadow_gate_blocked_when_zero_cycles_at_floor():
    blocked, reason = shadow_gate_blocked(
        {
            "cycles_total": 10,
            "cycles_by_profile": {
                "production_conservative": {"cycles_at_floor": 0},
                "diagnostic_near_econ": {"cycles_at_floor": 0},
            },
            "cycles_at_production_floor": 0,
        }
    )
    assert blocked is True
    assert "ZERO_CYCLES_AT_FLOOR" in reason


def test_top_bottleneck_legs_unknown_depth_reason():
    cycle = GraphCycle(
        edges=(
            _edge("r_low", None, sym_in="A", sym_out="B", pool_suffix="2"),
            _edge("r_ok", 500.0, sym_in="B", sym_out="A", pool_suffix="3"),
        ),
    )
    rows = top_bottleneck_legs([cycle], floor_usd=180.0, limit=5)
    assert rows
    assert rows[0]["route_id"] == "r_low"
    assert rows[0]["reason"] == "unknown_depth"


def test_spread_lifetime_requires_positive_gross():
    allowed, reason = spread_lifetime_allowed({"cycles_positive_gross": 0})
    assert allowed is False
    allowed2, _ = spread_lifetime_allowed({"cycles_positive_gross": 2})
    assert allowed2 is True
