#!/usr/bin/env python3
"""Quote-lane diagnostic: pool smoke (Balancer/Maverick) or cycle RCA from shadow artifact."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_SHADOW = REPO_ROOT / "data/tmp/m9_graph_bridge_shadow_latest.json"
_DEFAULT_OUT = REPO_ROOT / "data/tmp/m9_quote_lane_rca_latest.json"


def _canonical_dex_id(dex_id: str, route_id: str = "") -> str:
    """Normalize dex labels for RCA histograms."""
    d = str(dex_id or "").strip().lower()
    rid = str(route_id or "").lower()
    if d in ("balancer", "balancer_vault") or "balancer" in rid:
        return "balancer_vault"
    if d in ("maverick", "maverick_v2") or "maverick" in rid:
        return "maverick_v2"
    if d in ("curve", "curve_stable") or rid.startswith("curve"):
        return "curve_stable"
    if d == "uniswap_v4" or "uniswap_v4" in rid:
        return "uniswap_v4"
    if d in ("uniswap_v3", "v3") or "uniswap_v3" in rid:
        return "uniswap_v3"
    if d == "aerodrome" or "aerodrome" in rid:
        return "aerodrome"
    return d or "unknown"


def _adapter_family(route_id: str, edge: Dict[str, Any]) -> str:
    rid = str(route_id or edge.get("route_id") or "")
    dex = str(edge.get("dex_id") or "")
    if rid.startswith("curve") or dex.startswith("curve"):
        return "curve"
    if "balancer" in rid or "balancer" in dex:
        return "balancer"
    if "maverick" in rid or "maverick" in dex:
        return "maverick"
    if "uniswap_v4" in rid or dex == "uniswap_v4":
        return "uniswap_v4"
    if "uniswap_v3" in rid or dex == "uniswap_v3":
        return "uniswap_v3"
    if "aerodrome" in rid or dex == "aerodrome":
        return "aerodrome"
    return dex or "unknown"


def _cycle_length_from_id(cycle_id: str) -> int:
    parts = str(cycle_id or "").split(":")
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


def _cycle_length_from_id(cycle_id: str) -> int:
    parts = str(cycle_id or "").split(":")
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


_STABLE_PEG_SYMBOLS = frozenset(
    {"USDC", "USDT", "DAI", "USDbC", "EURC", "crvUSD", "USDBC", "FRAX", "LUSD"}
)


def _is_stable_peg_symbol(sym: str) -> bool:
    return (sym or "").strip().upper() in _STABLE_PEG_SYMBOLS


def _enrich_leg_rows_from_artifact(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten legs and backfill continuity / stable-outlier when absent."""
    rows: List[Dict[str, Any]] = []
    for source_key in ("top_opportunities", "top_cycles"):
        for opp in artifact.get(source_key) or []:
            if not isinstance(opp, dict):
                continue
            cid = opp.get("cycle_id")
            size_usd = opp.get("dynamic_size_usd") or opp.get("market_size_usd")
            spread_bps = opp.get("spread_bps")
            legs = opp.get("legs") or []
            prev_out = None
            for idx, leg in enumerate(legs):
                if not isinstance(leg, dict):
                    continue
                row = {
                    **leg,
                    "cycle_id": cid,
                    "market_size_usd": size_usd,
                    "cycle_spread_bps": spread_bps,
                    "source_block": source_key,
                    "leg_idx": leg.get("leg_idx", idx),
                }
                raw_in = row.get("raw_amount_in")
                if idx > 0:
                    row["prev_leg_out_raw"] = row.get("prev_leg_out_raw", prev_out)
                    row["current_leg_in_raw"] = row.get("current_leg_in_raw", raw_in)
                    if row.get("amount_continuity_ok") is None and prev_out is not None and raw_in is not None:
                        row["amount_continuity_ok"] = int(prev_out) == int(raw_in)
                ratio = row.get("norm_value_ratio")
                if ratio is None:
                    nin = row.get("norm_amount_in")
                    nout = row.get("norm_amount_out")
                    if nin and nout and float(nin) > 0:
                        ratio = float(nout) / float(nin)
                        row["norm_value_ratio"] = round(ratio, 8)
                if ratio is not None and not row.get("stable_value_ratio_outlier"):
                    tin = str(row.get("token_in") or "")
                    tout = str(row.get("token_out") or "")
                    if _is_stable_peg_symbol(tin) and _is_stable_peg_symbol(tout):
                        if ratio < 0.5 or ratio > 2.0:
                            row["stable_value_ratio_outlier"] = True
                            row["sanity_gate"] = "STABLE_VALUE_RATIO_OUTLIER"
                if row.get("raw_amount_out") is not None:
                    prev_out = row.get("raw_amount_out")
                rows.append(row)
    return rows


