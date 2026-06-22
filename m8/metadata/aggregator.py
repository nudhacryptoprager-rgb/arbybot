"""M8.3 root metadata aggregator — sole authority merge point."""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Set, Tuple

from m8.metadata.contracts import DexRouteMetadataResult, MetadataAuthorityDecision, TokenMetadataResult
from m8.metadata.dex.base import all_dex_workers, assign_route_worker, route_id_of
from m8.metadata.dex.erc20 import Erc20TokenWorker
from m8.metadata.registry import (
    SCHEMA_VERSION,
    _external_hint_map,
    _hint_map_from_routes,
    _route_scope_ids,
    _route_coverage_metrics,
    _verified_registry_cache_row,
    collect_token_addresses,
    is_economics_grade_entry,
    is_valid_eth_address,
)

log = logging.getLogger(__name__)

AUTHORITY_CONTRACT = "m8_3_aggregated_metadata_authority"


def build_aggregated_registry(
    *,
    chain: str = "base",
    bridge: Optional[Dict[str, Any]] = None,
    expansion: Optional[Dict[str, Any]] = None,
    sniper: Optional[Dict[str, Any]] = None,
    anchor: Optional[Dict[str, Any]] = None,
    external_hints: Optional[Dict[str, Any]] = None,
    prior_registry: Optional[Dict[str, Any]] = None,
    capacity: Optional[Dict[str, Any]] = None,
    cfg: Any = None,
    w3: Any = None,
    onchain_unresolved_only: bool = True,
    max_onchain_probes: Optional[int] = None,
    with_dex_workers: bool = True,
) -> Dict[str, Any]:
    """Build rolling M8.3 artifact via root scheduler + child workers."""
    from m8.metadata.registry import SOURCE_M8_1, SOURCE_M8_2, SOURCE_M8_SNIPER, _utc_now

    addrs = collect_token_addresses(
        bridge=bridge,
        expansion=expansion,
        sniper=sniper,
        anchor=anchor,
        external_hints=external_hints,
    )
    registry_cache: Dict[str, Dict[str, Any]] = {}
    prior_tokens = (prior_registry or {}).get("token_registry") or (prior_registry or {}).get("tokens") or {}
    for addr, row in prior_tokens.items():
        if isinstance(row, dict) and row.get("decimals") is not None and _verified_registry_cache_row(row):
            registry_cache[str(addr).lower()] = row

    sniper_hints = _hint_map_from_routes(
        (sniper or {}).get("recent_events") or [], source=SOURCE_M8_SNIPER
    )
    m81_hints = _hint_map_from_routes((anchor or {}).get("routes") or [], source=SOURCE_M8_1)
    m82_hints = _hint_map_from_routes(
        (expansion or {}).get("routes_admitted") or [], source=SOURCE_M8_2
    )
    ext_hints = _external_hint_map(external_hints)

    erc20 = Erc20TokenWorker()
    token_results: Dict[str, Dict[str, Any]] = {}
    token_decisions: List[Dict[str, Any]] = []
    worker_errors: Counter[str] = Counter()
    onchain_used = 0
    sorted_addrs = sorted(addrs)

    for addr in sorted_addrs:
        prior = registry_cache.get(addr)
        use_w3 = w3
        probe_cap_exhausted = False
        if max_onchain_probes is not None and onchain_used >= max_onchain_probes:
            use_w3 = None
            probe_cap_exhausted = prior is None or not is_economics_grade_entry(prior)

        if onchain_unresolved_only and prior and is_economics_grade_entry(prior):
            entry = dict(prior)
            entry.setdefault("address", addr)
            entry["source_provenance"] = "m8_3"
            entry["worker_id"] = "erc20_token"
            token_results[addr] = entry
            token_decisions.append(
                asdict(
                    MetadataAuthorityDecision(
                        entity_id=addr,
                        entity_kind="token_erc20",
                        accepted=True,
                        reason="prior_economics_grade_cache",
                        precedence_rank=1,
                    )
                )
            )
            continue

        task = erc20.build_task(addr)
        had_w3 = use_w3 is not None
        result: TokenMetadataResult = erc20.process(
            task,
            cfg=cfg,
            sniper_hints=sniper_hints,
            m81_hints=m81_hints,
            m82_hints=m82_hints,
            registry_cache=registry_cache,
            external_hints=ext_hints,
            w3=use_w3,
            probe_cap_exhausted=probe_cap_exhausted,
        )
        if had_w3 and use_w3 is not None:
            onchain_used += 1
        if result.error_code:
            worker_errors[str(result.error_code)] += 1
        entry = {
            "address": addr,
            "symbol": result.symbol,
            "name": result.name,
            "decimals": result.decimals,
            "source": result.source,
            "economics_grade": result.economics_grade,
            "error_code": result.error_code,
            "code_length": result.code_length,
            "worker_id": result.worker_id,
            "source_provenance": "m8_3",
        }
        token_results[addr] = entry
        token_decisions.append(
            asdict(
                MetadataAuthorityDecision(
                    entity_id=addr,
                    entity_kind="token_erc20",
                    accepted=result.decimals is not None and not result.error_code,
                    reason=str(result.error_code or result.source),
                    precedence_rank=2 if is_economics_grade_entry(entry) else 0,
                )
            )
        )

    from m8.metadata.token_risk import build_token_risk_metadata

    token_risk_metadata: Dict[str, Dict[str, Any]] = {}
    for addr, entry in token_results.items():
        token_risk_metadata[addr] = build_token_risk_metadata(
            addr,
            w3=w3,
            code_length=entry.get("code_length"),
            error_code=entry.get("error_code"),
            decimals_resolved=entry.get("decimals") is not None,
        )

    all_routes = list((bridge or {}).get("active_routes") or []) + list(
        (bridge or {}).get("exploration_routes") or []
    )
    scopes = _route_scope_ids(bridge, capacity=capacity)
    dex_by_route: Dict[str, Dict[str, Any]] = {}
    per_worker_metrics: Dict[str, Dict[str, Any]] = {}
    dex_route_results: List[DexRouteMetadataResult] = []
    token_tasks_assigned = len(sorted_addrs)
    token_tasks_completed = sum(1 for t in token_results.values() if t.get("decimals") is not None)
    token_tasks_failed = token_tasks_assigned - token_tasks_completed
    dex_tasks_assigned = 0
    dex_tasks_completed = 0
    dex_tasks_failed = 0

    if with_dex_workers:
        workers = all_dex_workers()
        seen_routes: Set[str] = set()
        for route in all_routes:
            rid = route_id_of(route)
            if not rid or rid in seen_routes:
                continue
            seen_routes.add(rid)
            worker = assign_route_worker(route, workers)
            if worker is None:
                continue
            scope = _route_scope_for_id(rid, scopes)
            task = worker.build_task(route, scope=scope)
            if task is None:
                continue
            dex_tasks_assigned += 1
            result = worker.process(task, w3=w3)
            dex_route_results.append(result)
            dex_by_route[rid] = _dex_result_to_dict(result)
            wm = per_worker_metrics.setdefault(
                result.worker_id,
                {"assigned": 0, "completed": 0, "failed": 0, "errors": {}, "failure_samples": []},
            )
            wm["assigned"] += 1
            if result.ready:
                wm["completed"] += 1
                dex_tasks_completed += 1
            else:
                wm["failed"] += 1
                dex_tasks_failed += 1
                if result.error_code:
                    err_hist = wm["errors"]
                    err_hist[str(result.error_code)] = err_hist.get(str(result.error_code), 0) + 1
                    worker_errors[str(result.error_code)] += 1
                samples = wm.setdefault("failure_samples", [])
                if len(samples) < 5:
                    samples.append(_worker_failure_sample(result))

    dex_route_coverage = _dex_route_coverage(all_routes, dex_by_route, scopes)

    from m8.metadata.pool_identity import build_pool_identity_metadata

    pool_identity_metadata = build_pool_identity_metadata(
        all_routes, dex_by_route, scopes=scopes
    )
    conflict_count = sum(
        1 for t in token_results.values() if t.get("error_code") == "DECIMALS_CONFLICT"
    )
    unresolved_count = sum(
        1
        for t in token_results.values()
        if t.get("error_code")
        in ("DECIMALS_UNRESOLVED", "ERC20_DECIMALS_REVERT", "NO_CODE", "NON_ERC20", "PROBE_CAP_EXHAUSTED")
    )
    econ_verified = sum(1 for t in token_results.values() if is_economics_grade_entry(t))

    route_coverage = {
        scope: {
            **_route_coverage_metrics(all_routes, token_results, route_ids=ids if ids else None),
            "route_ids": sorted(ids) if ids else [],
            "token_addrs": sorted(_scope_token_addrs(all_routes, ids)),
        }
        for scope, ids in scopes.items()
    }

    token_task_funnel = {
        "tasks_assigned": token_tasks_assigned,
        "tasks_completed": token_tasks_completed,
        "tasks_failed": token_tasks_failed,
    }
    dex_route_task_funnel = {
        "tasks_assigned": dex_tasks_assigned,
        "tasks_completed": dex_tasks_completed,
        "tasks_failed": dex_tasks_failed,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "chain": chain,
        "generated_at_utc": _utc_now(),
        "scope": "M8.3_token_metadata_registry",
        "truth_boundary": "on_chain_verified_required_for_economics_grade",
        "authority_contract": AUTHORITY_CONTRACT,
        "task_mode": "aggregated" if with_dex_workers else "token_only",
        "preflight_contract": "metadata_risk_pool_identity_v1",
        "token_registry": token_results,
        "tokens": token_results,
        "token_risk_metadata": {"by_address": token_risk_metadata},
        "dex_route_metadata": {
            "by_route_id": dex_by_route,
            "coverage": dex_route_coverage,
        },
        "pool_identity_metadata": pool_identity_metadata,
        "task_funnel": {
            "tasks_assigned": token_tasks_assigned + dex_tasks_assigned,
            "tasks_completed": token_tasks_completed + dex_tasks_completed,
            "tasks_failed": token_tasks_failed + dex_tasks_failed,
            "token_tasks": token_tasks_assigned,
            "dex_route_tasks": dex_tasks_assigned,
            "token_task_funnel": token_task_funnel,
            "dex_route_task_funnel": dex_route_task_funnel,
        },
        "per_dex_worker_metrics": per_worker_metrics,
        "authority_decisions_sample": token_decisions[:50],
        "coverage": {
            "all_tokens_count": len(token_results),
            "resolved_decimals_count": sum(
                1 for t in token_results.values() if t.get("decimals") is not None
            ),
            "economics_grade_verified_count": econ_verified,
            "decimals_conflict_count": conflict_count,
            "unresolved_count": unresolved_count,
            "onchain_probes_used": onchain_used,
            "onchain_probes_cap": max_onchain_probes,
            "dex_routes_tracked": len(dex_by_route),
            "dex_routes_ready": sum(1 for r in dex_by_route.values() if r.get("ready")),
        },
        "route_coverage": route_coverage,
    }


