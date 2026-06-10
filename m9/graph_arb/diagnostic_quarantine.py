"""Diagnostic vs production quarantine policy for M9 graph build."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set

from m9.graph_arb.route_quarantine import (
    _PERMANENT_QUARANTINE_REASONS,
    resolve_diagnostic_quarantine_pools,
    resolve_phantom_quarantine_addresses,
)

DIAGNOSTIC_QUARANTINE_MODES = frozenset({"production", "diagnostic_soft", "off"})

_DEFAULT_REVERT_PHANTOM_TTL_HOURS = 24.0
_DEFAULT_DIAGNOSTIC_MAX_AGE_HOURS = 6.0


@dataclass(frozen=True)
class QuarantinePlan:
    """Resolved pool exclusion / soft-tag sets for one runner build."""

    mode: str
    hard_exclude: FrozenSet[str] = frozenset()
    soft_tag: FrozenSet[str] = frozenset()
    breakdown: Dict[str, Any] = field(default_factory=dict)


def get_diagnostic_quarantine_mode() -> str:
    raw = os.environ.get("ARBY_M9_DIAGNOSTIC_QUARANTINE_MODE", "production").strip().lower()
    if raw in DIAGNOSTIC_QUARANTINE_MODES:
        return raw
    return "production"


def _parse_iso_age_hours(ts: Optional[str]) -> Optional[float]:
    if not ts:
        return None
    try:
        norm = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(norm)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(tz=timezone.utc) - dt).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return None


def _file_age_hours(path: Path) -> Optional[float]:
    if not path.exists():
        return None
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return (datetime.now(tz=timezone.utc) - mtime).total_seconds() / 3600.0
    except OSError:
        return None


def _pools_from_revert_data(data: Dict[str, Any]) -> Dict[str, str]:
    """Map pool_address → quarantine/reject reason."""
    out: Dict[str, str] = {}
    for row in data.get("routes") or []:
        pool = str(row.get("pool_address") or "").strip().lower()
        if not pool:
            continue
        reason = str(
            row.get("quarantine_reason")
            or row.get("reject_reason")
            or "QUOTE_REVERT"
        )
        out[pool] = reason
    return out


def _permanent_pool_set(pool_reasons: Dict[str, str]) -> Set[str]:
    permanent: Set[str] = set()
    for pool, reason in pool_reasons.items():
        upper = reason.upper()
        if reason in _PERMANENT_QUARANTINE_REASONS:
            permanent.add(pool)
        elif "PERMANENT" in upper or "PAUSED" in upper or "SWAPS_DISABLED" in upper:
            permanent.add(pool)
    return permanent


def filter_revert_pools_with_ttl(
    data: Dict[str, Any],
    *,
    file_path: Optional[Path] = None,
    ttl_hours: Optional[float] = None,
) -> tuple[Set[str], Set[str], bool]:
    """Return (hard_exclude, soft_candidates, ttl_expired)."""
    ttl = (
        float(ttl_hours)
        if ttl_hours is not None
        else float(os.environ.get("ARBY_M9_QUARANTINE_TTL_HOURS", _DEFAULT_REVERT_PHANTOM_TTL_HOURS))
    )
    pool_reasons = _pools_from_revert_data(data)
    if not pool_reasons:
        return set(), set(), False

    age_h = _parse_iso_age_hours(data.get("updated_at_utc"))
    if age_h is None and file_path is not None:
        age_h = _file_age_hours(file_path)
    ttl_expired = age_h is not None and age_h > ttl

    permanent = _permanent_pool_set(pool_reasons)
    all_pools = set(pool_reasons)
    if ttl_expired:
        return permanent, all_pools - permanent, True
    return all_pools, set(), False


def filter_phantom_pools_with_ttl(
    data: Dict[str, Any],
    *,
    file_path: Optional[Path] = None,
    ttl_hours: Optional[float] = None,
) -> tuple[Set[str], Set[str], bool]:
    """Return (hard_exclude, soft_candidates, ttl_expired) for phantom file."""
    ttl = (
        float(ttl_hours)
        if ttl_hours is not None
        else float(os.environ.get("ARBY_M9_QUARANTINE_TTL_HOURS", _DEFAULT_REVERT_PHANTOM_TTL_HOURS))
    )
    pools = {p.lower() for p in resolve_phantom_quarantine_addresses(data)}
    if not pools:
        return set(), set(), False
    age_h = _parse_iso_age_hours(data.get("updated_at_utc"))
    if age_h is None and file_path is not None:
        age_h = _file_age_hours(file_path)
    ttl_expired = age_h is not None and age_h > ttl
    if ttl_expired:
        return set(), pools, True
    return pools, set(), False


def resolve_diagnostic_quarantine_pools_fresh(
    diag: Dict[str, Any],
    *,
    max_age_hours: Optional[float] = None,
) -> tuple[Set[str], bool]:
    """Diagnostic pools to exclude; second value True when artifact is stale."""
    max_age = (
        float(max_age_hours)
        if max_age_hours is not None
        else float(
            os.environ.get(
                "ARBY_M9_DIAGNOSTIC_QUARANTINE_MAX_AGE_HOURS",
                _DEFAULT_DIAGNOSTIC_MAX_AGE_HOURS,
            )
        )
    )
    ts = diag.get("run_timestamp") or diag.get("generated_at_utc") or diag.get("updated_at_utc")
    age_h = _parse_iso_age_hours(ts)
    if age_h is not None and age_h > max_age:
        return set(), True
    return resolve_diagnostic_quarantine_pools(diag), False


def _sample_pools(pools: Set[str], limit: int = 8) -> List[str]:
    return sorted(pools)[:limit]


def build_quarantine_plan(
    *,
    depth_hard_pools: Set[str],
    revert_data: Optional[Dict[str, Any]] = None,
    revert_path: Optional[str] = None,
    phantom_data: Optional[Dict[str, Any]] = None,
    phantom_path: Optional[str] = None,
    diagnostic_data: Optional[Dict[str, Any]] = None,
    diagnostic_path: Optional[str] = None,
    legacy_revert_pools: Optional[Set[str]] = None,
) -> QuarantinePlan:
    """Merge quarantine sources according to ``ARBY_M9_DIAGNOSTIC_QUARANTINE_MODE``."""
    mode = get_diagnostic_quarantine_mode()
    hard: Set[str] = {p.lower() for p in depth_hard_pools}
    soft: Set[str] = set()
    breakdown: Dict[str, Any] = {
        "mode": mode,
        "depth_hard": {"count": len(depth_hard_pools), "samples": _sample_pools(depth_hard_pools)},
        "revert": {"count": 0, "permanent": 0, "ttl_expired": False, "samples": []},
        "phantom": {"count": 0, "ttl_expired": False, "samples": []},
        "diagnostic": {"count": 0, "stale": False, "samples": []},
        "legacy_revert_resolved": 0,
    }

    if mode == "off":
        breakdown["note"] = "feedback_quarantine_disabled"
        return QuarantinePlan(mode=mode, hard_exclude=frozenset(hard), soft_tag=frozenset(), breakdown=breakdown)

    rev_path = Path(revert_path) if revert_path else None
    if revert_data:
        rev_hard, rev_soft, rev_ttl = filter_revert_pools_with_ttl(
            revert_data, file_path=rev_path
        )
        if legacy_revert_pools:
            rev_hard |= {p.lower() for p in legacy_revert_pools}
            breakdown["legacy_revert_resolved"] = len(legacy_revert_pools)
        rev_all = rev_hard | rev_soft
        rev_permanent = _permanent_pool_set(_pools_from_revert_data(revert_data))
        breakdown["revert"] = {
            "count": len(rev_all),
            "permanent": len(rev_permanent),
            "ttl_expired": rev_ttl,
            "samples": _sample_pools(rev_all),
        }
        if mode == "diagnostic_soft":
            hard |= rev_permanent
            soft |= rev_all - rev_permanent
        else:
            hard |= rev_all

    ph_path = Path(phantom_path) if phantom_path else None
    if phantom_data:
        ph_hard, ph_soft, ph_ttl = filter_phantom_pools_with_ttl(
            phantom_data, file_path=ph_path
        )
        ph_all = ph_hard | ph_soft
        breakdown["phantom"] = {
            "count": len(ph_all),
            "ttl_expired": ph_ttl,
            "samples": _sample_pools(ph_all),
        }
        if mode == "diagnostic_soft":
            soft |= ph_all
        else:
            hard |= ph_all

    if diagnostic_data:
        diag_pools, diag_stale = resolve_diagnostic_quarantine_pools_fresh(diagnostic_data)
        breakdown["diagnostic"] = {
            "count": len(diag_pools),
            "stale": diag_stale,
            "samples": _sample_pools(diag_pools),
        }
        if not diag_stale:
            if mode == "diagnostic_soft":
                soft |= diag_pools
            else:
                hard |= diag_pools

    breakdown["hard_exclude_total"] = len(hard)
    breakdown["soft_tag_total"] = len(soft)
    return QuarantinePlan(
        mode=mode,
        hard_exclude=frozenset(hard),
        soft_tag=frozenset(soft),
        breakdown=breakdown,
    )


def _artifact_graph_metrics(artifact: Dict[str, Any]) -> Dict[str, Any]:
    scope = artifact.get("scan_scope") or {}
    return {
        "cycles_found": artifact.get("cycles_found_topology")
        or artifact.get("cycles_found")
        or scope.get("cycles_after_quarantine"),
        "cycles_before_quarantine": scope.get("cycles_before_quarantine"),
        "cycles_after_quarantine": scope.get("cycles_after_quarantine"),
        "cycles_quoteable": artifact.get("cycles_quoteable"),
        "actual_http_calls": artifact.get("actual_http_calls"),
        "quarantine_mode": scope.get("diagnostic_quarantine_mode"),
        "quarantine_breakdown": scope.get("quarantine_exclusion_breakdown"),
    }


def evaluate_quarantine_ab_pass(
    production_artifact: Dict[str, Any],
    diagnostic_soft_artifact: Dict[str, Any],
) -> Dict[str, Any]:
    """P1/P2 gate: PASS only if diagnostic_soft improves topology or prod drop is permanent."""
    prod = _artifact_graph_metrics(production_artifact)
    diag = _artifact_graph_metrics(diagnostic_soft_artifact)
    prod_cycles = int(prod.get("cycles_after_quarantine") or prod.get("cycles_found") or 0)
    diag_cycles = int(diag.get("cycles_after_quarantine") or diag.get("cycles_found") or 0)
    improved = diag_cycles > prod_cycles
    prod_breakdown = prod.get("quarantine_breakdown") or {}
    permanent_only = (
        prod_cycles == 0
        and int((prod_breakdown.get("revert") or {}).get("permanent", 0)) > 0
        and int((prod_breakdown.get("revert") or {}).get("count", 0))
        == int((prod_breakdown.get("revert") or {}).get("permanent", 0))
    )
    status = "PASS" if improved or (prod_cycles == 0 and permanent_only) else "FAIL"
    return {
        "status": status,
        "production": prod,
        "diagnostic_soft": diag,
        "cycles_delta": diag_cycles - prod_cycles,
        "production_drop_explained_by_permanent_quarantine": permanent_only,
    }
