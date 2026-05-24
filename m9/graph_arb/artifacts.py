"""Artifact builder and writer for M9 graph-arb scanner.

Schema revision: m9.1  (additive changes only — backward-compatible with rolling artifact).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from m9.graph_arb.models import CycleQuoteResult, GraphTopology

SCHEMA_FAMILY = "m9_graph_arb"
SCHEMA_REVISION = "m9.1"
ROLLING_PATH = "data/runs/_rolling/m9_graph_latest.json"

# Economics gate statuses
_ECON_BLOCKED_NO_CYCLES = "BLOCKED_NO_CYCLES"
_ECON_BLOCKED_QSR = "BLOCKED_QSR"
_ECON_NEAR_MISS = "NEAR_MISS"
_ECON_BLOCKED_NO_POSITIVE_GROSS = "BLOCKED_NO_POSITIVE_GROSS"
_ECON_PASS = "PASS"

# Topology gate statuses
_TOPO_NO_CYCLES = "NO_CYCLES"
_TOPO_CYCLES_FOUND = "CYCLES_FOUND"

# Near-positive threshold for router-sim eligibility (bps below zero)
_ROUTER_SIM_BPS_FLOOR = -10.0

# Economics blocker class constants
_BLOCKER_NOT_RUN = "NOT_RUN"
_BLOCKER_NOT_BLOCKED = "NOT_BLOCKED"
_BLOCKER_PROVIDER_QUALITY = "PROVIDER_QUALITY_BLOCKED"
_BLOCKER_INVENTORY_ANCHOR = "INVENTORY_TOO_ANCHOR_HEAVY"
_BLOCKER_MARKET = "MARKET_NO_POSITIVE_GROSS"

# Pair count threshold: at or below this → anchor-heavy inventory
_ANCHOR_HEAVY_PAIR_THRESHOLD = 15


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_cycle_summary(qr: CycleQuoteResult) -> Dict[str, Any]:
    cycle = qr.cycle
    return {
        "cycle_id": cycle.cycle_id,
        "length": cycle.length,
        "token_path": cycle.token_path,
        "start_token": cycle.start_token_sym,
        "total_fee_bps": round(cycle.total_fee_bps, 4),
        "min_factory_class": cycle.min_factory_class,
        "size_usd": qr.size_usd,
        "amount_in": qr.amount_in,
        "amount_out": qr.amount_out,
        "gross_bps": round(qr.gross_bps, 4),
        "status": qr.status,
        "reject_reason": qr.reject_reason,
        "elapsed_s": round(qr.elapsed_s, 3),
    }


def _build_top_opportunity(qr: CycleQuoteResult) -> Dict[str, Any]:
    """Build one operator-facing opportunity row from a CycleQuoteResult.

    Fields:
      dex           — dex_id of first edge (or comma-joined if mixed)
      factory       — factory_class of first edge (or comma-joined if mixed)
      factory_verified — True when all edges have a known (non-UNKNOWN) factory_class
      fee_tiers_bps — per-edge fee_bps list
      pool          — pool_address of first edge
      pool_path     — ordered list of pool addresses through cycle
      pair          — token path as "A/B/C"
      market_size_usd — quote size used for the selected row
      dynamic_size_usd — selected best size when dynamic sizing is enabled
      spread_bps    — gross_bps from quote
      spread_usd    — gross_bps * market_size_usd / 10000
      profit_usd    — gross_usd (gas model not yet implemented)
      main_blocker  — null when POSITIVE_GROSS, else reject_reason or status
      fee_drag_bps  — sum of all edge fees (total cost of the cycle)
      pre_fee_gross_bps — estimated gross before fees (spread_bps + fee_drag_bps)
      loss_reason   — diagnostic: UNFAVORABLE_PRICES | FEE_DRAG | QUOTE_FAILED | null
    """
    cycle = qr.cycle
    dexes = list(dict.fromkeys(e.dex_id for e in cycle.edges))
    factories = list(dict.fromkeys(e.factory_class for e in cycle.edges))
    pools = [e.pool_address for e in cycle.edges]
    pair = "/".join(cycle.token_path)
    spread_bps = round(qr.gross_bps, 4)
    spread_usd: Optional[float] = None
    if qr.size_usd and qr.size_usd > 0:
        spread_usd = round(qr.size_usd * qr.gross_bps / 10000.0, 6)
    profit_usd = spread_usd  # gross-only; no gas/slippage model in M9.3
    main_blocker: Optional[str] = None
    if qr.status not in ("POSITIVE_GROSS",):
        main_blocker = qr.reject_reason or qr.status

    # Economics RCA fields
    fee_drag_bps = round(cycle.total_fee_bps, 4)
    pre_fee_gross_bps = round(spread_bps + fee_drag_bps, 4)
    # factory_verified: True when ALL edges were on-chain confirmed by pool_verifier.
    # Uses the edge-level factory_verified flag (propagated from inventory),
    # NOT factory_class (which may be "UNKNOWN" even after verification).
    factory_verified = all(e.factory_verified for e in cycle.edges)
    fee_tiers_bps = [round(e.fee_bps, 4) for e in cycle.edges]
    # loss_reason: decompose why gross <= 0
    if qr.status in ("CYCLE_QUOTE_FAILED", "CYCLE_QUOTE_TIMEOUT", "QUOTE_FAILED"):
        loss_reason: Optional[str] = "QUOTE_FAILED"
    elif pre_fee_gross_bps < -500:
        loss_reason = "TOXIC_ROUTE_PRICE_IMPACT"  # catastrophic: prices alone -500+ bps off
    elif pre_fee_gross_bps < 0:
        loss_reason = "UNFAVORABLE_PRICES"  # prices don't support arb even before fees
    elif spread_bps < 0:
        loss_reason = "FEE_DRAG"  # prices would support arb but fees exceed the gross
    else:
        loss_reason = None

    return {
        "dex": dexes[0] if len(dexes) == 1 else ",".join(dexes),
        "factory": factories[0] if len(factories) == 1 else ",".join(factories),
        "factory_verified": factory_verified,
        "fee_tiers_bps": fee_tiers_bps,
        "pool": cycle.edges[0].pool_address,
        "pool_path": pools,
        "pair": pair,
        "market_size_usd": qr.size_usd,
        "dynamic_size_usd": qr.dynamic_size_usd,
        "size_candidates_usd": list(qr.size_candidates_usd or ()),
        "depth_curve": list(qr.depth_curve or []),
        "dynamic_size_source": qr.dynamic_size_source,
        "spread_bps": spread_bps,
        "spread_usd": spread_usd,
        "profit_usd": profit_usd,
        "main_blocker": main_blocker,
        "fee_drag_bps": fee_drag_bps,
        "pre_fee_gross_bps": pre_fee_gross_bps,
        "loss_reason": loss_reason,
        "legs": _build_per_leg_rca(qr),
    }


def _build_per_leg_rca(qr: CycleQuoteResult) -> List[Dict[str, Any]]:
    """Build per-leg RCA list: normalized in/out amounts, implied price, pool, dex, fee."""
    cycle = qr.cycle
    result: List[Dict[str, Any]] = []
    for i, edge in enumerate(cycle.edges):
        leg_data: Dict[str, Any] = {
            "leg_idx": i,
            "token_in": edge.token_in_sym,
            "token_out": edge.token_out_sym,
            "pool_address": edge.pool_address,
            "dex_id": edge.dex_id,
            "fee_bps": round(edge.fee_bps, 4),
            "factory_verified": edge.factory_verified,
        }
        # Per-leg quote result (ok, reject_reason, raw amounts)
        leg_result = (qr.leg_results or [])[i] if i < len(qr.leg_results or []) else None
        if leg_result is not None:
            leg_data["ok"] = leg_result.ok
            leg_data["reject_reason"] = leg_result.reject_reason if not leg_result.ok else None
            # Raw amounts (in token's native decimals)
            raw_in = getattr(leg_result, "amount_in", None)
            raw_out = getattr(leg_result, "amount_out", None)
            leg_data["raw_amount_in"] = raw_in
            leg_data["raw_amount_out"] = raw_out
            # Normalized: adjust for decimals to get human-readable amounts
            dec_in = edge.token_in_decimals
            dec_out = edge.token_out_decimals
            if raw_in is not None and raw_in > 0:
                norm_in = raw_in / (10 ** dec_in)
                leg_data["norm_amount_in"] = round(norm_in, 8)
                if raw_out is not None and raw_out > 0:
                    norm_out = raw_out / (10 ** dec_out)
                    leg_data["norm_amount_out"] = round(norm_out, 8)
                    # Implied price: how many token_out per token_in
                    leg_data["implied_price"] = round(norm_out / norm_in, 8)
                    # Value change: (out - in) / in as fraction (negative = loss on this leg)
                    # Only meaningful for same-USD tokens; provided for diagnosis
                    leg_data["norm_value_ratio"] = round(norm_out / norm_in, 8)
        result.append(leg_data)
    return result


def _compute_cycle_reject_histogram(cycle_results: List[CycleQuoteResult]) -> Dict[str, int]:
    """Count cycle outcomes by reject_reason or status."""
    histogram: Dict[str, int] = {}
    for qr in cycle_results:
        key = qr.reject_reason if qr.reject_reason else qr.status
        histogram[key] = histogram.get(key, 0) + 1
    return histogram


def _compute_route_error_histogram(
    cycle_results: List[CycleQuoteResult],
) -> Dict[str, Dict[str, int]]:
    """Aggregate quote errors per route_id from leg_results."""
    histogram: Dict[str, Dict[str, int]] = {}
    for qr in cycle_results:
        for leg in qr.leg_results or []:
            if not leg.ok and leg.reject_reason:
                route_errors = histogram.setdefault(leg.route_id, {})
                route_errors[leg.reject_reason] = route_errors.get(leg.reject_reason, 0) + 1
    return histogram


def _compute_edge_error_histogram(
    cycle_results: List[CycleQuoteResult],
) -> List[Dict[str, Any]]:
    """Aggregate quote errors per directed edge (token_in→token_out + route_id)."""
    # keyed by (token_in_sym, token_out_sym, route_id)
    edge_map: Dict[tuple, Dict[str, Any]] = {}
    for qr in cycle_results:
        edges = qr.cycle.edges
        for i, leg in enumerate(qr.leg_results or []):
            if i >= len(edges):
                continue
            if not leg.ok and leg.reject_reason:
                edge = edges[i]
                key = (edge.token_in_sym, edge.token_out_sym, leg.route_id)
                if key not in edge_map:
                    edge_map[key] = {
                        "token_in": edge.token_in_sym,
                        "token_out": edge.token_out_sym,
                        "route_id": leg.route_id,
                        "pair_id": edge.pair_id,
                        "errors": {},
                    }
                errors = edge_map[key]["errors"]
                errors[leg.reject_reason] = errors.get(leg.reject_reason, 0) + 1
    # Sort by total error count descending
    result = list(edge_map.values())
    result.sort(key=lambda x: -sum(x["errors"].values()))
    return result


def build_artifact(
    chain: str,
    duration_minutes: float,
    cycle_results: List[CycleQuoteResult],
    topology: GraphTopology,
    sizes_usd: "tuple[float, ...]",
    run_timestamp: str,
    started_at_mono: float,
    elapsed_s: float,
    execution_mode: str = "paper",
    gas_mode: str = "static",
    inventory_path: str = "",
    config_path: str = "",
    sweeps_completed: int = 0,
    scan_scope: Optional[Dict[str, Any]] = None,
    process_id: Optional[int] = None,
    python_executable: Optional[str] = None,
    venv_active: bool = False,
    strategy_gate_acceptance: bool = False,
    route_error_histogram: Optional[Dict[str, Dict[str, int]]] = None,
    edge_error_histogram: Optional[List[Dict[str, Any]]] = None,
    gap_candidates_path: Optional[str] = None,
    cycles_found_topology: Optional[int] = None,
    funnel_a: Optional[Dict[str, Any]] = None,
    inventory_reject_histogram: Optional[Dict[str, int]] = None,
    # Infra telemetry (Step 5 — M9 quote infrastructure slice)
    quote_backend: str = "direct_http",
    quote_workers: int = 4,
    provider_throttle_snapshot: Optional[Dict[str, Any]] = None,
    ws_freshness: Optional[Dict[str, Any]] = None,
    # RPC provider identity — filled by runner after resolve_rpc_http()
    rpc_provider: str = "unknown",
    rpc_source: str = "unknown",
    rpc_public_fallback_used: bool = False,
    # Inventory purity metric — count of active_routes without factory_verified=True
    unverified_active_routes: Optional[int] = None,
    # Multicall snapshot counters (Step 5 GPT fix)
    multicall_stats: Optional[Dict[str, Any]] = None,
    # Prequote funnel skip count (Step 6 GPT fix)
    prequote_cycles_skipped: int = 0,
    # Scheduler name for telemetry (Step 7 GPT fix)
    scheduler_name: Optional[str] = None,
    # Verified inventory present flag (Step 4 GPT fix)
    verified_inventory_exists: bool = False,
    # Source of sizes_usd: "config.scan_params" | "cli_default" | "cli_override" (Fix 7)
    sizes_usd_source: str = "cli_default",
    # Per-endpoint provider router telemetry snapshot (Fix 2+3)
    provider_router_snapshot: Optional[Dict[str, Any]] = None,
    # Effective prequote filter threshold used during this run
    prequote_min_bps: float = -500.0,
) -> Dict[str, Any]:
    """Build the canonical M9 rolling artifact dict.

    ``cycles_found_topology`` lets callers (e.g. dry-run mode) report how many
    cycles the topology analysis found even when ``cycle_results`` is empty.
    When provided it overrides ``len(cycle_results)`` for the ``cycles_found`` field.
    """
    generated_at_utc = _iso_now()

    # When dry-run skipped quoting, use explicit topology count
    cycles_found = cycles_found_topology if cycles_found_topology is not None else len(cycle_results)
    cycles_positive_gross = sum(1 for qr in cycle_results if qr.gross_bps > 0)
    # Near-positive cycles worth router-sim probing (within floor of breakeven)
    cycles_router_sim_eligible = sum(
        1 for qr in cycle_results
        if qr.status in ("POSITIVE_GROSS", "NEGATIVE_GROSS")
        and qr.gross_bps > _ROUTER_SIM_BPS_FLOOR
    )

    best_cycle_net_bps: Optional[float] = None
    if cycle_results:
        best = max(cycle_results, key=lambda qr: qr.gross_bps)
        best_cycle_net_bps = round(best.gross_bps, 4)

    # QSR: quote success rate (exclude ZERO_AMOUNT_IN — not a quoting attempt)
    quoted = [qr for qr in cycle_results if qr.status != "ZERO_AMOUNT_IN"]
    qsr = (
        sum(1 for qr in quoted if qr.status not in ("QUOTE_FAILED", "CYCLE_QUOTE_TIMEOUT"))
        / len(quoted)
        if quoted
        else 0.0
    )

    # Economics gate (applies only when we have actual quote results)
    if cycles_found == 0:
        econ_status = _ECON_BLOCKED_NO_CYCLES
    elif cycle_results and qsr < 0.5:
        econ_status = _ECON_BLOCKED_QSR
    elif cycles_positive_gross == 0:
        econ_status = _ECON_BLOCKED_NO_POSITIVE_GROSS
    elif best_cycle_net_bps is not None and 0 < best_cycle_net_bps < 5:
        econ_status = _ECON_NEAR_MISS
    else:
        econ_status = _ECON_PASS

    gate_acceptance = econ_status == _ECON_PASS

    # Topology gate
    topology_gate = _TOPO_CYCLES_FOUND if cycles_found > 0 else _TOPO_NO_CYCLES

    # Histograms: compute from cycle_results if not provided externally
    computed_cycle_histogram = _compute_cycle_reject_histogram(cycle_results)
    computed_route_hist = (
        route_error_histogram
        if route_error_histogram is not None
        else _compute_route_error_histogram(cycle_results)
    )
    computed_edge_hist = (
        edge_error_histogram
        if edge_error_histogram is not None
        else _compute_edge_error_histogram(cycle_results)
    )

    # scan_scope: use provided dict or derive minimal version from topology
    if scan_scope is None:
        scan_scope = {
            "routes_total": topology.route_count,
            "edge_count": topology.edge_count,
        }

    # Graph topology dict (canonical key in rolling artifact)
    graph_topology = {
        "token_count": topology.token_count,
        "edge_count": topology.edge_count,
        "route_count": topology.route_count,
        "hub_tokens": topology.hub_tokens,
        "dead_end_tokens": topology.dead_end_tokens[:10],
        "missing_edges_for_3cycle": topology.missing_edges_for_3cycle[:10],
    }

    # run_context: canonical provenance block
    run_context = {
        "chain": chain,
        "duration_minutes": duration_minutes,
        "sizes_usd": list(sizes_usd),
        "gas_mode": gas_mode,
        "inventory_path": inventory_path,
        "config_path": config_path,
        "execution_mode": execution_mode,
    }

    # Economics discovery metrics (Funnel economics signal quality)
    quoted_gross = [qr.gross_bps for qr in cycle_results if qr.status in ("POSITIVE_GROSS", "NEGATIVE_GROSS")]
    cycles_quoteable = len(quoted_gross)
    near_breakeven_count = sum(1 for bps in quoted_gross if bps >= _ROUTER_SIM_BPS_FLOOR)
    positive_gross_rate = (
        cycles_positive_gross / cycles_quoteable if cycles_quoteable else 0.0
    )
    near_breakeven_rate = (
        near_breakeven_count / cycles_quoteable if cycles_quoteable else 0.0
    )
    # Provider-level error counts from route error histogram (per-leg, not per-cycle)
    _provider_rpc_error_count = sum(
        v.get("QUOTE_RPC_ERROR", 0) for v in computed_route_hist.values() if isinstance(v, dict)
    )
    _provider_decode_error_count = sum(
        v.get("QUOTE_DECODE", 0) for v in computed_route_hist.values() if isinstance(v, dict)
    )
    # Quote error rates (relative to total cycles_found, not quoted only)
    # quote_rpc_error_rate uses provider route histogram (per-leg) — cycles reject as
    # CYCLE_QUOTE_FAILED so cycle histogram never contains QUOTE_RPC_ERROR.
    _denom = max(cycles_found, 1)
    quote_rpc_error_rate = round(_provider_rpc_error_count / _denom, 6)
    # quote_revert_rate: leg-level QUOTE_REVERT / total legs attempted.
    # The cycle-level histogram never carries QUOTE_REVERT (cycles fail as
    # CYCLE_QUOTE_FAILED), so we must count from leg_results directly.
    _leg_revert_count_early = sum(
        1
        for qr in cycle_results
        for leg in (qr.leg_results or [])
        if not leg.ok and leg.reject_reason == "QUOTE_REVERT"
    )
    _total_legs_attempted = sum(len(qr.leg_results or []) for qr in cycle_results)
    quote_revert_rate = round(
        _leg_revert_count_early / max(_total_legs_attempted, 1), 6
    )
    # Percentile gross bps: p50 and p90 across quoted cycles
    p50_gross_bps: Optional[float] = None
    p90_gross_bps: Optional[float] = None
    if quoted_gross:
        sorted_bps = sorted(quoted_gross)
        n = len(sorted_bps)
        mid = n // 2
        p50_gross_bps = (
            sorted_bps[mid] if n % 2 else round((sorted_bps[mid - 1] + sorted_bps[mid]) / 2, 4)
        )
        p90_gross_bps = round(sorted_bps[min(int(n * 0.90), n - 1)], 4)
    median_gross_bps = p50_gross_bps
    economics_metrics = {
        "positive_gross_rate": round(positive_gross_rate, 6),
        "near_breakeven_count": near_breakeven_count,
        "near_breakeven_rate": round(near_breakeven_rate, 6),
        "median_gross_bps": median_gross_bps,
        "p50_gross_bps": p50_gross_bps,
        "p90_gross_bps": p90_gross_bps,
        "quoted_cycles_count": cycles_quoteable,
        "quote_rpc_error_rate": quote_rpc_error_rate,
        "quote_revert_rate": quote_revert_rate,
        "router_sim_bps_floor": _ROUTER_SIM_BPS_FLOOR,
    }

    # Loss reason histogram across all cycle_results (Step 6 — root cause breakdown)
    _loss_reason_histogram: Dict[str, int] = {}
    _toxic_route_count = 0
    for _qr in cycle_results:
        _fee_drag = _qr.cycle.total_fee_bps
        _pfgb = round(_qr.gross_bps + _fee_drag, 4)
        if _qr.status in ("CYCLE_QUOTE_FAILED", "CYCLE_QUOTE_TIMEOUT", "QUOTE_FAILED"):
            _lr = "QUOTE_FAILED"
        elif _pfgb < -500:
            _lr = "TOXIC_ROUTE_PRICE_IMPACT"
            _toxic_route_count += 1
        elif _pfgb < 0:
            _lr = "UNFAVORABLE_PRICES"
        elif _qr.gross_bps < 0:
            _lr = "FEE_DRAG"
        else:
            _lr = "POSITIVE"
        _loss_reason_histogram[_lr] = _loss_reason_histogram.get(_lr, 0) + 1
    economics_metrics["loss_reason_histogram"] = _loss_reason_histogram
    economics_metrics["toxic_route_count"] = _toxic_route_count
    if cycles_quoteable > 0:
        economics_metrics["toxic_route_rate"] = round(_toxic_route_count / cycles_quoteable, 4)

    # Economics blocker classification: distinguish inventory quality from market signal
    pair_count = (scan_scope or {}).get("pair_count") or (
        (funnel_a or {}).get("pairs_probed") or 0
    )
    if cycles_found == 0 or not cycle_results:
        economics_blocker_class = _BLOCKER_NOT_RUN
    elif cycles_positive_gross > 0:
        economics_blocker_class = _BLOCKER_NOT_BLOCKED
    elif qsr < 0.5:
        economics_blocker_class = _BLOCKER_PROVIDER_QUALITY
    elif 0 < pair_count <= _ANCHOR_HEAVY_PAIR_THRESHOLD:
        economics_blocker_class = _BLOCKER_INVENTORY_ANCHOR
    else:
        economics_blocker_class = _BLOCKER_MARKET

    # M9 risk metrics placeholders (M9.4 — not yet implemented)
    risk_metrics = {
        "honeypot_checked": 0,
        "transfer_tax_checked": 0,
        "blacklist_checked": 0,
        "liquidity_sanity_checked": 0,
        "unsafe_rejected": 0,
        "risk_gate": "NOT_STARTED",
    }

    # Top cycles summary (up to 10 best by gross_bps).
    # Quoteable cycles (POSITIVE_GROSS / NEGATIVE_GROSS) are ranked first because
    # their gross_bps is meaningful. CYCLE_QUOTE_FAILED has gross_bps=0 which would
    # incorrectly sort above all NEGATIVE_GROSS cycles without the is_quoteable flag.
    def _top_cycle_sort_key(qr: CycleQuoteResult):
        is_quoteable = 1 if qr.status in ("POSITIVE_GROSS", "NEGATIVE_GROSS") else 0
        return (is_quoteable, qr.gross_bps)

    top_cycles = sorted(cycle_results, key=_top_cycle_sort_key, reverse=True)[:10]

    artifact: Dict[str, Any] = {
        "schema_family": SCHEMA_FAMILY,
        "schema_revision": SCHEMA_REVISION,
        "generated_at_utc": generated_at_utc,
        "freshness_s": round(elapsed_s, 1),
        "run_timestamp": run_timestamp,
        "requested_duration_minutes": duration_minutes,
        "elapsed_s": round(elapsed_s, 1),
        "sweeps_completed": sweeps_completed,
        "duration_fulfilled": elapsed_s >= duration_minutes * 60 * 0.9,
        "sizes_usd": list(sizes_usd),
        "gate_acceptance": gate_acceptance,
        "strategy_gate_acceptance": strategy_gate_acceptance,
        "execution_mode": execution_mode,
        "cycles_found": cycles_found,
        "cycles_positive_gross": cycles_positive_gross,
        "cycles_quoteable": cycles_quoteable,
        "cycles_router_sim_eligible": cycles_router_sim_eligible,
        "best_cycle_net_bps": best_cycle_net_bps,
        "qsr": round(qsr, 4),
        "quote_rpc_error_rate": quote_rpc_error_rate,
        "quote_revert_rate": quote_revert_rate,
        "provider_rpc_error_count": _provider_rpc_error_count,
        "provider_decode_error_count": _provider_decode_error_count,
        "cycle_reject_histogram": computed_cycle_histogram,
        "economics_gate_status": econ_status,
        "economics_blocker_class": economics_blocker_class,
        "economics_metrics": economics_metrics,
        "risk_metrics": risk_metrics,
        "route_error_histogram": computed_route_hist,
        "edge_error_histogram": computed_edge_hist,
        "scan_scope": scan_scope,
        "top_cycles": [_build_cycle_summary(qr) for qr in top_cycles],
        "top_opportunities": [_build_top_opportunity(qr) for qr in top_cycles],
        "graph_topology": graph_topology,
        "topology_gate": topology_gate,
        "gap_candidates_path": gap_candidates_path,
        "run_context": run_context,
    }
    # Funnel A counters and inventory reject taxonomy (optional)
    if funnel_a is not None:
        artifact["funnel_a"] = funnel_a
    if inventory_reject_histogram is not None:
        artifact["inventory_reject_histogram"] = inventory_reject_histogram

    # Infra telemetry block (quote infrastructure slice)
    infra_telemetry: Dict[str, Any] = {
        "quote_backend": quote_backend,
        "quote_workers": quote_workers,
        # RPC provider identity (no URL — avoids leaking keys)
        "rpc_provider": rpc_provider,
        "rpc_source": rpc_source,
        "rpc_public_fallback_used": rpc_public_fallback_used,
    }
    # Expose effective RPC rate-limiter settings (separate from provider_throttle budgets)
    try:
        from core.rpc_rate_limiter import rpc_throttle as _rt
        infra_telemetry["effective_rpc_rps_limit"] = _rt.rps
        infra_telemetry["effective_rpc_burst"] = _rt.burst
        infra_telemetry["actual_http_calls"] = _rt.stats()["total_acquired"]
    except Exception:
        infra_telemetry["effective_rpc_rps_limit"] = None
        infra_telemetry["effective_rpc_burst"] = None
        infra_telemetry["actual_http_calls"] = None
    if provider_throttle_snapshot is not None:
        # Derive top-level 429 count from "calls" bucket for quick access
        calls_snap = provider_throttle_snapshot.get("calls", {})
        _throttle_429_count = calls_snap.get("total_429", 0)
        infra_telemetry["blocked_by_breaker"] = calls_snap.get("total_blocked", 0)
        infra_telemetry["provider_throttle_rps_budget"] = calls_snap.get("rps_limit", None)
        infra_telemetry["provider_throttle_snapshot"] = provider_throttle_snapshot
    else:
        _throttle_429_count = 0
        infra_telemetry["blocked_by_breaker"] = 0
        infra_telemetry["provider_throttle_rps_budget"] = None
        infra_telemetry["provider_throttle_snapshot"] = None

    # Count 429s from leg_results.raw_error as fallback when throttle is disabled
    # (ARBY_PROVIDER_THROTTLE defaults to 0, so throttle snapshot is empty).
    # raw_http_probe sets raw_error="HTTP 429: ..." for HTTP 429 responses.
    _leg_429_count = sum(
        1
        for qr in cycle_results
        for leg in (qr.leg_results or [])
        if not leg.ok and leg.raw_error and "429" in leg.raw_error
    )
    # Use throttle count if it reported something; otherwise fall back to leg-derived count.
    if _throttle_429_count > 0:
        infra_telemetry["http_429_count"] = _throttle_429_count
        infra_telemetry["http_429_count_source"] = "provider_throttle"
    else:
        infra_telemetry["http_429_count"] = _leg_429_count
        infra_telemetry["http_429_count_source"] = "leg_results"

    # Normalized 429 counters (Fix 4): separate quote vs multicall channels.
    # raw_http_429_count  — 429s from direct quote RPC calls (leg_results)
    # multicall_429_count — 429s from multicall batch calls (prequote)
    # quote_429_count     — alias for raw_http_429_count (quote-path 429s only)
    _mc_429_count = multicall_stats.get("http_429", 0) if multicall_stats else 0
    infra_telemetry["raw_http_429_count"] = _leg_429_count
    infra_telemetry["multicall_429_count"] = _mc_429_count
    infra_telemetry["quote_429_count"] = _leg_429_count

    # HTTP error taxonomy counters (from leg_results.raw_error):
    # http_408_count  — request timeout (server-side flakiness)
    # http_500_count  — internal server error (RPC node overload)
    # http_5xx_count  — all 5xx server errors combined
    _leg_408_count = sum(
        1 for qr in cycle_results for leg in (qr.leg_results or [])
        if not leg.ok and (leg.raw_error or "").startswith("HTTP 408")
    )
    _leg_500_count = sum(
        1 for qr in cycle_results for leg in (qr.leg_results or [])
        if not leg.ok and (leg.raw_error or "").startswith("HTTP 500")
    )
    _leg_5xx_count = sum(
        1 for qr in cycle_results for leg in (qr.leg_results or [])
        if not leg.ok and (leg.raw_error or "").startswith("HTTP 5")
    )
    infra_telemetry["http_408_count"] = _leg_408_count
    infra_telemetry["http_500_count"] = _leg_500_count
    infra_telemetry["http_5xx_count"] = _leg_5xx_count

    # Absolute QUOTE_REVERT count from leg_results (complements quote_revert_rate above)
    # Re-use the already-computed count (no second iteration needed).
    _quote_revert_count = _leg_revert_count_early
    infra_telemetry["quote_revert_count"] = _quote_revert_count

    # Surface quote_revert_rate at infra level (convenience: avoids digging into diagnostics)
    infra_telemetry["quote_revert_rate"] = quote_revert_rate

    # Inventory purity: how many active_routes lacked factory_verified=True at scan start
    if unverified_active_routes is not None:
        infra_telemetry["unverified_active_routes"] = unverified_active_routes
    if ws_freshness is not None:
        infra_telemetry["ws_freshness"] = ws_freshness
    # Multicall snapshot counters
    if multicall_stats is not None:
        infra_telemetry["multicall_stats"] = multicall_stats
        # Derive success_rate for quick access
        _mc_attempted = multicall_stats.get("attempted", 0)
        if _mc_attempted > 0:
            infra_telemetry["multicall_success_rate"] = round(
                multicall_stats.get("success", 0) / _mc_attempted, 4
            )
        # Data completeness: fetched / requested (1.0 = no data lost via failed chunks)
        _mc_requested = multicall_stats.get("requested_total", 0)
        if _mc_requested > 0:
            infra_telemetry["data_completeness"] = round(
                multicall_stats.get("fetched_total", 0) / _mc_requested, 4
            )
        # Adaptive split counter (Steps 2+3 GPT fix)
        if multicall_stats.get("subchunk_splits", 0) > 0:
            infra_telemetry["multicall_subchunk_splits"] = multicall_stats["subchunk_splits"]
    # Prequote funnel skip metrics
    if prequote_cycles_skipped > 0:
        infra_telemetry["prequote_cycles_skipped"] = prequote_cycles_skipped
        # skip_ratio = skipped / (skipped + cycles actually quoted)
        _denom_prequote = max(prequote_cycles_skipped + cycles_found, 1)
        infra_telemetry["prequote_skip_ratio"] = round(
            prequote_cycles_skipped / _denom_prequote, 4
        )
    # Scheduler name
    if scheduler_name is not None:
        infra_telemetry["scheduler_name"] = scheduler_name
    _dynamic_results = [qr for qr in cycle_results if qr.dynamic_size_usd is not None]
    infra_telemetry["dynamic_size_enabled"] = bool(
        any(qr.size_candidates_usd for qr in cycle_results)
    )
    infra_telemetry["dynamic_size_selected_count"] = len(_dynamic_results)
    if _dynamic_results:
        infra_telemetry["dynamic_size_selection_rate"] = round(
            len(_dynamic_results) / max(len(cycle_results), 1), 4
        )
    # Verified inventory availability (Step 4 GPT fix)
    infra_telemetry["verified_inventory_exists"] = verified_inventory_exists
    # Source of sizes_usd (Fix 7): "config.scan_params" | "cli_default" | "cli_override"
    infra_telemetry["sizes_usd_source"] = sizes_usd_source
    # Prequote filter threshold used during this run (operator-visible)
    infra_telemetry["prequote_min_bps"] = prequote_min_bps
    # Per-endpoint provider router telemetry (Fix 2+3)
    if provider_router_snapshot is not None:
        infra_telemetry["provider_router_snapshot"] = provider_router_snapshot
    artifact["infra_telemetry"] = infra_telemetry

    # Runtime gates block (Step 6 GPT fix) — explicit pass/fail for each quality threshold
    _mc_rate = infra_telemetry.get("multicall_success_rate")
    _dc_val = infra_telemetry.get("data_completeness")
    _unverified = infra_telemetry.get("unverified_active_routes", 0) or 0
    _qsr_val = round(qsr, 4) if isinstance(qsr, float) else 0.0
    _revert_val = quote_revert_rate if isinstance(quote_revert_rate, float) else 0.0
    runtime_gates: Dict[str, Any] = {
        "multicall_success_rate": {
            "value": _mc_rate,
            "threshold": 0.9,
            "pass": bool(_mc_rate is not None and _mc_rate >= 0.9),
        },
        "data_completeness": {
            "value": _dc_val,
            "threshold": 0.98,
            "pass": bool(_dc_val is not None and _dc_val >= 0.98),
        },
        "unverified_active_routes": {
            "value": _unverified,
            "threshold": 0,
            "pass": _unverified == 0,
        },
        "qsr": {
            "value": _qsr_val,
            "threshold": 0.8,
            "pass": _qsr_val >= 0.8,
        },
        "quote_revert_rate": {
            "value": _revert_val,
            "threshold": 0.05,
            "pass": _revert_val < 0.05,
        },
    }
    runtime_gates["all_pass"] = all(
        v["pass"] for v in runtime_gates.values() if isinstance(v, dict) and "pass" in v
    )
    artifact["runtime_gates"] = runtime_gates

    return artifact


def write_artifact(artifact: Dict[str, Any], artifact_path: str = ROLLING_PATH) -> None:
    """Write artifact atomically to artifact_path (via .tmp rename)."""
    import time as _time

    path = os.path.abspath(artifact_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2)
    # On Windows, os.replace can raise PermissionError if antivirus scans
    # the .tmp file between write and rename.  Retry with backoff.
    for attempt in range(6):
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError:
            if attempt < 5:
                _time.sleep(0.5 * (attempt + 1))
            else:
                raise
