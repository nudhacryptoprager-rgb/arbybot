"""Data-driven productive admission overrides for expansion routes."""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, Optional, Set, Union

from m9.graph_arb.depth_capacity_probe import (
    DEPTH_PROBE_ANALYTICAL_SUSPECT,
    DEPTH_PROBE_LOWER_BOUND_AT_MAX,
    DEPTH_PROBE_MEASURED_CAPACITY,
    MAX_SANE_DEPTH_USD,
    MIN_SANE_MEASURED_DEPTH_USD,
    is_measured_depth_status,
)

ProductiveDexSet = Union[Set[str], FrozenSet[str]]


def is_analytical_suspect_depth(route: Dict[str, Any]) -> bool:
    if route.get("depth_probe_status") == DEPTH_PROBE_ANALYTICAL_SUSPECT:
        return True
    depth = route.get("effective_depth_usd")
    if depth is None:
        return False
    try:
        return float(depth) > MAX_SANE_DEPTH_USD
    except (TypeError, ValueError):
        return False


def is_sane_measured_depth(route: Dict[str, Any]) -> bool:
    """Measured depth in the productive admission band (excludes analytical outliers)."""
    if is_analytical_suspect_depth(route):
        return False
    status = route.get("depth_probe_status")
    if not is_measured_depth_status(status):
        return False
    depth = route.get("effective_depth_usd")
    if depth is None:
        return False
    try:
        depth_f = float(depth)
    except (TypeError, ValueError):
        return False
    return MIN_SANE_MEASURED_DEPTH_USD <= depth_f <= MAX_SANE_DEPTH_USD


def measured_depth_productive_override(route: Dict[str, Any]) -> bool:
    """Admit a non-productive-config dex when depth is measured and sane."""
    return is_sane_measured_depth(route)


def expansion_productive_admit(
    route: Dict[str, Any],
    productive_dexes: ProductiveDexSet,
) -> bool:
    """Config gate with per-route measured-depth override (no blanket V4 enable)."""
    dex_id = str(route.get("dex_id") or "")
    if dex_id in productive_dexes:
        return True
    return measured_depth_productive_override(route)


def refresh_expansion_productive_admit(
    route: Dict[str, Any],
    productive_dexes: ProductiveDexSet,
) -> bool:
    """Recompute ``expansion_productive_admit`` after depth enrichment."""
    admitted = expansion_productive_admit(route, productive_dexes)
    route["expansion_productive_admit"] = admitted
    if admitted and str(route.get("dex_id") or "") not in productive_dexes:
        route["expansion_productive_admit_source"] = "measured_depth_override"
    return admitted
