"""Shared M9 shadow/capacity universe contract — binds diagnostic and runner inputs."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.pipeline_provenance import ENV_PIPELINE_SESSION_ID, pipeline_session_id

CONTRACT_SCHEMA_VERSION = "m9_universe_contract.2"
BLOCKER_CAPACITY_UNIVERSE_MISMATCH = "CAPACITY_UNIVERSE_MISMATCH"

_COMPARE_KEYS = (
    "inventory_path",
    "config_path",
    "lane",
    "require_factory_verified",
    "cycle_lengths",
    "active_economics_profile",
    "admission_policy",
)

_GRAPH_COMPARE_KEYS = (
    "resolved_inventory_path",
    "active_route_count",
    "graph_edge_count",
    "graph_route_count",
)


def normalize_artifact_path(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    try:
        return str(Path(raw).resolve()).replace("\\", "/").lower()
    except OSError:
        return raw.replace("\\", "/").lower()


def admission_policy_label(
    *,
    lane: str,
    require_factory_verified: bool,
    diagnostic_admission_mode: Optional[str] = None,
) -> str:
    mode = diagnostic_admission_mode
    if mode is None and lane == "productive":
        mode = "topology_probe"
    return (
        f"lane={lane};factory_verified={bool(require_factory_verified)};"
        f"admission={mode or 'default'}"
    )


def resolve_session_id(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve session id from explicit CLI value or env fallback (no env mutation)."""
    sid = str(explicit or "").strip()
    if sid:
        return sid
    return pipeline_session_id()


def bind_cli_session_to_env(session_id: Optional[str]) -> Optional[str]:
    """CLI entry only: bind explicit session id to env for subprocess compatibility."""
    explicit = str(session_id or "").strip()
    if explicit:
        os.environ[ENV_PIPELINE_SESSION_ID] = explicit
        return explicit
    return pipeline_session_id()


def apply_explicit_session_id(session_id: Optional[str]) -> Optional[str]:
    """Deprecated alias — prefer resolve_session_id / bind_cli_session_to_env."""
    return bind_cli_session_to_env(session_id)


