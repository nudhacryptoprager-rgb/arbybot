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
    sweep refresh window (≈120s) and the production scan loop cadence.
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
    swap on this pool — the pool is automatically COLD.
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
        # Future timestamp — treat as just-active (clock skew tolerance).
        return "hot"
    if age <= thresholds.hot_max_age_s:
        return "hot"
    if age <= thresholds.warm_max_age_s:
        return "warm"
    return "cold"
