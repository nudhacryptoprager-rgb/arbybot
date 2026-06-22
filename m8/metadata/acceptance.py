"""M8.3 strict acceptance gates."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from m8.metadata.registry import SCHEMA_VERSION, SCHEMA_VERSION_LEGACY

CYCLE_PARTICIPATING_DECIMALS_MIN = 0.95
DEX_ROUTE_METADATA_READY_MIN = 0.95
POOL_IDENTITY_VERIFIED_MIN = 0.95
_VALID_SCHEMAS = frozenset({SCHEMA_VERSION, SCHEMA_VERSION_LEGACY})
_M8_3_BLOCKERS = frozenset(
    {
        "M8_3_REGISTRY_MISSING",
        "M8_3_DECIMALS_CONFLICT",
        "M8_3_CYCLE_PARTICIPATING_DECIMALS_LOW",
        "M8_3_ECON_CAPACITY_METADATA_MISSING",
        "M8_3_REGISTRY_SCHEMA_INVALID",
        "M8_3_DEX_ROUTE_METADATA_LOW",
        "M8_3_ECON_CAPACITY_DEX_METADATA_MISSING",
        "M8_3_POOL_IDENTITY_LOW",
        "M8_3_ECON_CAPACITY_POOL_IDENTITY_MISSING",
    }
)


def evaluate_m8_3_acceptance(
    registry: Optional[Dict[str, Any]],
    *,
    strict: bool = False,
    cycle_participating_min: float = CYCLE_PARTICIPATING_DECIMALS_MIN,
    dex_route_metadata_min: float = DEX_ROUTE_METADATA_READY_MIN,
    pool_identity_min: float = POOL_IDENTITY_VERIFIED_MIN,
) -> Dict[str, Any]:
    """Evaluate M8.3 registry against strict gates."""
    blockers: List[str] = []
    if not registry:
        blockers.append("M8_3_REGISTRY_MISSING")
        return {
            "goal_status": "BLOCKED",
            "strict": strict,
            "m8_3_blockers": blockers,
            "gate_results": {},
            "token_metadata_gates": {},
            "dex_route_metadata_gates": {},
            "risk_metadata_warnings": {},
            "pool_identity_gates": {},
        }

    if registry.get("schema_version") not in _VALID_SCHEMAS:
        blockers.append("M8_3_REGISTRY_SCHEMA_INVALID")

    coverage = registry.get("coverage") or {}
    conflict_count = int(coverage.get("decimals_conflict_count") or 0)
    if conflict_count > 0:
        blockers.append("M8_3_DECIMALS_CONFLICT")

    route_cov = registry.get("route_coverage") or {}
    cycle = route_cov.get("cycle_participating_routes") or {}
    cycle_rate = float(cycle.get("economics_grade_known_rate") or 0.0)
    if cycle.get("legs_total", 0) > 0 and cycle_rate < cycle_participating_min:
        blockers.append("M8_3_CYCLE_PARTICIPATING_DECIMALS_LOW")

    econ_cap = route_cov.get("econ_capacity_routes") or {}
    econ_missing = len(_capacity_routes_without_economics_grade(registry))
    if econ_cap.get("routes_count", 0) > 0:
        missing_rate = 1.0 - float(econ_cap.get("economics_grade_known_rate") or 0.0)
        if missing_rate > 0 and econ_missing > 0:
            blockers.append("M8_3_ECON_CAPACITY_METADATA_MISSING")

    dex_cov = (registry.get("dex_route_metadata") or {}).get("coverage") or {}
    cycle_dex = dex_cov.get("cycle_participating_routes") or {}
    cycle_dex_rate = float(cycle_dex.get("dex_metadata_ready_rate") or 0.0)
    if cycle_dex.get("routes_count", 0) > 0 and cycle_dex_rate < dex_route_metadata_min:
        blockers.append("M8_3_DEX_ROUTE_METADATA_LOW")

    econ_dex = dex_cov.get("econ_capacity_routes") or {}
    econ_dex_rate = float(econ_dex.get("dex_metadata_ready_rate") or 0.0)
    if econ_dex.get("routes_count", 0) > 0 and econ_dex_rate < dex_route_metadata_min:
        blockers.append("M8_3_ECON_CAPACITY_DEX_METADATA_MISSING")

    pool_cov = (registry.get("pool_identity_metadata") or {}).get("coverage") or {}
    cycle_pool = pool_cov.get("cycle_participating_routes") or {}
    cycle_pool_rate = float(cycle_pool.get("pool_identity_verified_rate") or 0.0)
    if cycle_pool.get("routes_count", 0) > 0 and cycle_pool_rate < pool_identity_min:
        blockers.append("M8_3_POOL_IDENTITY_LOW")

    econ_pool = pool_cov.get("econ_capacity_routes") or {}
    econ_pool_rate = float(econ_pool.get("pool_identity_verified_rate") or 0.0)
    if econ_pool.get("routes_count", 0) > 0 and econ_pool_rate < pool_identity_min:
        blockers.append("M8_3_ECON_CAPACITY_POOL_IDENTITY_MISSING")

    risk_metadata_warnings = _build_risk_metadata_warnings(registry)

    goal = "REACHED" if not blockers else "BLOCKED"
    if strict and blockers:
        goal = "BLOCKED"

    diagnostics = build_m8_3_diagnostics(registry)

    token_metadata_gates = {
        "cycle_participating_token_metadata_rate": cycle_rate,
        "cycle_participating_min_required": cycle_participating_min,
        "econ_capacity_token_metadata_missing": econ_missing,
        "decimals_conflict_count": conflict_count,
    }
    dex_route_metadata_gates = {
        "cycle_participating_dex_route_metadata_ready_rate": cycle_dex_rate,
        "econ_capacity_dex_route_metadata_ready_rate": econ_dex_rate,
        "dex_route_metadata_min_required": dex_route_metadata_min,
        "dex_routes_tracked": int(coverage.get("dex_routes_tracked") or 0),
        "dex_routes_ready": int(coverage.get("dex_routes_ready") or 0),
    }
    pool_identity_gates = {
        "cycle_participating_pool_identity_verified_rate": cycle_pool_rate,
        "econ_capacity_pool_identity_verified_rate": econ_pool_rate,
        "pool_identity_min_required": pool_identity_min,
    }

    return {
        "goal_status": goal,
        "strict": strict,
        "m8_3_blockers": sorted(set(blockers)),
        "gate_results": {
            "decimals_conflict_count": conflict_count,
            "cycle_participating_decimals_known_rate": cycle_rate,
            "cycle_participating_min_required": cycle_participating_min,
            "economics_grade_missing_for_capacity_routes": econ_missing,
            "route_coverage": route_cov,
            "coverage": coverage,
            "dex_route_coverage": dex_cov,
        },
        "token_metadata_gates": token_metadata_gates,
        "dex_route_metadata_gates": dex_route_metadata_gates,
        "risk_metadata_warnings": risk_metadata_warnings,
        "pool_identity_gates": pool_identity_gates,
        "diagnostics": diagnostics,
    }


def _build_risk_metadata_warnings(registry: Dict[str, Any]) -> Dict[str, Any]:
    """Warning-only risk summary; NON_ERC20 out of cycle scope is not a strict gate."""
    from m8.metadata.aggregator import get_token_risk_metadata
    from m8.metadata.token_risk import risk_warnings_for_token

    cycle_addrs = set(
        (registry.get("route_coverage") or {})
        .get("cycle_participating_routes", {})
        .get("token_addrs")
        or []
    )
    risks = get_token_risk_metadata(registry)
    non_erc20_in_cycle = 0
    non_erc20_out_of_scope = 0
    proxy_count = 0
    behavior_counts: Counter[str] = Counter()

    for addr, row in risks.items():
        if row.get("proxy_detected"):
            proxy_count += 1
        reason = row.get("non_erc20_reason")
        if reason:
            if addr in cycle_addrs:
                non_erc20_in_cycle += 1
            else:
                non_erc20_out_of_scope += 1
        for w in risk_warnings_for_token(row):
            if w not in ("NO_CODE", "NON_ERC20", "ERC20_DECIMALS_REVERT"):
                behavior_counts[w] += 1

    return {
        "warning_only": True,
        "non_erc20_in_cycle_count": non_erc20_in_cycle,
        "non_erc20_out_of_scope_count": non_erc20_out_of_scope,
        "proxy_detected_count": proxy_count,
        "behavior_flag_counts": dict(sorted(behavior_counts.items())),
    }


def build_m8_3_diagnostics(registry: Dict[str, Any]) -> Dict[str, Any]:
    """Route/token-level offenders for operator triage."""
    from m8.metadata.aggregator import build_m8_3_worker_diagnostics, get_token_registry
    from m8.metadata.registry import is_economics_grade_entry

    tokens = get_token_registry(registry)
    missing_by_error: Counter[str] = Counter()
    missing_by_source: Counter[str] = Counter()
    top_missing_all_tokens: List[Dict[str, Any]] = []
    cycle_token_addrs = set(
        (registry.get("route_coverage") or {})
        .get("cycle_participating_routes", {})
        .get("token_addrs")
        or []
    )

    for addr, row in tokens.items():
        if is_economics_grade_entry(row):
            continue
        err = str(row.get("error_code") or "DECIMALS_UNRESOLVED")
        src = str(row.get("source") or "unresolved")
        wid = str(row.get("worker_id") or "erc20_token")
        missing_by_error[err] += 1
        missing_by_source[src] += 1
        if len(top_missing_all_tokens) < 20:
            top_missing_all_tokens.append(
                {
                    "address": addr,
                    "source": src,
                    "worker_id": wid,
                    "error_code": err,
                    "economics_grade": row.get("economics_grade"),
                }
            )

    top_missing_cycle_tokens: List[Dict[str, Any]] = []
    if cycle_token_addrs:
        for addr, row in tokens.items():
            if addr not in cycle_token_addrs:
                continue
            if is_economics_grade_entry(row):
                continue
            if len(top_missing_cycle_tokens) >= 20:
                break
            top_missing_cycle_tokens.append(
                {
                    "address": addr,
                    "source": str(row.get("source") or "unresolved"),
                    "worker_id": str(row.get("worker_id") or "erc20_token"),
                    "error_code": str(row.get("error_code") or "DECIMALS_UNRESOLVED"),
                    "economics_grade": row.get("economics_grade"),
                }
            )

    cycle_route_ids = set(
        (registry.get("route_coverage") or {})
        .get("cycle_participating_routes", {})
        .get("route_ids")
        or []
    )
    top_missing_capacity_routes: List[str] = list(cycle_route_ids)[:20]

    worker_diag = build_m8_3_worker_diagnostics(registry)

    return {
        "top_missing_all_tokens": top_missing_all_tokens,
        "top_missing_cycle_tokens": top_missing_cycle_tokens,
        "top_missing_capacity_routes": top_missing_capacity_routes,
        "missing_by_source": dict(sorted(missing_by_source.items())),
        "missing_by_error_code": dict(sorted(missing_by_error.items())),
        **worker_diag,
    }


def _capacity_routes_without_economics_grade(registry: Dict[str, Any]) -> List[str]:
    """Route ids in econ_capacity scope lacking economics-grade on any leg."""
    missing: List[str] = []
    route_cov = registry.get("route_coverage") or {}
    econ = route_cov.get("econ_capacity_routes") or {}
    if int(econ.get("routes_count") or 0) == 0:
        return missing
    rate = float(econ.get("economics_grade_known_rate") or 0.0)
    if rate >= 1.0:
        return missing
    if rate < 1.0:
        missing.append("econ_capacity_scope")
    return missing


def is_m8_3_ready(acceptance: Dict[str, Any]) -> bool:
    return acceptance.get("goal_status") == "REACHED" and not acceptance.get("m8_3_blockers")
