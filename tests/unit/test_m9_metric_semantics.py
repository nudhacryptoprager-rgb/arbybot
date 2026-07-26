"""Tests for honest metric semantics and economics_all_pass gate (Step 1 P0)."""
from __future__ import annotations

from m9.graph_arb.artifacts import build_artifact
from m9.graph_arb.models import CycleQuoteResult, GraphCycle, GraphEdge, GraphTopology


def _edge(route_id="r1", depth=10.0):
    return GraphEdge(
        token_in_sym="USDC",
        token_out_sym="DAI",
        token_in_addr="0x0",
        token_out_addr="0x1",
        token_in_decimals=6,
        token_out_decimals=18,
        route_id=route_id,
        dex_id="maverick_v2",
        adapter_type="maverick_v2",
        fee=0,
        tick_spacing=None,
        quoter_addr="0xquoter",
        pool_address="0xpool",
        fee_bps=0.0,
        factory_class="UNISWAP_V2",
        pair_id="DAI_USDC",
        effective_depth_usd=depth,
    )


def _cycle(edges):
    if len(edges) == 2:
        src = edges[0]
        e2 = GraphEdge(
            **{
                **edges[1].__dict__,
                "token_in_sym": src.token_out_sym,
                "token_out_sym": src.token_in_sym,
                "token_in_addr": src.token_out_addr,
                "token_out_addr": src.token_in_addr,
            }
        )
        if e2.pool_address.lower() == src.pool_address.lower():
            e2 = GraphEdge(**{**e2.__dict__, "pool_address": "0xpool2"})
        edges = [src, e2]
    return GraphCycle(edges=tuple(edges))


def _qr(cycle, status, size_usd=180.0, leg_results=None):
    return CycleQuoteResult(
        cycle=cycle,
        size_usd=size_usd,
        amount_in=0,
        amount_out=0,
        gross_bps=0.0,
        status=status,
        reject_reason=status,
        leg_results=leg_results or [],
        elapsed_s=0.0,
    )


def _build_artifact(results, **kw):
    """Helper wrapping build_artifact with required positional args."""
    topo = GraphTopology(
        token_count=2,
        edge_count=2,
        route_count=2,
        hub_tokens=["USDC"],
        dead_end_tokens=[],
        missing_edges_for_3cycle=[],
        adjacency_summary={},
    )
    return build_artifact(
        chain="base",
        duration_minutes=1.0,
        cycle_results=results,
        topology=topo,
        sizes_usd=(0.25, 180.0),
        run_timestamp="2026-07-26T13:04:06Z",
        started_at_mono=0.0,
        elapsed_s=60.0,
        sweeps_completed=kw.get("sweeps_completed", 1),
    )


def test_artifact_records_quote_attempt_rows_and_unique_cycles():
    c = _cycle([_edge(), _edge(route_id="r2")])
    # Two attempt rows for the same cycle
    results = [_qr(c, "DEPTH_BELOW_ECONOMICS_FLOOR"), _qr(c, "DEPTH_BELOW_ECONOMICS_FLOOR")]
    art = _build_artifact(results, sweeps_completed=2)
    assert art["quote_attempt_rows"] == 2
    assert art["unique_cycles_evaluated"] == 1
    assert art["cycles_found"] == 2  # legacy semantics
    assert art["cycles_found_semantics"] == "attempt_rows_legacy"


def test_economic_test_status_not_tested_when_zero_rpc():
    c = _cycle([_edge(), _edge(route_id="r2")])
    results = [_qr(c, "DEPTH_BELOW_ECONOMICS_FLOOR") for _ in range(5)]
    art = _build_artifact(results)
    assert art["economic_test_status"] == "NOT_TESTED"
    assert art["transport_qsr"] is None


def test_economics_all_pass_false_when_zero_quoteable():
    c = _cycle([_edge(), _edge(route_id="r2")])
    results = [_qr(c, "DEPTH_BELOW_ECONOMICS_FLOOR") for _ in range(5)]
    art = _build_artifact(results)
    rg = art["runtime_gates"]
    assert rg["economics_all_pass"] is False
    assert rg["economic_test_status"] == "NOT_TESTED"