def _iter_quoted_cycle_rows(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten top_opportunities / top_cycles legs for RCA."""
    return _enrich_leg_rows_from_artifact(artifact)


def _build_amount_continuity_rca(artifact: Dict[str, Any]) -> Dict[str, Any]:
    violations: List[Dict[str, Any]] = []
    seen: set[tuple] = set()
    for row in _enrich_leg_rows_from_artifact(artifact):
        if int(row.get("leg_idx") or 0) == 0:
            continue
        ok = row.get("amount_continuity_ok")
        if ok is not False:
            continue
        key = (row.get("cycle_id"), row.get("leg_idx"))
        if key in seen:
            continue
        seen.add(key)
        violations.append(
            {
                "cycle_id": row.get("cycle_id"),
                "leg_idx": row.get("leg_idx"),
                "route_id": row.get("route_id"),
                "dex_id": row.get("dex_id"),
                "token_in": row.get("token_in"),
                "token_out": row.get("token_out"),
                "prev_leg_out_raw": row.get("prev_leg_out_raw"),
                "current_leg_in_raw": row.get("current_leg_in_raw"),
            }
        )
    return {
        "violation_count": len(violations),
        "violations": violations[:20],
    }


def _build_top_value_loss_legs(
    artifact: Dict[str, Any],
    inventory: Optional[Dict[str, Any]],
    *,
    limit: int = 15,
) -> List[Dict[str, Any]]:
    """Rank legs by worst normalized value ratio / stable peg breakage."""
    route_meta: Dict[str, Dict[str, Any]] = {}
    if inventory:
        from m9.graph_arb.cycle_lane_prefilter import build_route_metadata_from_routes

        route_meta = build_route_metadata_from_routes(
            inventory.get("active_routes") or []
        )

    ranked: List[Dict[str, Any]] = []
    for row in _iter_quoted_cycle_rows(artifact):
        ratio = row.get("norm_value_ratio")
        if ratio is None:
            continue
        loss_score = 1.0 - float(ratio) if float(ratio) < 1.0 else 0.0
        pool = str(row.get("pool_address") or "").lower()
        inv = route_meta.get(pool) or {}
        entry = {
            "cycle_id": row.get("cycle_id"),
            "leg_idx": row.get("leg_idx"),
            "route_id": row.get("route_id") or inv.get("route_id"),
            "dex_id": row.get("dex_id") or inv.get("dex_id"),
            "adapter_type": row.get("adapter_type"),
            "token_in": row.get("token_in"),
            "token_out": row.get("token_out"),
            "token_in_addr": row.get("token_in_addr"),
            "token_out_addr": row.get("token_out_addr"),
            "norm_amount_in": row.get("norm_amount_in"),
            "norm_amount_out": row.get("norm_amount_out"),
            "norm_value_ratio": ratio,
            "raw_amount_in": row.get("raw_amount_in"),
            "raw_amount_out": row.get("raw_amount_out"),
            "pool_address": row.get("pool_address"),
            "pool_id": row.get("pool_id") or inv.get("pool_id"),
            "amount_continuity_ok": row.get("amount_continuity_ok"),
            "stable_value_ratio_outlier": row.get("stable_value_ratio_outlier"),
            "sanity_gate": row.get("sanity_gate"),
            "loss_score": round(loss_score, 6),
            "market_size_usd": row.get("market_size_usd"),
        }
        ranked.append(entry)

    ranked.sort(key=lambda r: (r.get("loss_score") or 0), reverse=True)
    deduped: List[Dict[str, Any]] = []
    seen_keys: set[tuple] = set()
    for row in ranked:
        key = (row.get("cycle_id"), row.get("leg_idx"), row.get("pool_address"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(row)
    return deduped[:limit]


def _build_adapter_leg_isolation(
    artifact: Dict[str, Any],
    inventory: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Isolate Curve USDC→USDbC and Maverick USDbC→WETH legs from quoted cycles."""
    route_meta: Dict[str, Dict[str, Any]] = {}
    if inventory:
        from m9.graph_arb.cycle_lane_prefilter import build_route_metadata_from_routes

        route_meta = build_route_metadata_from_routes(
            inventory.get("active_routes") or []
        )

    curve_usdc_usdbc: List[Dict[str, Any]] = []
    maverick_usdbc_weth: List[Dict[str, Any]] = []
    for row in _iter_quoted_cycle_rows(artifact):
        tin = str(row.get("token_in") or "").upper()
        tout = str(row.get("token_out") or "").upper()
        dex = str(row.get("dex_id") or row.get("adapter_type") or "").lower()
        pool = str(row.get("pool_address") or "").lower()
        inv = route_meta.get(pool) or {}
        leg_row = {
            "cycle_id": row.get("cycle_id"),
            "leg_idx": row.get("leg_idx"),
            "route_id": row.get("route_id") or inv.get("route_id"),
            "pool_address": row.get("pool_address"),
            "pool_id": row.get("pool_id") or inv.get("pool_id"),
            "token_in": tin,
            "token_out": tout,
            "norm_amount_in": row.get("norm_amount_in"),
            "norm_amount_out": row.get("norm_amount_out"),
            "norm_value_ratio": row.get("norm_value_ratio"),
            "raw_amount_in": row.get("raw_amount_in"),
            "raw_amount_out": row.get("raw_amount_out"),
            "amount_continuity_ok": row.get("amount_continuity_ok"),
            "stable_value_ratio_outlier": row.get("stable_value_ratio_outlier"),
            "curve_coin_indices": inv.get("curve_coin_indices"),
            "balancer_assets": inv.get("balancer_assets"),
            "maverick_token_a_in_probe": inv.get("maverick_token_a_in_probe"),
            "maverick_pool_lane_probe_amount": inv.get("maverick_pool_lane_probe_amount"),
            "token0_decimals": inv.get("token0_decimals"),
            "token1_decimals": inv.get("token1_decimals"),
        }
        if (
            ("curve" in dex or str(row.get("route_id") or "").startswith("curve"))
            and tin in ("USDC",) and tout in ("USDBC", "USDbC")
        ):
            curve_usdc_usdbc.append(leg_row)
        if (
            ("maverick" in dex or str(row.get("route_id") or "").startswith("maverick"))
            and tin in ("USDBC", "USDbC") and tout in ("WETH",)
        ):
            maverick_usdbc_weth.append(leg_row)

    return {
        "curve_usdc_usdbc": curve_usdc_usdbc[:10],
        "maverick_usdbc_weth": maverick_usdbc_weth[:10],
    }


def _adapter_rca_from_quote_diagnostics(
    artifact: Dict[str, Any],
    family: str,
    *,
    primary_reason: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Deep RCA rows from runner quote_failure_diagnostics.top_routes."""
    qfd = artifact.get("quote_failure_diagnostics") or {}
    rows: List[Dict[str, Any]] = []
    for row in qfd.get("top_routes") or []:
        if not isinstance(row, dict):
            continue
        dex = str(row.get("dex_id") or row.get("adapter_type") or "")
        if _adapter_family(str(row.get("route_id") or ""), {"dex_id": dex}) != family:
            continue
        errors = row.get("errors") or {}
        if not errors.get(primary_reason) and primary_reason not in errors:
            continue
        inv_meta: Dict[str, Any] = {}
        rows.append(
            {
                "route_id": row.get("route_id"),
                "pool_address": row.get("pool_address"),
                "pair_id": row.get("pair_id"),
                "dex_id": row.get("dex_id"),
                "adapter_type": row.get("adapter_type"),
                "top_reject_reason": primary_reason,
                "error_counts": {str(k): int(v) for k, v in errors.items()},
                "sample_raw_error": row.get("sample_raw_error"),
                "http_status": row.get("http_status"),
                **inv_meta,
            }
        )
    return rows[:limit]


def _enrich_balancer_rca(
    rows: List[Dict[str, Any]],
    inventory: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    from m9.graph_arb.quote_reject_classify import extract_balancer_code

    by_pool: Dict[str, Dict[str, Any]] = {}
    by_route_pool: Dict[str, str] = {}
    if inventory:
        for r in inventory.get("active_routes") or []:
            pool = str(r.get("pool_address", "")).lower()
            if pool:
                by_pool[pool] = r
            rid = str(r.get("route_id") or "")
            if rid and pool:
                by_route_pool[rid] = pool

    enriched = []
    for row in rows:
        pool = str(row.get("pool_address") or "").lower()
        if not pool:
            rid = str(row.get("route_id") or "")
            for inv_r in (inventory or {}).get("active_routes") or []:
                _t0 = str(inv_r.get("token0") or "")
                _t1 = str(inv_r.get("token1") or "")
                if _t0 in rid and _t1 in rid and inv_r.get("dex_id", "").startswith("balancer"):
                    pool = str(inv_r.get("pool_address", "")).lower()
                    break
        inv = by_pool.get(pool) or {}
        raw = str(row.get("sample_raw_error") or "")
        code = extract_balancer_code(raw)
        from m9.graph_arb.quote_reject_classify import balancer_reason_for_code

        reason_name = balancer_reason_for_code(code) if code else None
        enriched.append(
            {
                **row,
                "pool_address": pool or row.get("pool_address"),
                "pool_id": inv.get("pool_id") or row.get("pool_id"),
                "vault_address": inv.get("vault_address"),
                "token0_addr": inv.get("token0_addr"),
                "token1_addr": inv.get("token1_addr"),
                "balancer_assets": inv.get("balancer_assets"),
                "balancer_balances": inv.get("balancer_balances"),
                "pool_kind": inv.get("pool_kind"),
                "swap_kind": "GIVEN_IN",
                "asset_in_index": (
                    list(inv.get("balancer_assets") or []).index(inv.get("token0_addr"))
                    if inv.get("balancer_assets") and inv.get("token0_addr") in (inv.get("balancer_assets") or [])
                    else None
                ),
                "asset_out_index": (
                    list(inv.get("balancer_assets") or []).index(inv.get("token1_addr"))
                    if inv.get("balancer_assets") and inv.get("token1_addr") in (inv.get("balancer_assets") or [])
                    else None
                ),
                "amount_in": row.get("amount_in"),
                "balancer_query_target": "queryBatchSwap",
                "balancer_revert_code": code,
                "balancer_reason": reason_name,
            }
        )
    return enriched


def _build_m8_cycle_trace(
    artifact: Dict[str, Any],
    inventory: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Why M8 pools may not appear in quoted cycles."""
    m8_part = artifact.get("m8_participation") or {}
    m8_routes: List[Dict[str, Any]] = []
    if inventory:
        m8_routes = [
            r
            for r in inventory.get("active_routes") or []
            if r.get("source") == "m8_sniper"
        ]
    edges_in_graph = int(m8_part.get("graph_edges_from_m8") or 0)
    cycles_with_m8 = int(m8_part.get("cycles_with_m8_pool") or 0)
    cycles_with_direct = int(m8_part.get("cycles_with_direct_sniper_pool") or 0)
    cycles_with_derived = int(m8_part.get("cycles_with_m8_derived_pool") or 0)
    pool_rows = []
    for r in m8_routes[:12]:
        pool_rows.append(
            {
                "pool_address": r.get("pool_address"),
                "route_id": r.get("route_id"),
                "token0": r.get("token0"),
                "token1": r.get("token1"),
                "dex_id": r.get("dex_id"),
                "freshness_window": r.get("freshness_window"),
            }
        )
    hints: List[str] = []
    if m8_routes and edges_in_graph == 0:
        hints.append("m8_routes_present_but_zero_graph_edges")
    if edges_in_graph > 0 and cycles_with_m8 == 0:
        hints.append("m8_edges_in_graph_but_no_cycle_quotes_traversed_m8_pool")
    if not m8_routes:
        hints.append("no_m8_sniper_routes_in_active_bridge_inventory")
    return {
        "m8_sniper_routes_in_inventory": len(m8_routes),
        "graph_edges_from_m8": edges_in_graph,
        "graph_ready_from_m8": m8_part.get("graph_ready_from_m8"),
        "cycles_with_m8_pool": cycles_with_m8,
        "cycles_with_direct_sniper_pool": cycles_with_direct,
        "cycles_with_m8_derived_pool": cycles_with_derived,
        "m8_pool_addrs_tracked": m8_part.get("m8_pool_addrs_tracked"),
        "m8_route_samples": pool_rows,
        "diagnostic_hints": hints,
    }


def _build_micro_size_policy(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Requested vs effective sizes and depth rejects."""
    sizes = list(artifact.get("sizes_usd") or [])
    reject = dict(artifact.get("cycle_reject_histogram") or {})
    oversized = int(reject.get("OVERSIZED_VS_DEPTH", 0))
    phantom = int(reject.get("PHANTOM_QUOTE_BPS_OVERFLOW", 0))
    cycles_found = int(artifact.get("cycles_found") or 0)
    top = artifact.get("top_cycles") or []
    size_hist: Counter[float] = Counter()
    for cyc in top:
        if isinstance(cyc, dict) and cyc.get("size_usd") is not None:
            size_hist[float(cyc["size_usd"])] += 1
    return {
        "configured_sizes_usd": sizes,
        "smallest_configured_usd": min(sizes) if sizes else None,
        "oversized_vs_depth_count": oversized,
        "phantom_overflow_count": phantom,
        "oversized_rate": round(oversized / cycles_found, 4) if cycles_found else 0.0,
        "top_cycle_size_histogram": dict(size_hist),
        "policy_hint": (
            "depth_cap_dominates_before_quoteable"
            if oversized > cycles_found // 3
            else None
        ),
    }


def _top_route_failures(
    edge_hist: List[Dict[str, Any]],
    route_hist: Dict[str, Any],
    family: str,
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Top failing routes for a given adapter family."""
    rows: List[Dict[str, Any]] = []
    for edge in edge_hist:
        rid = str(edge.get("route_id") or "")
        if _adapter_family(rid, edge) != family:
            continue
        errors = edge.get("errors") or {}
        if not errors:
            continue
        top_reason = max(errors.items(), key=lambda kv: int(kv[1]))[0]
        rows.append(
            {
                "route_id": rid,
                "pool_address": edge.get("pool_address"),
                "pool_id": edge.get("pool_id"),
                "dex_id": edge.get("dex_id"),
                "top_reject_reason": top_reason,
                "error_counts": {str(k): int(v) for k, v in errors.items()},
            }
        )
    if len(rows) < limit:
        for route_id, errors in route_hist.items():
            if _adapter_family(str(route_id), {}) != family:
                continue
            if not isinstance(errors, dict) or not errors:
                continue
            top_reason = max(errors.items(), key=lambda kv: int(kv[1]))[0]
            rows.append(
                {
                    "route_id": route_id,
                    "top_reject_reason": top_reason,
                    "error_counts": {str(k): int(v) for k, v in errors.items()},
                }
            )
    return rows[:limit]


def graph_fingerprint(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Stable identity for graph artifact ↔ RCA sync checks."""
    return {
        "run_timestamp": artifact.get("run_timestamp"),
        "cycles_found": int(artifact.get("cycles_found") or 0),
        "cycles_quoteable": int(artifact.get("cycles_quoteable") or 0),
        "qsr_liveness": artifact.get("qsr_liveness"),
        "qsr_econ": artifact.get("qsr_econ"),
    }


def check_rca_graph_consistency(
    rca: Dict[str, Any],
    artifact: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare RCA summary to source graph; surface stale RCA drift."""
    graph_fp = graph_fingerprint(artifact)
    rca_fp = dict(rca.get("source_graph_fingerprint") or {})
    mismatches: List[str] = []
    for key in ("run_timestamp", "cycles_found", "cycles_quoteable"):
        if rca_fp.get(key) != graph_fp.get(key):
            mismatches.append(key)
    return {
        "graph_fingerprint": graph_fp,
        "rca_fingerprint": rca_fp,
        "consistent": not mismatches,
        "mismatched_fields": mismatches,
    }


def build_cycle_rca(
    artifact: Dict[str, Any],
    inventory: Optional[Dict[str, Any]] = None,
    *,
    source_artifact: Optional[str] = None,
) -> Dict[str, Any]:
    """Break down cycles_quoteable=0 from a bridge-shadow graph artifact."""
    from m9.graph_arb.cycle_lane_prefilter import build_route_metadata_from_routes

    cycles_found = int(artifact.get("cycles_found") or 0)
    cycles_quoteable = int(artifact.get("cycles_quoteable") or 0)
    cycle_reject = dict(artifact.get("cycle_reject_histogram") or {})
    route_hist = artifact.get("route_error_histogram") or {}
    edge_hist: List[Dict[str, Any]] = list(artifact.get("edge_error_histogram") or [])

    by_adapter: Counter[str] = Counter()
    by_dex_id: Counter[str] = Counter()
    by_reject: Counter[str] = Counter()
    by_leg_index: Counter[int] = Counter()
    for edge in edge_hist:
        route_id = str(edge.get("route_id") or "")
        family = _adapter_family(route_id, edge)
        dex_id = _canonical_dex_id(str(edge.get("dex_id") or ""), route_id)
        errors = edge.get("errors") or {}
        for reason, count in errors.items():
            by_adapter[family] += int(count)
            by_dex_id[dex_id] += int(count)
            by_reject[str(reason)] += int(count)
            by_leg_index[0] += int(count)

    route_level: Dict[str, Dict[str, int]] = {}
    for route_id, errors in route_hist.items():
        if not isinstance(errors, dict):
            continue
        family = _adapter_family(str(route_id), {})
        dex_id = _canonical_dex_id("", str(route_id))
        route_level[str(route_id)] = {str(k): int(v) for k, v in errors.items()}
        for reason, count in errors.items():
            by_adapter[family] += int(count)
            by_dex_id[dex_id] += int(count)
            by_reject[str(reason)] += int(count)

    by_cycle_length: Dict[str, int] = dict(
        artifact.get("cycles_found_by_length") or artifact.get("cycles_by_length") or {}
    )
    cycles_quoteable_by_length: Dict[str, int] = dict(
        artifact.get("cycles_quoteable_by_length") or {}
    )
    by_adapter_family_cycles: Dict[str, int] = dict(
        artifact.get("cycles_by_adapter_family") or {}
    )

    route_meta = (
        build_route_metadata_from_routes(inventory.get("active_routes") or [])
        if inventory
        else {}
    )

    top_cycles = artifact.get("top_cycles") or []
    cycle_kill_explanations: List[Dict[str, Any]] = []
    sample_failures: List[Dict[str, Any]] = []
    for qr in top_cycles[:20]:
        if not isinstance(qr, dict):
            continue
        status = str(qr.get("status") or "")
        if status in ("POSITIVE_GROSS", "NEGATIVE_GROSS"):
            continue
        legs = []
        kill_leg: Optional[Dict[str, Any]] = None
        for idx, leg in enumerate(qr.get("legs") or []):
            if not isinstance(leg, dict):
                continue
            pool = str(leg.get("pool_address") or "").lower()
            row = route_meta.get(pool) or {}
            leg_row = {
                "leg_index": idx,
                "route_id": leg.get("route_id"),
                "reject_reason": leg.get("reject_reason"),
                "quote_error": leg.get("reject_reason") or leg.get("quote_error"),
                "dex_id": leg.get("dex_id"),
                "pool_address": pool or leg.get("pool_address"),
                "amount_in": leg.get("raw_amount_in"),
                "effective_depth_usd": leg.get("effective_depth_usd") or row.get(
                    "effective_depth_usd"
                ),
                "depth_status": leg.get("depth_status") or row.get("depth_status"),
                "productive_quote_status": row.get("productive_quote_status"),
                "balancer_assets_present": bool(row.get("balancer_assets")),
                "pool_id": row.get("pool_id") or leg.get("pool_id"),
                "cycle_amount_in": leg.get("raw_amount_in"),
                "pool_lane_probe_amount": row.get("maverick_pool_lane_probe_amount"),
                "token_a_in_probe": row.get("maverick_token_a_in_probe"),
                "token_in": leg.get("token_in_addr"),
                "token_out": leg.get("token_out_addr"),
            }
            if leg.get("ok"):
                continue
            legs.append(leg_row)
            if kill_leg is None:
                kill_leg = leg_row
        failure = {
            "cycle_id": qr.get("cycle_id"),
            "cycle_length": qr.get("length") or _cycle_length_from_id(
                str(qr.get("cycle_id") or "")
            ),
            "status": status,
            "reject_reason": qr.get("reject_reason"),
            "failed_legs": legs,
            "kill_leg": kill_leg,
        }
        sample_failures.append(failure)
        if kill_leg and len(cycle_kill_explanations) < 15:
            cycle_kill_explanations.append(
                {
                    "cycle_id": qr.get("cycle_id"),
                    "status": status,
                    "kill_leg": kill_leg,
                }
            )

    m8_part = artifact.get("m8_participation") or {}
    bridge_shadow = artifact.get("bridge_shadow") or {}
    cross_mechanic_cycles = (
        artifact.get("cross_mechanic_cycles")
        if artifact.get("cross_mechanic_cycles") is not None
        else m8_part.get("cross_mechanic_cycles")
        if m8_part.get("cross_mechanic_cycles") is not None
        else bridge_shadow.get("cross_mechanic_cycles")
    )

    root_cause_hints: List[str] = []
    if cycles_quoteable == 0 and cycles_found > 0:
        if by_reject.get("QUOTE_REVERT", 0) > by_reject.get("QUOTE_RPC_ERROR", 0):
            root_cause_hints.append("dominant_leg_reject=QUOTE_REVERT (ABI/path/config)")
        if by_adapter.get("curve", 0) > sum(
            by_adapter.get(k, 0) for k in ("balancer", "maverick")
        ):
            root_cause_hints.append("curve_lane_dominates_failures")
        if cycle_reject.get("OVERSIZED_VS_DEPTH", 0) > 0:
            root_cause_hints.append("oversized_vs_depth_excludes_quoteable_denominator")
        if int(cross_mechanic_cycles or 0) == 0:
            root_cause_hints.append("no_cross_mechanic_cycles_in_graph")

    cm_diag: Dict[str, Any] = {}
    if inventory:
        active = inventory.get("active_routes") or []
        cm_pools = {
            str(r.get("pool_address", "")).lower()
            for r in active
            if r.get("cross_mechanic") and r.get("pool_address")
        }
        cm_diag = {
            "cross_mechanic_routes_in_inventory": sum(
                1 for r in active if r.get("cross_mechanic")
            ),
            "cross_mechanic_unique_pools": len(cm_pools),
            "cross_mechanic_cycles_in_shadow": int(cross_mechanic_cycles or 0),
            "hypothesis": (
                "cross_mechanic_pools_present_but_cycles_do_not_traverse_them"
                if cm_pools and int(cross_mechanic_cycles or 0) == 0
                else None
            ),
        }

    cm_found = int(
        artifact.get("cross_mechanic_cycles_found")
        or cross_mechanic_cycles
        or 0
    )
    cm_quoteable = int(artifact.get("cross_mechanic_cycles_quoteable") or 0)
    phantom_diag = artifact.get("phantom_quote_diagnostics") or {}
    phantom_count = int(
        phantom_diag.get("phantom_count")
        or cycle_reject.get("PHANTOM_QUOTE_BPS_OVERFLOW", 0)
        or 0
    )
    balancer_rca = _enrich_balancer_rca(
        _adapter_rca_from_quote_diagnostics(
            artifact, "balancer", primary_reason="QUOTE_REVERT"
        )
        or _top_route_failures(edge_hist, route_hist, "balancer"),
        inventory,
    )
    maverick_rca = _adapter_rca_from_quote_diagnostics(
        artifact, "maverick", primary_reason="QUOTE_REVERT"
    ) or _top_route_failures(edge_hist, route_hist, "maverick")

    fp = graph_fingerprint(artifact)
    qsr = artifact.get("qsr")
    qsr_liveness = artifact.get("qsr_liveness")
    qsr_econ = artifact.get("qsr_econ")
    discovery_by_len = dict(artifact.get("discovery_cycles_by_length") or {})
    by_cycle_length_rca: Dict[str, Any] = {}
    for label, key in (("2_leg", "2"), ("3_leg", "3"), ("4_leg", "4")):
        by_cycle_length_rca[label] = {
            "discovery_cycles": int(discovery_by_len.get(key) or 0),
            "cycles_found_unique": int(by_cycle_length.get(key) or 0),
            "cycles_quoteable_unique": int(cycles_quoteable_by_length.get(key) or 0),
            "quoteability_proven": int(cycles_quoteable_by_length.get(key) or 0) > 0,
        }
    three_four_proven = (
        int(cycles_quoteable_by_length.get("3") or 0) > 0
        or int(cycles_quoteable_by_length.get("4") or 0) > 0
    )
    productive_lane_gap: Dict[str, Any] = {
        "3_4_leg_quoteability_proven": three_four_proven,
        "discovery_has_3_4_cycles": any(
            int(discovery_by_len.get(k) or 0) > 0 for k in ("3", "4")
        ),
        "next_rca_focus": (
            None
            if three_four_proven
            else (
                "productive_lane_narrows_graph: discovery sees 3/4-leg cycles "
                "but runner quotes fewer unique cycles — check quarantine, "
                "depth-hard filter, and cycle productive prefilter"
            )
        ),
    }
    qsr_liveness_notes: List[str] = []
    if cycles_quoteable > 0 and float(qsr or 0) > 0:
        if qsr_liveness is not None and float(qsr_liveness or 0) == 0.0:
            qsr_liveness_notes.append(
                "qsr_liveness=0 with cycles_quoteable>0: liveness subset uses "
                "size_usd<=5 only; dynamic sizing may exclude all attempts"
            )
    per_dex_matrix: Dict[str, Any] = {}
    try:
        from m9.graph_arb.dex_quality_matrix import build_dex_quality_matrix

        per_dex_matrix = build_dex_quality_matrix(
            bridge=inventory,
            shadow=artifact,
        )
    except Exception:
        per_dex_matrix = {}

    amount_continuity_rca = _build_amount_continuity_rca(artifact)
    enriched_rows = _enrich_leg_rows_from_artifact(artifact)
    top_value_loss_legs = _build_top_value_loss_legs(artifact, inventory)
    adapter_leg_isolation = _build_adapter_leg_isolation(artifact, inventory)
    stable_outlier_count = len(
        {
            (r.get("cycle_id"), r.get("leg_idx"))
            for r in enriched_rows
            if r.get("stable_value_ratio_outlier")
        }
    )

    return {
        "schema_version": "m9_quote_lane_rca.8",
        "per_dex_funnel_matrix": per_dex_matrix.get("per_dex_funnel") or {},
        "dex_quality_matrix": per_dex_matrix.get("matrix") or {},
        "source_artifact": source_artifact or str(_DEFAULT_SHADOW),
        "source_graph_fingerprint": fp,
        "cycle_lengths_used": artifact.get("cycle_lengths_used") or [],
        "discovery_cycles_by_length": discovery_by_len,
        "cycles_found": cycles_found,
        "cycles_quoteable": cycles_quoteable,
        "qsr": qsr,
        "qsr_liveness": qsr_liveness,
        "qsr_econ": qsr_econ,
        "summary": {
            "cycles_found": cycles_found,
            "cycles_quoteable": cycles_quoteable,
            "cycles_positive_gross": int(artifact.get("cycles_positive_gross") or 0),
            "cycles_found_vs_quoteable_gap": max(cycles_found - cycles_quoteable, 0),
            "cycles_found_by_length": by_cycle_length,
            "cycles_quoteable_by_length": cycles_quoteable_by_length,
            "by_cycle_length_rca": by_cycle_length_rca,
            "productive_lane_3_4_gap": productive_lane_gap,
            "cross_mechanic_cycles": int(cross_mechanic_cycles or 0),
            "cross_mechanic_cycles_found": cm_found,
            "cross_mechanic_cycles_quoteable": cm_quoteable,
            "phantom_quote_count": phantom_count,
            "qsr": artifact.get("qsr"),
            "qsr_liveness": qsr_liveness,
            "qsr_econ": qsr_econ,
            "qsr_liveness_consistency_notes": qsr_liveness_notes,
            "economics_status": (
                "NOT_PROVEN"
                if int(artifact.get("cycles_positive_gross") or 0) == 0
                else "PARTIAL"
            ),
            "stable_value_ratio_outlier_legs": stable_outlier_count,
            "amount_continuity_violations": amount_continuity_rca.get("violation_count"),
        },
        "by_cycle_length_rca": by_cycle_length_rca,
        "productive_lane_3_4_gap": productive_lane_gap,
        "cycle_reject_histogram": cycle_reject,
        "by_adapter_family_leg_errors": dict(by_adapter),
        "by_dex_id_leg_errors": dict(by_dex_id),
        "by_reject_reason": dict(by_reject),
        "by_cycle_length": by_cycle_length,
        "cycles_quoteable_by_length": cycles_quoteable_by_length,
        "cycles_by_adapter_family": by_adapter_family_cycles,
        "route_error_histogram": route_level,
        "edge_error_histogram_top": edge_hist[:25],
        "top_20_failed_cycles": sample_failures,
        "sample_cycle_failures": sample_failures,
        "cycle_kill_leg_explanations": cycle_kill_explanations,
        "stamped_routes_in_inventory": sum(
            1
            for r in (inventory or {}).get("active_routes") or []
            if r.get("productive_quote_status")
        ),
        "balancer_top_revert_routes": balancer_rca,
        "maverick_top_revert_routes": maverick_rca,
        "maverick_top_rpc_error_routes": maverick_rca,
        "phantom_quote_diagnostics": phantom_diag,
        "m8_cycle_trace": _build_m8_cycle_trace(artifact, inventory),
        "micro_size_policy": _build_micro_size_policy(artifact),
        "cross_mechanic_diagnostic": cm_diag,
        "root_cause_hints": root_cause_hints,
        "amount_continuity_rca": amount_continuity_rca,
        "top_value_loss_legs": top_value_loss_legs,
        "adapter_leg_isolation": adapter_leg_isolation,
        "interpretation": (
            "cycles_found counts attempted cycle quotes; cycles_quoteable counts "
            "cycles with POSITIVE_GROSS or NEGATIVE_GROSS status only."
        ),
    }


def _run_pool_lane(args: argparse.Namespace) -> int:
    from m8.discovery.specialized_index_rpc import resolve_productive_rpc

    rpc = resolve_productive_rpc(args.chain)
    if not rpc:
        print("ERROR: no RPC", file=sys.stderr)
        return 1

    results = []
    if args.dex == "balancer_vault":
        from m8.discovery.balancer_indexer import build_balancer_index, load_balancer_config

        verified, metrics = build_balancer_index(
            chain=args.chain,
            rpc_url=rpc,
            watchlist_tokens=set(),
            connector_tokens=set(),
            use_graphql=True,
            verify_vault=True,
            quote_smoke=True,
        )
        for row in verified[: args.max_pools]:
            results.append(
                {
                    "pool_id": row.get("pool_id"),
                    "probe_status": row.get("probe_status"),
                    "quote_smoke_status": row.get("quote_smoke_status"),
                }
            )
        out_default = load_balancer_config(args.chain).get(
            "quote_debug_artifact", "data/tmp/m9_balancer_quote_debug_latest.json"
        )
    else:
        from m8.discovery.maverick_indexer import build_maverick_index, load_maverick_config

        cfg = load_maverick_config(args.chain)
        verified, metrics = build_maverick_index(
            chain=args.chain,
            rpc_url=rpc,
            watchlist_tokens=set(),
            connector_tokens=set(),
            scan_factory_pagination=True,
            verify_factory=True,
            quote_smoke=True,
        )
        for row in verified[: args.max_pools]:
            results.append(
                {
                    "pool_address": row.get("pool_address"),
                    "probe_status": row.get("probe_status"),
                    "quote_smoke_status": row.get("quote_smoke_status"),
                }
            )
        out_default = cfg.get("quote_debug_artifact", "data/tmp/m9_maverick_quote_debug_latest.json")

    payload = {
        "mode": "pool_lane",
        "dex": args.dex,
        "chain": args.chain,
        "metrics": metrics,
        "sample_pools": results,
    }
    out_path = Path(args.output or out_default)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def _run_cycle_rca(args: argparse.Namespace) -> int:
    art_path = Path(args.artifact or _DEFAULT_SHADOW)
    if not art_path.exists():
        print(f"ERROR: shadow artifact not found: {art_path}", file=sys.stderr)
        return 1
    artifact = json.loads(art_path.read_text(encoding="utf-8"))
    inv_path = Path(
        getattr(args, "inventory", None)
        or REPO_ROOT / "data/tmp/m9_bridge_inventory_shadow_latest.json"
    )
    inventory = (
        json.loads(inv_path.read_text(encoding="utf-8")) if inv_path.exists() else None
    )
    payload = build_cycle_rca(
        artifact, inventory=inventory, source_artifact=str(art_path)
    )
    out_path = Path(args.output or _DEFAULT_OUT)
    if out_path.exists():
        try:
            prior = json.loads(out_path.read_text(encoding="utf-8"))
            payload["prior_rca_consistency"] = check_rca_graph_consistency(
                prior, artifact
            )
        except (json.JSONDecodeError, OSError):
            payload["prior_rca_consistency"] = {"consistent": None}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if getattr(args, "strict_consistency", False):
        prior = payload.get("prior_rca_consistency") or {}
        if prior.get("consistent") is False:
            print(
                "ERROR: stale RCA vs graph:",
                prior.get("mismatched_fields"),
                file=sys.stderr,
            )
            return 1
    print(json.dumps(payload["summary"], indent=2))
    print(json.dumps(payload["by_adapter_family_leg_errors"], indent=2))
    print(json.dumps(payload["by_reject_reason"], indent=2))
    if payload["root_cause_hints"]:
        print("root_cause_hints:", payload["root_cause_hints"])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="M9 quote lane diagnostic (pool or cycle RCA)")
    ap.add_argument(
        "--mode",
        choices=["cycle-rca", "pool_lane"],
        default="cycle-rca",
        help="cycle-rca: parse shadow artifact; pool_lane: Balancer/Maverick smoke",
    )
    ap.add_argument("--dex", choices=["balancer_vault", "maverick_v2"], default=None)
    ap.add_argument("--chain", default="base")
    ap.add_argument("--output", default=None)
    ap.add_argument("--artifact", default=None, help="Bridge shadow graph artifact for cycle-rca")
    ap.add_argument("--inventory", default=None, help="Bridge inventory for cross-mechanic RCA")
    ap.add_argument(
        "--strict-consistency",
        action="store_true",
        help="Fail if prior RCA fingerprint mismatches source graph artifact",
    )
    ap.add_argument("--max-pools", type=int, default=5)
    args = ap.parse_args()

    if args.mode == "cycle-rca":
        return _run_cycle_rca(args)
    if not args.dex:
        print("ERROR: --dex required for pool_lane mode", file=sys.stderr)
        return 1
    return _run_pool_lane(args)


if __name__ == "__main__":
    sys.exit(main())
