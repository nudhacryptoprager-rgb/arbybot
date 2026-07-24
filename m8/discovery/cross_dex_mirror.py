"""Mirror readiness scoring for M8.2 cross-DEX expansion (extracted module)."""
from __future__ import annotations

from typing import Any, Dict


def same_pair_route_quoteable(route: Dict[str, Any]) -> bool:
    status = str(route.get("quote_smoke_status") or route.get("quote_smoke") or "")
    upper = status.upper()
    if not upper or upper in ("NOT_RUN", "SKIPPED_REGISTRY"):
        return False
    if "SKIPPED_REGISTRY" in upper:
        return False
    if any(upper.startswith(p) for p in ("QUOTE_OK", "OK", "PASS", "SUCCESS", "INDEXED")):
        return True
    return route.get("effective_depth_usd") is not None


def mirror_missing_reason(
    *,
    token_seen_on_dexes: int,
    same_pair_routes: int,
    same_pair_dexes: int,
    quoteable_same_pair_routes: int = 0,
    topology_ready: bool = False,
) -> str:
    if token_seen_on_dexes < 2:
        return "TOKEN_SEEN_ON_ONE_DEX"
    if same_pair_routes < 2:
        return "SAME_PAIR_ROUTES_LT_2"
    if same_pair_dexes < 2:
        return "SAME_PAIR_DEXES_LT_2"
    if topology_ready and quoteable_same_pair_routes < 2:
        return "SAME_PAIR_QUOTES_LT_2"
    return "READY"


def evaluate_mirror_readiness(
    *,
    token_seen_on_dexes: int,
    same_pair_routes: int,
    same_pair_dexes: int,
    quoteable_same_pair_routes: int = 0,
) -> Dict[str, Any]:
    """M8.2 2-leg same-pair mirror gate (parallel to 3+ token subgraph_ready)."""
    mirror_topology_ready = (
        token_seen_on_dexes >= 2
        and same_pair_routes >= 2
        and same_pair_dexes >= 2
    )
    mirror_quote_ready = mirror_topology_ready and quoteable_same_pair_routes >= 2
    same_pair_mirror_token = same_pair_routes >= 2 and same_pair_dexes >= 2
    return {
        "token_seen_on_dexes": token_seen_on_dexes,
        "same_pair_routes": same_pair_routes,
        "same_pair_dexes": same_pair_dexes,
        "quoteable_same_pair_routes": quoteable_same_pair_routes,
        "same_pair_mirror_token": same_pair_mirror_token,
        "mirror_topology_ready": mirror_topology_ready,
        "mirror_quote_ready": mirror_quote_ready,
        "missing_reason": (
            "READY"
            if mirror_quote_ready
            else mirror_missing_reason(
                token_seen_on_dexes=token_seen_on_dexes,
                same_pair_routes=same_pair_routes,
                same_pair_dexes=same_pair_dexes,
                quoteable_same_pair_routes=quoteable_same_pair_routes,
                topology_ready=mirror_topology_ready,
            )
        ),
    }
