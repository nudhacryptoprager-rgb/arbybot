"""Unit tests for quote_failure_diagnostics in M9 artifacts."""
from __future__ import annotations

from m8_1.stable_anchor.quote_probe import QuoteResult
from m9.graph_arb.artifacts import (
    _compute_phantom_quote_diagnostics,
    _compute_quote_failure_diagnostics,
    _trim_route_error_histogram,
)
from m9.graph_arb.quoter import quote_cycle_sync
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


def test_phantom_quote_diagnostics_exposes_raw_gross_and_ceiling():
    qr = CycleQuoteResult(
        cycle=_tri_cycle(),
        size_usd=100.0,
        amount_in=10**18,
        amount_out=0,
        gross_bps=0.0,
        status="QUOTE_FAILED",
        reject_reason="PHANTOM_QUOTE_BPS_OVERFLOW",
        leg_results=[],
        elapsed_s=0.1,
        raw_gross_bps=2500.0,
        phantom_ceiling_bps=500.0,
        cycle_min_depth_usd=None,
    )
    diag = _compute_phantom_quote_diagnostics([qr])
    assert diag["phantom_count"] == 1
    assert diag["blocker_class_hint"] == "PHANTOM_VALIDATION"
    assert diag["depth_unknown_count"] == 1
    assert diag["sample_overflows"][0]["raw_gross_bps"] == 2500.0
    assert diag["sample_overflows"][0]["phantom_ceiling_bps"] == 500.0
    assert diag["top_pools"]


def test_phantom_not_classified_as_rpc_in_quote_failure_diagnostics():
    """Leg-level RPC histogram must not absorb cycle-level phantom rejects."""
    phantom = CycleQuoteResult(
        cycle=_tri_cycle(),
        size_usd=100.0,
        amount_in=10**18,
        amount_out=0,
        gross_bps=0.0,
        status="QUOTE_FAILED",
        reject_reason="PHANTOM_QUOTE_BPS_OVERFLOW",
        leg_results=[],
        elapsed_s=0.1,
        raw_gross_bps=9000.0,
        phantom_ceiling_bps=500.0,
    )
    leg_rpc = CycleQuoteResult(
        cycle=_tri_cycle(),
        size_usd=100.0,
        amount_in=10**18,
        amount_out=0,
        gross_bps=0.0,
        status="QUOTE_FAILED",
        reject_reason="CYCLE_QUOTE_FAILED",
        leg_results=[
            QuoteResult(
                route_id="r1",
                size_usd=100.0,
                amount_in=10**18,
                amount_out=0,
                ok=False,
                reject_reason="QUOTE_RPC_ERROR",
                gas_estimate=None,
                raw_error="HTTP 429: limited",
            )
        ],
        elapsed_s=0.1,
    )
    leg_diag = _compute_quote_failure_diagnostics([phantom, leg_rpc])
    phantom_diag = _compute_phantom_quote_diagnostics([phantom, leg_rpc])
    assert "PHANTOM_QUOTE_BPS_OVERFLOW" not in leg_diag.get("by_reject_reason", {})
    assert phantom_diag["phantom_count"] == 1
    assert leg_diag["by_reject_reason"].get("QUOTE_RPC_ERROR") == 1


def test_quoter_phantom_reject_populates_debug_fields():
    """quote_cycle_sync must preserve raw gross when phantom ceiling trips."""
    from unittest.mock import MagicMock, patch

    cycle = _tri_cycle()
    w3 = MagicMock()

    def _double_leg(*_args, **kwargs):
        amount_in = _args[4] if len(_args) > 4 else 10**18
        return QuoteResult(
            route_id="mock",
            size_usd=100.0,
            amount_in=amount_in,
            amount_out=amount_in * 2,
            ok=True,
            reject_reason=None,
            gas_estimate=None,
            raw_error=None,
        )

    with patch("m9.graph_arb.quoter._probe_leg", side_effect=_double_leg):
        result = quote_cycle_sync(cycle, 100.0, w3, quote_backend="raw_http", rpc_url="http://x")
    assert result.reject_reason == "PHANTOM_QUOTE_BPS_OVERFLOW"
    assert result.raw_gross_bps is not None
    assert abs(result.raw_gross_bps) > 500.0
    assert result.phantom_ceiling_bps == 500.0
    assert result.cycle_min_depth_usd is None


def test_route_error_histogram_trim_keeps_top_offenders():
    hist = {
        f"route_{i:02d}": {"QUOTE_RPC_ERROR": i}
        for i in range(45)
    }

    trimmed, meta = _trim_route_error_histogram(hist, limit=3)

    assert meta == {"total": 45, "kept": 3, "dropped": 42}
    assert list(trimmed) == ["route_44", "route_43", "route_42"]


