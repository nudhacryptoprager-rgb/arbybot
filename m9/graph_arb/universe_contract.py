"""Shared M9 shadow/capacity universe contract — binds diagnostic and runner inputs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

CONTRACT_SCHEMA_VERSION = "m9_universe_contract.1"
BLOCKER_CAPACITY_UNIVERSE_MISMATCH = "CAPACITY_UNIVERSE_MISMATCH"

_COMPARE_KEYS = (
    "inventory_path",
    "config_path",
    "lane",
    "require_factory_verified",
    "cycle_lengths",
    "active_economics_profile",
)


def normalize_artifact_path(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    try:
        return str(Path(raw).resolve()).replace("\\", "/").lower()
    except OSError:
        return raw.replace("\\", "/").lower()


def resolve_cycle_lengths_from_config(
    config_path: str,
    *,
    env_override: Optional[str] = None,
    default: Tuple[int, ...] = (3, 4),
) -> Tuple[int, ...]:
    """Match runner scan_params.cycle_lengths resolution (default productive: 3, 4)."""
    if env_override:
        parts = [p.strip() for p in str(env_override).split(",") if p.strip()]
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


def build_universe_contract(
    *,
    inventory_path: str,
    config_path: str,
    lane: str,
    require_factory_verified: bool,
    cycle_lengths: Sequence[int],
    active_economics_profile: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    from core.pipeline_provenance import pipeline_session_id

    sid = (session_id or pipeline_session_id() or "").strip() or None
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "inventory_path": normalize_artifact_path(inventory_path),
        "config_path": normalize_artifact_path(config_path),
        "lane": str(lane or "productive"),
        "require_factory_verified": bool(require_factory_verified),
        "cycle_lengths": [int(v) for v in cycle_lengths],
        "active_economics_profile": str(active_economics_profile or ""),
        "session_id": sid,
    }


def contract_from_capacity_doc(doc: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    uc = doc.get("universe_contract")
    if isinstance(uc, Mapping) and uc.get("schema_version"):
        return dict(uc)
    # Legacy capacity artifacts before universe_contract existed.
    return build_universe_contract(
        inventory_path=str(doc.get("inventory_path") or ""),
        config_path=str(doc.get("config_path") or ""),
        lane=str(doc.get("lane") or "productive"),
        require_factory_verified=bool(doc.get("require_factory_verified")),
        cycle_lengths=tuple(doc.get("cycle_lengths") or ()),
        active_economics_profile=str(doc.get("active_economics_profile") or ""),
        session_id=str(doc.get("session_id") or "") or None,
    )


def compare_universe_contracts(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
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
    exp_sid = str(expected.get("session_id") or "").strip()
    act_sid = str(actual.get("session_id") or "").strip()
    if exp_sid and act_sid and exp_sid != act_sid:
        mismatches.append("session_id")
    elif exp_sid and not act_sid:
        mismatches.append("session_id_missing_in_capacity")
    return mismatches


def validate_capacity_for_runner(
    capacity_doc: Optional[Mapping[str, Any]],
    runner_contract: Mapping[str, Any],
) -> Tuple[bool, List[str]]:
    if not capacity_doc:
        return False, ["capacity_diagnostic_missing"]
    cap_contract = contract_from_capacity_doc(capacity_doc)
    if not cap_contract:
        return False, ["universe_contract_missing"]
    if not capacity_doc.get("universe_contract"):
        return False, ["universe_contract_missing"]
    mismatches = compare_universe_contracts(runner_contract, cap_contract)
    return len(mismatches) == 0, mismatches


def stamp_universe_contract(
    doc: Dict[str, Any],
    contract: Mapping[str, Any],
) -> Dict[str, Any]:
    doc["universe_contract"] = dict(contract)
    return doc
