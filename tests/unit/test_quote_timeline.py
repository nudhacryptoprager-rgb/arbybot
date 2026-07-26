"""Tests for quote timeline tracker."""
from __future__ import annotations

from core.rpc_dispatch_hooks import clear_on_rpc_dispatch, notify_rpc_dispatch, set_on_rpc_dispatch
from m9.graph_arb.quote_timeline import QuoteTimelineTracker


def test_quote_timeline_marks_only_economic_dispatch():
    tl = QuoteTimelineTracker()
    tl.try_mark_econ_dispatch(size_usd=50.0, econ_floor_usd=180.0, queue_delay_s=1.0)
    assert tl.first_econ_rpc_attempt_at_utc is None
    tl.try_mark_econ_dispatch(size_usd=250.0, econ_floor_usd=180.0, queue_delay_s=12.5)
    tl.mark_successful_quote(rpc_duration_s=0.42)
    scope = tl.to_scan_scope()
    assert scope["first_econ_rpc_attempt_at_utc"]
    assert scope["first_successful_econ_quote_at_utc"]
    assert scope["quote_queue_delay_seconds"] == 12.5
    assert scope["quote_rpc_service_duration_seconds"] == 0.42


def test_transport_hook_marks_on_actual_rpc_dispatch():
    tl = QuoteTimelineTracker()
    set_on_rpc_dispatch(
        lambda: tl.try_mark_econ_dispatch(
            size_usd=250.0,
            econ_floor_usd=180.0,
            queue_delay_s=3.0,
        )
    )
    try:
        notify_rpc_dispatch()
    finally:
        clear_on_rpc_dispatch()
    assert tl.first_econ_rpc_attempt_at_utc is not None


def test_probe_leg_capacity_reject_does_not_notify_transport(monkeypatch):
    from m8_1.stable_anchor.pairs import TokenInfo
    from m8_1.stable_anchor.pool_discovery import DexRoute
    from m9.graph_arb.quoter import _probe_leg

    marks = {"n": 0}

    def _mark():
        marks["n"] += 1

    set_on_rpc_dispatch(_mark)

    def _reject_capacity(edge, amount_in, **kwargs):
        return amount_in, "LEG_AMOUNT_EXCEEDS_POOL_CAPACITY"

    monkeypatch.setattr(
        "m9.graph_arb.leg_capacity.resolve_leg_amount_in",
        _reject_capacity,
    )
    try:
        route = DexRoute(
            dex_id="test",
            adapter_type="uniswap_v3",
            quoter="0x" + "11" * 20,
            fee=3000,
            tick_spacing=None,
            curve_coin0_sym=None,
        )
        token_in = TokenInfo(symbol="A", address="0x" + "aa" * 20, decimals=18)
        token_out = TokenInfo(symbol="B", address="0x" + "bb" * 20, decimals=18)
        edge = object()
        result = _probe_leg(
            None,
            route,
            token_in,
            token_out,
            10**18,
            edge=edge,
            leg_index=0,
            size_usd=500.0,
        )
        assert result.ok is False
        assert marks["n"] == 0
    finally:
        clear_on_rpc_dispatch()


def test_probe_leg_cache_hit_does_not_notify_transport(monkeypatch):
    from m8_1.stable_anchor.pairs import TokenInfo
    from m8_1.stable_anchor.pool_discovery import DexRoute
    from m8_1.stable_anchor.quote_probe import QuoteResult
    from m9.graph_arb.quoter import _probe_leg, edge_quote_cache

    marks = {"n": 0}
    set_on_rpc_dispatch(lambda: marks.__setitem__("n", marks["n"] + 1))

    class _Edge:
        pool_address = "0x" + "cc" * 20
        token_in_addr = "0x" + "aa" * 20

    edge = _Edge()
    route = DexRoute(
        dex_id="test",
        adapter_type="uniswap_v3",
        quoter="0x" + "11" * 20,
        fee=3000,
        tick_spacing=None,
        curve_coin0_sym=None,
    )
    cached = QuoteResult(
        route_id="cached",
        size_usd=250.0,
        amount_in=1,
        amount_out=1,
        ok=True,
        reject_reason=None,
        gas_estimate=None,
        raw_error=None,
    )
    monkeypatch.setattr(edge_quote_cache, "get", lambda _key: cached)
    try:
        result = _probe_leg(
            None,
            route,
            TokenInfo(symbol="A", address=edge.token_in_addr, decimals=18),
            TokenInfo(symbol="B", address="0x" + "bb" * 20, decimals=18),
            10**18,
            edge=edge,
            leg_index=0,
            size_usd=250.0,
        )
        assert result.ok is True
        assert marks["n"] == 0
    finally:
        clear_on_rpc_dispatch()
