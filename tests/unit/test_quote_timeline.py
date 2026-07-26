"""Tests for quote timeline tracker."""
from __future__ import annotations

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
