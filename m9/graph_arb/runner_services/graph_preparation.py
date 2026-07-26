"""Graph preparation service — wraps inventory graph build for runner."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

__all__ = ["build_productive_adjacency"]


def build_productive_adjacency(
    *,
    inventory_path: str,
    config_path: str,
    require_factory_verified: bool,
    exclude_pool_addresses: Optional[set[str]],
    min_effective_depth_usd: float,
    lane: str,
    token_prices_usd: Optional[Dict[str, float]],
    diagnostic_admission_mode: Optional[str],
    w3: Any,
) -> Tuple[Any, Dict[str, Any]]:
    from m9.graph_arb.builder import build_graph_from_inventory

    adjacency = build_graph_from_inventory(
        inventory_path=inventory_path,
        config_path=config_path,
        require_factory_verified=require_factory_verified,
        exclude_pool_addresses=exclude_pool_addresses,
        soft_quarantine_pools=None,
        min_effective_depth_usd=min_effective_depth_usd,
        lane=lane,
        token_prices_usd=token_prices_usd,
        diagnostic_admission_mode=diagnostic_admission_mode,
        w3=w3,
    )
    metrics: Dict[str, Any] = {"route_count": len(adjacency or {})}
    return adjacency, metrics
