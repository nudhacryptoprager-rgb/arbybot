"""Shared AMM pool metadata helpers for M8.3 dex workers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def amm_pool_static_metadata(route: Dict[str, Any]) -> Dict[str, Any]:
    """Static pool fields only — no reserves/depth/liquidity."""
    return {
        "pool_address": route.get("pool_address"),
        "token0": route.get("token0_addr"),
        "token1": route.get("token1_addr"),
        "token0_addr": route.get("token0_addr"),
        "token1_addr": route.get("token1_addr"),
        "fee": route.get("fee"),
        "tick_spacing": route.get("tick_spacing"),
        "factory_verified": route.get("factory_verified"),
        "factory_source": route.get("factory") or route.get("factory_address") or route.get("dex_id"),
        "init_state_available": bool(
            route.get("pool_address")
            and route.get("token0_addr")
            and route.get("token1_addr")
        ),
        "direction_support": "bidirectional",
    }
