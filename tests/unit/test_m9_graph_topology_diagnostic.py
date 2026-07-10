"""Tests for M9 graph topology diagnostic."""
from __future__ import annotations

import json
from pathlib import Path

from m9.graph_arb.finder import find_cycles
from m9.graph_arb.topology_diagnostic import (
    strong_components,
    summarize_topology,
    weak_components,
)


def _triangle_adjacency():
    """A->B->C->A triangle using minimal GraphEdge stubs."""
    from m9.graph_arb.models import GraphEdge

    addrs = {
        "A": "0x" + "a" * 40,
        "B": "0x" + "b" * 40,
        "C": "0x" + "c" * 40,
    }

    def _e(a: str, b: str, pool: str) -> GraphEdge:
        return GraphEdge(
            token_in_sym=a,
            token_out_sym=b,
            token_in_addr=addrs[a],
            token_out_addr=addrs[b],
            token_in_decimals=18,
            token_out_decimals=18,
            route_id=f"r_{a}_{b}",
            dex_id="uniswap_v3",
            adapter_type="uniswap_v3",
            fee=3000,
            tick_spacing=60,
            quoter_addr="0x" + "d" * 40,
            pool_address=pool,
            fee_bps=30.0,
            factory_class="EFFICIENT_BASELINE",
            pair_id=f"{a}_{b}",
            factory_verified=True,
        )

    return {
        "A": {"B": [_e("A", "B", "0x" + "1" * 40)]},
        "B": {"C": [_e("B", "C", "0x" + "2" * 40)]},
        "C": {"A": [_e("C", "A", "0x" + "3" * 40)]},
    }


def test_weak_and_strong_components_triangle():
    adj = _triangle_adjacency()
    w = weak_components(adj)
    s = strong_components(adj)
    assert len(w) == 1
    assert set(w[0]) == {"A", "B", "C"}
    assert len(s) == 1
    assert set(s[0]) == {"A", "B", "C"}


def test_find_cycles_length_3():
    adj = _triangle_adjacency()
    cycles = find_cycles(adj, cycle_lengths=(3,), max_cycles=10)
    assert len(cycles) >= 1


def test_summarize_topology_reports_cycles():
    adj = _triangle_adjacency()
    topo = summarize_topology(adj, cycle_lengths=(2, 3, 4))
    assert topo["cycles_found_topology"] >= 1
    assert topo["cycles_by_length"]["3"] >= 1


def test_summarize_topology_degree_fields_are_parser_safe_arrays():
    """Regression: token symbols that differ only by case must not become
    JSON object keys. PowerShell ConvertFrom-Json treats those as duplicates.
    """
    from m9.graph_arb.models import GraphEdge

    def _e(a: str, b: str) -> GraphEdge:
        return GraphEdge(
            token_in_sym=a,
            token_out_sym=b,
            token_in_addr="0x" + "1" * 40,
            token_out_addr="0x" + "2" * 40,
            token_in_decimals=18,
            token_out_decimals=18,
            route_id=f"r_{a}_{b}",
            dex_id="uniswap_v3",
            adapter_type="uniswap_v3",
            fee=3000,
            tick_spacing=60,
            quoter_addr="0x" + "3" * 40,
            pool_address="0x" + "4" * 40,
            fee_bps=30.0,
            factory_class="EFFICIENT_BASELINE",
            pair_id=f"{a}_{b}",
            factory_verified=True,
        )

    topo = summarize_topology(
        {
            "FOMO": {"USDC": [_e("FOMO", "USDC")]},
            "Fomo": {"WETH": [_e("Fomo", "WETH")]},
        },
        cycle_lengths=(2, 3, 4),
    )

    for key in ("out_degree", "in_degree"):
        assert isinstance(topo[key], list)
        assert all(set(row) == {"token", "degree"} for row in topo[key])
        tokens = [row["token"] for row in topo[key]]
        assert "FOMO" in tokens
        assert "Fomo" in tokens
        assert not isinstance(topo[key], dict)
    json.dumps(topo)


def test_run_topology_diagnostic_on_min_inventory(tmp_path: Path):
    from m9.graph_arb.topology_diagnostic import run_topology_diagnostic

    inv = {
        "active_routes": [
            {
                "route_id": "r1",
                "pair_id": "WETH_USDC",
                "dex_id": "uniswap_v3",
                "adapter_type": "uniswap_v3",
                "token0": "WETH",
                "token1": "USDC",
                "token0_addr": "0x4200000000000000000000000000000000000006",
                "token1_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                "token0_decimals": 18,
                "token1_decimals": 6,
                "pool_address": "0x" + "b" * 40,
                "factory_verified": True,
                "factory_class": "EFFICIENT_BASELINE",
                "fee": 3000,
            }
        ]
    }
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(inv), encoding="utf-8")
    report = run_topology_diagnostic(
        inventory_path=str(path),
        config_path="config/exotic_base_anchor.yaml",
        cycle_lengths=(2, 3, 4),
        lanes=("discovery",),
    )
    assert report["active_routes_count"] == 1
    assert report["schema_version"] == "m9_graph_topology_diagnostic.2"
    assert "lanes" in report
    assert "discovery" in report["lanes"]
