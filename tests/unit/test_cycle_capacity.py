"""Unit tests for M9 cycle usable-capacity diagnostics."""
from __future__ import annotations

from types import SimpleNamespace

from m9.graph_arb.cycle_capacity import (
    cycle_bottleneck_usable_capacity_usd,
    cycle_meets_usable_floor,
    edge_usable_capacity_usd,
    is_econ_gate_attempt,
    is_econ_rpc_quote_attempt,
)
from m9.graph_arb.models import GraphCycle, GraphEdge
from m9.graph_arb.size_truth import economic_size_floor_usd, quote_size_truth_metrics


def _edge(
    *,
    route_id: str,
    depth: float | None,
    token_in_sym: str = "A",
    token_out_sym: str = "B",
    token_in_addr: str = "0x" + "a" * 40,
    token_out_addr: str = "0x" + "b" * 40,
    dex_id: str = "uniswap_v3",
    adapter_type: str = "uniswap_v3",
    depth_probe_status: str | None = None,
) -> GraphEdge:
    return GraphEdge(
        token_in_sym=token_in_sym,
        token_out_sym=token_out_sym,
        token_in_addr=token_in_addr,
        token_out_addr=token_out_addr,
        token_in_decimals=18,
        token_out_decimals=18,
        route_id=route_id,
        dex_id=dex_id,
        adapter_type=adapter_type,
        fee=3000,
        tick_spacing=60,
        quoter_addr="0x" + "3" * 40,
        pool_address="0x" + route_id.zfill(40)[-40:],
        fee_bps=30.0,
        factory_class="EFFICIENT_BASELINE",
        pair_id=f"pair-{route_id}",
        effective_depth_usd=depth,
        depth_probe_status=depth_probe_status,
    )


def test_edge_usable_capacity_applies_family_fraction():
    edge = _edge(
        route_id="bal",
        depth=10_000.0,
        dex_id="balancer_v2",
        adapter_type="balancer_vault",
    )
    assert edge_usable_capacity_usd(edge) == 200.0


def test_cycle_bottleneck_usable_is_min_per_leg_not_min_depth_times_min_frac():
    addr_a = "0x" + "a" * 40
    addr_b = "0x" + "b" * 40
    cycle = GraphCycle(
        edges=(
            _edge(
                route_id="bal",
                depth=1000.0,
                token_in_sym="A",
                token_out_sym="B",
                token_in_addr=addr_a,
                token_out_addr=addr_b,
                dex_id="balancer_v2",
                adapter_type="balancer_vault",
            ),
            _edge(
                route_id="v3",
                depth=500.0,
                token_in_sym="B",
                token_out_sym="A",
                token_in_addr=addr_b,
                token_out_addr=addr_a,
                dex_id="uniswap_v3",
                adapter_type="uniswap_v3",
            ),
        )
    )
    assert cycle_bottleneck_usable_capacity_usd(cycle) == 20.0
    assert cycle_meets_usable_floor(cycle, 25.0) is False
    assert cycle_meets_usable_floor(cycle, 15.0) is True


def test_cycle_unknown_depth_leg_returns_none():
    addr_a = "0x" + "a" * 40
    addr_b = "0x" + "b" * 40
    cycle = GraphCycle(
        edges=(
            _edge(
                route_id="a",
                depth=1000.0,
                token_in_sym="A",
                token_out_sym="B",
                token_in_addr=addr_a,
                token_out_addr=addr_b,
            ),
            _edge(
                route_id="b",
                depth=None,
                token_in_sym="B",
                token_out_sym="A",
                token_in_addr=addr_b,
                token_out_addr=addr_a,
            ),
        )
    )
    assert cycle_bottleneck_usable_capacity_usd(cycle) is None


def test_quote_size_truth_splits_gate_vs_rpc():
    floor = economic_size_floor_usd()
    gate_qr = SimpleNamespace(
        size_usd=floor,
        status="DEPTH_BELOW_ECONOMICS_FLOOR",
        leg_results=[],
    )
    rpc_qr = SimpleNamespace(
        size_usd=floor,
        status="NEGATIVE_GROSS",
        leg_results=[{"ok": True}],
    )
    metrics = quote_size_truth_metrics([gate_qr, rpc_qr], econ_floor_usd=floor)
    assert metrics["econ_gate_attempts"] == 1
    assert metrics["econ_rpc_quote_attempts"] == 1


def test_is_econ_gate_and_rpc_helpers():
    floor = economic_size_floor_usd()
    gate = SimpleNamespace(
        size_usd=floor,
        status="DEPTH_BELOW_ECONOMICS_FLOOR",
        leg_results=[],
    )
    rpc = SimpleNamespace(
        size_usd=floor,
        status="QUOTE_FAILED",
        leg_results=[{}],
    )
    assert is_econ_gate_attempt(gate, floor) is True
    assert is_econ_rpc_quote_attempt(gate, floor) is False
    assert is_econ_rpc_quote_attempt(rpc, floor) is True
