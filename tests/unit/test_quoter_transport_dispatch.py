"""Regression tests: rpc_dispatched only on real transport dispatch."""
from __future__ import annotations

from unittest.mock import MagicMock

from m8_1.stable_anchor.quote_probe import QuoteResult
from m9.graph_arb.models import GraphCycle, GraphEdge
from m9.graph_arb.quoter import edge_quote_cache, quote_cycle_sync


def _edge(pool="0xpool1", route_id="r1"):
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
        pool_address=pool,
        fee_bps=0.0,
        factory_class="UNISWAP_V2",
        pair_id="DAI_USDC",
        effective_depth_usd=5000.0,
    )


def _cycle():
    e1 = _edge()
    e2 = GraphEdge(
        **{
            **_edge(route_id="r2", pool="0xpool2").__dict__,
            "token_in_sym": "DAI",
            "token_out_sym": "USDC",
            "token_in_addr": "0x1",
            "token_out_addr": "0x0",
        }
    )
    return GraphCycle(edges=(e1, e2))


def _ok_leg(amount_out: int = 1_000_000) -> QuoteResult:
    return QuoteResult(
        route_id="r1",
        size_usd=180.0,
        amount_in=1_000_000,
        amount_out=amount_out,
        ok=True,
        reject_reason=None,
        gas_estimate=None,
        raw_error=None,
    )


def test_leg_capacity_reject_does_not_mark_transport(monkeypatch):
    monkeypatch.setattr(
        "m9.graph_arb.leg_capacity.resolve_leg_amount_in",
        lambda *args, **kwargs: (1_000_000, "LEG_AMOUNT_EXCEEDS_POOL_CAPACITY"),
    )
    result = quote_cycle_sync(
        _cycle(),
        180.0,
        MagicMock(),
        token_price_usd={"0x0": 1.0, "USDC": 1.0},
    )
    assert result.rpc_dispatched is False
    assert result.transport_call_count == 0


def test_edge_cache_hit_does_not_mark_transport(monkeypatch):
    edge_quote_cache.clear()

    def _probe_dispatch(w3, route, token_in, token_out, amount_in):
        from core.rpc_dispatch_hooks import notify_rpc_dispatch

        notify_rpc_dispatch()
        return _ok_leg(amount_out=amount_in)

    monkeypatch.setattr("m9.graph_arb.quoter.probe_quote", _probe_dispatch)
    prices = {"0x0": 1.0, "USDC": 1.0}
    cycle = _cycle()
    first = quote_cycle_sync(cycle, 180.0, MagicMock(), token_price_usd=prices)
    second = quote_cycle_sync(cycle, 180.0, MagicMock(), token_price_usd=prices)
    assert first.transport_call_count >= 1
    assert second.transport_call_count == 0
    assert second.rpc_dispatched is False
    edge_quote_cache.clear()


def test_actual_transport_dispatch_marks_metrics(monkeypatch):
    edge_quote_cache.clear()

    def _probe_with_dispatch(w3, route, token_in, token_out, amount_in):
        from core.rpc_dispatch_hooks import notify_rpc_dispatch

        notify_rpc_dispatch()
        return _ok_leg(amount_out=amount_in)

    monkeypatch.setattr("m9.graph_arb.quoter.probe_quote", _probe_with_dispatch)
    result = quote_cycle_sync(
        _cycle(),
        180.0,
        MagicMock(),
        token_price_usd={"0x0": 1.0, "USDC": 1.0},
    )
    assert result.rpc_dispatched is True
    assert result.transport_call_count >= 1
