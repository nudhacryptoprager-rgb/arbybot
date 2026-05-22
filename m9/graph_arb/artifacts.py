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
      pool          — pool_address of first edge
      pool_path     — ordered list of pool addresses through cycle
      pair          — token path as "A/B/C"
      market_size_usd — quote size used (from sizes_usd[0])
      dynamic_size_usd — null (M9.5 router-sim will fill this)
      spread_bps    — gross_bps from quote
      spread_usd    — gross_bps * market_size_usd / 10000
      profit_usd    — gross_usd (gas model not yet implemented)
      main_blocker  — null when POSITIVE_GROSS, else reject_reason or status
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
    return {
        "dex": dexes[0] if len(dexes) == 1 else ",".join(dexes),
        "factory": factories[0] if len(factories) == 1 else ",".join(factories),
        "pool": cycle.edges[0].pool_address,
        "pool_path": pools,
        "pair": pair,
        "market_size_usd": qr.size_usd,
        "dynamic_size_usd": None,
        "spread_bps": spread_bps,
        "spread_usd": spread_usd,
        "profit_usd": profit_usd,
        "main_blocker": main_blocker,
    }


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
    quote_revert_rate = round(
        computed_cycle_histogram.get("QUOTE_REVERT", 0) / _denom, 6
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

    # Top cycles summary (up to 10 best by gross_bps)
    top_cycles = sorted(cycle_results, key=lambda qr: -qr.gross_bps)[:10]

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
    return artifact


def write_artifact(artifact: Dict[str, Any], artifact_path: str = ROLLING_PATH) -> None:
    """Write artifact atomically to artifact_path (via .tmp rename)."""
    path = os.path.abspath(artifact_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2)
    os.replace(tmp_path, path)
