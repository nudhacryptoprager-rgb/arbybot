"""Active-route loading from inventory artifacts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from core.logging import get_logger

_log = get_logger(__name__)
_SUPPORTED_SCHEMA_PREFIXES = ("m8_1.",)


@dataclass(frozen=True)
class ActiveRoute:
    route_id: str
    pair_id: str
    dex_id: str
    fee: int
    factory_class: str
    pool_address: Optional[str]


def _config_pool_address_for(entry: dict, cfg: Optional[dict] = None) -> Optional[str]:
    dex_id = entry.get("dex_id")
    pair_id = entry.get("pair_id")
    if cfg is None:
        return entry.get("pool_address")
    dexes = cfg.get("dexes", {})
    dex_cfg = dexes.get(dex_id, {})
    adapter_type = dex_cfg.get("adapter_type", "_")
    pools = dex_cfg.get("pools", {})
    return pools.get(pair_id)


def load_inventory_artifact(path: "str | Path") -> dict:
    """Load and shallow-validate the inventory JSON artifact."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"inventory artifact not found: {p}")
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw)
    version = data.get("schema_version", "")
    if not any(str(version).startswith(pfx) for pfx in _SUPPORTED_SCHEMA_PREFIXES):
        raise ValueError(
            f"unsupported inventory schema_version: {version!r} "
            f"(expected {_SUPPORTED_SCHEMA_PREFIXES}*)"
        )
    if "active_routes" not in data:
        raise ValueError("inventory artifact missing 'active_routes' array")
    return data


def extract_active_routes(artifact: dict, cfg: Optional[dict] = None) -> "List[ActiveRoute]":
    routes: List[ActiveRoute] = []
    for entry in artifact.get("active_routes", []):
        route_id = entry.get("route_id", "?")
        quarantine_reason = entry.get("quarantine_reason")
        if quarantine_reason:
            pool = entry.get("pool_address")
            _log.debug(
                "inventory: skipping quarantined route %s (reason: %s pool: %s)",
                route_id, quarantine_reason, pool,
            )
            continue
        config_pool = _config_pool_address_for(entry, cfg)
        inventory_pool = entry.get("pool_address")
        if config_pool and inventory_pool and config_pool != inventory_pool:
            _log.warning(
                "inventory: skipping route %s — pool address mismatch "
                "(inventory=%s config=%s); regenerate inventory to fix",
                route_id, inventory_pool, config_pool,
            )
            continue
        routes.append(
            ActiveRoute(
                route_id=route_id,
                pair_id=entry.get("pair_id", ""),
                dex_id=entry.get("dex_id", ""),
                fee=int(entry.get("fee", 0)),
                factory_class=entry.get("factory_class", "MID_EFFICIENCY"),
                pool_address=inventory_pool,
            )
        )
    return routes


def load_active_routes(path: "str | Path", cfg: Optional[dict] = None) -> "List[ActiveRoute]":
    artifact = load_inventory_artifact(path)
    return extract_active_routes(artifact, cfg)


def active_route_ids_by_pair(routes: "List[ActiveRoute]") -> "Dict[str, Set[str]]":
    """Group route_ids by pair_id for fast O(1) lookup in the runner."""
    result: Dict[str, Set[str]] = {}
    for r in routes:
        result.setdefault(r.pair_id, set()).add(r.route_id)
    return result


def flat_active_route_ids(routes: "List[ActiveRoute]") -> "Set[str]":
    """Union of all route_ids across all pairs (for global allowlist)."""
    return {r.route_id for r in routes}
