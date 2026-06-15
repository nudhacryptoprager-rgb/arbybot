"""Cycle quoter for M9 graph-arbitrage scanner."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Dict, List, Optional, Tuple

from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute
from m8_1.stable_anchor.quote_probe import probe_quote, QuoteResult
from m9.graph_arb.depth_telemetry import oversized_reject_for_depth
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
# P0a: a catastrophically *negative* gross that exceeds the depth-aware phantom
# ceiling is NOT a phantom (impossible positive arb) and NOT an RPC failure — it
# is a real, if extreme, quote of a notional that overwhelms the bottleneck pool
# depth.  It is reported under its own status so it is excluded from the quote
# success rate (QSR) denominator rather than inflating phantom/quote failures.
STATUS_OVERSIZED_VS_DEPTH = "OVERSIZED_VS_DEPTH"
_REJECT_OVERSIZED_VS_DEPTH = "OVERSIZED_VS_DEPTH"
_REJECT_PHANTOM_QUOTE_BPS_OVERFLOW = "PHANTOM_QUOTE_BPS_OVERFLOW"
_REJECT_TOKEN_DECIMALS_UNKNOWN = "TOKEN_DECIMALS_UNKNOWN"
_REJECT_UNKNOWN_PRICE = "UNKNOWN_PRICE"

STATUS_TOKEN_DECIMALS_UNKNOWN = "TOKEN_DECIMALS_UNKNOWN"
STATUS_UNKNOWN_PRICE = "UNKNOWN_PRICE"

# Depth-aware sizing (package #2): fraction of the bottleneck pool's
# effective_depth_usd that the quote ladder is allowed to reach.  effective_depth_usd
# is the notional at which marginal price impact hits the LOW threshold (~10%), so a
# fraction of 1.0 caps trades at that point. Kept <1.0 for a slippage safety margin.
_DEPTH_SIZE_FRACTION: float = 1.0

# P0b: when every ladder size exceeds the bottleneck depth we synthesize a single
# probe AT the depth cap instead of quoting a notional many times the pool depth
# (which yields a guaranteed ~-99% price-impact "loss" that is an artifact of
# oversizing, not the market).  The probe is floored to a tiny minimum so the
# USD->amount_in conversion never rounds to dust/zero on ultra-thin pools.
_MIN_DEPTH_PROBE_USD: float = 1.0


def cap_sizes_to_depth(
    sizes_usd: "tuple[float, ...]",
    depth_usd: Optional[float],
    max_fraction: float = _DEPTH_SIZE_FRACTION,
) -> "tuple[float, ...]":
    """Clamp a size ladder to the bottleneck pool depth.

    Returns the subset of ``sizes_usd`` that does not exceed
    ``max_fraction * depth_usd``.  When every ladder size exceeds the cap we do
    NOT keep the smallest oversized size (P0b): quoting a notional many times the
    pool depth produces a guaranteed ~-99% price-impact "loss" that is an
    artifact of oversizing, not a market signal.  Instead we synthesize a single
    probe AT the depth cap (floored to ``_MIN_DEPTH_PROBE_USD``) so the cycle
    still yields one realistic data point.  When ``depth_usd`` is None/<=0 the
    ladder is returned unchanged.
    """
    if depth_usd is None or depth_usd <= 0:
        return sizes_usd
    cap = depth_usd * max_fraction
    kept = tuple(s for s in sizes_usd if s <= cap)
    if kept:
        return kept
    if not sizes_usd:
        return sizes_usd
    # All sizes above cap: probe at the depth cap itself (floored), not the
    # smallest oversized size, so price impact reflects the pool's real capacity.
    probe = max(cap, _MIN_DEPTH_PROBE_USD)
    return (round(probe, 6),)


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
    if edge is not None:
        from m9.graph_arb.productive_distinct_quote import cap_leg_amount_in_for_edge

        amount_in = cap_leg_amount_in_for_edge(edge, amount_in)
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
    token_in_index = edge.token_in_index
    if edge.adapter_type == "maverick_v2" and edge.token_a_address and edge.token_in_addr:
        token_in_index = (
            1 if edge.token_in_addr.lower() == edge.token_a_address.lower() else 0
        )
    return DexRoute(
        dex_id=edge.dex_id,
        adapter_type=edge.adapter_type,
        quoter=edge.quoter_addr,
        fee=edge.fee,
        tick_spacing=edge.tick_spacing,
        curve_coin0_sym=None,
        hooks=edge.hooks,
        token_in_index=token_in_index,
        token_out_index=edge.token_out_index,
        pool_id=edge.pool_id,
        vault_address=edge.vault_address,
        pool_kind=edge.pool_kind,
        balancer_assets=list(edge.balancer_assets) if edge.balancer_assets else None,
        balancer_balances=list(edge.balancer_balances) if edge.balancer_balances else None,
        maverick_pool_lane_probe_amount=edge.maverick_pool_lane_probe_amount,
        maverick_min_quoteable_amount_raw=edge.maverick_min_quoteable_amount_raw,
        maverick_max_quoteable_amount_raw=edge.maverick_max_quoteable_amount_raw,
        maverick_token_a_in_probe=edge.maverick_token_a_in_probe,
        maverick_pool_lane_token_in=edge.maverick_pool_lane_token_in,
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

    from m9.graph_arb.per_dex_sizing import productive_cycle_size_usd_cap

    size_usd = productive_cycle_size_usd_cap(cycle, size_usd, token_price_usd)

    # Convert size_usd to amount_in for start token (address-first price/decimals)
    start_edge = cycle.edges[0]
    from m9.graph_arb.token_price_fetcher import resolve_token_price_usd

    if start_edge.token_in_decimals is None or int(start_edge.token_in_decimals) < 0:
        return CycleQuoteResult(
            cycle=cycle,
            size_usd=size_usd,
            amount_in=0,
            amount_out=0,
            gross_bps=0.0,
            status=STATUS_TOKEN_DECIMALS_UNKNOWN,
            reject_reason=_REJECT_TOKEN_DECIMALS_UNKNOWN,
            leg_results=[],
            elapsed_s=time.monotonic() - started,
        )

    token_price = resolve_token_price_usd(
        start_edge.token_in_addr,
        start_edge.token_in_sym,
        token_price_usd,
    )
    if token_price is None or token_price <= 0:
        return CycleQuoteResult(
            cycle=cycle,
            size_usd=size_usd,
            amount_in=0,
            amount_out=0,
            gross_bps=0.0,
            status=STATUS_UNKNOWN_PRICE,
            reject_reason=_REJECT_UNKNOWN_PRICE,
            leg_results=[],
            elapsed_s=time.monotonic() - started,
        )

    initial_amount = int(size_usd / token_price * (10 ** int(start_edge.token_in_decimals)))
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

    # Depth-aware phantom ceiling (Step 3): a round-trip cycle reporting a
    # spread larger than the plausible ceiling for its bottleneck depth is a
    # phantom (revert data decoded as amount_out, wrong token indices, or a thin
    # one-directional pool).  Unknown-depth pools get the strictest ceiling.
    from m9.graph_arb.profit_validation import depth_aware_phantom_ceiling_bps

    _cycle_depth = cycle.min_effective_depth_usd
    _depth_statuses = [
        getattr(e, "depth_probe_status", None)
        for e in cycle.edges
        if getattr(e, "depth_probe_status", None)
    ]
    _cycle_depth_status = _depth_statuses[0] if len(_depth_statuses) == 1 else None
    _fresh = any(getattr(e, "freshness_window", False) for e in cycle.edges)
    _max_reasonable_bps = depth_aware_phantom_ceiling_bps(
        _cycle_depth,
        depth_probe_status=_cycle_depth_status,
        freshness_window=_fresh,
    )
    if abs(gross_bps) > _max_reasonable_bps:
        # P0a: split the overflow by sign.
        #  * POSITIVE overflow → an impossible arbitrage spread → genuine phantom
        #    (revert data decoded as amount_out, wrong token indices, etc.).  This
        #    is a real quote failure and counts against QSR.
        #  * NEGATIVE overflow → a real (if extreme) quote of a notional that
        #    overwhelms the bottleneck pool depth.  Not a phantom and not an RPC
        #    failure → its own status so it is excluded from the QSR denominator
        #    rather than masquerading as a quote failure.
        if gross_bps > 0:
            _ovf_status = STATUS_QUOTE_FAILED
            _ovf_reject = _REJECT_PHANTOM_QUOTE_BPS_OVERFLOW
        else:
            _legs_ok = bool(leg_results) and all(l.ok for l in leg_results)
            if _cycle_depth is None and _legs_ok:
                # Unknown-depth probe/micro quotes can show large negative gross while
                # every leg returned a real on-chain price — count as quoteable liveness.
                return CycleQuoteResult(
                    cycle=cycle,
                    size_usd=size_usd,
                    amount_in=initial_amount,
                    amount_out=current_amount,
                    gross_bps=gross_bps,
                    status=STATUS_NEGATIVE_GROSS,
                    reject_reason=None,
                    leg_results=leg_results,
                    elapsed_s=time.monotonic() - started,
                    raw_gross_bps=round(gross_bps, 4),
                    phantom_ceiling_bps=round(_max_reasonable_bps, 4),
                    cycle_min_depth_usd=_cycle_depth,
                )
            _ovf_status, _ovf_reject = oversized_reject_for_depth(
                _cycle_depth, gross_bps=gross_bps
            )
        return CycleQuoteResult(
            cycle=cycle,
            size_usd=size_usd,
            amount_in=initial_amount,
            amount_out=0,
            gross_bps=0.0,
            status=_ovf_status,
            reject_reason=_ovf_reject,
            leg_results=leg_results,
            elapsed_s=time.monotonic() - started,
            raw_gross_bps=round(gross_bps, 4),
            phantom_ceiling_bps=round(_max_reasonable_bps, 4),
            cycle_min_depth_usd=_cycle_depth,
        )

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
        cycle_min_depth_usd=_cycle_depth,
    )


def quote_cycle_dynamic_sync(
    cycle: GraphCycle,
    sizes_usd: "tuple[float, ...]",
    w3: Any,
    token_price_usd: Optional[Dict[str, float]] = None,
    timeout_s: float = 10.0,
    quote_backend: str = BACKEND_DIRECT_HTTP,
    rpc_url: Optional[str] = None,
    depth_aware: bool = True,
    depth_size_fraction: float = _DEPTH_SIZE_FRACTION,
) -> CycleQuoteResult:
    """Quote a cycle across a bounded USD ladder and select the best size.

    This is opt-in because each extra size can add RPC pressure.  The selected
    result is the quoteable size with the highest gross_bps.  If no size is
    quoteable, return the first failed quote with the depth_curve attached.

    Depth-aware sizing (package #2): when ``depth_aware`` is True and the cycle's
    bottleneck pool reports an ``effective_depth_usd`` (from pool_depth_probe),
    the ladder is clamped to ``depth_size_fraction * min_effective_depth_usd`` so
    we never quote a notional larger than the shallowest pool can absorb.  When
    no edge carries a measured depth, the ladder is used unchanged.
    """
    candidates = tuple(float(s) for s in sizes_usd if float(s) > 0)
    if not candidates:
        candidates = (1000.0,)

    from m9.graph_arb.depth_telemetry import REJECT_DEPTH_BELOW_ECONOMICS_FLOOR
    from m9.graph_arb.size_truth import economic_size_floor_usd

    cycle_depth = cycle.min_effective_depth_usd if depth_aware else None
    depth_capped = False
    _econ_floor_usd = economic_size_floor_usd()
    if isinstance(cycle_depth, (int, float)) and not isinstance(cycle_depth, bool) and cycle_depth > 0:
        try:
            from m9.graph_arb.per_dex_sizing import (
                bottleneck_depth_fraction,
                cap_sizes_to_depth_per_family,
            )

            _frac = bottleneck_depth_fraction(cycle.edges)
            _depth_cap_usd = float(cycle_depth) * _frac
            if _depth_cap_usd < _econ_floor_usd:
                return CycleQuoteResult(
                    cycle=cycle,
                    size_usd=_econ_floor_usd,
                    amount_in=0,
                    amount_out=0,
                    gross_bps=0.0,
                    status="DEPTH_BELOW_ECONOMICS_FLOOR",
                    reject_reason=REJECT_DEPTH_BELOW_ECONOMICS_FLOOR,
                    leg_results=[],
                    elapsed_s=0.0,
                    cycle_min_depth_usd=float(cycle_depth),
                    depth_capped=True,
                )
            capped = cap_sizes_to_depth_per_family(
                candidates,
                float(cycle_depth),
                edges=cycle.edges,
            )
        except Exception:
            capped = cap_sizes_to_depth(candidates, cycle_depth, depth_size_fraction)
        depth_capped = capped != candidates
        candidates = capped
        if not any(s >= _econ_floor_usd for s in candidates):
            candidates = tuple(sorted(set(candidates) | {_econ_floor_usd}))
    else:
        cycle_depth = None

    try:
        from m9.graph_arb.per_dex_sizing import productive_cycle_size_usd_cap

        normalized_candidates: List[float] = []
        for candidate in candidates:
            normalized = float(productive_cycle_size_usd_cap(cycle, candidate, token_price_usd))
            if normalized > 0 and normalized not in normalized_candidates:
                normalized_candidates.append(normalized)
        if normalized_candidates:
            candidates = tuple(normalized_candidates)
    except Exception:
        pass

    results: List[CycleQuoteResult] = []
    depth_curve: List[Dict[str, Any]] = []
    per_size_timeout = max(timeout_s / max(len(candidates), 1), 1.0)

    for size_usd in candidates:
        result = quote_cycle_sync(
            cycle,
            size_usd,
            w3,
            token_price_usd,
            per_size_timeout,
            quote_backend,
            rpc_url,
        )
        results.append(result)
        depth_curve.append(
            {
                "size_usd": result.size_usd,
                "gross_bps": round(result.gross_bps, 6),
                "status": result.status,
                "reject_reason": result.reject_reason,
                "profit_usd": round(result.size_usd * result.gross_bps / 10000.0, 6),
            }
        )

    quoteable = [
        r for r in results
        if r.status in (STATUS_POSITIVE_GROSS, STATUS_NEGATIVE_GROSS)
    ]
    selected = max(quoteable, key=lambda r: r.gross_bps) if quoteable else results[0]
    selected.dynamic_size_usd = selected.size_usd
    selected.size_candidates_usd = candidates
    selected.depth_curve = depth_curve
    selected.dynamic_size_source = "multi_size_quote" if quoteable else "multi_size_no_quoteable"
    selected.cycle_min_depth_usd = cycle_depth
    selected.depth_capped = depth_capped
    return selected


def quote_cycle_roundtrip_sync(
    cycle: GraphCycle,
    size_usd: float,
    w3: Any,
    token_price_usd: Optional[Dict[str, float]] = None,
    timeout_s: float = 10.0,
    quote_backend: str = BACKEND_DIRECT_HTTP,
    rpc_url: Optional[str] = None,
) -> CycleQuoteResult:
    """Quote a cycle forward AND in reverse, rejecting asymmetric phantoms.

    Step 3 round-trip validation: a genuine closed arbitrage cycle and its
    reverse cannot both be profitable.  This quotes both directions, records
    ``reverse_gross_bps`` / ``asymmetry_bps`` on the forward result, and
    downgrades the forward result to a phantom rejection when the pair is
    internally inconsistent.

    This doubles RPC cost, so it is opt-in (used to *confirm* a candidate, not
    for the bulk discovery sweep).
    """
    from m9.graph_arb.profit_validation import detect_asymmetry, REASON_ASYMMETRIC_ROUNDTRIP

    forward = quote_cycle_sync(
        cycle, size_usd, w3, token_price_usd, timeout_s, quote_backend, rpc_url,
    )
    if forward.status not in (STATUS_POSITIVE_GROSS, STATUS_NEGATIVE_GROSS):
        return forward

    reverse = quote_cycle_sync(
        cycle.reversed(), size_usd, w3, token_price_usd, timeout_s, quote_backend, rpc_url,
    )
    if reverse.status not in (STATUS_POSITIVE_GROSS, STATUS_NEGATIVE_GROSS):
        # Reverse leg not quoteable → cannot confirm symmetry; leave forward as-is
        # but record that the reverse was missing.
        forward.reverse_gross_bps = None
        return forward

    forward.reverse_gross_bps = reverse.gross_bps
    forward.asymmetry_bps = abs(forward.gross_bps + reverse.gross_bps)

    if detect_asymmetry(forward.gross_bps, reverse.gross_bps):
        forward.gross_bps = 0.0
        forward.status = STATUS_QUOTE_FAILED
        forward.reject_reason = REASON_ASYMMETRIC_ROUNDTRIP
    return forward


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
    dynamic_sizes: bool = False,
    dynamic_size_limit: Optional[int] = None,
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
    if dynamic_sizes and dynamic_size_limit is None:
        dynamic_limit = len(cycles)
    elif dynamic_sizes and int(dynamic_size_limit or 0) <= 0:
        # 0 (or negative) = apply multi-size ladder to every cycle in the batch.
        dynamic_limit = len(cycles)
    else:
        dynamic_limit = max(int(dynamic_size_limit or 0), 0)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = []
        for i, cycle in enumerate(cycles):
            if dynamic_sizes and i < dynamic_limit:
                futures.append(
                    pool.submit(
                        quote_cycle_dynamic_sync, cycle, tuple(sizes_usd), w3,
                        token_prices, timeout_s, quote_backend, rpc_url,
                    )
                )
            else:
                futures.append(
                    pool.submit(
                        quote_cycle_sync, cycle, size_usd, w3, token_prices,
                        timeout_s, quote_backend, rpc_url,
                    )
                )
        futures = [
            future
            for future in futures
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