def test_quoter_negative_overflow_is_oversized_not_phantom():
    """P0a: a catastrophic *negative* gross is OVERSIZED_VS_DEPTH, not a phantom.

    A real quote whose notional overwhelms the bottleneck pool depth produces a
    deeply negative gross (~-99%).  That is a sizing artifact, not an impossible
    positive arb (phantom) and not an RPC failure, so it must NOT be reported as
    PHANTOM_QUOTE_BPS_OVERFLOW / QUOTE_FAILED.
    """
    from unittest.mock import MagicMock, patch

    cycle = _tri_cycle()  # no measured depth → strictest ceiling (500 bps)
    w3 = MagicMock()

    def _shrink_leg(*_args, **_kwargs):
        amount_in = _args[4] if len(_args) > 4 else 10**18
        return QuoteResult(
            route_id="mock",
            size_usd=100.0,
            amount_in=amount_in,
            amount_out=amount_in // 4,  # 3 legs → ~/64 → ~-9843 bps
            ok=True,
            reject_reason=None,
            gas_estimate=None,
            raw_error=None,
        )

    with patch("m9.graph_arb.quoter._probe_leg", side_effect=_shrink_leg):
        result = quote_cycle_sync(cycle, 100.0, w3, quote_backend="raw_http", rpc_url="http://x")

    assert result.status == "OVERSIZED_VS_DEPTH"
    assert result.reject_reason == "OVERSIZED_VS_DEPTH"
    assert result.raw_gross_bps is not None
    assert result.raw_gross_bps < -500.0
    assert result.phantom_ceiling_bps == 500.0
    # The negative overflow must NOT be aggregated as a phantom.
    phantom_diag = _compute_phantom_quote_diagnostics([result])
    assert phantom_diag["phantom_count"] == 0


def test_positive_overflow_still_phantom():
    """P0a: a positive gross above the ceiling remains a genuine phantom."""
    from unittest.mock import MagicMock, patch

    cycle = _tri_cycle()
    w3 = MagicMock()

    def _double_leg(*_args, **_kwargs):
        amount_in = _args[4] if len(_args) > 4 else 10**18
        return QuoteResult(
            route_id="mock", size_usd=100.0, amount_in=amount_in,
            amount_out=amount_in * 2, ok=True, reject_reason=None,
            gas_estimate=None, raw_error=None,
        )

    with patch("m9.graph_arb.quoter._probe_leg", side_effect=_double_leg):
        result = quote_cycle_sync(cycle, 100.0, w3, quote_backend="raw_http", rpc_url="http://x")

    assert result.status == "QUOTE_FAILED"
    assert result.reject_reason == "PHANTOM_QUOTE_BPS_OVERFLOW"
    assert result.raw_gross_bps > 500.0


def test_cap_sizes_to_depth_probes_at_cap_when_all_oversized():
    """P0b: when every ladder size exceeds depth, probe AT the cap, not the smallest.

    Previously the smallest oversized size was kept (e.g. $100 into a $10-depth
    pool), guaranteeing a ~-99% price-impact loss that is a sizing artifact.  The
    fix synthesizes a single probe at ``depth * fraction``.
    """
    from m9.graph_arb.quoter import cap_sizes_to_depth

    # depth=10, fraction=1.0 → cap=10; ladder [100,250,500] all exceed it.
    capped = cap_sizes_to_depth((100.0, 250.0, 500.0), 10.0, 1.0)
    assert capped == (10.0,)
    # Smallest ladder size must NOT be returned anymore.
    assert 100.0 not in capped


def test_cap_sizes_to_depth_floors_tiny_depth():
    """P0b: ultra-thin depth is floored so amount_in never rounds to dust."""
    from m9.graph_arb.quoter import cap_sizes_to_depth, _MIN_DEPTH_PROBE_USD

    capped = cap_sizes_to_depth((100.0, 250.0), 0.01, 1.0)
    assert capped == (round(_MIN_DEPTH_PROBE_USD, 6),)


def test_cap_sizes_to_depth_keeps_subset_when_some_fit():
    """P0b: unchanged behaviour when some ladder sizes fit within the cap."""
    from m9.graph_arb.quoter import cap_sizes_to_depth

    capped = cap_sizes_to_depth((100.0, 250.0, 500.0), 300.0, 1.0)
    assert capped == (100.0, 250.0)

