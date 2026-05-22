"""Cycle quoter for M9 graph-arbitrage scanner."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Dict, List, Optional

from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute
from m8_1.stable_anchor.quote_probe import probe_quote, QuoteResult
from m9.graph_arb.models import CycleQuoteResult, GraphCycle, GraphEdge

_REJECT_CYCLE_QUOTE_FAILED = "CYCLE_QUOTE_FAILED"
_REJECT_CYCLE_ZERO_OUTPUT = "CYCLE_ZERO_OUTPUT"

STATUS_QUOTE_FAILED = "QUOTE_FAILED"
STATUS_ZERO_AMOUNT_IN = "ZERO_AMOUNT_IN"
STATUS_POSITIVE_GROSS = "POSITIVE_GROSS"
STATUS_NEGATIVE_GROSS = "NEGATIVE_GROSS"
STATUS_CYCLE_QUOTE_TIMEOUT = "CYCLE_QUOTE_TIMEOUT"


def _make_dex_route(edge: GraphEdge) -> DexRoute:
    """Convert a GraphEdge to a DexRoute for the quote probe."""
    return DexRoute(
        dex_id=edge.dex_id,
        adapter_type=edge.adapter_type,
        quoter=edge.quoter_addr,
        fee=edge.fee,
        tick_spacing=edge.tick_spacing,
        curve_coin0_sym=None,
    )


def _make_token_info(sym: str, addr: str, decimals: int) -> TokenInfo:
    """Create a TokenInfo from raw fields."""
    return TokenInfo(symbol=sym, address=addr, decimals=decimals)


def quote_cycle_sync(
    cycle: GraphCycle,
    size_usd: float,
    w3: Any,
    token_price_usd: Optional[Dict[str, float]] = None,
    timeout_s: float = 10.0,
) -> CycleQuoteResult:
    """Quote all legs of a cycle synchronously and return cumulative result."""
    started = time.monotonic()

    if size_usd <= 0:
        return CycleQuoteResult(
            cycle=cycle,
            size_usd=size_usd,
            amount_in=0,
            amount_out=0,
            gross_bps=0.0,
            status=STATUS_ZERO_AMOUNT_IN,
            reject_reason=_REJECT_CYCLE_ZERO_OUTPUT,
            leg_results=[],
            elapsed_s=0.0,
        )

    # Convert size_usd to amount_in for start token
    start_edge = cycle.edges[0]
    token_price = 1.0
    if token_price_usd:
        token_price = token_price_usd.get(start_edge.token_in_sym, 1.0)

    initial_amount = int(size_usd / token_price * (10 ** start_edge.token_in_decimals))
    current_amount = initial_amount
    leg_results: List[QuoteResult] = []

    for edge in cycle.edges:
        if time.monotonic() - started > timeout_s:
            return CycleQuoteResult(
                cycle=cycle,
                size_usd=size_usd,
                amount_in=initial_amount,
                amount_out=0,
                gross_bps=0.0,
                status=STATUS_CYCLE_QUOTE_TIMEOUT,
                reject_reason="TIMEOUT",
                leg_results=leg_results,
                elapsed_s=time.monotonic() - started,
            )

        route = _make_dex_route(edge)
        token_in = _make_token_info(edge.token_in_sym, edge.token_in_addr, edge.token_in_decimals)
        token_out = _make_token_info(edge.token_out_sym, edge.token_out_addr, edge.token_out_decimals)

        leg_result = probe_quote(w3, route, token_in, token_out, current_amount)
        leg_results.append(leg_result)

        if not leg_result.ok:
            return CycleQuoteResult(
                cycle=cycle,
                size_usd=size_usd,
                amount_in=initial_amount,
                amount_out=0,
                gross_bps=0.0,
                status=STATUS_QUOTE_FAILED,
                reject_reason=_REJECT_CYCLE_QUOTE_FAILED,
                leg_results=leg_results,
                elapsed_s=time.monotonic() - started,
            )
        current_amount = leg_result.amount_out

    # Calculate gross_bps
    if initial_amount > 0:
        gross_bps = (current_amount - initial_amount) / initial_amount * 10000.0
    else:
        gross_bps = 0.0

    status = STATUS_POSITIVE_GROSS if gross_bps > 0 else STATUS_NEGATIVE_GROSS

    return CycleQuoteResult(
        cycle=cycle,
        size_usd=size_usd,
        amount_in=initial_amount,
        amount_out=current_amount,
        gross_bps=gross_bps,
        status=status,
        reject_reason=None,
        leg_results=leg_results,
        elapsed_s=time.monotonic() - started,
    )


async def quote_cycle_async(
    cycle: GraphCycle,
    size_usd: float,
    w3: Any,
    token_prices: Optional[Dict[str, float]] = None,
    timeout_s: float = 10.0,
) -> CycleQuoteResult:
    """Async wrapper around quote_cycle_sync."""
    return quote_cycle_sync(cycle, size_usd, w3, token_prices, timeout_s)


def schedule_cycle_quotes(
    cycles: List[GraphCycle],
    w3: Any,
    sizes_usd: "tuple[float, ...]",
    max_workers: int = 4,
    token_prices: Optional[Dict[str, float]] = None,
) -> List[CycleQuoteResult]:
    """Quote all cycles in parallel using ThreadPoolExecutor."""
    results: List[CycleQuoteResult] = []
    size_usd = sizes_usd[0] if sizes_usd else 1000.0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(quote_cycle_sync, cycle, size_usd, w3, token_prices)
            for cycle in cycles
        ]
        for future in futures:
            try:
                result = future.result(timeout=30.0)
                results.append(result)
            except Exception as exc:
                # Build a failed result for this cycle
                if futures:
                    idx = futures.index(future) if future in futures else 0
                    cycle = cycles[idx] if idx < len(cycles) else cycles[0]
                else:
                    continue
                results.append(
                    CycleQuoteResult(
                        cycle=cycle,
                        size_usd=size_usd,
                        amount_in=0,
                        amount_out=0,
                        gross_bps=0.0,
                        status=STATUS_QUOTE_FAILED,
                        reject_reason=str(exc)[:80],
                        leg_results=[],
                        elapsed_s=0.0,
                    )
                )

    return results
