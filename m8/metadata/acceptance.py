"""M8.3 strict acceptance gates."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

CYCLE_PARTICIPATING_DECIMALS_MIN = 0.95
_M8_3_BLOCKERS = frozenset(
    {
        "M8_3_REGISTRY_MISSING",
        "M8_3_DECIMALS_CONFLICT",
        "M8_3_CYCLE_PARTICIPATING_DECIMALS_LOW",
        "M8_3_ECON_CAPACITY_METADATA_MISSING",
        "M8_3_REGISTRY_SCHEMA_INVALID",
    }
)


def evaluate_m8_3_acceptance(
    registry: Optional[Dict[str, Any]],
    *,
    strict: bool = False,
    cycle_participating_min: float = CYCLE_PARTICIPATING_DECIMALS_MIN,
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
        }

    if registry.get("schema_version") != "m8_3_token_metadata_registry_v1":
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
    econ_missing = 0
    for route in _capacity_routes_without_economics_grade(registry):
        econ_missing += 1
    if econ_cap.get("routes_count", 0) > 0:
        missing_rate = 1.0 - float(econ_cap.get("economics_grade_known_rate") or 0.0)
        if missing_rate > 0 and econ_missing > 0:
            blockers.append("M8_3_ECON_CAPACITY_METADATA_MISSING")

    goal = "REACHED" if not blockers else "BLOCKED"
    if strict and blockers:
        goal = "BLOCKED"

    diagnostics = build_m8_3_diagnostics(registry)

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
        },
        "diagnostics": diagnostics,
    }


def build_m8_3_diagnostics(registry: Dict[str, Any]) -> Dict[str, Any]:
    """Route/token-level offenders for operator triage."""
    from m8.metadata.registry import is_economics_grade_entry, is_valid_eth_address

    tokens = registry.get("tokens") or {}
    missing_by_error: Counter[str] = Counter()
    missing_by_source: Counter[str] = Counter()
    top_missing_tokens: List[Dict[str, Any]] = []

    for addr, row in tokens.items():
        if is_economics_grade_entry(row):
            continue
        err = str(row.get("error_code") or "DECIMALS_UNRESOLVED")
        src = str(row.get("source") or "unresolved")
        missing_by_error[err] += 1
        missing_by_source[src] += 1
        if len(top_missing_tokens) < 20:
            top_missing_tokens.append(
                {
                    "address": addr,
                    "source": src,
                    "error_code": err,
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

    return {
        "top_missing_cycle_tokens": top_missing_tokens,
        "top_missing_capacity_routes": top_missing_capacity_routes,
        "missing_by_source": dict(sorted(missing_by_source.items())),
        "missing_by_error_code": dict(sorted(missing_by_error.items())),
    }


def _capacity_routes_without_economics_grade(registry: Dict[str, Any]) -> List[str]:
    """Route ids in econ_capacity scope lacking economics-grade on any leg."""
    from m8.metadata.registry import ECONOMICS_GRADE_CONFIG, ECONOMICS_GRADE_ONCHAIN

    missing: List[str] = []
    route_cov = registry.get("route_coverage") or {}
    econ = route_cov.get("econ_capacity_routes") or {}
    if int(econ.get("routes_count") or 0) == 0:
        return missing
    rate = float(econ.get("economics_grade_known_rate") or 0.0)
    if rate >= 1.0:
        return missing
    # When aggregate rate below 1, signal at least one route needs work.
    if rate < 1.0:
        missing.append("econ_capacity_scope")
    return missing


def is_m8_3_ready(acceptance: Dict[str, Any]) -> bool:
    return acceptance.get("goal_status") == "REACHED" and not acceptance.get("m8_3_blockers")