def get_token_registry(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return dict(doc.get("token_registry") or doc.get("tokens") or {})


def get_dex_route_metadata(doc: Dict[str, Any]) -> Dict[str, Any]:
    return dict((doc.get("dex_route_metadata") or {}).get("by_route_id") or {})


def get_token_risk_metadata(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return dict((doc.get("token_risk_metadata") or {}).get("by_address") or {})


def get_pool_identity_metadata(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return dict((doc.get("pool_identity_metadata") or {}).get("by_route_id") or {})


def _route_scope_for_id(rid: str, scopes: Dict[str, Set[str]]) -> str:
    for scope, ids in scopes.items():
        if rid in ids:
            return scope
    return "all_routes"


def _scope_token_addrs(routes: List[Dict[str, Any]], route_ids: Optional[Set[str]]) -> Set[str]:
    out: Set[str] = set()
    for route in routes:
        if route_ids is not None and route_id_of(route) not in route_ids:
            continue
        for key in ("token0_addr", "token1_addr"):
            addr = route.get(key)
            if is_valid_eth_address(addr):
                out.add(str(addr).lower())
    return out


def _worker_failure_sample(result: DexRouteMetadataResult) -> Dict[str, Any]:
    meta = result.metadata or {}
    sample: Dict[str, Any] = {
        "route_id": result.route_id,
        "missing_fields": list(result.missing_fields or []),
        "error_code": result.error_code,
    }
    if result.worker_id == "maverick":
        sample["has_probe_by_token_in"] = meta.get("has_probe_by_token_in")
        sample["can_infer_token_a_b"] = meta.get("can_infer_token_a_b")
        sample["token_pair_source"] = meta.get("token_pair_source")
    return sample


def _dex_result_to_dict(result: DexRouteMetadataResult) -> Dict[str, Any]:
    return {
        "route_id": result.route_id,
        "worker_id": result.worker_id,
        "dex_family": result.dex_family,
        "ready": result.ready,
        "metadata": result.metadata,
        "error_code": result.error_code,
        "missing_fields": result.missing_fields,
        "quoteability_hint": result.quoteability_hint,
    }


def _dex_route_coverage(
    routes: List[Dict[str, Any]],
    dex_by_route: Dict[str, Dict[str, Any]],
    scopes: Dict[str, Set[str]],
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for scope, ids in scopes.items():
        scoped = [r for r in routes if route_id_of(r) in ids] if ids else routes
        total = len(scoped)
        ready = sum(1 for r in scoped if dex_by_route.get(route_id_of(r), {}).get("ready"))
        out[scope] = {
            "routes_count": total,
            "dex_metadata_ready_count": ready,
            "dex_metadata_ready_rate": round(ready / total, 4) if total else 0.0,
        }
    return out


def build_m8_3_worker_diagnostics(registry: Dict[str, Any]) -> Dict[str, Any]:
    """Worker-level diagnostics for acceptance report."""
    per_worker = registry.get("per_dex_worker_metrics") or {}
    funnel = registry.get("task_funnel") or {}
    top_missing_by_worker: Dict[str, List[str]] = {}
    worker_failure_samples: Dict[str, List[Dict[str, Any]]] = {}
    for wid, metrics in per_worker.items():
        if int(metrics.get("failed") or 0) > 0:
            top_missing_by_worker[wid] = list((metrics.get("errors") or {}).keys())[:10]
            worker_failure_samples[wid] = list(metrics.get("failure_samples") or [])[:5]

    dex_meta = registry.get("dex_route_metadata") or {}
    dex_cov = dex_meta.get("coverage") or {}
    return {
        "top_missing_by_worker": top_missing_by_worker,
        "worker_failure_samples": worker_failure_samples,
        "worker_error_histogram": _worker_error_histogram(registry),
        "tasks_assigned": funnel.get("tasks_assigned"),
        "tasks_completed": funnel.get("tasks_completed"),
        "tasks_failed": funnel.get("tasks_failed"),
        "token_task_funnel": funnel.get("token_task_funnel"),
        "dex_route_task_funnel": funnel.get("dex_route_task_funnel"),
        "per_dex_route_metadata_ready": {
            scope: row.get("dex_metadata_ready_rate")
            for scope, row in dex_cov.items()
        },
    }


def _worker_error_histogram(registry: Dict[str, Any]) -> Dict[str, int]:
    hist: Counter[str] = Counter()
    for row in get_token_registry(registry).values():
        err = row.get("error_code")
        wid = row.get("worker_id") or "erc20_token"
        if err:
            hist[f"{wid}:{err}"] += 1
    for row in get_dex_route_metadata(registry).values():
        err = row.get("error_code")
        wid = row.get("worker_id") or "unknown"
        if err:
            hist[f"{wid}:{err}"] += 1
    return dict(sorted(hist.items()))
