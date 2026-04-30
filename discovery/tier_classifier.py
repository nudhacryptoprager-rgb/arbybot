"""Tiered pool topology scaffold (hot / warm / cold).

Reviewer post-2h-soak step #7: classify pools into tiers so the runtime
can budget RPC quota and refresh cadence per tier rather than scanning a
flat list. The 2h Base soak demonstrated that a flat universe under a
shared latency budget produces ``FAST_PATH_SCORED_TOO_LOW=1`` because
inactive pools consume calls that should have gone to the few hot pools.

This module is a **pure-function scaffold**:
  - no I/O, no globals,
  - inputs are a ``PoolActivitySnapshot`` and the current wall clock,
  - outputs a ``PoolTier`` literal that the discovery / orderflow layer
    can attach to existing pool registry entries as a side label.

A future iteration will:
  - wire the classifier into ``discovery.runtime`` to attach a tier to
    each ``DiscoveredPool``,
  - feed the tier into the latency budget so HOT pools get sub-200ms
    refresh while COLD pools refresh on a much slower cadence.

The threshold values are intentionally configurable via the dataclass so
that operators can tune them without code changes once observed activity
distributions stabilise on each chain.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


__all__ = [
    "PoolTier",
    "TierThresholds",
    "PoolActivitySnapshot",
    "classify_tier",
]


PoolTier = Literal["hot", "warm", "cold"]


@dataclass(frozen=True)
class TierThresholds:
    """Cutoffs in seconds for the activity-recency classification.

    Default: HOT = swap within last 2 minutes; WARM = within last 30
    minutes; otherwise COLD. Defaults are chosen to match the M7 hot
    sweep refresh window (в‰€120s) and the production scan loop cadence.
    """

    hot_max_age_s: float = 120.0
    warm_max_age_s: float = 1800.0

    def __post_init__(self) -> None:
        if self.hot_max_age_s <= 0 or self.warm_max_age_s <= 0:
            raise ValueError("thresholds must be positive")
        if self.hot_max_age_s >= self.warm_max_age_s:
            raise ValueError("hot threshold must be smaller than warm threshold")


@dataclass(frozen=True)
class PoolActivitySnapshot:
    """Minimum activity signal needed to classify a pool.

    ``last_swap_ts`` is the wall-clock timestamp (epoch seconds) of the
    most recent observed swap. ``None`` means we have never observed a
    swap on this pool вЂ" the pool is automatically COLD.
    """

    pool_address: str
    last_swap_ts: float | None
    swap_count_window: int = 0  # informational; not used for current tier
    chain: str = ""


def classify_tier(
    snapshot: PoolActivitySnapshot,
    *,
    now_ts: float,
    thresholds: TierThresholds | None = None,
) -> PoolTier:
    """Return the tier for ``snapshot`` based on swap recency.

    The function is total: it never raises for valid input, and
    ``last_swap_ts is None`` deterministically returns ``"cold"``.
    """
    if thresholds is None:
        thresholds = TierThresholds()
    if snapshot.last_swap_ts is None:
        return "cold"
    age = now_ts - snapshot.last_swap_ts
    if age < 0:
        # Future timestamp вЂ" treat as just-active (clock skew tolerance).
        return "hot"
    if age <= thresholds.hot_max_age_s:
        return "hot"
    if age <= thresholds.warm_max_age_s:
        return "warm"
    return "cold"




# ---------------------------------------------------------------------------
# E1.42 Iter 5 - runtime wiring helpers (still side-effect controlled).
#
# These build on the pure ``classify_tier`` primitive and provide the
# minimal aggregation + artifact API the cold lane needs to emit a tier
# map for the hot lane to consume. No RPC, no globals.
# ---------------------------------------------------------------------------

import json as _json
import os as _os
import tempfile as _tempfile
from datetime import datetime as _datetime, timezone as _timezone
from typing import Dict, Iterable, List, Optional


TIER_MAP_SCHEMA_VERSION = "tier_map_v1"
_DEFAULT_TIER_MAP_DIR = _os.path.join("data", "runs", "_rolling")


def default_tier_map_path(chain: str, root: Optional[str] = None) -> str:
    """Canonical tier-map artifact path."""
    base = root or _DEFAULT_TIER_MAP_DIR
    return _os.path.join(base, f"m7_tier_map_{chain}.json")


def classify_pools_to_tiers(
    snapshots: Iterable["PoolActivitySnapshot"],
    *,
    now_ts: float,
    thresholds: TierThresholds | None = None,
) -> Dict[str, List[str]]:
    """Return ``{"hot":[addr...], "warm":[...], "cold":[...]}`` for snapshots."""
    out: Dict[str, List[str]] = {"hot": [], "warm": [], "cold": []}
    seen: Dict[str, set] = {"hot": set(), "warm": set(), "cold": set()}
    for snap in snapshots:
        if not getattr(snap, "pool_address", None):
            continue
        tier = classify_tier(snap, now_ts=now_ts, thresholds=thresholds)
        addr = str(snap.pool_address).lower()
        if addr in seen[tier]:
            continue
        seen[tier].add(addr)
        out[tier].append(addr)
    return out


def write_tier_map_artifact(
    tier_map: Dict[str, List[str]],
    *,
    chain: str,
    path: Optional[str] = None,
    now_iso: Optional[str] = None,
) -> str:
    """Atomic-write the tier map. Returns the path written."""
    p_out = path or default_tier_map_path(chain)
    payload = {
        "schema_version": TIER_MAP_SCHEMA_VERSION,
        "chain": chain,
        "updated_at": now_iso or _datetime.now(_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {k: len(v) for k, v in tier_map.items()},
        "tiers": {k: list(v) for k, v in tier_map.items()},
    }
    _os.makedirs(_os.path.dirname(p_out), exist_ok=True)
    fd, tmp = _tempfile.mkstemp(
        dir=_os.path.dirname(p_out), suffix=".tmp", prefix=".arby_tier_"
    )
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump(payload, f, indent=2, sort_keys=True)
        _os.replace(tmp, p_out)
    except BaseException:
        try:
            _os.unlink(tmp)
        except OSError:
            pass
        raise
    return p_out


def read_tier_map_artifact(
    *,
    chain: str,
    path: Optional[str] = None,
) -> Dict[str, List[str]]:
    """Read the tier map. Returns canonical empty dict on miss/error."""
    p_in = path or default_tier_map_path(chain)
    empty = {"hot": [], "warm": [], "cold": []}
    try:
        if not _os.path.exists(p_in):
            return empty
        with open(p_in, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if not isinstance(data, dict):
            return empty
        if data.get("schema_version") != TIER_MAP_SCHEMA_VERSION:
            return empty
        if data.get("chain") != chain:
            return empty
        tiers = data.get("tiers") or {}
        return {
            "hot": [str(a).lower() for a in tiers.get("hot", []) if a],
            "warm": [str(a).lower() for a in tiers.get("warm", []) if a],
            "cold": [str(a).lower() for a in tiers.get("cold", []) if a],
        }
    except (OSError, ValueError, _json.JSONDecodeError):
        return empty


__all__ = list(__all__) + [
    "classify_pools_to_tiers",
    "write_tier_map_artifact",
    "read_tier_map_artifact",
    "default_tier_map_path",
    "TIER_MAP_SCHEMA_VERSION",
]
