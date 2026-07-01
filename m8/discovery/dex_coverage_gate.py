"""DEX coverage gate: admit DEXes only as full packages (config + factory + quote + depth)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


def _adapter_metadata_dexes() -> Dict[str, Any]:
    try:
        import yaml
        from pathlib import Path

        p = Path("config/adapter_metadata.yaml")
        if not p.is_file():
            return {}
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data.get("dexes") or data.get("adapters") or {}
    except Exception:
        return {}


def validate_dex_package(
    dex_id: str,
    config: Dict[str, Any],
    *,
    require_depth_adapter: bool = True,
) -> Dict[str, Any]:
    """Return package completeness for a DEX id."""
    dexes = config.get("dexes") or {}
    row = dexes.get(dex_id) or {}
    adapter = str(row.get("adapter_type") or "")
    factory = str(row.get("factory") or "")
    quoter = str(row.get("quoter") or row.get("quoter_v2") or "")
    enabled = bool(row.get("enabled", True))
    meta = _adapter_metadata_dexes()
    has_depth = dex_id in meta or adapter in {
        "uniswap_v3",
        "uniswap_v2",
        "uniswap_v4",
        "aerodrome_slipstream",
        "ve33",
        "aerodrome_v2_stable",
        "curve_stable",
        "balancer_stable",
        "maverick_v2",
        "algebra",
    }
    if adapter in ("ve33", "aerodrome_v2_stable", "uniswap_v2"):
        has_depth = True
    missing: List[str] = []
    if not enabled:
        missing.append("disabled_in_config")
    if not factory:
        missing.append("factory")
    if not adapter:
        missing.append("adapter_type")
    if adapter not in ("ve33", "aerodrome_v2_stable", "uniswap_v2") and not quoter:
        missing.append("quoter")
    if require_depth_adapter and not has_depth:
        missing.append("depth_adapter")
    complete = not missing or missing == ["disabled_in_config"]
    return {
        "dex_id": dex_id,
        "package_complete": complete and enabled,
        "missing": missing,
        "adapter_type": adapter,
        "hint_only_blocked": not complete,
    }


def filter_productive_dex_ids(
    dex_ids: Set[str],
    config: Dict[str, Any],
) -> Set[str]:
    """Drop hint-only DEX ids that lack a full package."""
    out: Set[str] = set()
    for dex_id in dex_ids:
        verdict = validate_dex_package(dex_id, config)
        if verdict.get("package_complete"):
            out.add(dex_id)
    return out


def classify_dex_support_status(
    *,
    source: str,
    raw_dex_id: str,
    config: Dict[str, Any],
) -> tuple[str, str]:
    """Classify external dexId for mirror max-recall (supported / unsupported / unknown_alias)."""
    from m8.discovery.pool_hints import normalize_dex_id

    raw = str(raw_dex_id or "").strip().lower()
    if not raw:
        return "", "unknown_alias"
    normalized = normalize_dex_id(source, raw_dex_id)
    internal = normalized or raw.replace("-", "_").replace(" ", "_")
    dexes = config.get("dexes") or {}
    if not internal:
        return "", "unknown_alias"
    if internal not in dexes and normalized is None:
        return internal, "unknown_alias"
    verdict = validate_dex_package(internal, config)
    if verdict.get("package_complete"):
        return internal, "supported"
    if internal in dexes:
        return internal, "unsupported"
    return internal, "unknown_alias"


def stamp_hint_support_status(
    hint,
    config: Dict[str, Any],
    *,
    source: str = "dexscreener",
):
    """Ensure hint.raw carries support_status for mirror admission metrics."""
    raw = dict(hint.raw or {})
    status = str(raw.get("support_status") or "")
    if status in ("supported", "unsupported", "unknown_alias"):
        return hint
    raw_dex = str(
        raw.get("raw_dex_id") or raw.get("dexId") or hint.dex_id or ""
    ).strip()
    internal, new_status = classify_dex_support_status(
        source=source,
        raw_dex_id=raw_dex or hint.dex_id,
        config=config,
    )
    if internal and not hint.dex_id:
        hint.dex_id = internal
    raw["support_status"] = new_status
    raw["raw_dex_id"] = raw_dex or internal or hint.dex_id
    raw["normalized_dex_id"] = internal or hint.dex_id
    hint.raw = raw
    return hint


def dex_coverage_report(config: Dict[str, Any]) -> Dict[str, Any]:
    dexes = config.get("dexes") or {}
    rows = [validate_dex_package(did, config) for did in sorted(dexes.keys())]
    complete = [r for r in rows if r.get("package_complete")]
    blocked = [r for r in rows if r.get("hint_only_blocked") and not r.get("package_complete")]
    return {
        "schema_version": "m8_dex_coverage_gate_v1",
        "dex_count": len(rows),
        "package_complete_count": len(complete),
        "hint_only_blocked_count": len(blocked),
        "dexes": rows,
    }
