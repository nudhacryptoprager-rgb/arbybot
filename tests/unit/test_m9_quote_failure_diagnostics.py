"""Unit tests for quote_failure_diagnostics in M9 artifacts."""
from __future__ import annotations

from m8_1.stable_anchor.quote_probe import QuoteResult
from m9.graph_arb.artifacts import _compute_quote_failure_diagnostics
from m9.graph_arb.models import CycleQuoteResult, GraphCycle, GraphEdge


def _mk_edge(
    token_in_sym: str,
    token_out_sym: str,
    token_in_addr: str,
    token_out_addr: str,
    route_id: str,
    pair_id: str,
) -> GraphEdge:
    return GraphEdge(
        token_in_sym=token_in_sym,
        token_out_sym=token_out_sym,
        token_in_addr=token_in_addr,
        token_out_addr=token_out_addr,
        token_in_decimals=18,
        token_out_decimals=6 if token_out_sym == "USDC" else 18,
        route_id=route_id,
        dex_id="aerodrome",
        adapter_type="uniswap_v3",
        fee=100,
        tick_spacing=None,
        quoter_addr="0x" + "3" * 40,
        pool_address="0x" + "4" * 40,
        fee_bps=30.0,
        factory_class="EFFICIENT_BASELINE",
        pair_id=pair_id,
    )


def _tri_cycle() -> GraphCycle:
    a = "0x" + "1" * 40
    b = "0x" + "2" * 40
    c = "0x" + "5" * 40
    e1 = _mk_edge("AERO", "USDC", a, b, "r1", "AERO_USDC")
    e2 = _mk_edge("USDC", "WETH", b, c, "r2", "USDC_WETH")
    e3 = _mk_edge("WETH", "AERO", c, a, "r3", "WETH_AERO")
    return GraphCycle(edges=(e1, e2, e3))


def test_quote_failure_diagnostics_http_status_and_top_routes():
    leg_fail = QuoteResult(
        route_id="r1",
        size_usd=100.0,
        amount_in=10**18,
        amount_out=0,
        ok=False,
        reject_reason="QUOTE_RPC_ERROR",
        gas_estimate=None,
        raw_error="HTTP 429: rate limited",
    )
    qr = CycleQuoteResult(
        cycle=_tri_cycle(),
        size_usd=100.0,
        amount_in=10**18,
        amount_out=0,
        gross_bps=0.0,
        status="QUOTE_FAILED",
        reject_reason="CYCLE_QUOTE_FAILED",
        leg_results=[leg_fail],
        elapsed_s=0.1,
    )
    diag = _compute_quote_failure_diagnostics([qr])
    assert diag["leg_failures_total"] == 1
    assert diag["by_reject_reason"]["QUOTE_RPC_ERROR"] == 1
    assert diag["by_http_status"]["429"] == 1
    assert diag["top_routes"][0]["pair_id"] == "AERO_USDC"
    assert diag["top_routes"][0]["http_status"] == 429
