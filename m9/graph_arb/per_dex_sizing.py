"""Per-adapter-family depth-aware size caps for M9 quote ladders."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from m9.graph_arb.adapter_families import (
    FAMILY_BALANCER_VAULT,
    FAMILY_CURVE_STABLE,
    FAMILY_MAVERICK_V2,
    FAMILY_V2_FORK,
    FAMILY_V3_FORK,
    FAMILY_V4_POOL_MANAGER,
    route_family,
)

# Max fraction of effective depth to quote per family (unknown / fallback-capped).
DEPTH_FRACTION_BY_FAMILY: Dict[str, float] = {
    FAMILY_V2_FORK: 0.12,
    FAMILY_V3_FORK: 0.18,
    FAMILY_V4_POOL_MANAGER: 0.10,
    FAMILY_CURVE_STABLE: 0.15,
    FAMILY_BALANCER_VAULT: 0.02,
    FAMILY_MAVERICK_V2: 0.02,
    "aerodrome_ve33_volatile": 0.12,
    "aerodrome_ve33_stable": 0.10,
    "aerodrome_slipstream_cl": 0.15,
}

# Raised fractions when ``depth_probe_status`` confirms measured capacity.
DEPTH_FRACTION_MEASURED_BY_FAMILY: Dict[str, float] = {
    FAMILY_BALANCER_VAULT: 0.15,
    FAMILY_MAVERICK_V2: 0.15,
    FAMILY_CURVE_STABLE: 0.20,
    FAMILY_V2_FORK: 0.15,
    FAMILY_V3_FORK: 0.20,
    FAMILY_V4_POOL_MANAGER: 0.12,
}

_DEFAULT_DEPTH_FRACTION: float = 0.15
_MIN_PROBE_USD: float = 0.02
_GLOBAL_MICRO_LADDER: Tuple[float, ...] = (0.25, 0.5, 1.0, 5.0, 10.0)


def _edge_depth_probe_status(edge: Any) -> Optional[str]:
    return getattr(edge, "depth_probe_status", None)


def depth_fraction_for_family(
    family: str,
    *,
    depth_probe_status: Optional[str] = None,
) -> float:
    from m9.graph_arb.depth_capacity_probe import is_measured_depth_status

    base = DEPTH_FRACTION_BY_FAMILY.get(family, _DEFAULT_DEPTH_FRACTION)
    if is_measured_depth_status(depth_probe_status):
        measured = DEPTH_FRACTION_MEASURED_BY_FAMILY.get(family, base)
        return max(base, measured)
    return base


def bottleneck_depth_fraction(edges: Iterable[Any]) -> float:
    """Tightest depth fraction across cycle edges (bottleneck pool wins)."""
    fractions = []
    for edge in edges:
        fam = route_family(
            {
                "dex_id": getattr(edge, "dex_id", None),
                "adapter_type": getattr(edge, "adapter_type", None),
            }
        )
        fractions.append(
            depth_fraction_for_family(fam, depth_probe_status=_edge_depth_probe_status(edge))
        )
    return min(fractions) if fractions else _DEFAULT_DEPTH_FRACTION


def cap_sizes_to_depth_per_family(
    sizes_usd: Sequence[float],
    depth_usd: Optional[float],
    *,
    edges: Optional[Iterable[Any]] = None,
    global_fraction: Optional[float] = None,
) -> Tuple[float, ...]:
    """Clamp ladder using per-family depth fraction; global_fraction is fallback."""
    if depth_usd is None or depth_usd <= 0:
        return tuple(float(s) for s in sizes_usd if float(s) > 0) or _GLOBAL_MICRO_LADDER

    fraction = global_fraction
    if fraction is None and edges is not None:
        fraction = bottleneck_depth_fraction(edges)
    if fraction is None:
        fraction = _DEFAULT_DEPTH_FRACTION

    cap = float(depth_usd) * fraction
    candidates = tuple(float(s) for s in sizes_usd if float(s) > 0)
    kept = tuple(s for s in candidates if s <= cap)
    if kept:
        return kept
    probe = max(cap, _MIN_PROBE_USD)
    return (round(probe, 6),)


_PRODUCTIVE_DISTINCT_MICRO_CAP_USD: float = 0.05


def _cycle_has_measured_depth(cycle: Any) -> bool:
    from m9.graph_arb.depth_capacity_probe import is_measured_depth_status

    depth = getattr(cycle, "min_effective_depth_usd", None)
    if isinstance(depth, (int, float)) and not isinstance(depth, bool) and float(depth) > 100.0:
        return True
    for edge in getattr(cycle, "edges", ()) or ():
        if is_measured_depth_status(_edge_depth_probe_status(edge)):
            return True
        edge_depth = getattr(edge, "effective_depth_usd", None)
        if edge_depth is not None and float(edge_depth) > 100.0:
            return True
    return False


def productive_cycle_size_usd_cap(
    cycle: Any,
    size_usd: float,
    token_price_usd: Optional[Dict[str, float]] = None,
) -> float:
    """Cap cycle USD notional when distinct-pricing legs lack measured depth."""
    _ = token_price_usd
    if _cycle_has_measured_depth(cycle):
        return float(size_usd)
    edges = getattr(cycle, "edges", ()) or ()
    for edge in edges:
        fam = route_family(
            {
                "dex_id": getattr(edge, "dex_id", None),
                "adapter_type": getattr(edge, "adapter_type", None),
            }
        )
        if fam in (FAMILY_MAVERICK_V2, FAMILY_BALANCER_VAULT, FAMILY_CURVE_STABLE):
            return min(float(size_usd), _PRODUCTIVE_DISTINCT_MICRO_CAP_USD)
    return float(size_usd)


def micro_ladder_for_family(family: str) -> Tuple[float, ...]:
    """Optional family-specific micro front; global ladder is fallback."""
    if family in (FAMILY_MAVERICK_V2, FAMILY_BALANCER_VAULT):
        return (0.02, 0.05, 0.1, 0.25, 0.5, 1.0)
    if family == FAMILY_V4_POOL_MANAGER:
        return (0.25, 0.5, 1.0, 5.0, 10.0)
    return _GLOBAL_MICRO_LADDER
