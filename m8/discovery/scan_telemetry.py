"""M8.2 active-scan coverage telemetry (token × dex × anchor matrix)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


def empty_scan_telemetry() -> Dict[str, Any]:
    return {
        "scan_expected_attempts": 0,
        "scan_actual_attempts": 0,
        "active_scan_attempted_by_dex": {},
        "active_scan_attempted_by_anchor": {},
        "active_scan_no_pool_by_dex": {},
        "active_scan_unsupported_dex_by_dex": {},
        "active_scan_skipped_dry_run_by_dex": {},
        "scan_attempt_matrix": {},
    }


def empty_candidate_scan_telemetry() -> Dict[str, Any]:
    return {
        "candidate_scan_expected_attempts": 0,
        "candidate_scan_actual_attempts": 0,
        "candidate_scan_attempted_by_dex": {},
        "candidate_scan_attempted_by_anchor": {},
        "candidate_scan_unsupported_by_dex": {},
        "candidate_scan_no_pool_by_dex": {},
        "candidate_dex_attempt_matrix": {},
    }


def record_scan_attempt(
    telemetry: Dict[str, Any],
    *,
    token_address: str,
    dex_id: str,
    anchor: str,
    attempted: bool,
    result: str,
    reason: str,
    pool_address: Optional[str] = None,
    count_expected: bool = True,
) -> None:
    """Record one active-scan attempt in counters and nested matrix."""
    token = token_address.lower()
    matrix = telemetry.setdefault("scan_attempt_matrix", {})
    token_row = matrix.setdefault(token, {})
    dex_row = token_row.setdefault(dex_id, {})
    dex_row[anchor] = {
        "attempted": attempted,
        "result": result,
        "reason": reason,
        "pool_address": pool_address,
    }

    if not attempted:
        return

    if count_expected:
        telemetry["scan_expected_attempts"] = int(
            telemetry.get("scan_expected_attempts", 0)
        ) + 1
    telemetry["scan_actual_attempts"] = int(
        telemetry.get("scan_actual_attempts", 0)
    ) + 1

    by_dex = telemetry.setdefault("active_scan_attempted_by_dex", {})
    by_dex[dex_id] = int(by_dex.get(dex_id, 0)) + 1

    by_anchor = telemetry.setdefault("active_scan_attempted_by_anchor", {})
    by_anchor[anchor] = int(by_anchor.get(anchor, 0)) + 1

    if result == "NO_POOL" or reason == "NO_POOL":
        no_pool = telemetry.setdefault("active_scan_no_pool_by_dex", {})
        no_pool[dex_id] = int(no_pool.get(dex_id, 0)) + 1
    elif result == "UNSUPPORTED_DEX" or reason == "UNSUPPORTED_DEX":
        unsup = telemetry.setdefault("active_scan_unsupported_dex_by_dex", {})
        unsup[dex_id] = int(unsup.get(dex_id, 0)) + 1
    elif result == "SKIPPED_DRY_RUN" or reason == "SKIPPED_DRY_RUN":
        dry = telemetry.setdefault("active_scan_skipped_dry_run_by_dex", {})
        dry[dex_id] = int(dry.get(dex_id, 0)) + 1


def record_candidate_scan_attempt(
    telemetry: Dict[str, Any],
    *,
    token_address: str,
    dex_id: str,
    anchor: str,
    registry_status: str,
    attempted: bool,
    result: str,
    reason: str,
    pool_address: Optional[str] = None,
    count_expected: bool = True,
) -> None:
    """Record one candidate-DEX coverage attempt (separate from canonical 13-DEX matrix)."""
    token = token_address.lower()
    matrix = telemetry.setdefault("candidate_dex_attempt_matrix", {})
    token_row = matrix.setdefault(token, {})
    dex_row = token_row.setdefault(dex_id, {})
    dex_row[anchor] = {
        "attempted": attempted,
        "registry_status": registry_status,
        "result": result,
        "reason": reason,
        "pool_address": pool_address,
    }

    if not attempted:
        return

    if count_expected:
        telemetry["candidate_scan_expected_attempts"] = int(
            telemetry.get("candidate_scan_expected_attempts", 0)
        ) + 1
    telemetry["candidate_scan_actual_attempts"] = int(
        telemetry.get("candidate_scan_actual_attempts", 0)
    ) + 1

    by_dex = telemetry.setdefault("candidate_scan_attempted_by_dex", {})
    by_dex[dex_id] = int(by_dex.get(dex_id, 0)) + 1

    by_anchor = telemetry.setdefault("candidate_scan_attempted_by_anchor", {})
    by_anchor[anchor] = int(by_anchor.get(anchor, 0)) + 1

    if result == "NO_POOL" or reason == "NO_POOL":
        no_pool = telemetry.setdefault("candidate_scan_no_pool_by_dex", {})
        no_pool[dex_id] = int(no_pool.get(dex_id, 0)) + 1
    elif result == "UNSUPPORTED_DEX" or str(reason).startswith("UNSUPPORTED"):
        unsup = telemetry.setdefault("candidate_scan_unsupported_by_dex", {})
        unsup[dex_id] = int(unsup.get(dex_id, 0)) + 1


def merge_candidate_scan_telemetry(
    dest: Dict[str, Any],
    src: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not src:
        return dest
    dest["candidate_scan_expected_attempts"] = int(
        dest.get("candidate_scan_expected_attempts", 0)
    ) + int(src.get("candidate_scan_expected_attempts", 0))
    dest["candidate_scan_actual_attempts"] = int(
        dest.get("candidate_scan_actual_attempts", 0)
    ) + int(src.get("candidate_scan_actual_attempts", 0))
    for key in (
        "candidate_scan_attempted_by_dex",
        "candidate_scan_attempted_by_anchor",
        "candidate_scan_unsupported_by_dex",
        "candidate_scan_no_pool_by_dex",
    ):
        d_hist = dest.setdefault(key, {})
        for k, v in (src.get(key) or {}).items():
            d_hist[k] = int(d_hist.get(k, 0)) + int(v or 0)

    dest_matrix = dest.setdefault("candidate_dex_attempt_matrix", {})
    for token, dex_map in (src.get("candidate_dex_attempt_matrix") or {}).items():
        dest_matrix.setdefault(token, {}).update(dex_map)
    return dest


def merge_scan_telemetry(
    dest: Dict[str, Any],
    src: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge per-token telemetry into batch aggregate."""
    if not src:
        return dest
    dest["scan_expected_attempts"] = int(dest.get("scan_expected_attempts", 0)) + int(
        src.get("scan_expected_attempts", 0)
    )
    dest["scan_actual_attempts"] = int(dest.get("scan_actual_attempts", 0)) + int(
        src.get("scan_actual_attempts", 0)
    )
    for key in (
        "active_scan_attempted_by_dex",
        "active_scan_attempted_by_anchor",
        "active_scan_no_pool_by_dex",
        "active_scan_unsupported_dex_by_dex",
        "active_scan_skipped_dry_run_by_dex",
    ):
        d_hist = dest.setdefault(key, {})
        for k, v in (src.get(key) or {}).items():
            d_hist[k] = int(d_hist.get(k, 0)) + int(v or 0)

    dest_matrix = dest.setdefault("scan_attempt_matrix", {})
    for token, dex_map in (src.get("scan_attempt_matrix") or {}).items():
        dest_matrix.setdefault(token, {}).update(dex_map)
    return dest


