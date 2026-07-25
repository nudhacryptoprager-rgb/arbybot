"""M_control read-only projection — session-coherent M8→M9 funnel view."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from api.artifact_provenance import is_test_or_fixture_artifact
from api.projections import ProjectionCache

SCHEMA_VERSION = "m_control_funnel_v2"
TRACE_SCHEMA_VERSION = "m_control_traces_v2"

_ARTIFACT_PATHS: Dict[str, str] = {
    "sniper": "data/runs/_rolling/new_pool_sniper_latest.json",
    "m8_1": "data/tmp/m8_1_exotic_inventory_latest.json",
    "m8_2": "data/tmp/m8_2_acceptance_report_latest.json",
    "m8_3": "data/runs/_rolling/m8_3_token_metadata_registry_latest.json",
    "bridge": "data/tmp/m9_bridge_inventory_production_latest.json",
    "capacity": "data/tmp/m9_capacity_cycle_diagnostic_latest.json",
    "shadow": "data/runs/_rolling/m9_graph_latest.json",
    "acceptance": "data/tmp/m9_lane_acceptance_report_latest.json",
    "pipeline": "data/tmp/start_pipeline_current.json",
    "truth_gate": "data/tmp/m8_m9_runtime_truth_gate_latest.json",
}

_SHADOW_FALLBACK_CANDIDATES = (
    "data/tmp/m9_shadow_capacity_smoke.json",
    "data/tmp/m9_graph_handoff_quote_validation_10m.json",
    "data/runs/_rolling/m9_graph_latest.json",
)


def resolve_mcontrol_shadow_rel_path(
    repo_root: Path | str,
    pipeline_doc: Optional[Mapping[str, Any]] = None,
) -> str:
    """Prefer pipeline-declared shadow artifact, then smoke handoff, then rolling."""
    root = Path(repo_root)
    candidates: List[str] = []
    if pipeline_doc:
        for key in (
            "shadow_artifact_path",
            "m9_shadow_artifact_path",
            "current_shadow_artifact",
            "artifact_path",
        ):
            raw = str(pipeline_doc.get(key) or "").strip()
            if raw:
                candidates.append(raw)
    env_path = os.environ.get("ARBY_MCONTROL_SHADOW_PATH", "").strip()
    if env_path:
        candidates.append(env_path)
    env_dashboard = os.environ.get("ARBY_DASHBOARD_M9_SHADOW_PATH", "").strip()
    if env_dashboard:
        candidates.append(env_dashboard)
    candidates.extend(list(_SHADOW_FALLBACK_CANDIDATES))
    for rel in candidates:
        if (root / rel).is_file():
            return rel
    return _ARTIFACT_PATHS["shadow"]


def _session_id_from_doc(doc: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not doc:
        return None
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
    present = doc is not None and not (
        name == "M9_shadow" and is_test_or_fixture_artifact(doc)
    )
    status = None
    blockers: List[str] = []
    if present and doc:
        status = doc.get(status_key) or doc.get("status") or fallback_status
        raw_blockers = doc.get("blockers") or doc.get("m9_blockers") or []
        if isinstance(raw_blockers, list):
            blockers = [str(b) for b in raw_blockers]
    return {
        "stage": name,
        "present": present,
        "status": status,
        "blockers": blockers,
        "generated_at_utc": doc.get("generated_at_utc") if present and doc else None,
        "session_id": _session_id_from_doc(doc) if present and doc else None,
    }


def _coherence_status(
    canonical_session: Optional[str],
    loaded: Dict[str, Optional[Dict[str, Any]]],
) -> Dict[str, Any]:
    warnings = _session_mismatch_warnings(canonical_session, loaded)
    capacity = loaded.get("capacity")
    if capacity and not _session_id_from_doc(capacity):
        warnings.append("capacity_missing_session_id")
    if not canonical_session:
        return {
            "status": "UNKNOWN_COHERENCE",
            "warnings": sorted(set(warnings)),
        }
    if warnings:
        return {
            "status": "SESSION_MISMATCH",
            "warnings": sorted(set(warnings)),
        }
    return {"status": "ALIGNED", "warnings": []}


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
        sid = _session_id_from_doc(doc)
        if sid and sid != canonical_session:
            warnings.append(f"{name}_session_mismatch")
    return warnings


def _reason_class(reason: str) -> str:
    r = reason.upper()
    if "DEPTH" in r or "CAPACITY" in r or "ADMISSION" in r:
        return "policy_admission"
    if "RPC" in r or "QUOTE" in r or "REVERT" in r:
        return "infra_quote"
    if "MARKET" in r or "GROSS" in r or "POSITIVE" in r:
        return "market_economics"
    if "DATA" in r or "DECIMAL" in r or "UNKNOWN" in r:
        return "data_quality"
    return "other"


def _build_trace_ledger(
    loaded: Dict[str, Optional[Dict[str, Any]]],
    *,
    session_id: Optional[str],
) -> List[Dict[str, Any]]:
    ledger: List[Dict[str, Any]] = []
    bridge = loaded.get("bridge") or {}
    capacity = loaded.get("capacity") or {}
    shadow = loaded.get("shadow") or {}
    bsm = bridge.get("bridge_source_metrics") or {}

    for route in (bridge.get("active_routes") or [])[:50]:
        if not isinstance(route, dict):
            continue
        token = str(
            route.get("token_address")
            or route.get("focus_token_address")
            or route.get("matched_m8_token")
            or ""
        ).lower()
        if not token:
            continue
        if route.get("mirror_quote_ready") is True:
            continue
        if route.get("matched_m8_token") and not route.get("factory_verified"):
            ledger.append(
                {
                    "entity_type": "token",
                    "entity_id": token,
                    "token_address": token,
                    "entered_stage": "M8_2_expansion",
                    "exited_stage": "M9_bridge",
                    "first_blocker": "FACTORY_NOT_VERIFIED",
                    "reason_class": "policy_admission",
                    "session_id": session_id,
                }
            )

    fresh_ready = int(
        bridge.get("fresh_long_tail_quote_ready_tokens")
        or bsm.get("fresh_long_tail_quote_ready_tokens")
        or 0
    )
    if fresh_ready <= 0:
        ledger.append(
            {
                "entity_type": "token_universe",
                "entity_id": "fresh_long_tail",
                "entered_stage": "M8_2_expansion",
                "exited_stage": "M9_bridge",
                "first_blocker": "FRESH_LONG_TAIL_QUOTE_READY_ZERO",
                "reason_class": "policy_admission",
                "session_id": session_id,
            }
        )

    for leg in (capacity.get("top_bottleneck_legs") or [])[:8]:
        if not isinstance(leg, dict):
            continue
        route_id = str(leg.get("route_id") or "")
        pool = str(leg.get("pool_address") or "").lower()
        entity_id = pool or route_id or "unknown"
        ledger.append(
            {
                "entity_type": "pool",
                "entity_id": entity_id,
                "pool_address": pool or None,
                "route_id": route_id or None,
                "entered_stage": "M9_capacity",
                "exited_stage": "M9_shadow",
                "first_blocker": str(leg.get("reason") or leg.get("bottleneck_reason") or "DEPTH_BELOW_FLOOR"),
                "reason_class": _reason_class(str(leg.get("reason") or leg.get("bottleneck_reason") or "")),
                "session_id": session_id,
            }
        )

    for sample in (capacity.get("sample_cycles_at_econ_floor") or [])[:12]:
        if not isinstance(sample, dict):
            continue
        cycle_id = str(sample.get("cycle_id") or "")
        if not cycle_id:
            continue
        ledger.append(
            {
                "entity_type": "cycle",
                "entity_id": cycle_id,
                "cycle_id": cycle_id,
                "entered_stage": "M9_capacity",
                "exited_stage": "M9_shadow",
                "first_blocker": str(
                    shadow.get("shadow_lane_blocker")
                    or bsm.get("shadow_lane_blocker")
                    or "CAPACITY_VALID_NOT_SELECTED"
                ),
                "reason_class": "policy_admission",
                "session_id": session_id,
            }
        )

    reject_hist = shadow.get("cycle_reject_histogram") or {}
    if isinstance(reject_hist, dict):
        for reason, count in sorted(reject_hist.items(), key=lambda kv: -int(kv[1] or 0))[:10]:
            ledger.append(
                {
                    "entity_type": "reject_reason",
                    "entity_id": str(reason),
                    "entered_stage": "M9_shadow",
                    "exited_stage": "M9_economics",
                    "first_blocker": str(reason),
                    "reason_class": _reason_class(str(reason)),
                    "session_id": session_id,
                    "count": int(count or 0),
                }
            )

    cap_ids = capacity.get("capacity_valid_cycle_ids") or []
    selected = (shadow.get("scan_scope") or {}).get("shadow_selected_cycle_ids") or []
    quoted = (shadow.get("scan_scope") or {}).get("shadow_quoted_cycle_ids") or []
    if cap_ids and not selected:
        for cycle_id in cap_ids[:12]:
            ledger.append(
                {
                    "entity_type": "cycle",
                    "entity_id": str(cycle_id),
                    "cycle_id": str(cycle_id),
                    "entered_stage": "M9_capacity",
                    "exited_stage": "M9_shadow_selection",
                    "first_blocker": "CAPACITY_VALID_CYCLES_NOT_SELECTED",
                    "reason_class": "policy_admission",
                    "session_id": session_id,
                }
            )
    if cap_ids and not quoted:
        for cycle_id in (selected or cap_ids)[:12]:
            ledger.append(
                {
                    "entity_type": "cycle",
                    "entity_id": str(cycle_id),
                    "cycle_id": str(cycle_id),
                    "entered_stage": "M9_shadow_selection",
                    "exited_stage": "M9_rpc_quote",
                    "first_blocker": "CAPACITY_VALID_CYCLES_NOT_QUOTED",
                    "reason_class": "infra_quote",
                    "session_id": session_id,
                }
            )

    return ledger


class ControlProjectionBuilder:
    """Build M_control views from cached artifact projections."""

    def __init__(
        self,
        repo_root: Path | str = ".",
        cache: Optional[ProjectionCache] = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.cache = cache or ProjectionCache()

    def _load(self, key: str) -> Optional[Dict[str, Any]]:
        if key == "shadow":
            pipeline = self._load_raw("pipeline")
            rel = resolve_mcontrol_shadow_rel_path(self.repo_root, pipeline)
        else:
            rel = _ARTIFACT_PATHS.get(key)
        if not rel:
            return None
        proj = self.cache.get(self.repo_root / rel)
        if proj is None or not isinstance(proj.data, dict):
            return None
        data = proj.data
        if key == "shadow" and is_test_or_fixture_artifact(data):
            return None
        return data

    def _load_raw(self, key: str) -> Optional[Dict[str, Any]]:
        rel = _ARTIFACT_PATHS.get(key)
        if not rel:
            return None
        proj = self.cache.get(self.repo_root / rel)
        if proj is None or not isinstance(proj.data, dict):
            return None
        return proj.data

    def load_all(self) -> Dict[str, Optional[Dict[str, Any]]]:
        return {key: self._load(key) for key in _ARTIFACT_PATHS}

    def build_funnel(self) -> Dict[str, Any]:
        loaded = self.load_all()
        bridge = loaded.get("bridge")
        capacity = loaded.get("capacity")
        shadow = loaded.get("shadow")
        acceptance = loaded.get("acceptance")
        pipeline = loaded.get("pipeline")
        truth = loaded.get("truth_gate")
        m8_2 = loaded.get("m8_2")
        m8_3 = loaded.get("m8_3")
        m8_1 = loaded.get("m8_1")
        shadow_source_path = resolve_mcontrol_shadow_rel_path(self.repo_root, pipeline)

        session_id = _session_id_from_doc(pipeline) or _session_id_from_doc(bridge)
        scan_scope = (shadow or {}).get("scan_scope") or {}
        cap_ids = list(
            scan_scope.get("capacity_valid_cycle_ids")
            or (capacity or {}).get("capacity_valid_cycle_ids")
            or []
        )
        selected_ids = list(scan_scope.get("shadow_selected_cycle_ids") or [])
        quoted_ids = list(scan_scope.get("shadow_quoted_cycle_ids") or [])
        qst = (shadow or {}).get("quote_size_truth") or {}
        econ_rpc = int(qst.get("econ_rpc_quote_attempts") or 0)

        reject_hist = (shadow or {}).get("cycle_reject_histogram") or {}
        reason_histogram: Dict[str, int] = {}
        if isinstance(reject_hist, dict):
            reason_histogram = {str(k): int(v or 0) for k, v in reject_hist.items()}

        shadow_fixture_rejected = self._load("shadow") is None and (
            self.cache.get(self.repo_root / _ARTIFACT_PATHS["shadow"]) is not None
        )

        economics_not_yet_tested = bool(
            shadow is None
            or (
                int((shadow or {}).get("cycles_found") or 0) > 0
                and int((shadow or {}).get("cycles_quoteable") or 0) == 0
                and econ_rpc == 0
            )
        )

        m82_summary = (m8_2 or {}).get("summary") or {}
        exploration = int(m82_summary.get("routes_rejected_not_m8_derived") or 0)

        stages = [
            _stage_row("M8_sniper", loaded.get("sniper"), status_key="status"),
            _stage_row(
                "M8_1_probe_admission",
                m8_1,
                status_key="status",
                fallback_status="PRESENT" if m8_1 else None,
            ),
            _stage_row(
                "M8_2_canonical_handoff",
                m8_2,
                status_key="goal_status",
            ),
            _stage_row(
                "M8_2_exploration_partition",
                {"status": "PARTITIONED" if exploration else "NONE", "count": exploration}
                if m8_2
                else None,
                status_key="status",
            ),
            _stage_row(
                "M8_3_metadata_authority",
                m8_3,
                status_key="goal_status",
                fallback_status="PRESENT" if m8_3 else None,
            ),
            _stage_row(
                "M9_bridge",
                bridge,
                status_key="status",
                fallback_status="READY" if bridge else None,
            ),
            _stage_row("M9_capacity", capacity, status_key="blocker_hint"),
            _stage_row("M9_shadow", shadow, status_key="runner_outcome"),
            _stage_row("M9_acceptance", acceptance, status_key="goal_status"),
            _stage_row("runtime_truth_gate", truth, status_key="truth_status"),
        ]

        cap_valid = len(cap_ids)
        cap_selected = len(set(cap_ids) & set(selected_ids))
        cap_quoted = len(set(cap_ids) & set(quoted_ids))

        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": datetime.now(tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "session_id": session_id,
            "shadow_source_path": shadow_source_path,
            "coherence": _coherence_status(session_id, loaded),
            "shadow_fixture_rejected": shadow_fixture_rejected,
            "pipeline_step": (pipeline or {}).get("step"),
            "pipeline_status": (pipeline or {}).get("status"),
            "shadow_lane_mode": scan_scope.get("shadow_lane_mode"),
            "stages": stages,
            "capacity_conversion": {
                "capacity_valid_count": cap_valid,
                "shadow_selected_count": len(selected_ids),
                "shadow_quoted_count": len(quoted_ids),
                "capacity_selected_overlap": cap_selected,
                "capacity_quoted_overlap": cap_quoted,
                "capacity_selected_rate": round(cap_selected / cap_valid, 4)
                if cap_valid
                else None,
                "capacity_quoted_rate": round(cap_quoted / cap_valid, 4) if cap_valid else None,
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

    def build_traces(self) -> Dict[str, Any]:
        loaded = self.load_all()
        bridge = loaded.get("bridge") or {}
        shadow = loaded.get("shadow") or {}
        capacity = loaded.get("capacity") or {}
        bsm = bridge.get("bridge_source_metrics") or {}
        session_id = _session_id_from_doc(loaded.get("pipeline")) or _session_id_from_doc(
            bridge
        )

        ledger = _build_trace_ledger(loaded, session_id=session_id)

        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "generated_at_utc": datetime.now(tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "session_id": session_id,
            "trace_ledger": ledger,
            "tokens": {
                "fresh_long_tail_quote_ready": int(
                    bridge.get("fresh_long_tail_quote_ready_tokens")
                    or bsm.get("fresh_long_tail_quote_ready_tokens")
                    or 0
                ),
                "graph_ready_total": int(bsm.get("graph_ready_total") or 0),
            },
            "pools": {
                "m8_direct_pools": int(bsm.get("m8_direct_pool_addrs_tracked") or 0),
                "verified_mirror_pools": int(
                    bsm.get("verified_mirror_pool_addrs_tracked") or 0
                ),
            },
            "routes": {
                "active_routes": len(bridge.get("active_routes") or []),
                "exploration_routes_excluded": int(
                    bsm.get("routes_rejected_not_m8_derived") or 0
                ),
            },
            "cycles": {
                "cycles_found": int(shadow.get("cycles_found") or 0),
                "cycles_quoteable": int(shadow.get("cycles_quoteable") or 0),
                "cycles_with_direct_sniper_pool": int(
                    shadow.get("cycles_with_direct_sniper_pool") or 0
                ),
                "capacity_valid_total": len(
                    capacity.get("capacity_valid_cycle_ids") or []
                ),
            },
            "blocker_classes": {
                "economics_blocker_class": shadow.get("economics_blocker_class"),
                "shadow_lane_blocker": shadow.get("shadow_lane_blocker")
                or bsm.get("shadow_lane_blocker"),
                "capacity_blocker_hint": capacity.get("blocker_hint"),
            },
        }


def build_control_funnel(repo_root: Path | str = ".") -> Dict[str, Any]:
    return ControlProjectionBuilder(repo_root).build_funnel()


def build_control_traces(repo_root: Path | str = ".") -> Dict[str, Any]:
    return ControlProjectionBuilder(repo_root).build_traces()
