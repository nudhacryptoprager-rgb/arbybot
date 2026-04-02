"""Shared test helpers for M7 orderflow test suites."""
from __future__ import annotations

from m7.orderflow.contracts import BackrunResult, OrderflowEvent


def _make_event(eid="e1", block=100, **overrides) -> OrderflowEvent:
    """Build a test OrderflowEvent with sensible defaults."""
    defaults = dict(
        event_id=eid,
        event_type="swap",
        chain="arbitrum_one",
        block_number=block,
        tx_hash="0xabc",
        token_in="USDC",
        token_out="WETH",
        amount_in_wei=1_000_000,
        amount_out_wei=500_000,
        dex="uniswap_v3",
        pool_address="0xpool",
        fee_tier=3000,
        estimated_size_usd=100.0,
        estimated_impact_bps=5.0,
        timestamp="2025-01-01T00:00:00Z",
    )
    defaults.update(overrides)
    return OrderflowEvent(**defaults)


def _make_result(**overrides) -> BackrunResult:
    """Build a test BackrunResult with sensible defaults."""
    defaults = dict(
        event_id="e1",
        event_source="live",
        event_type="uniswap_v3_swap",
        post_trade_state_used="live",
        backrun_direction="buy_depressed",
    )
    defaults.update(overrides)
    return BackrunResult(**defaults)
