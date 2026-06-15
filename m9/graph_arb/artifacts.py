"""Artifact builder and writer for M9 graph-arb scanner.

Schema revision: m9.1  (additive changes only — backward-compatible with rolling artifact).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from m9.graph_arb.models import CycleQuoteResult, GraphTopology
from m9.graph_arb.pool_scorecard import (
    build_pool_scorecards,
    recommend_quarantine,
)

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
_TOPO_FILTER_BLOCKED = "TOPOLOGY_FILTER_BLOCKED"

_REQUIRED_PRODUCTIVE_SCAN_SCOPE_KEYS = (
    "quarantine_exclusion_breakdown",
    "productive_admission_skip_histogram",
    "cycles_before_quarantine",
    "cycles_after_quarantine",
    "graph_build_metrics",
)


def validate_scan_scope_telemetry(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Return validation result for productive-lane scan-scope telemetry."""
    scope = artifact.get("scan_scope") or {}
    lane = scope.get("pool_quality_lane") or artifact.get("pool_quality_lane")
    if lane != "productive":
        return {"valid": True, "lane": lane, "missing": [], "blocker": None}
    missing = [k for k in _REQUIRED_PRODUCTIVE_SCAN_SCOPE_KEYS if k not in scope]
    return {
        "valid": not missing,
        "lane": lane,
        "missing": missing,
        "blocker": "NO_CYCLES_WITH_MISSING_SCAN_SCOPE_TELEMETRY" if missing else None,
    }

# Near-positive threshold for router-sim eligibility (bps below zero)
_ROUTER_SIM_BPS_FLOOR = -10.0

# Economics blocker class constants
_BLOCKER_NOT_RUN = "NOT_RUN"
_BLOCKER_NOT_BLOCKED = "NOT_BLOCKED"
_BLOCKER_PROVIDER_QUALITY = "PROVIDER_QUALITY_BLOCKED"
_BLOCKER_INVENTORY_ANCHOR = "INVENTORY_TOO_ANCHOR_HEAVY"
_BLOCKER_MARKET = "MARKET_NO_POSITIVE_GROSS"

# Infra / quote-quality status (distinct from economics verdict)
_INFRA_NOT_RUN = "NOT_RUN"
_INFRA_OK = "OK"
_INFRA_QUOTE_QUALITY_BLOCKED = "INFRA_OR_QUOTE_QUALITY_BLOCKED"

# M9 acceptance: QSR and data completeness gates (aligned with runtime_gates)
_QSR_ACCEPTANCE_THRESHOLD = 0.8
_DATA_COMPLETENESS_ACCEPTANCE_THRESHOLD = 0.98

# Pair count threshold: at or below this → anchor-heavy inventory
_ANCHOR_HEAVY_PAIR_THRESHOLD = 15

# Rolling artifacts are an operational interface, not an append-only debug log.
# Keep enough RCA detail for the active blocker while dropping long legacy tails.
_MAX_ROUTE_ERROR_HISTOGRAM_ROUTES = 40
_MAX_EDGE_ERROR_HISTOGRAM_EDGES = 40
_MAX_QUOTE_DIAGNOSTIC_TOP_ROUTES = 12


def compute_estimated_cost_bps(
    size_usd: float,
    gas_usd: float,
    l1_fee_usd: float,
    slippage_bps: float,
) -> Optional[float]:
    """Estimate total cost of a trade in basis points.

    Formula: (gas_usd + l1_fee_usd) / size_usd * 10_000 + slippage_bps

    For $100 size with gas_usd=0.05, l1_fee_usd=0.01, slippage_bps=5.0:
      (0.05 + 0.01) / 100 * 10_000 + 5.0 = 6.0 + 5.0 = 11.0 bps

    Returns None when size_usd <= 0 (defensive).
    """
    if size_usd <= 0:
        return None
    gas_cost_bps = (gas_usd + l1_fee_usd) / size_usd * 10_000.0
    return round(gas_cost_bps + slippage_bps, 4)


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_cycle_origin(
    cycle: "ArbitrageCycle",
    m8_pool_addrs: "Optional[frozenset[str]]",
) -> "Optional[str]":
    """Return 'm8' when any cycle edge uses an M8-sourced pool, else 'base'.

    Returns None when m8_pool_addrs is not provided (bridge metrics unavailable).
    Distinguishing 'base' from 'm8' is the key RCA signal for
    positive_cycles_with_m8_pool diagnostics.
    """
    if m8_pool_addrs is None:
        return None
    for e in cycle.edges:
        if e.pool_address.lower() in m8_pool_addrs:
            return "m8"
    return "base"


def _build_cycle_summary(
    qr: "CycleQuoteResult",
    m8_pool_addrs: "Optional[frozenset[str]]" = None,
    cost_profile: "Optional[Dict[str, Any]]" = None,
    route_meta_by_pool: "Optional[Dict[str, Dict[str, Any]]]" = None,
) -> Dict[str, Any]:
    cycle = qr.cycle
    # Per-cycle cost estimate (when cost_profile is available)
    _est_cost_cycle: Optional[float] = None
    _cost_adj_net_cycle: Optional[float] = None
    if cost_profile and qr.size_usd and qr.size_usd > 0:
        _est_cost_cycle = compute_estimated_cost_bps(
            size_usd=qr.size_usd,
            gas_usd=cost_profile.get("gas_usd", 0.05),
            l1_fee_usd=cost_profile.get("l1_fee_usd", 0.01),
            slippage_bps=cost_profile.get("slippage_bps", 5.0),
        )
        if _est_cost_cycle is not None:
            _cost_adj_net_cycle = round(qr.gross_bps - _est_cost_cycle, 4)
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
        "cycle_origin": _compute_cycle_origin(cycle, m8_pool_addrs),
        "estimated_cost_bps": _est_cost_cycle,
        "cost_adjusted_net_bps": _cost_adj_net_cycle,
        "legs": _build_per_leg_rca(qr, route_meta_by_pool),
    }


def _build_top_opportunity(
    qr: CycleQuoteResult,
    cost_profile: "Optional[Dict[str, Any]]" = None,
    route_meta_by_pool: "Optional[Dict[str, Dict[str, Any]]]" = None,
) -> Dict[str, Any]:
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
      estimated_cost_bps — gas+slippage cost estimate in bps (null if no cost profile)
      cost_adjusted_net_bps — spread_bps - estimated_cost_bps (null if no cost profile)
      cost_adjusted_profit_usd — cost_adjusted_net_bps * size_usd / 10000 (null if no cost profile)
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
    # Cost-aware fields for operator dashboard (step 3)
    _est_cost_opp: Optional[float] = None
    _cost_adj_net_opp: Optional[float] = None
    _cost_adj_profit_opp: Optional[float] = None
    if cost_profile and qr.size_usd and qr.size_usd > 0:
        _est_cost_opp = compute_estimated_cost_bps(
            size_usd=qr.size_usd,
            gas_usd=cost_profile.get("gas_usd", 0.05),
            l1_fee_usd=cost_profile.get("l1_fee_usd", 0.01),
            slippage_bps=cost_profile.get("slippage_bps", 5.0),
        )
        if _est_cost_opp is not None:
            _cost_adj_net_opp = round(spread_bps - _est_cost_opp, 4)
            _cost_adj_profit_opp = round(_cost_adj_net_opp * qr.size_usd / 10000.0, 6)
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

    from m9.graph_arb.depth_telemetry import opportunity_depth_fields

    _depth_fields = opportunity_depth_fields(qr, route_meta_by_pool)
    return {
        "cycle_id": cycle.cycle_id,
        "status": qr.status,
        "reject_reason": qr.reject_reason,
        **_depth_fields,
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
        "estimated_cost_bps": _est_cost_opp,
        "cost_adjusted_net_bps": _cost_adj_net_opp,
        "cost_adjusted_profit_usd": _cost_adj_profit_opp,
        "main_blocker": main_blocker,
        "fee_drag_bps": fee_drag_bps,
        "pre_fee_gross_bps": pre_fee_gross_bps,
        "loss_reason": loss_reason,
        "legs": _build_per_leg_rca(qr, route_meta_by_pool),
    }


