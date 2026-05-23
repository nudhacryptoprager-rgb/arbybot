"""Cycle quoter for M9 graph-arbitrage scanner."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Dict, List, Optional, Tuple

from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute
from m8_1.stable_anchor.quote_probe import probe_quote, QuoteResult
from m9.graph_arb.models import CycleQuoteResult, GraphCycle, GraphEdge

# Quote backend identifiers
BACKEND_DIRECT_HTTP = "direct_http"
BACKEND_RAW_HTTP = "raw_http"
BACKEND_ANVIL_FORK = "anvil_fork"
_VALID_BACKENDS = (BACKEND_DIRECT_HTTP, BACKEND_RAW_HTTP, BACKEND_ANVIL_FORK)

_REJECT_CYCLE_QUOTE_FAILED = "CYCLE_QUOTE_FAILED"
_REJECT_CYCLE_ZERO_OUTPUT = "CYCLE_ZERO_OUTPUT"

STATUS_QUOTE_FAILED = "QUOTE_FAILED"
STATUS_ZERO_AMOUNT_IN = "ZERO_AMOUNT_IN"
STATUS_POSITIVE_GROSS = "POSITIVE_GROSS"
STATUS_NEGATIVE_GROSS = "NEGATIVE_GROSS"
STATUS_CYCLE_QUOTE_TIMEOUT = "CYCLE_QUOTE_TIMEOUT"

# ---------------------------------------------------------------------------
# Edge-level quote cache (Step 9)
# ---------------------------------------------------------------------------
# A lightweight TTL cache for single-leg quote results, keyed by
# (pool_addr, token_in_addr, amount_in).  This avoids redundant RPC calls
# when the same edge appears in multiple cycles within a single sweep.
#
# TTL is short (default 2 s) so prices never go stale across sweeps.
# Thread-safe via a per-cache lock.

_EdgeKey = Tuple[str, str, int]  # (pool_addr_lower, token_in_addr_lower, amount_in)

_EDGE_CACHE_TTL_S: float = 2.0


class _EdgeQuoteCache:
    """Thread-safe TTL cache for single-leg QuoteResult objects."""

    def __init__(self, ttl_s: float = _EDGE_CACHE_TTL_S) -> None:
        self._ttl = ttl_s
        self._lock = threading.Lock()
        # value: (QuoteResult, expires_at_monotonic)
        self._store: Dict[_EdgeKey, tuple] = {}

    def get(self, key: _EdgeKey) -> Optional["QuoteResult"]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            result, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return result

    def put(self, key: _EdgeKey, result: "QuoteResult") -> None:
        with self._lock:
            self._store[key] = (result, time.monotonic() + self._ttl)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)


# Module-level cache shared across all threads within a process.
# Callers can replace this with a custom instance (e.g. in tests).
edge_quote_cache: _EdgeQuoteCache = _EdgeQuoteCache()


def _edge_cache_key(edge: "GraphEdge", amount_in: int) -> _EdgeKey:
    """Derive a stable cache key from the edge and input amount."""
    pool_addr = (edge.pool_address or "").lower()
    token_in = (edge.token_in_addr or "").lower()
    return (pool_addr, token_in, amount_in)


def _probe_leg(
    w3: Any,
    route: DexRoute,
    token_in: TokenInfo,
    token_out: TokenInfo,
    amount_in: int,
    quote_backend: str = BACKEND_DIRECT_HTTP,
    rpc_url: Optional[str] = None,
    edge: Optional["GraphEdge"] = None,
    use_cache: bool = True,
) -> QuoteResult:
    """Route a single leg probe to the correct backend.

    When ``edge`` is supplied and ``use_cache=True`` (default), the result is
    looked up in / stored to the module-level ``edge_quote_cache`` before
    issuing an RPC call.  This avoids redundant calls when the same pool
    appears in multiple cycles within a single sweep.
    """
    # Cache read (only when we have a stable pool address to key on)
    cache_key: Optional[_EdgeKey] = None
    if use_cache and edge is not None and edge.pool_address:
        cache_key = _edge_cache_key(edge, amount_in)
        cached = edge_quote_cache.get(cache_key)
        if cached is not None:
            return cached
    if quote_backend == BACKEND_RAW_HTTP:
        from m9.graph_arb.raw_http_probe import probe_quote_raw_http
        if rpc_url is None:
            raise ValueError("rpc_url is required for raw_http backend")
        result = probe_quote_raw_http(rpc_url, route, token_in, token_out, amount_in)
    elif quote_backend == BACKEND_ANVIL_FORK:
        # anvil_fork always routes to Anvil local fork — ignores rpc_url to avoid
        # accidentally hitting the external RPC when runner resolves BASE_RPC first.
        import os as _os
        from m9.graph_arb.raw_http_probe import probe_quote_raw_http
        anvil_url = _os.environ.get("ARBY_ANVIL_RPC_URL", "http://127.0.0.1:8545")
        result = probe_quote_raw_http(anvil_url, route, token_in, token_out, amount_in)
    else:
        # default: direct_http (web3 path)
        result = probe_quote(w3, route, token_in, token_out, amount_in)

    # Cache write
    if cache_key is not None:
        edge_quote_cache.put(cache_key, result)

    return result


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
    quote_backend: str = BACKEND_DIRECT_HTTP,
    rpc_url: Optional[str] = None,
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

        leg_result = _probe_leg(
            w3, route, token_in, token_out, current_amount,
            quote_backend, rpc_url, edge=edge,
        )
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
    quote_backend: str = BACKEND_DIRECT_HTTP,
    rpc_url: Optional[str] = None,
) -> CycleQuoteResult:
    """Async wrapper around quote_cycle_sync."""
    return quote_cycle_sync(cycle, size_usd, w3, token_prices, timeout_s, quote_backend, rpc_url)


def schedule_cycle_quotes(
    cycles: List[GraphCycle],
    w3: Any,
    sizes_usd: "tuple[float, ...]",
    max_workers: int = 4,
    token_prices: Optional[Dict[str, float]] = None,
    timeout_s: float = 10.0,
    quote_backend: str = BACKEND_DIRECT_HTTP,
    rpc_url: Optional[str] = None,
) -> List[CycleQuoteResult]:
    """Quote all cycles in parallel using ThreadPoolExecutor.

    Args:
        max_workers: number of parallel quote threads (reduce to 1-2 for dRPC free tier)
        quote_backend: "direct_http" (web3 + eth_chainId), "raw_http" (JSON-RPC only),
                       or "anvil_fork" (local fork)
        rpc_url: required for raw_http and anvil_fork backends
    """
    results: List[CycleQuoteResult] = []
    size_usd = sizes_usd[0] if sizes_usd else 1000.0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(
                quote_cycle_sync, cycle, size_usd, w3, token_prices, timeout_s,
                quote_backend, rpc_url,
            )
            for cycle in cycles
        ]
        for i, future in enumerate(futures):
            try:
                result = future.result(timeout=30.0)
                results.append(result)
            except Exception as exc:
                cycle = cycles[i] if i < len(cycles) else cycles[0]
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
