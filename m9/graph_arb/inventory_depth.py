"""Merge depth / pool-quality fields between M9 inventories."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_VERIFIED_DEFAULT = "data/tmp/m9_verified_inventory.json"
_BRIDGE_DEFAULT = "data/runs/_rolling/m9_bridge_inventory_latest.json"

_DEPTH_KEYS = (
    "effective_depth_usd",
    "pool_quality_state",
    "depth_probe_status",
    "depth_probe_error",
)


def _index_routes(routes: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_pool: Dict[str, Dict[str, Any]] = {}
    by_route: Dict[str, Dict[str, Any]] = {}
    for r in routes:
        pool = (r.get("pool_address") or "").strip().lower()
        if pool:
            by_pool[pool] = r
        rid = r.get("route_id")
        if rid:
            by_route[str(rid)] = r
    return by_pool, by_route


def merge_depth_from_bridge(
    target_routes: List[Dict[str, Any]],
    bridge_routes: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Copy depth fields from bridge routes into *target_routes* (in place)."""
    by_pool, by_route = _index_routes(bridge_routes)
    merged = 0
    for r in target_routes:
        src = None
        pool = (r.get("pool_address") or "").strip().lower()
        if pool:
            src = by_pool.get(pool)
        if src is None:
            rid = r.get("route_id")
            if rid:
                src = by_route.get(str(rid))
        if not src:
            continue
        if src.get("effective_depth_usd") is None:
            continue
        for key in _DEPTH_KEYS:
            if src.get(key) is not None:
                r[key] = src[key]
        merged += 1
    return {"merged": merged, "target": len(target_routes)}


def merge_verified_inventory_from_bridge(
    verified_path: str = _VERIFIED_DEFAULT,
    bridge_path: str = _BRIDGE_DEFAULT,
    *,
    write: bool = True,
) -> Dict[str, Any]:
    """Load verified + bridge inventories; merge depth into verified active routes."""
    vpath = Path(verified_path)
    bpath = Path(bridge_path)
    if not vpath.exists():
        raise FileNotFoundError(f"Verified inventory missing: {vpath}")
    if not bpath.exists():
        raise FileNotFoundError(f"Bridge inventory missing: {bpath}")

    verified = json.loads(vpath.read_text(encoding="utf-8"))
    bridge = json.loads(bpath.read_text(encoding="utf-8"))
    active = verified.get("active_routes", [])
    stats = merge_depth_from_bridge(active, bridge.get("active_routes", []))
    stats["with_depth_after"] = sum(
        1 for r in active if r.get("effective_depth_usd") is not None
    )
    stats["verified_path"] = str(vpath)
    stats["bridge_path"] = str(bpath)

    if write:
        tmp = str(vpath) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(verified, fh, indent=2)
        os.replace(tmp, str(vpath))
        logger.info(
            "Merged depth into verified inventory: merged=%d with_depth=%d/%d",
            stats["merged"],
            stats["with_depth_after"],
            len(active),
        )
    return stats


def ensure_verified_depth_merged(
    inventory_path: str,
    *,
    bridge_path: str = _BRIDGE_DEFAULT,
) -> Optional[Dict[str, Any]]:
    """If *inventory_path* is the verified inventory, merge bridge depth first."""
    norm = inventory_path.replace("\\", "/")
    if "m9_verified_inventory" not in norm:
        return None
    if not Path(bridge_path).exists():
        logger.warning("Bridge inventory missing; skip depth merge: %s", bridge_path)
        return None
    return merge_verified_inventory_from_bridge(
        verified_path=inventory_path,
        bridge_path=bridge_path,
        write=True,
    )
