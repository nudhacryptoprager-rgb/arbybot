"""Route quarantine helpers from diagnostic / soak feedback."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from m9.graph_arb.quote_reject_classify import HARD_QUOTE_REJECTS

_HARD_DIAG_REJECTS = HARD_QUOTE_REJECTS

_REVERT_QUARANTINE_PATH = "data/tmp/m9_revert_quarantine.json"

_PERMANENT_QUARANTINE_REASONS = frozenset(
    {
        "BALANCER_PAUSED",
        "BALANCER_SWAPS_DISABLED",
        "BALANCER_POOL_NOT_REGISTERED",
    }
)


def resolve_diagnostic_quarantine_pools(diag: Dict[str, Any]) -> Set[str]:
    """Pool addresses to exclude after failed route diagnostic probes."""
    pools: Set[str] = set()
    for row in diag.get("rows") or diag.get("routes") or []:
        if row.get("ok"):
            continue
        reason = (row.get("reject_reason") or "").strip()
        if reason not in _HARD_DIAG_REJECTS and not reason.startswith("QUOTE_CONFIG_MISSING"):
            continue
        pool = (row.get("pool_address") or "").strip().lower()
        if pool:
            pools.add(pool)
    return pools


def update_revert_quarantine_from_diagnostic(
    diagnostic_path: str,
    *,
    output_path: str = _REVERT_QUARANTINE_PATH,
    merge: bool = True,
) -> Dict[str, Any]:
    """Append diagnostic failures to revert quarantine file."""
    path = Path(diagnostic_path)
    if not path.exists():
        raise FileNotFoundError(diagnostic_path)
    diag = json.loads(path.read_text(encoding="utf-8"))
    new_entries: List[Dict[str, Any]] = []
    for row in diag.get("rows") or []:
        if row.get("ok"):
            continue
        reason = row.get("reject_reason") or "UNKNOWN"
        if reason not in _HARD_DIAG_REJECTS and not str(reason).startswith(
            "QUOTE_CONFIG_MISSING"
        ):
            continue
        pool = (row.get("pool_address") or "").strip()
        if not pool:
            continue
        new_entries.append(
            {
                "route_id": row.get("route_id"),
                "pool_address": pool,
                "pair_id": row.get("pair_id"),
                "adapter_type": row.get("adapter_type"),
                "reject_reason": reason,
                "source": "route_diagnostic",
            }
        )

    existing: Dict[str, Any] = {"routes": []}
    out = Path(output_path)
    if merge and out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
        except Exception:
            existing = {"routes": []}

    seen = {
        (e.get("pool_address") or "").lower()
        for e in existing.get("routes") or []
        if e.get("pool_address")
    }
    merged = list(existing.get("routes") or [])
    added = 0
    for entry in new_entries:
        pool = entry["pool_address"].lower()
        if pool in seen:
            continue
        seen.add(pool)
        merged.append(entry)
        added += 1

    payload = {
        "schema_version": "m9_revert_quarantine.2",
        "updated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "source_diagnostic": str(path),
        "routes": merged,
        "summary": {"total": len(merged), "added_this_run": added},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(out) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, str(out))
    return {"added": added, "total": len(merged), "output_path": str(out)}


def load_hard_quarantine_pool_addresses(
    path: str = _REVERT_QUARANTINE_PATH,
) -> frozenset[str]:
    """Pool addresses that must never enter productive graph (paused / permanent)."""
    p = Path(path)
    if not p.exists():
        return frozenset()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return frozenset()
    pools: set[str] = set()
    for row in data.get("routes") or []:
        reason = str(row.get("quarantine_reason") or row.get("reject_reason") or "")
        if reason in _PERMANENT_QUARANTINE_REASONS or "PERMANENT" in reason or "PAUSED" in reason:
            pool = (row.get("pool_address") or "").strip().lower()
            if pool:
                pools.add(pool)
    return frozenset(pools)


def merge_paused_pools_from_lane_rca(
    rca_path: str = "data/tmp/m9_quote_lane_rca_latest.json",
    *,
    output_path: str = _REVERT_QUARANTINE_PATH,
) -> Dict[str, Any]:
    """Promote BALANCER_PAUSED pools from lane RCA into hard quarantine."""
    rca = Path(rca_path)
    if not rca.exists():
        return {"added": 0, "total": 0}
    try:
        data = json.loads(rca.read_text(encoding="utf-8"))
    except Exception:
        return {"added": 0, "total": 0}

    new_entries: List[Dict[str, Any]] = []
    for row in data.get("balancer_top_revert_routes") or data.get("top_routes") or []:
        reason = str(row.get("primary_reason") or row.get("reject_reason") or "")
        if "PAUSED" not in reason and "BAL#402" not in str(row.get("sample_raw_error") or ""):
            continue
        pool = (row.get("pool_address") or "").strip()
        if not pool:
            continue
        new_entries.append(
            {
                "route_id": row.get("route_id"),
                "pool_address": pool,
                "pair_id": row.get("pair_id"),
                "adapter_type": row.get("adapter_type") or "balancer_stable",
                "reject_reason": "BALANCER_PAUSED",
                "quarantine_reason": "BALANCER_402_PERMANENT",
                "source": "lane_rca",
            }
        )

    existing: Dict[str, Any] = {"routes": []}
    out = Path(output_path)
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
        except Exception:
            existing = {"routes": []}

    seen = {
        (e.get("pool_address") or "").lower()
        for e in existing.get("routes") or []
        if e.get("pool_address")
    }
    merged = list(existing.get("routes") or [])
    added = 0
    for entry in new_entries:
        pool = entry["pool_address"].lower()
        if pool in seen:
            continue
        seen.add(pool)
        merged.append(entry)
        added += 1

    if added:
        payload = {
            "schema_version": "m9_revert_quarantine.2",
            "updated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
            "source_lane_rca": str(rca),
            "routes": merged,
            "summary": {"total": len(merged), "added_from_rca": added},
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(out) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, str(out))
    return {"added": added, "total": len(merged), "output_path": str(out)}


def parse_max_cycles_per_length_env(raw: str) -> Dict[int, int]:
    """Parse ``3:20,4:6`` into length caps for apply_sweep_budget."""
    out: Dict[int, int] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        length_s, cap_s = part.split(":", 1)
        out[int(length_s.strip())] = int(cap_s.strip())
    return out