def active_scan_coverage_rate(telemetry: Dict[str, Any]) -> float:
    expected = int(telemetry.get("scan_expected_attempts") or 0)
    actual = int(telemetry.get("scan_actual_attempts") or 0)
    if expected <= 0:
        return 0.0
    return round(actual / expected, 4)


def build_coverage_audit(
    expansion: Dict[str, Any],
    *,
    min_coverage_rate: float = 0.98,
) -> Dict[str, Any]:
    """Audit scan matrix vs dex_ids_checked from expansion artifact."""
    summary = expansion.get("summary") or {}
    telemetry = expansion.get("scan_telemetry") or {}
    if not telemetry and summary:
        telemetry = {
            k: summary.get(k)
            for k in (
                "scan_expected_attempts",
                "scan_actual_attempts",
                "active_scan_attempted_by_dex",
                "active_scan_attempted_by_anchor",
                "active_scan_no_pool_by_dex",
                "active_scan_unsupported_dex_by_dex",
                "active_scan_skipped_dry_run_by_dex",
                "active_scan_coverage_rate",
            )
            if summary.get(k) is not None
        }
        telemetry["scan_attempt_matrix"] = expansion.get("scan_attempt_matrix") or {}

    expected_dexes = sorted(summary.get("dex_ids_checked") or [])
    attempted_dexes = sorted((telemetry.get("active_scan_attempted_by_dex") or {}).keys())
    missing_dexes = sorted(set(expected_dexes) - set(attempted_dexes))

    rate = float(
        summary.get("active_scan_coverage_rate")
        or telemetry.get("active_scan_coverage_rate")
        or active_scan_coverage_rate(telemetry)
    )

    blockers: List[str] = []
    if not expansion.get("scan_attempt_matrix") and not (
        telemetry.get("scan_attempt_matrix")
    ):
        blockers.append("ACTIVE_SCAN_COVERAGE_INCOMPLETE")
    if missing_dexes and int(summary.get("tokens_in") or 0) > 1:
        blockers.append("ACTIVE_SCAN_COVERAGE_INCOMPLETE")
    if rate < min_coverage_rate and int(telemetry.get("scan_expected_attempts") or 0) > 0:
        blockers.append("ACTIVE_SCAN_COVERAGE_INCOMPLETE")

    return {
        "schema_version": "m8_2_scan_coverage.1",
        "dex_ids_checked": expected_dexes,
        "active_scan_attempted_by_dex": dict(
            telemetry.get("active_scan_attempted_by_dex") or {}
        ),
        "active_scan_attempted_by_anchor": dict(
            telemetry.get("active_scan_attempted_by_anchor") or {}
        ),
        "active_scan_no_pool_by_dex": dict(
            telemetry.get("active_scan_no_pool_by_dex") or {}
        ),
        "active_scan_unsupported_dex_by_dex": dict(
            telemetry.get("active_scan_unsupported_dex_by_dex") or {}
        ),
        "scan_expected_attempts": int(telemetry.get("scan_expected_attempts") or 0),
        "scan_actual_attempts": int(telemetry.get("scan_actual_attempts") or 0),
        "active_scan_coverage_rate": rate,
        "missing_dexes": missing_dexes,
        "missing_anchor_attempts": _missing_anchor_attempts(
            telemetry.get("scan_attempt_matrix") or {},
            anchors=("USDC", "WETH", "cbBTC", "EURC", "USDbC", "DAI"),
        ),
        "matrix_token_count": len((expansion.get("scan_attempt_matrix") or {})),
        "blockers": sorted(set(blockers)),
        "goal_status": "REACHED" if not blockers else "BLOCKED",
    }


def _missing_anchor_attempts(
    matrix: Dict[str, Any],
    *,
    anchors: tuple[str, ...],
) -> List[str]:
    """Anchors with zero attempts across all tokens in matrix."""
    if not matrix:
        return list(anchors)
    seen: Set[str] = set()
    for dex_map in matrix.values():
        for anchor_map in dex_map.values():
            seen.update(anchor_map.keys())
    return sorted(a for a in anchors if a not in seen)