def resolve_cycle_lengths_from_config(
    config_path: str,
    *,
    env_override: Optional[str] = None,
    default: Tuple[int, ...] = (3, 4),
) -> Tuple[int, ...]:
    """Match runner scan_params.cycle_lengths resolution (default productive: 3, 4)."""
    override = env_override
    if override is None:
        override = os.environ.get("ARBY_M9_CYCLE_LENGTHS", "").strip() or None
    if override:
        parts = [p.strip() for p in str(override).split(",") if p.strip()]
        if parts:
            try:
                parsed = tuple(sorted({int(v) for v in parts if int(v) >= 2}))
                if parsed:
                    return parsed
            except ValueError:
                pass
    try:
        import yaml

        with open(config_path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        raw = (cfg.get("scan_params") or {}).get("cycle_lengths")
        if raw:
            parsed = tuple(sorted({int(v) for v in raw if int(v) >= 2}))
            if parsed:
                return parsed
    except Exception:
        pass
    return default


def load_active_route_count(inventory_path: str) -> int:
    try:
        inv = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
        return len(inv.get("active_routes") or [])
    except Exception:
        return 0


def build_pregraph_admission_adjacency(
    *,
    inventory_path: str,
    config_path: str,
    lane: str,
    require_factory_verified: bool,
) -> Any:
    """Build graph with the same admission policy as capacity diagnostic (pre-quarantine)."""
    from m9.graph_arb.builder import build_graph_from_inventory

    return build_graph_from_inventory(
        inventory_path=inventory_path,
        config_path=config_path,
        lane=lane,
        require_factory_verified=require_factory_verified,
        diagnostic_admission_mode=(
            "topology_probe" if lane == "productive" else None
        ),
    )


def build_graph_fingerprint(
    *,
    inventory_path: str,
    adjacency: Any,
    active_route_count: int,
    lane: str,
    require_factory_verified: bool,
) -> Dict[str, Any]:
    from m9.graph_arb.builder import graph_edge_count, graph_route_count

    return {
        "resolved_inventory_path": normalize_artifact_path(inventory_path),
        "active_route_count": int(active_route_count),
        "graph_edge_count": int(graph_edge_count(adjacency)) if adjacency else 0,
        "graph_route_count": int(graph_route_count(adjacency)) if adjacency else 0,
        "admission_policy": admission_policy_label(
            lane=lane,
            require_factory_verified=require_factory_verified,
        ),
    }


def build_runner_admission_graph_fingerprint(
    *,
    inventory_path: str,
    config_path: str,
    lane: str,
    require_factory_verified: bool,
) -> Dict[str, Any]:
    """Deterministic pre-graph admission fingerprint shared with capacity diagnostic."""
    adjacency = build_pregraph_admission_adjacency(
        inventory_path=inventory_path,
        config_path=config_path,
        lane=lane,
        require_factory_verified=require_factory_verified,
    )
    return build_graph_fingerprint(
        inventory_path=inventory_path,
        adjacency=adjacency,
        active_route_count=load_active_route_count(inventory_path),
        lane=lane,
        require_factory_verified=require_factory_verified,
    )


def enrich_contract_with_graph_fingerprint(
    contract: Mapping[str, Any],
    graph_fingerprint: Mapping[str, Any],
) -> Dict[str, Any]:
    out = dict(contract)
    for key in _GRAPH_COMPARE_KEYS:
        if key in graph_fingerprint:
            out[key] = graph_fingerprint.get(key)
    return out


def build_universe_contract(
    *,
    inventory_path: str,
    config_path: str,
    lane: str,
    require_factory_verified: bool,
    cycle_lengths: Sequence[int],
    active_economics_profile: str,
    session_id: Optional[str] = None,
    graph_fingerprint: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    sid = (session_id or resolve_session_id() or "").strip() or None
    contract: Dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "inventory_path": normalize_artifact_path(inventory_path),
        "config_path": normalize_artifact_path(config_path),
        "lane": str(lane or "productive"),
        "require_factory_verified": bool(require_factory_verified),
        "cycle_lengths": [int(v) for v in cycle_lengths],
        "active_economics_profile": str(active_economics_profile or ""),
        "session_id": sid,
        "admission_policy": admission_policy_label(
            lane=lane,
            require_factory_verified=require_factory_verified,
        ),
    }
    if graph_fingerprint:
        contract = enrich_contract_with_graph_fingerprint(contract, graph_fingerprint)
    return contract


def contract_from_capacity_doc(doc: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    uc = doc.get("universe_contract")
    if isinstance(uc, Mapping) and uc.get("schema_version"):
        out = dict(uc)
        fp = doc.get("graph_fingerprint") or {}
        if isinstance(fp, Mapping) and fp:
            out = enrich_contract_with_graph_fingerprint(out, fp)
        return out
    fp = doc.get("graph_fingerprint") or {}
    return build_universe_contract(
        inventory_path=str(doc.get("inventory_path") or ""),
        config_path=str(doc.get("config_path") or ""),
        lane=str(doc.get("lane") or "productive"),
        require_factory_verified=bool(doc.get("require_factory_verified")),
        cycle_lengths=tuple(doc.get("cycle_lengths") or ()),
        active_economics_profile=str(doc.get("active_economics_profile") or ""),
        session_id=str(doc.get("session_id") or "") or None,
        graph_fingerprint=fp if isinstance(fp, Mapping) else None,
    )


def _compare_session_ids(
    runner_sid: Any,
    capacity_sid: Any,
    *,
    require_session_binding: bool,
) -> List[str]:
    mismatches: List[str] = []
    exp_sid = str(runner_sid or "").strip()
    act_sid = str(capacity_sid or "").strip()
    if exp_sid and act_sid and exp_sid != act_sid:
        mismatches.append("session_id")
    elif exp_sid and not act_sid:
        mismatches.append("session_id_missing_in_capacity")
    elif act_sid and not exp_sid:
        mismatches.append("session_id_missing_in_runner")
    elif require_session_binding and not exp_sid and not act_sid:
        mismatches.append("session_id_missing")
    return mismatches


def _graph_fingerprint_required(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    *,
    require_graph_fingerprint: bool,
) -> bool:
    if require_graph_fingerprint:
        return True
    for contract in (expected, actual):
        schema = str(contract.get("schema_version") or "")
        if schema.endswith(".2"):
            return True
    return False


def compare_universe_contracts(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    *,
    require_session_binding: bool = True,
    require_graph_fingerprint: bool = False,
) -> List[str]:
    mismatches: List[str] = []
    for key in _COMPARE_KEYS:
        ev = expected.get(key)
        av = actual.get(key)
        if key == "cycle_lengths":
            if sorted(int(v) for v in (ev or [])) != sorted(int(v) for v in (av or [])):
                mismatches.append(key)
            continue
        if ev != av:
            mismatches.append(key)

    req_fp = _graph_fingerprint_required(
        expected, actual, require_graph_fingerprint=require_graph_fingerprint
    )
    for key in _GRAPH_COMPARE_KEYS:
        ev = expected.get(key)
        av = actual.get(key)
        if req_fp:
            if ev is None:
                mismatches.append(f"graph_fingerprint_missing_in_runner_{key}")
            if av is None:
                mismatches.append(f"graph_fingerprint_missing_in_capacity_{key}")
            if ev is not None and av is not None and ev != av:
                mismatches.append(key)
        elif ev is not None and av is not None and ev != av:
            mismatches.append(key)

    mismatches.extend(
        _compare_session_ids(
            expected.get("session_id"),
            actual.get("session_id"),
            require_session_binding=require_session_binding,
        )
    )
    return mismatches


def validate_capacity_for_runner(
    capacity_doc: Optional[Mapping[str, Any]],
    runner_contract: Mapping[str, Any],
    *,
    require_session_binding: bool = True,
    require_graph_fingerprint: bool = True,
) -> Tuple[bool, List[str]]:
    if not capacity_doc:
        return False, ["capacity_diagnostic_missing"]
    cap_contract = contract_from_capacity_doc(capacity_doc)
    if not cap_contract:
        return False, ["universe_contract_missing"]
    if not capacity_doc.get("universe_contract"):
        return False, ["universe_contract_missing"]

    req_fp = _graph_fingerprint_required(
        runner_contract,
        cap_contract,
        require_graph_fingerprint=require_graph_fingerprint,
    )
    if req_fp:
        fp = capacity_doc.get("graph_fingerprint") or {}
        if not isinstance(fp, Mapping) or not fp:
            return False, ["graph_fingerprint_missing_in_capacity"]
        for key in _GRAPH_COMPARE_KEYS:
            if fp.get(key) is None:
                return False, [f"graph_fingerprint_missing_in_capacity_{key}"]

    mismatches = compare_universe_contracts(
        runner_contract,
        cap_contract,
        require_session_binding=require_session_binding,
        require_graph_fingerprint=req_fp,
    )
    return len(mismatches) == 0, mismatches


def stamp_universe_contract(
    doc: Dict[str, Any],
    contract: Mapping[str, Any],
) -> Dict[str, Any]:
    doc["universe_contract"] = dict(contract)
    return doc
