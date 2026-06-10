"""Cycle-lane productive prefilter tests."""
from __future__ import annotations

from m9.graph_arb.cycle_lane_prefilter import (
    build_route_metadata_from_routes,
    cycle_productive_readiness_score,
    prioritize_productive_ready_cycles,
)
from m9.graph_arb.models import GraphCycle, GraphEdge
from scripts.m9_quote_lane_diagnostic import check_rca_graph_consistency, graph_fingerprint


def _edge(
    pool: str,
    adapter: str = "maverick_v2",
    *,
    token_in_sym: str = "A",
    token_out_sym: str = "B",
    token_in_addr: str = "0x" + "1" * 40,
    token_out_addr: str = "0x" + "2" * 40,
) -> GraphEdge:
    return GraphEdge(
        token_in_sym=token_in_sym,
        token_out_sym=token_out_sym,
        token_in_addr=token_in_addr,
        token_out_addr=token_out_addr,
        token_in_decimals=18,
        token_out_decimals=18,
        route_id=f"{adapter}:{pool}@0",
        dex_id=adapter,
        adapter_type=adapter,
        fee=0,
        tick_spacing=None,
        quoter_addr=pool,
        pool_address=pool,
        fee_bps=1.0,
        factory_class="EFFICIENT_BASELINE",
        pair_id="A_B",
        factory_verified=True,
    )


def test_prioritize_productive_ready_cycles():
    pool_ok_a = "0x" + "a" * 40
    pool_ok_b = "0x" + "c" * 40
    pool_bad = "0x" + "b" * 40
    meta = build_route_metadata_from_routes(
        [
            {
                "pool_address": pool_ok_a,
                "productive_quote_status": "QUOTE_OK_MAVERICK",
                "maverick_pool_lane_probe_amount": 10_000,
                "maverick_min_quoteable_amount_raw": 10_000,
                "maverick_max_quoteable_amount_raw": 10**15,
            },
            {
                "pool_address": pool_ok_b,
                "productive_quote_status": "QUOTE_OK_PRODUCTIVE",
            },
        ]
    )
    _addr_a = "0x" + "1" * 40
    _addr_b = "0x" + "2" * 40
    ready = GraphCycle(
        edges=(
            _edge(pool_ok_a, token_in_addr=_addr_a, token_out_addr=_addr_b),
            _edge(
                pool_ok_b,
                "uniswap_v3",
                token_in_sym="B",
                token_out_sym="A",
                token_in_addr=_addr_b,
                token_out_addr=_addr_a,
            ),
        )
    )
    weak = GraphCycle(
        edges=(
            _edge(pool_bad, token_in_addr=_addr_a, token_out_addr=_addr_b),
            _edge(
                pool_ok_a,
                token_in_sym="B",
                token_out_sym="A",
                token_in_addr=_addr_b,
                token_out_addr=_addr_a,
            ),
        )
    )
    ranked = prioritize_productive_ready_cycles([weak, ready], meta)
    assert ranked[0].cycle_id == ready.cycle_id
    assert cycle_productive_readiness_score(ready, meta) == (2, 2)


def test_graph_fingerprint_consistency():
    graph = {"run_timestamp": "t1", "cycles_found": 80, "cycles_quoteable": 0}
    rca = {"source_graph_fingerprint": graph_fingerprint(graph)}
    assert check_rca_graph_consistency(rca, graph)["consistent"] is True
    stale = {"source_graph_fingerprint": {"run_timestamp": "t0", "cycles_found": 104}}
    drift = check_rca_graph_consistency(stale, graph)
    assert drift["consistent"] is False
    assert "cycles_found" in drift["mismatched_fields"]
