"""M_control read-only projection — session-coherent M8→M9 funnel view."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

SCHEMA_VERSION = "m_control_funnel_v1"

_ARTIFACT_PATHS: Dict[str, str] = {
    "bridge": "data/tmp/m9_bridge_inventory_production_latest.json",
    "capacity": "data/tmp/m9_capacity_cycle_diagnostic_latest.json",
    "shadow": "data/runs/_rolling/m9_graph_latest.json",
    "acceptance": "data/tmp/m9_lane_acceptance_report_latest.json",
    "pipeline": "data/tmp/start_pipeline_current.json",
    "truth_gate": "data/tmp/m8_m9_runtime_truth_gate_latest.json",
    "sniper": "data/runs/_rolling/new_pool_sniper_latest.json",
}


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _session_id_from_docs(*docs: Optional[Mapping[str, Any]]) -> Optional[str]:
    for doc in docs:
        if not doc:
            continue
        sid = doc.get("session_id")
        if sid:
            return str(sid)
        rc = doc.get("run_context")
        if isinstance(rc, Mapping) and rc.get("session_id"):
            return str(rc["session_id"])
    return None


def _stage_row(
    name: str,
    doc: Optional[Mapping[str, Any]],
    *,
    status_key: str = "goal_status",
    fallback_status: Optional[str] = None,
) -> Dict[str, Any]:
    present = doc is not None
    status = None
    blockers: List[str] = []
    if doc:
        status = doc.get(status_key) or doc.get("status") or fallback_status
        raw_blockers = doc.get("blockers") or doc.get("m9_blockers") or []
        if isinstance(raw_blockers, list):
            blockers = [str(b) for b in raw_blockers]
    return {
        "stage": name,
        "present": present,
        "status": status,
        "blockers": blockers,
        "generated_at_utc": doc.get("generated_at_utc") if doc else None,
    }


def build_control_funnel(repo_root: Path | str = ".") -> Dict[str, Any]:
    """Read-only M8→M9 funnel projection (no orchestration)."""
    root = Path(repo_root)
    loaded: Dict[str, Optional[Dict[str, Any]]] = {
        key: _read_json(root / rel) for key, rel in _ARTIFACT_PATHS.items()
    }
    bridge = loaded.get("bridge")
    capacity = loaded.get("capacity")
    shadow = loaded.get("shadow")
    acceptance = loaded.get("acceptance")
    pipeline = loaded.get("pipeline")
    truth = loaded.get("truth_gate")

    session_id = _session_id_from_docs(bridge, shadow, acceptance, pipeline)
    scan_scope = (shadow or {}).get("scan_scope") or {}
    cap_ids = list(scan_scope.get("capacity_valid_cycle_ids") or capacity.get("capacity_valid_cycle_ids") if capacity else [])
    selected_ids = list(scan_scope.get("shadow_selected_cycle_ids") or [])
    quoted_ids = list(scan_scope.get("shadow_quoted_cycle_ids") or [])
    qst = (shadow or {}).get("quote_size_truth") or {}
    econ_rpc = int(qst.get("econ_rpc_quote_attempts") or 0)

    reject_hist = (shadow or {}).get("cycle_reject_histogram") or {}
    reason_histogram: Dict[str, int] = {}
    if isinstance(reject_hist, dict):
        reason_histogram = {str(k): int(v or 0) for k, v in reject_hist.items()}

    economics_not_yet_tested = bool(
        (shadow or {}).get("cycles_found", 0) > 0
        and int((shadow or {}).get("cycles_quoteable") or 0) == 0
        and econ_rpc == 0
    )

    stages = [
        _stage_row("M8_sniper", loaded.get("sniper"), status_key="status"),
        _stage_row("M8_2_handoff", acceptance.get("m8_2_upstream") if acceptance else None),
        _stage_row("M9_bridge", bridge, status_key="status", fallback_status="READY" if bridge else None),
        _stage_row("M9_capacity", capacity, status_key="blocker_hint"),
        _stage_row("M9_shadow", shadow, status_key="runner_outcome"),
        _stage_row("M9_acceptance", acceptance, status_key="goal_status"),
        _stage_row("runtime_truth_gate", truth, status_key="truth_status"),
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": session_id,
        "pipeline_step": (pipeline or {}).get("step"),
        "pipeline_status": (pipeline or {}).get("status"),
        "shadow_lane_mode": scan_scope.get("shadow_lane_mode"),
        "stages": stages,
        "capacity_conversion": {
            "capacity_valid_count": len(cap_ids),
            "shadow_selected_count": len(selected_ids),
            "shadow_quoted_count": len(quoted_ids),
            "capacity_selected_overlap": len(set(cap_ids) & set(selected_ids)),
            "capacity_quoted_overlap": len(set(cap_ids) & set(quoted_ids)),
            "econ_rpc_quote_attempts": econ_rpc,
        },
        "economics_not_yet_tested": economics_not_yet_tested,
        "reason_histogram": reason_histogram,
        "top_attrition_reasons": sorted(
            reason_histogram.items(), key=lambda kv: -kv[1]
        )[:10],
        "session_mismatch_warnings": _session_mismatch_warnings(session_id, loaded),
        "acceptance_blockers": list((acceptance or {}).get("blockers") or []),
    }


def _session_mismatch_warnings(
    canonical_session: Optional[str],
    loaded: Dict[str, Optional[Dict[str, Any]]],
) -> List[str]:
    if not canonical_session:
        return []
    warnings: List[str] = []
    for name, doc in loaded.items():
        if not doc:
            continue
        sid = _session_id_from_docs(doc)
        if sid and sid != canonical_session:
            warnings.append(f"{name}_session_mismatch")
    return warnings


def build_control_traces(repo_root: Path | str = ".") -> Dict[str, Any]:
    """Entity trace summary for token/pool/route/cycle funnel attrition."""
    root = Path(repo_root)
    bridge = _read_json(root / _ARTIFACT_PATHS["bridge"])
    shadow = _read_json(root / _ARTIFACT_PATHS["shadow"])
    capacity = _read_json(root / _ARTIFACT_PATHS["capacity"])

    bsm = (bridge or {}).get("bridge_source_metrics") or {}
    scan_scope = (shadow or {}).get("scan_scope") or {}

    return {
        "schema_version": "m_control_traces_v1",
        "generated_at_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tokens": {
            "fresh_long_tail_quote_ready": int(
                (bridge or {}).get("fresh_long_tail_quote_ready_tokens")
                or bsm.get("fresh_long_tail_quote_ready_tokens")
                or 0
            ),
            "graph_ready_total": int(bsm.get("graph_ready_total") or 0),
        },
        "pools": {
            "m8_direct_pools": int(bsm.get("m8_direct_pool_addrs_tracked") or 0),
            "m8_derived_pools": int(bsm.get("m8_derived_pool_addrs_tracked") or 0),
        },
        "routes": {
            "active_routes": len((bridge or {}).get("active_routes") or []),
            "exploration_routes_excluded": int(
                scan_scope.get("exploration_routes_excluded_count")
                or bsm.get("routes_rejected_not_m8_derived")
                or 0
            ),
        },
        "cycles": {
            "cycles_found": int((shadow or {}).get("cycles_found") or 0),
            "cycles_quoteable": int((shadow or {}).get("cycles_quoteable") or 0),
            "cycles_with_direct_sniper_pool": int(
                (shadow or {}).get("cycles_with_direct_sniper_pool") or 0
            ),
            "capacity_valid_ids": list(
                (capacity or {}).get("capacity_valid_cycle_ids") or []
            )[:32],
            "capacity_valid_total": len(
                (capacity or {}).get("capacity_valid_cycle_ids") or []
            ),
        },
        "blocker_classes": {
            "economics_blocker_class": (shadow or {}).get("economics_blocker_class"),
            "shadow_lane_blocker": bsm.get("shadow_lane_blocker"),
            "capacity_blocker_hint": (capacity or {}).get("blocker_hint"),
        },
    }