_STABLE_PEG_SYMBOLS = frozenset(
    {"USDC", "USDT", "DAI", "USDbC", "EURC", "crvUSD", "USDBC", "FRAX", "LUSD"}
)
_STABLE_VALUE_RATIO_OUTLIER_MIN = 0.5
_STABLE_VALUE_RATIO_OUTLIER_MAX = 2.0


def _is_stable_peg_symbol(sym: str) -> bool:
    return (sym or "").strip().upper() in _STABLE_PEG_SYMBOLS


def _stable_value_ratio_outlier(
    token_in: str,
    token_out: str,
    norm_ratio: Optional[float],
) -> bool:
    """Flag stable-stable legs with implausible 1:1 value transfer."""
    if norm_ratio is None:
        return False
    if not (_is_stable_peg_symbol(token_in) and _is_stable_peg_symbol(token_out)):
        return False
    return (
        norm_ratio < _STABLE_VALUE_RATIO_OUTLIER_MIN
        or norm_ratio > _STABLE_VALUE_RATIO_OUTLIER_MAX
    )


def _build_per_leg_rca(
    qr: CycleQuoteResult,
    route_meta_by_pool: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build per-leg RCA list: normalized in/out amounts, implied price, pool, dex, fee."""
    cycle = qr.cycle
    result: List[Dict[str, Any]] = []
    prev_raw_out: Optional[int] = None
    for i, edge in enumerate(cycle.edges):
        pool_lc = str(edge.pool_address or "").lower()
        inv_row = (route_meta_by_pool or {}).get(pool_lc) or {}
        leg_data: Dict[str, Any] = {
            "leg_idx": i,
            "token_in": edge.token_in_sym,
            "token_out": edge.token_out_sym,
            "pool_address": edge.pool_address,
            "dex_id": edge.dex_id,
            "adapter_type": edge.adapter_type,
            "fee_bps": round(edge.fee_bps, 4),
            "factory_verified": edge.factory_verified,
            "effective_depth_usd": edge.effective_depth_usd or inv_row.get(
                "effective_depth_usd"
            ),
            "productive_quote_status": inv_row.get("productive_quote_status"),
            "balancer_assets_present": bool(
                edge.balancer_assets or inv_row.get("balancer_assets")
            ),
            "pool_id": edge.pool_id or inv_row.get("pool_id"),
            "token_in_addr": edge.token_in_addr,
            "token_out_addr": edge.token_out_addr,
            "pool_lane_probe_amount": (
                edge.maverick_pool_lane_probe_amount
                or inv_row.get("maverick_pool_lane_probe_amount")
            ),
            "token_a_in_probe": (
                edge.maverick_token_a_in_probe
                if edge.maverick_token_a_in_probe is not None
                else inv_row.get("maverick_token_a_in_probe")
            ),
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
            if i > 0:
                leg_data["prev_leg_out_raw"] = prev_raw_out
                leg_data["current_leg_in_raw"] = raw_in
                if prev_raw_out is not None and raw_in is not None:
                    leg_data["amount_continuity_ok"] = int(raw_in) == int(prev_raw_out)
                else:
                    leg_data["amount_continuity_ok"] = None
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
                    from m9.graph_arb.cycle_sanity import (
                        MIN_STABLE_SANITY_NORM_IN_USD,
                        stable_value_ratio_outlier,
                    )

                    if norm_in >= MIN_STABLE_SANITY_NORM_IN_USD and stable_value_ratio_outlier(
                        edge, leg_result
                    ):
                        leg_data["stable_value_ratio_outlier"] = True
                        leg_data["sanity_gate"] = "STABLE_VALUE_RATIO_OUTLIER"
        if leg_result is not None and getattr(leg_result, "amount_out", None) is not None:
            prev_raw_out = int(leg_result.amount_out)
        result.append(leg_data)
    return result


def _compute_cycle_reject_histogram(cycle_results: List[CycleQuoteResult]) -> Dict[str, int]:
    """Count cycle outcomes by reject_reason or status."""
    histogram: Dict[str, int] = {}
    for qr in cycle_results:
        key = qr.reject_reason if qr.reject_reason else qr.status
        histogram[key] = histogram.get(key, 0) + 1
    return histogram


def _compute_toxic_pool_families(
    cycle_results: List[CycleQuoteResult],
) -> List[Dict[str, Any]]:
    """Aggregate top toxic pool families from TOXIC_ROUTE_PRICE_IMPACT cycles (Step 7).

    A pool is considered toxic when it appears in any cycle whose effective
    pre-fee gross (``raw_gross_bps`` when the cycle was depth-zeroed, else
    ``gross_bps``) is ``< -500`` (catastrophic price impact). Using the
    pre-zeroing value ensures OVERSIZED_VS_DEPTH cycles — whose ``gross_bps`` is
    reset to 0 — are still attributed to the pools that caused them.

    Returns a list of pool-level dicts sorted by cycle_count descending (top 20).
    Each entry contains: pool_address, pair_id, dex_id, fee_bps, cycle_count,
    min_gross_bps, max_gross_bps.
    """
    pool_stats: Dict[str, Dict[str, Any]] = {}
    for qr in cycle_results:
        fee_drag = qr.cycle.total_fee_bps
        # OVERSIZED_VS_DEPTH and phantom cycles zero out gross_bps and stash the
        # real (extreme) spread in raw_gross_bps. Use that pre-zeroing value so the
        # catastrophic-impact filter actually sees them — otherwise the dominant
        # depth-toxic pools are invisible in toxic_pool_families (the metric the
        # operator relies on to identify pools poisoning every cycle).
        effective_gross = qr.raw_gross_bps if isinstance(qr.raw_gross_bps, (int, float)) else qr.gross_bps
        pfgb = effective_gross + fee_drag
        if pfgb >= -500:
            continue  # not a toxic-impact cycle
        for edge in qr.cycle.edges:
            key = edge.pool_address.lower()
            if key not in pool_stats:
                pool_stats[key] = {
                    "pool_address": edge.pool_address,
                    "pair_id": edge.pair_id,
                    "dex_id": edge.dex_id,
                    "fee_bps": round(edge.fee_bps, 4),
                    "cycle_count": 0,
                    "min_gross_bps": None,
                    "max_gross_bps": None,
                }
            stats = pool_stats[key]
            stats["cycle_count"] += 1
            if stats["min_gross_bps"] is None or effective_gross < stats["min_gross_bps"]:
                stats["min_gross_bps"] = round(effective_gross, 4)
            if stats["max_gross_bps"] is None or effective_gross > stats["max_gross_bps"]:
                stats["max_gross_bps"] = round(effective_gross, 4)
    result = sorted(pool_stats.values(), key=lambda x: -x["cycle_count"])
    return result[:20]  # top 20 toxic pool families


def _http_status_from_raw_error(raw_error: Optional[str]) -> Optional[int]:
    if not raw_error:
        return None
    match = re.search(r"\bHTTP\s+(\d{3})\b", raw_error)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    if raw_error == "provider_throttle_cooldown":
        return 429
    return None


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


def _route_error_count(errors: Any) -> int:
    if isinstance(errors, dict):
        return sum(v for v in errors.values() if isinstance(v, int))
    return 0


def _trim_route_error_histogram(
    histogram: Dict[str, Dict[str, int]],
    *,
    limit: int = _MAX_ROUTE_ERROR_HISTOGRAM_ROUTES,
) -> tuple[Dict[str, Dict[str, int]], Dict[str, int]]:
    """Keep top route-error offenders and expose explicit trim metadata."""
    if not isinstance(histogram, dict):
        return histogram, {"total": 0, "kept": 0, "dropped": 0}
    total = len(histogram)
    if total <= limit:
        return histogram, {"total": total, "kept": total, "dropped": 0}
    items = sorted(
        histogram.items(),
        key=lambda kv: (-_route_error_count(kv[1]), kv[0]),
    )
    kept = dict(items[:limit])
    return kept, {"total": total, "kept": len(kept), "dropped": total - len(kept)}


def _compute_quote_failure_diagnostics(
    cycle_results: List[CycleQuoteResult],
    *,
    top_n: int = _MAX_QUOTE_DIAGNOSTIC_TOP_ROUTES,
) -> Dict[str, Any]:
    """Leg-level quote failure RCA: reject reasons, HTTP status, top routes/edges.

    Helps separate RPC overload (429/cooldown) from adapter/config bugs (decode/revert).
    """
    by_reject: Dict[str, int] = {}
    by_http_status: Dict[str, int] = {}
    route_agg: Dict[str, Dict[str, Any]] = {}

    for qr in cycle_results:
        edges = qr.cycle.edges
        for i, leg in enumerate(qr.leg_results or []):
            if leg.ok or not leg.reject_reason:
                continue
            by_reject[leg.reject_reason] = by_reject.get(leg.reject_reason, 0) + 1
            http_status = _http_status_from_raw_error(leg.raw_error)
            if http_status is not None:
                key = str(http_status)
                by_http_status[key] = by_http_status.get(key, 0) + 1
            elif leg.raw_error:
                by_http_status["other"] = by_http_status.get("other", 0) + 1

            edge = edges[i] if i < len(edges) else None
            rid = leg.route_id
            entry = route_agg.setdefault(
                rid,
                {
                    "route_id": rid,
                    "pair_id": edge.pair_id if edge else None,
                    "dex_id": edge.dex_id if edge else None,
                    "adapter_type": edge.adapter_type if edge else None,
                    "pool_address": edge.pool_address if edge else None,
                    "errors": {},
                    "sample_raw_error": None,
                },
            )
            entry["errors"][leg.reject_reason] = entry["errors"].get(leg.reject_reason, 0) + 1
            if entry["sample_raw_error"] is None and leg.raw_error:
                entry["sample_raw_error"] = str(leg.raw_error)[:200]
            if entry.get("http_status") is None and http_status is not None:
                entry["http_status"] = http_status

    top_routes = sorted(
        route_agg.values(),
        key=lambda x: -sum(x["errors"].values()),
    )[:top_n]
    for row in top_routes:
        row["error_count"] = sum(row["errors"].values())

    top_edges = _compute_edge_error_histogram(cycle_results)[:top_n]

    return {
        "leg_failures_total": sum(by_reject.values()),
        "by_reject_reason": by_reject,
        "by_http_status": by_http_status,
        "top_routes": top_routes,
        "top_edges": top_edges,
    }


_PHANTOM_REJECT = "PHANTOM_QUOTE_BPS_OVERFLOW"
_MAX_PHANTOM_DIAGNOSTIC_TOP = 20


def _compute_phantom_quote_diagnostics(
    cycle_results: List[CycleQuoteResult],
    *,
    top_n: int = _MAX_PHANTOM_DIAGNOSTIC_TOP,
) -> Dict[str, Any]:
    """Cycle-level RCA for depth-aware phantom rejects (not RPC/provider failures)."""
    total = len(cycle_results)
    phantoms = [qr for qr in cycle_results if qr.reject_reason == _PHANTOM_REJECT]
    phantom_count = len(phantoms)
    depth_unknown = 0
    pool_agg: Dict[str, Dict[str, Any]] = {}
    route_agg: Dict[str, Dict[str, Any]] = {}
    samples: List[Dict[str, Any]] = []

    for qr in phantoms:
        depth = (
            qr.cycle_min_depth_usd
            if qr.cycle_min_depth_usd is not None
            else qr.cycle.min_effective_depth_usd
        )
        if depth is None or depth <= 0:
            depth_unknown += 1
        raw = qr.raw_gross_bps if qr.raw_gross_bps is not None else qr.gross_bps
        ceiling = qr.phantom_ceiling_bps
        overflow_bps = (
            round(abs(raw) - ceiling, 4)
            if raw is not None and ceiling is not None
            else None
        )
        for edge in qr.cycle.edges:
            pool_key = edge.pool_address.lower()
            pool_row = pool_agg.setdefault(
                pool_key,
                {
                    "pool_address": edge.pool_address,
                    "pair_id": edge.pair_id,
                    "dex_id": edge.dex_id,
                    "adapter_type": edge.adapter_type,
                    "phantom_count": 0,
                },
            )
            pool_row["phantom_count"] += 1
            rid = edge.route_id
            route_row = route_agg.setdefault(
                rid,
                {
                    "route_id": rid,
                    "pair_id": edge.pair_id,
                    "pool_address": edge.pool_address,
                    "adapter_type": edge.adapter_type,
                    "phantom_count": 0,
                },
            )
            route_row["phantom_count"] += 1
        if len(samples) < top_n:
            samples.append(
                {
                    "cycle_id": qr.cycle.cycle_id,
                    "pair_path": [e.pair_id for e in qr.cycle.edges],
                    "raw_gross_bps": raw,
                    "phantom_ceiling_bps": ceiling,
                    "overflow_bps": overflow_bps,
                    "cycle_min_depth_usd": depth,
                    "size_usd": qr.size_usd,
                }
            )

    top_pools = sorted(pool_agg.values(), key=lambda x: -x["phantom_count"])[:top_n]
    top_routes = sorted(route_agg.values(), key=lambda x: -x["phantom_count"])[:top_n]

    return {
        "blocker_class_hint": "PHANTOM_VALIDATION",
        "economics_interpretation": (
            "Phantom overflow is a quote-validation blocker, not PROVIDER_QUALITY or MARKET."
        ),
        "phantom_count": phantom_count,
        "phantom_rate": round(phantom_count / max(total, 1), 6),
        "cycles_total": total,
        "depth_unknown_count": depth_unknown,
        "depth_unknown_rate": round(depth_unknown / max(phantom_count, 1), 6),
        "top_pools": top_pools,
        "top_routes": top_routes,
        "sample_overflows": samples,
    }


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


def _compute_layer_telemetry(
    cycle_results: List[CycleQuoteResult],
    *,
    qsr: float,
    provider_router_snapshot: Optional[Dict[str, Any]] = None,
    ws_freshness: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Per-layer QSR breakdown for unified data-driven pipeline."""
    from collections import Counter

    def _is_success(status: str) -> bool:
        return status not in ("QUOTE_FAILED", "CYCLE_QUOTE_TIMEOUT", "ZERO_AMOUNT_IN")

    quoted = [
        qr for qr in cycle_results
        if qr.status not in (
            "ZERO_AMOUNT_IN",
            "OVERSIZED_VS_DEPTH",
            "OVERSIZED_VS_MEASURED_DEPTH",
            "OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK",
            "DEPTH_BELOW_LIVENESS_FLOOR",
        )
    ]
    by_adapter: Counter[str] = Counter()
    ok_adapter: Counter[str] = Counter()
    by_length: Counter[int] = Counter()
    ok_length: Counter[int] = Counter()
    for qr in quoted:
        adapters = {e.adapter_type for e in qr.cycle.edges}
        fam = next(iter(adapters)) if len(adapters) == 1 else "mixed"
        by_adapter[fam] += 1
        if _is_success(qr.status):
            ok_adapter[fam] += 1
        ln = len(qr.cycle.edges)
        by_length[ln] += 1
        if _is_success(qr.status):
            ok_length[ln] += 1

    qsr_by_adapter = {
        k: round(ok_adapter[k] / by_adapter[k], 4) if by_adapter[k] else 0.0
        for k in by_adapter
    }
    qsr_by_cycle_length = {
        str(k): round(ok_length[k] / by_length[k], 4) if by_length[k] else 0.0
        for k in sorted(by_length)
    }
    cycles_by_length = {str(k): by_length[k] for k in sorted(by_length)}

    out: Dict[str, Any] = {
        "qsr_by_adapter": qsr_by_adapter,
        "qsr_by_cycle_length": qsr_by_cycle_length,
        "cycles_by_length": cycles_by_length,
    }

    if provider_router_snapshot:
        out["qsr_by_provider"] = {
            "primary": provider_router_snapshot.get("primary_netloc"),
            "secondary_active": provider_router_snapshot.get("using_secondary"),
            "failover_count": provider_router_snapshot.get("failover_count", 0),
        }
        out["provider_failover_count"] = int(
            provider_router_snapshot.get("failover_count", 0) or 0
        )
    else:
        out["qsr_by_provider"] = None
        out["provider_failover_count"] = 0

    if ws_freshness:
        out["ws_event_freshness_s"] = ws_freshness.get("age_s") or ws_freshness.get(
            "freshness_s"
        )

    depth_capped = sum(1 for qr in cycle_results if getattr(qr, "depth_capped", False))
    out["depth_capped_count"] = depth_capped
    out["global_qsr"] = round(qsr, 4)
    return out


def _unique_cycle_counts_by_length(
    cycle_results: List[CycleQuoteResult],
    *,
    quoteable_only: bool = False,
) -> Dict[str, int]:
    """Count distinct cycle_ids per edge-length (not per quote attempt)."""
    by_len: Dict[int, Set[str]] = defaultdict(set)
    for qr in cycle_results:
        if quoteable_only and qr.status not in ("POSITIVE_GROSS", "NEGATIVE_GROSS"):
            continue
        by_len[len(qr.cycle.edges)].add(qr.cycle.cycle_id)
    return {str(k): len(v) for k, v in sorted(by_len.items())}


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
    # Operator intent for dynamic sizing (CLI --dynamic-sizes / config), independent
    # of whether any cycle survived prequote to actually exercise dynamic sizing.
    dynamic_sizes_intent: bool = False,
    # Pool-quality gate lane: 'discovery' or 'productive' (Steps 2+3)
    pool_quality_lane: str = "discovery",
    # Discovery-lane cycle count when productive lane filters graph to zero cycles
    discovery_cycles_found: Optional[int] = None,
    # Count of pools excluded by productive lane depth/quarantine filter
    depth_quarantine_skipped: int = 0,
    # Count of pools excluded via revert-quarantine feedback from previous run
    revert_quarantine_skipped: int = 0,
    phantom_quarantine_skipped: int = 0,
    diagnostic_quarantine_skipped: int = 0,
    quarantine_exclusion_breakdown: Optional[Dict[str, Any]] = None,
    diagnostic_quarantine_mode: Optional[str] = None,
    diagnostic_admission_mode: Optional[str] = None,
    cycles_before_quarantine: Optional[int] = None,
    cycles_after_quarantine: Optional[int] = None,
    graph_build_admission_histogram: Optional[Dict[str, int]] = None,
    graph_build_metrics: Optional[Dict[str, Any]] = None,
    # M8→M9 bridge provenance block (bridge_builder.build_bridge_inventory output)
    bridge_source_metrics: Optional[Dict[str, Any]] = None,
    route_meta_by_pool: Optional[Dict[str, Dict[str, Any]]] = None,
    # M8 pool address set for cycle origin annotation in top_cycles (step 9 RCA)
    m8_pool_addrs_for_annotation: "Optional[frozenset[str]]" = None,
    # Cost model from config (cost_model.profiles.default); enables estimated_cost_bps
    cost_model: Optional[Dict[str, Any]] = None,
    # Step 4 (GPT session-14): Per-sweep active RPC netloc (sweep-number → masked label).
    # Filled by runner after each sweep; allows tracing which endpoint served each sweep.
    active_rpc_by_sweep: "Optional[Dict[int, str]]" = None,
    spread_lifetime_block: "Optional[Dict[str, Any]]" = None,
    # Cycle topology config + discovery reference (graph-handoff RCA)
    cycle_lengths_used: "Optional[Tuple[int, ...]]" = None,
    discovery_cycles_by_length: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Build the canonical M9 rolling artifact dict.

    ``cycles_found_topology`` lets callers (e.g. dry-run mode) report how many
    cycles the topology analysis found even when ``cycle_results`` is empty.
    When provided it overrides ``len(cycle_results)`` for the ``cycles_found`` field.
    """
    generated_at_utc = _iso_now()

    # When dry-run skipped quoting, use explicit topology count
    cycles_found = cycles_found_topology if cycles_found_topology is not None else len(cycle_results)
    def _counts_as_positive_evidence(qr: CycleQuoteResult) -> bool:
        if qr.gross_bps <= 0:
            return False
        try:
            from monitoring.sniper_honeypot import positive_gross_counts_as_evidence

            anchors = frozenset({"USDC", "USDBC", "USDbC", "DAI", "WETH", "ETH"})
            exotic_addrs = [
                e.token_in_addr.lower()
                for e in qr.cycle.edges
                if e.token_in_sym.upper() not in anchors and e.token_in_addr
            ] + [
                e.token_out_addr.lower()
                for e in qr.cycle.edges
                if e.token_out_sym.upper() not in anchors and e.token_out_addr
            ]
            return positive_gross_counts_as_evidence(
                list(dict.fromkeys(exotic_addrs)),
                strict=True,
            )
        except Exception:
            return qr.gross_bps > 0

    cycles_positive_gross_quote = sum(
        1 for qr in cycle_results if qr.status == "POSITIVE_GROSS"
    )
    cycles_positive_gross_raw = sum(
        1 for qr in cycle_results if _counts_as_positive_evidence(qr)
    )
    cycles_positive_gross = cycles_positive_gross_raw
    _economics_claim_suppressed = diagnostic_admission_mode == "topology_probe"
    if _economics_claim_suppressed:
        cycles_positive_gross = 0

    # Extract cost profile once — used for router-sim eligibility, per-cycle summaries,
    # and the top-level estimated_cost_bps field.
    _cost_profile_for_compute: Optional[Dict[str, Any]] = None
    if cost_model:
        _profile_name = cost_model.get("default_profile", "default")
        _cost_profile_for_compute = (cost_model.get("profiles") or {}).get(_profile_name) or {}

    # Cost-aware helper: returns cost-adjusted net bps when cost profile is available,
    # else returns raw gross_bps for backward-compatible floor comparisons.
    def _cycle_net_bps_for_gate(qr_x: "CycleQuoteResult") -> float:
        if _cost_profile_for_compute and qr_x.size_usd and qr_x.size_usd > 0:
            _ec = compute_estimated_cost_bps(
                size_usd=qr_x.size_usd,
                gas_usd=_cost_profile_for_compute.get("gas_usd", 0.05),
                l1_fee_usd=_cost_profile_for_compute.get("l1_fee_usd", 0.01),
                slippage_bps=_cost_profile_for_compute.get("slippage_bps", 5.0),
            )
            if _ec is not None:
                return qr_x.gross_bps - _ec
        return qr_x.gross_bps

    # Near-positive cycles worth router-sim probing (within floor of breakeven).
    # Step 8 (cost-aware): use cost-adjusted net when cost model present.
    cycles_router_sim_eligible = sum(
        1 for qr in cycle_results
        if qr.status in ("POSITIVE_GROSS", "NEGATIVE_GROSS")
        and _cycle_net_bps_for_gate(qr) > _ROUTER_SIM_BPS_FLOOR
    )

    # Step 4 (GPT fix): explicit gross/net distinction.
    # best_cycle_gross_bps = raw quote bps, no gas/slippage/router simulation.
    # best_cycle_net_bps   = alias kept for backward compat; equals gross until router_sim exists.
    # estimated_cost_bps   = gas + router fee estimate (null until cost model implemented).
    # router_sim_net_bps   = true execution net bps (null until router simulation enabled).
    best_cycle_gross_bps: Optional[float] = None
    if cycle_results:
        best = max(cycle_results, key=lambda qr: qr.gross_bps)
        best_cycle_gross_bps = round(best.gross_bps, 4)
    best_cycle_net_bps = best_cycle_gross_bps  # alias — gross only until router_sim
    # Step 4 (GPT round-3): explicit cost-adjusted best cycle metric.
    # Distinct from best_cycle_net_bps (which is gross alias) — so operator cannot
    # mistake gross for true net.
    best_cycle_cost_adjusted_net_bps: Optional[float] = None
    if _cost_profile_for_compute and cycle_results:
        _best_for_cadj = max(cycle_results, key=lambda qr: qr.gross_bps)
        _cadj_cost = compute_estimated_cost_bps(
            size_usd=_best_for_cadj.size_usd or (sizes_usd[0] if sizes_usd else 100.0),
            gas_usd=_cost_profile_for_compute.get("gas_usd", 0.05),
            l1_fee_usd=_cost_profile_for_compute.get("l1_fee_usd", 0.01),
            slippage_bps=_cost_profile_for_compute.get("slippage_bps", 5.0),
        )
        if _cadj_cost is not None and best_cycle_gross_bps is not None:
            best_cycle_cost_adjusted_net_bps = round(best_cycle_gross_bps - _cadj_cost, 4)
    # Compute estimated_cost_bps using best cycle's size and cost model from config
    estimated_cost_bps: Optional[float] = None
    if _cost_profile_for_compute and cycle_results:
        _best_for_cost = max(cycle_results, key=lambda qr: qr.gross_bps)
        _best_size_for_cost = (
            _best_for_cost.size_usd
            if _best_for_cost.size_usd and _best_for_cost.size_usd > 0
            else (sizes_usd[0] if sizes_usd else 100.0)
        )
        estimated_cost_bps = compute_estimated_cost_bps(
            size_usd=_best_size_for_cost,
            gas_usd=_cost_profile_for_compute.get("gas_usd", 0.05),
            l1_fee_usd=_cost_profile_for_compute.get("l1_fee_usd", 0.01),
            slippage_bps=_cost_profile_for_compute.get("slippage_bps", 5.0),
        )
    cost_adjusted_net_bps: Optional[float] = None
    if estimated_cost_bps is not None and best_cycle_gross_bps is not None:
        cost_adjusted_net_bps = round(best_cycle_gross_bps - estimated_cost_bps, 4)
    router_sim_net_bps: Optional[float] = None  # TODO: on-chain router simulation

    # Step 6 (GPT fix): positive-cycle repeatability counters.
    # Counts how many distinct cycle_ids were POSITIVE_GROSS in ≥2 independent quotes
    # (sweeps), indicating market-signal stability vs one-off noise.
    from collections import Counter as _Counter
    _positive_repeat_counts = _Counter(
        qr.cycle.cycle_id
        for qr in cycle_results
        if qr.gross_bps > 0
    )
    positive_cycle_multi_hit_count = sum(1 for v in _positive_repeat_counts.values() if v >= 2)
    positive_cycle_max_repeat = max(_positive_repeat_counts.values(), default=0)

    def _qsr_for_subset(results: List[CycleQuoteResult]) -> float:
        quoted_sub = [
            qr for qr in results
            if qr.status not in (
            "ZERO_AMOUNT_IN",
            "OVERSIZED_VS_DEPTH",
            "OVERSIZED_VS_MEASURED_DEPTH",
            "OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK",
            "DEPTH_BELOW_LIVENESS_FLOOR",
        )
        ]
        if not quoted_sub:
            return 0.0
        return (
            sum(1 for qr in quoted_sub if qr.status not in ("QUOTE_FAILED", "CYCLE_QUOTE_TIMEOUT"))
            / len(quoted_sub)
        )

    # QSR: quote success rate. Exclude ZERO_AMOUNT_IN (not a quoting attempt)
    # and OVERSIZED_VS_DEPTH (P0a: a real but extreme quote whose notional
    # overwhelms the bottleneck pool depth; neither a quote failure nor a market
    # signal, so it must not deflate QSR).
    quoted = [
        qr for qr in cycle_results
        if qr.status not in (
            "ZERO_AMOUNT_IN",
            "OVERSIZED_VS_DEPTH",
            "OVERSIZED_VS_MEASURED_DEPTH",
            "OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK",
            "DEPTH_BELOW_LIVENESS_FLOOR",
        )
    ]
    qsr = _qsr_for_subset(cycle_results)

    from m9.graph_arb.size_truth import (
        LIVENESS_MAX_SIZE_USD,
        economic_size_floor_usd,
        is_econ_size,
        is_liveness_size,
    )

    _cp = _cost_profile_for_compute or {}
    _econ_floor_usd = economic_size_floor_usd(
        gas_usd=float(_cp.get("gas_usd", 0.05)),
        l1_fee_usd=float(_cp.get("l1_fee_usd", 0.01)),
        slippage_bps=float(_cp.get("slippage_bps", 5.0)),
    )
    _liveness_results = [qr for qr in cycle_results if is_liveness_size(qr.size_usd)]
    _econ_results = [qr for qr in cycle_results if is_econ_size(qr.size_usd, _econ_floor_usd)]
    qsr_liveness = _qsr_for_subset(_liveness_results)
    qsr_econ = _qsr_for_subset(_econ_results)
    oversized_vs_depth_count = sum(
        1
        for qr in cycle_results
        if qr.status
        in (
            "OVERSIZED_VS_DEPTH",
            "OVERSIZED_VS_MEASURED_DEPTH",
            "OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK",
        )
    )
    oversized_vs_measured_depth_count = sum(
        1 for qr in cycle_results if qr.status == "OVERSIZED_VS_MEASURED_DEPTH"
    )
    oversized_vs_unknown_depth_fallback_count = sum(
        1 for qr in cycle_results if qr.status == "OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK"
    )

    # Economics gate (applies only when we have actual quote results)
    if cycles_found == 0:
        econ_status = _ECON_BLOCKED_NO_CYCLES
    elif cycle_results and qsr < _QSR_ACCEPTANCE_THRESHOLD:
        econ_status = _ECON_BLOCKED_QSR
    elif cycles_positive_gross == 0:
        econ_status = _ECON_BLOCKED_NO_POSITIVE_GROSS
    elif best_cycle_net_bps is not None and 0 < best_cycle_net_bps < 5:
        econ_status = _ECON_NEAR_MISS
    else:
        econ_status = _ECON_PASS

    gate_acceptance = econ_status == _ECON_PASS

    _bridge_depth_kr = (
        (bridge_source_metrics or {}).get("depth_known_rate")
        if bridge_source_metrics
        else None
    )
    _economics_blocked_depth = False
    if _bridge_depth_kr is not None:
        from m9.graph_arb.depth_telemetry import economics_blocked_by_depth_telemetry

        _economics_blocked_depth = economics_blocked_by_depth_telemetry(float(_bridge_depth_kr))
        if _economics_blocked_depth and econ_status == _ECON_PASS:
            econ_status = "BLOCKED_DEPTH_TELEMETRY_MISSING"

    # Topology gate
    if cycles_found > 0:
        topology_gate = _TOPO_CYCLES_FOUND
    elif (
        discovery_cycles_found is not None
        and discovery_cycles_found > 0
        and pool_quality_lane == "productive"
    ):
        topology_gate = _TOPO_FILTER_BLOCKED
    else:
        topology_gate = _TOPO_NO_CYCLES

    # Histograms: compute from cycle_results if not provided externally
    computed_cycle_histogram = _compute_cycle_reject_histogram(cycle_results)
    computed_route_hist_full = (
        route_error_histogram
        if route_error_histogram is not None
        else _compute_route_error_histogram(cycle_results)
    )
    computed_edge_hist_full = (
        edge_error_histogram
        if edge_error_histogram is not None
        else _compute_edge_error_histogram(cycle_results)
    )
    quote_failure_diagnostics = _compute_quote_failure_diagnostics(cycle_results)
    phantom_quote_diagnostics = _compute_phantom_quote_diagnostics(cycle_results)
    computed_route_hist, _route_hist_trim = _trim_route_error_histogram(computed_route_hist_full)
    _edge_hist_total = len(computed_edge_hist_full) if isinstance(computed_edge_hist_full, list) else 0
    computed_edge_hist = (
        computed_edge_hist_full[:_MAX_EDGE_ERROR_HISTOGRAM_EDGES]
        if isinstance(computed_edge_hist_full, list)
        else computed_edge_hist_full
    )
    _edge_hist_trim = {
        "total": _edge_hist_total,
        "kept": len(computed_edge_hist) if isinstance(computed_edge_hist, list) else 0,
        "dropped": max(_edge_hist_total - len(computed_edge_hist), 0)
        if isinstance(computed_edge_hist, list)
        else 0,
    }

    # scan_scope: use provided dict or derive minimal version from topology
    if scan_scope is None:
        scan_scope = {
            "routes_total": topology.route_count,
            "edge_count": topology.edge_count,
        }
    # Inject pool-quality gate lane metadata into scan_scope (Steps 2+3)
    scan_scope["pool_quality_lane"] = pool_quality_lane
    if depth_quarantine_skipped > 0:
        scan_scope["depth_quarantine_skipped"] = depth_quarantine_skipped
    if revert_quarantine_skipped > 0:
        scan_scope["revert_quarantine_skipped"] = revert_quarantine_skipped
    if phantom_quarantine_skipped > 0:
        scan_scope["phantom_quarantine_skipped"] = phantom_quarantine_skipped
    if diagnostic_quarantine_skipped > 0:
        scan_scope["diagnostic_quarantine_skipped"] = diagnostic_quarantine_skipped
    if diagnostic_quarantine_mode:
        scan_scope["diagnostic_quarantine_mode"] = diagnostic_quarantine_mode
    if diagnostic_admission_mode:
        scan_scope["diagnostic_admission_mode"] = diagnostic_admission_mode
    if _economics_claim_suppressed:
        scan_scope["economics_claim_suppressed"] = True
    if pool_quality_lane == "productive":
        scan_scope["quarantine_exclusion_breakdown"] = quarantine_exclusion_breakdown or {
            "mode": diagnostic_quarantine_mode or "production",
            "note": "empty_breakdown",
        }
        scan_scope["productive_admission_skip_histogram"] = (
            graph_build_admission_histogram if graph_build_admission_histogram is not None else {}
        )
        scan_scope["cycles_before_quarantine"] = (
            0 if cycles_before_quarantine is None else cycles_before_quarantine
        )
        scan_scope["cycles_after_quarantine"] = (
            0 if cycles_after_quarantine is None else cycles_after_quarantine
        )
        scan_scope["graph_build_metrics"] = graph_build_metrics or {}
        _edge_hist = (graph_build_metrics or {}).get("edge_build_skip_histogram")
        if _edge_hist is not None:
            scan_scope["edge_build_skip_histogram"] = _edge_hist
        scan_scope["scan_scope_telemetry_complete"] = True
    else:
        if quarantine_exclusion_breakdown:
            scan_scope["quarantine_exclusion_breakdown"] = quarantine_exclusion_breakdown
        if cycles_before_quarantine is not None:
            scan_scope["cycles_before_quarantine"] = cycles_before_quarantine
        if cycles_after_quarantine is not None:
            scan_scope["cycles_after_quarantine"] = cycles_after_quarantine
        if graph_build_admission_histogram is not None:
            scan_scope["productive_admission_skip_histogram"] = graph_build_admission_histogram
        if graph_build_metrics:
            scan_scope["graph_build_metrics"] = graph_build_metrics

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
        v.get("QUOTE_RPC_ERROR", 0) for v in computed_route_hist_full.values() if isinstance(v, dict)
    )
    _provider_decode_error_count = sum(
        v.get("QUOTE_DECODE", 0) for v in computed_route_hist_full.values() if isinstance(v, dict)
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
    economics_metrics["cost_model_applied"] = _cost_profile_for_compute is not None
    economics_metrics["router_sim_eligible_after_cost"] = cycles_router_sim_eligible

    # Economics blocker classification: distinguish inventory quality from market signal
    pair_count = (scan_scope or {}).get("pair_count") or (
        (funnel_a or {}).get("pairs_probed") or 0
    )
    if cycles_found == 0 or not cycle_results:
        economics_blocker_class = _BLOCKER_NOT_RUN
    elif qsr < _QSR_ACCEPTANCE_THRESHOLD:
        # QSR below acceptance means quote/infra data is unreliable; not a market verdict.
        economics_blocker_class = _BLOCKER_PROVIDER_QUALITY
    elif cycles_positive_gross > 0:
        economics_blocker_class = _BLOCKER_NOT_BLOCKED
    elif 0 < pair_count <= _ANCHOR_HEAVY_PAIR_THRESHOLD:
        economics_blocker_class = _BLOCKER_INVENTORY_ANCHOR
    else:
        economics_blocker_class = _BLOCKER_MARKET

    _data_completeness_early: Optional[float] = None
    if multicall_stats and multicall_stats.get("requested_total", 0) > 0:
        _data_completeness_early = round(
            multicall_stats.get("fetched_total", 0) / multicall_stats["requested_total"],
            4,
        )
    if not cycle_results:
        infra_status = _INFRA_NOT_RUN
    elif qsr < _QSR_ACCEPTANCE_THRESHOLD:
        infra_status = _INFRA_QUOTE_QUALITY_BLOCKED
    elif (
        _data_completeness_early is not None
        and _data_completeness_early < _DATA_COMPLETENESS_ACCEPTANCE_THRESHOLD
    ):
        infra_status = _INFRA_QUOTE_QUALITY_BLOCKED
    else:
        infra_status = _INFRA_OK

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
    # Step 8: push TOXIC_ROUTE_PRICE_IMPACT cycles to the bottom of top_opportunities
    # so operator sees near-breakeven cycles first, not dominated by -9000+ bps toxics.
    # Sort key: (is_quoteable, is_not_toxic, gross_bps) — all descending.
    def _top_cycle_sort_key(qr: CycleQuoteResult):
        is_quoteable = 1 if qr.status in ("POSITIVE_GROSS", "NEGATIVE_GROSS") else 0
        # Detect toxic: quoteable cycle with pre_fee_gross < -500 bps
        _fee_drag_sort = qr.cycle.total_fee_bps
        _pfgb_sort = qr.gross_bps + _fee_drag_sort
        is_not_toxic = 0 if (is_quoteable and _pfgb_sort < -500) else 1
        return (is_quoteable, is_not_toxic, qr.gross_bps)

    # Deduplicate by cycle_id: one row per unique cycle (best quote), not per sweep.
    _best_by_cycle_id: Dict[str, CycleQuoteResult] = {}
    for qr in cycle_results:
        cid = qr.cycle.cycle_id
        prev = _best_by_cycle_id.get(cid)
        if prev is None or _top_cycle_sort_key(qr) > _top_cycle_sort_key(prev):
            _best_by_cycle_id[cid] = qr
    top_cycles = sorted(_best_by_cycle_id.values(), key=_top_cycle_sort_key, reverse=True)[:10]
    _cycle_sweep_occurrence: Dict[str, int] = {}
    for qr in cycle_results:
        _cycle_sweep_occurrence[qr.cycle.cycle_id] = (
            _cycle_sweep_occurrence.get(qr.cycle.cycle_id, 0) + 1
        )

    # Step 7: toxic_pool_families — operator-visible list of pools dominating toxic cycles
    _toxic_pool_families = _compute_toxic_pool_families(cycle_results)

    # Per-pool fair data-quality scorecards: classify each observed pool as
    # HEALTHY / PROBATION / LOW_SAMPLE / TOXIC from attributed, sampled evidence
    # (deeper partners are credited; transient RPC noise is ignored). TOXIC pools
    # become soft, TTL'd quarantine recommendations the operator/executor can
    # promote into data/quarantine/m9_pool_depth_quarantine.json.
    _pool_scorecards = build_pool_scorecards(cycle_results)
    _pool_quarantine_recommendations = recommend_quarantine(_pool_scorecards)

    # Dashboard fields: pull M8 cycle participation metrics from bridge_source_metrics
    # to top-level so CI gates and dashboards can read them without nested traversal.
    _cycles_with_m8_pool: int = 0
    _cycles_with_direct_sniper_pool: int = 0
    _cycles_with_m8_derived_pool: int = 0
    _positive_cycles_with_m8_pool: int = 0
    _cross_mechanic_cycles: int = 0
    _cross_mechanic_cycles_found: int = 0
    _cross_mechanic_cycles_quoteable: int = 0
    _m8_multi_venue_verified: Optional[int] = None
    _graph_edges_from_m8: Optional[int] = None
    _graph_ready_from_m8: Optional[int] = None
    _m8_pool_addrs_tracked: Optional[int] = None
    if bridge_source_metrics is not None:
        _cycles_with_m8_pool = bridge_source_metrics.get("cycles_with_m8_pool") or 0
        _cycles_with_direct_sniper_pool = (
            bridge_source_metrics.get("cycles_with_direct_sniper_pool") or 0
        )
        _cycles_with_m8_derived_pool = (
            bridge_source_metrics.get("cycles_with_m8_derived_pool") or 0
        )
        _positive_cycles_with_m8_pool = bridge_source_metrics.get("positive_cycles_with_m8_pool") or 0
        _cross_mechanic_cycles = bridge_source_metrics.get("cross_mechanic_cycles") or 0
        _cross_mechanic_cycles_found = (
            bridge_source_metrics.get("cross_mechanic_cycles_found")
            or _cross_mechanic_cycles
        )
        _cross_mechanic_cycles_quoteable = (
            bridge_source_metrics.get("cross_mechanic_cycles_quoteable") or 0
        )
        _m8_multi_venue_verified = bridge_source_metrics.get("m8_multi_venue_verified_count")
        _graph_edges_from_m8 = bridge_source_metrics.get("graph_edges_from_m8")
        _graph_ready_from_m8 = bridge_source_metrics.get("graph_ready_from_m8")
        _m8_pool_addrs_tracked = bridge_source_metrics.get("m8_pool_addrs_tracked")
    if m8_pool_addrs_for_annotation is not None and _m8_pool_addrs_tracked is None:
        _m8_pool_addrs_tracked = len(m8_pool_addrs_for_annotation)

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
        "cycle_lengths_used": list(cycle_lengths_used) if cycle_lengths_used else [],
        "cycles_found_by_length": _unique_cycle_counts_by_length(cycle_results),
        "cycles_quoteable_by_length": _unique_cycle_counts_by_length(
            cycle_results, quoteable_only=True
        ),
        "discovery_cycles_by_length": dict(discovery_cycles_by_length or {}),
        "cycles_positive_gross": cycles_positive_gross,
        "cycles_positive_gross_raw": cycles_positive_gross_raw,
        "cycles_positive_gross_quote": cycles_positive_gross_quote,
        "cycles_quoteable": cycles_quoteable,
        "cycles_router_sim_eligible": cycles_router_sim_eligible,
        "best_cycle_net_bps": best_cycle_net_bps,  # alias for best_cycle_gross_bps; backward compat
        "best_cycle_gross_bps": best_cycle_gross_bps,  # raw quote bps, no router/gas simulation
        "best_cycle_cost_adjusted_net_bps": best_cycle_cost_adjusted_net_bps,  # gross - estimated_cost
        "estimated_cost_bps": estimated_cost_bps,  # gas + l1_fee + slippage in bps
        "cost_adjusted_net_bps": cost_adjusted_net_bps,  # best_cycle_gross_bps - estimated_cost_bps
        "router_sim_net_bps": router_sim_net_bps,  # null until router simulation enabled
        "cycles_with_m8_pool": _cycles_with_m8_pool,  # cycles that traverse ≥1 M8-sourced pool
        "cycles_with_direct_sniper_pool": _cycles_with_direct_sniper_pool,
        "cycles_with_m8_derived_pool": _cycles_with_m8_derived_pool,
        "positive_cycles_with_m8_pool": _positive_cycles_with_m8_pool,  # positive gross only
        "cross_mechanic_cycles": _cross_mechanic_cycles,  # backward compat: cycles found
        "cross_mechanic_cycles_found": _cross_mechanic_cycles_found,
        "cross_mechanic_cycles_quoteable": _cross_mechanic_cycles_quoteable,
        "m8_multi_venue_verified": _m8_multi_venue_verified,  # tokens confirmed on >=2 DEXes
        "positive_cycle_multi_hit_count": positive_cycle_multi_hit_count,  # cycles positive ≥2 sweeps
        "positive_cycle_max_repeat": positive_cycle_max_repeat,  # max repeat for single cycle_id
        "qsr": round(qsr, 4),
        "qsr_liveness": round(qsr_liveness, 4),
        "qsr_econ": round(qsr_econ, 4),
        "quote_size_truth": {
            "liveness_max_size_usd": LIVENESS_MAX_SIZE_USD,
            "economic_size_floor_usd": _econ_floor_usd,
            "liveness_quote_attempts": len(_liveness_results),
            "econ_quote_attempts": len(_econ_results),
        },
        "oversized_vs_depth_count": oversized_vs_depth_count,
        "oversized_vs_measured_depth_count": oversized_vs_measured_depth_count,
        "oversized_vs_unknown_depth_fallback_count": oversized_vs_unknown_depth_fallback_count,
        "bridge_depth_telemetry": {
            "depth_known_rate": _bridge_depth_kr,
            "economics_conclusion_blocked": _economics_blocked_depth,
        },
        "infra_status": infra_status,
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
        "quote_failure_diagnostics": quote_failure_diagnostics,
        "phantom_quote_diagnostics": phantom_quote_diagnostics,
        "artifact_compaction": {
            "route_error_histogram": _route_hist_trim,
            "edge_error_histogram": _edge_hist_trim,
            "quote_failure_diagnostics_top_routes_kept": len(
                quote_failure_diagnostics.get("top_routes") or []
            ),
            "json_format": "compact",
        },
        "m8_participation": {
            "m8_pool_addrs_tracked": _m8_pool_addrs_tracked,
            "graph_ready_from_m8": _graph_ready_from_m8,
            "graph_edges_from_m8": _graph_edges_from_m8,
            "cycles_with_m8_pool": _cycles_with_m8_pool,
            "cycles_with_direct_sniper_pool": _cycles_with_direct_sniper_pool,
            "cycles_with_m8_derived_pool": _cycles_with_m8_derived_pool,
            "positive_cycles_with_m8_pool": _positive_cycles_with_m8_pool,
            "cross_mechanic_cycles": _cross_mechanic_cycles,
            "cross_mechanic_cycles_found": _cross_mechanic_cycles_found,
            "cross_mechanic_cycles_quoteable": _cross_mechanic_cycles_quoteable,
        },
        **(
            {
                "bridge_shadow": {
                    "bridge_routes_in_m9": bridge_source_metrics.get("bridge_routes_in_m9"),
                    "bridge_cycles_found": bridge_source_metrics.get("bridge_cycles_found"),
                    "bridge_cycles_quoteable": bridge_source_metrics.get("bridge_cycles_quoteable"),
                    "bridge_discovery_cycles_found": bridge_source_metrics.get(
                        "bridge_discovery_cycles_found"
                    ),
                    "cycles_with_m8_pool": _cycles_with_m8_pool,
                    "cross_mechanic_cycles": _cross_mechanic_cycles,
                    "cross_mechanic_cycles_found": _cross_mechanic_cycles_found,
                    "cross_mechanic_cycles_quoteable": _cross_mechanic_cycles_quoteable,
                    "graph_ready_from_m8": _graph_ready_from_m8,
                    "graph_ready_from_expansion": bridge_source_metrics.get(
                        "graph_ready_from_expansion"
                    ),
                    "expansion_routes_raw_input": bridge_source_metrics.get(
                        "expansion_routes_raw_input"
                    ),
                    "expansion_routes_after_dedupe": bridge_source_metrics.get(
                        "expansion_routes_after_dedupe"
                    ),
                    "spread_lifetime": (spread_lifetime_block or {}).get("spread_lifetime"),
                    "existence_blocker": bridge_source_metrics.get(
                        "existence_blocker",
                        "M8_2_FRESH_MULTI_VENUE_UNIVERSE_TOO_SMALL",
                    ),
                }
            }
            if bridge_source_metrics and bridge_source_metrics.get("bridge_shadow_run")
            else {}
        ),
        "scan_scope": scan_scope,
        "top_cycles": [
            _build_cycle_summary(
                qr,
                m8_pool_addrs_for_annotation,
                _cost_profile_for_compute,
                route_meta_by_pool,
            )
            for qr in top_cycles
        ],
        "top_opportunities": [
            {
                **_build_top_opportunity(qr, _cost_profile_for_compute, route_meta_by_pool),
                "unique_cycle_rank": rank + 1,
                "sweep_occurrence_count": _cycle_sweep_occurrence.get(qr.cycle.cycle_id, 1),
            }
            for rank, qr in enumerate(top_cycles)
        ],
        "toxic_pool_families": _toxic_pool_families,
        "pool_scorecards": _pool_scorecards,
        "pool_quarantine_recommendations": _pool_quarantine_recommendations,
        "graph_topology": graph_topology,
        "topology_gate": topology_gate,
        "discovery_cycles_found": discovery_cycles_found,
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
    # Productive-cycle funnel around the prequote stage (operator-visible regardless
    # of whether anything was skipped). "before" = cycles that entered the prequote
    # stage; "after" = cycles that survived and reached the quoter.
    infra_telemetry["productive_cycles_before_prequote"] = prequote_cycles_skipped + cycles_found
    infra_telemetry["productive_cycles_after_prequote"] = cycles_found
    # Scheduler name
    if scheduler_name is not None:
        infra_telemetry["scheduler_name"] = scheduler_name
    _dynamic_results = [
        qr
        for qr in cycle_results
        if qr.dynamic_size_usd is not None
        or (qr.size_candidates_usd and len(qr.size_candidates_usd) > 0)
    ]
    infra_telemetry["dynamic_size_enabled"] = bool(
        any(qr.size_candidates_usd for qr in cycle_results)
    )
    # Operator intent (CLI/config) is reported separately from the observed result so
    # that a run which requested --dynamic-sizes but quoted zero cycles still shows the
    # intent was on, instead of a misleading dynamic_size_enabled=False.
    infra_telemetry["dynamic_size_intent"] = bool(dynamic_sizes_intent)
    infra_telemetry["dynamic_size_selected_count"] = len(_dynamic_results)
    if _dynamic_results:
        infra_telemetry["dynamic_size_selection_rate"] = round(
            len(_dynamic_results) / max(len(cycle_results), 1), 4
        )
    # Depth-aware sizing telemetry (package #2): how many cycles carried a measured
    # bottleneck depth and how many had their size ladder clamped by it.
    _depth_known = [qr for qr in cycle_results if qr.cycle_min_depth_usd is not None]
    _depth_capped = [qr for qr in cycle_results if getattr(qr, "depth_capped", False)]
    infra_telemetry["depth_aware_known_count"] = len(_depth_known)
    infra_telemetry["depth_aware_capped_count"] = len(_depth_capped)
    if cycle_results:
        infra_telemetry["depth_aware_known_rate"] = round(
            len(_depth_known) / max(len(cycle_results), 1), 4
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
    if active_rpc_by_sweep:
        infra_telemetry["active_rpc_by_sweep"] = active_rpc_by_sweep
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
    _depth_known_rate = infra_telemetry.get("depth_aware_known_rate")
    runtime_gates["depth_aware_known_rate"] = {
        "value": _depth_known_rate,
        "threshold": 0.8,
        "pass": bool(
            _depth_known_rate is None
            or _depth_known_rate >= 0.8
        ),
    }
    _failover = 0
    if provider_router_snapshot:
        _failover = int(
            provider_router_snapshot.get("failover_count", 0)
            or provider_router_snapshot.get("failover_events", 0)
            or 0
        )
    runtime_gates["provider_failover_count"] = {
        "value": _failover,
        "threshold": 50,
        "pass": _failover < 50,
    }
    runtime_gates["all_pass"] = all(
        v["pass"] for v in runtime_gates.values() if isinstance(v, dict) and "pass" in v
    )
    artifact["runtime_gates"] = runtime_gates

    _layer = _compute_layer_telemetry(
        cycle_results,
        qsr=qsr,
        provider_router_snapshot=provider_router_snapshot,
        ws_freshness=ws_freshness,
    )
    artifact.update(_layer)

    # M8→M9 bridge provenance (optional; populated when runner uses bridge inventory)
    if bridge_source_metrics is not None:
        artifact["bridge_source_metrics"] = bridge_source_metrics

    # Per-adapter cost breakdown and adapter-family cycle distribution (Step 2 + cost_model)
    try:
        from m9.graph_arb.cost_model import build_cost_breakdown as _build_cost_breakdown
        _adapter_breakdown = _build_cost_breakdown(cycle_results)
        artifact["cost_breakdown_by_adapter"] = _adapter_breakdown["cost_breakdown_by_adapter"]
        artifact["cycles_by_adapter_family"] = _adapter_breakdown["cycles_by_adapter_family"]
        artifact["positive_cycles_by_adapter_family"] = _adapter_breakdown["positive_cycles_by_adapter_family"]
        artifact["cycles_by_pricing_model"] = _adapter_breakdown["cycles_by_pricing_model"]
        artifact["positive_cycles_by_pricing_model"] = _adapter_breakdown["positive_cycles_by_pricing_model"]
    except Exception:
        artifact["cost_breakdown_by_adapter"] = None
        artifact["cycles_by_adapter_family"] = None
        artifact["positive_cycles_by_adapter_family"] = None
        artifact["cycles_by_pricing_model"] = None
        artifact["positive_cycles_by_pricing_model"] = None

    artifact["scan_scope_telemetry"] = validate_scan_scope_telemetry(artifact)
    if _economics_claim_suppressed:
        artifact["economics_claim_suppressed"] = True

    return artifact


def write_artifact(artifact: Dict[str, Any], artifact_path: str = ROLLING_PATH) -> None:
    """Write artifact atomically to artifact_path (via .tmp rename)."""
    import time as _time
    import uuid

    path = os.path.abspath(artifact_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Per-write unique tmp avoids WinError 2 when concurrent runners share path.tmp
    tmp_path = f"{path}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, ensure_ascii=False, separators=(",", ":"))
    # On Windows, os.replace can raise PermissionError if antivirus scans
    # the .tmp file between write and rename.  Retry with backoff.
    for attempt in range(6):
        try:
            os.replace(tmp_path, path)
            return
        except (PermissionError, FileNotFoundError):
            if attempt < 5:
                _time.sleep(0.5 * (attempt + 1))
                if not os.path.exists(tmp_path):
                    with open(tmp_path, "w", encoding="utf-8") as fh:
                        json.dump(artifact, fh, ensure_ascii=False, separators=(",", ":"))
            else:
                raise
