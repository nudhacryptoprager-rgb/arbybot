"""Pure bridge inventory projection helpers (I/O-free transforms)."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

__all__ = ["project_active_route_summary", "project_bridge_source_counters"]


def project_active_route_summary(routes: List[Mapping[str, Any]]) -> Dict[str, int]:
    return {
        "active_routes": len(routes),
        "factory_verified_routes": sum(1 for r in routes if r.get("factory_verified")),
        "m8_sniper_routes": sum(1 for r in routes if str(r.get("source") or "") == "m8_sniper"),
        "cross_mechanic_routes": sum(1 for r in routes if r.get("cross_mechanic")),
    }


def project_bridge_source_counters(
    routes: List[Mapping[str, Any]],
    *,
    exploration_routes: List[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    summary = project_active_route_summary(routes)
    exploration = list(exploration_routes or [])
    summary["exploration_routes"] = len(exploration)
    return summary
