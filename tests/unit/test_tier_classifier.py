"""Tests for ``discovery.tier_classifier`` scaffold (post-2h-soak step #7)."""
from __future__ import annotations

import pytest

from discovery.tier_classifier import (
    PoolActivitySnapshot,
    TierThresholds,
    classify_tier,
)


NOW = 1_700_000_000.0


def _snap(*, age: float | None) -> PoolActivitySnapshot:
    return PoolActivitySnapshot(
        pool_address="0xPOOL",
        last_swap_ts=None if age is None else NOW - age,
        chain="base",
    )


class TestTierThresholds:
    def test_default_thresholds_are_ordered(self):
        t = TierThresholds()
        assert t.hot_max_age_s < t.warm_max_age_s

    def test_invalid_ordering_rejected(self):
        with pytest.raises(ValueError):
            TierThresholds(hot_max_age_s=600.0, warm_max_age_s=120.0)

    def test_negative_threshold_rejected(self):
        with pytest.raises(ValueError):
            TierThresholds(hot_max_age_s=-1.0, warm_max_age_s=10.0)


class TestClassifyTier:
    def test_unknown_last_swap_is_cold(self):
        assert classify_tier(_snap(age=None), now_ts=NOW) == "cold"

    def test_recent_swap_is_hot(self):
        assert classify_tier(_snap(age=10.0), now_ts=NOW) == "hot"

    def test_boundary_hot_inclusive(self):
        # Default hot threshold = 120s.
        assert classify_tier(_snap(age=120.0), now_ts=NOW) == "hot"

    def test_just_past_hot_is_warm(self):
        assert classify_tier(_snap(age=121.0), now_ts=NOW) == "warm"

    def test_warm_boundary_inclusive(self):
        assert classify_tier(_snap(age=1800.0), now_ts=NOW) == "warm"

    def test_just_past_warm_is_cold(self):
        assert classify_tier(_snap(age=1801.0), now_ts=NOW) == "cold"

    def test_far_past_is_cold(self):
        assert classify_tier(_snap(age=86400.0), now_ts=NOW) == "cold"

    def test_future_ts_treated_as_hot(self):
        # Clock skew tolerance: future last_swap_ts -> hot, never raise.
        snap = PoolActivitySnapshot(
            pool_address="0xPOOL", last_swap_ts=NOW + 5.0, chain="base"
        )
        assert classify_tier(snap, now_ts=NOW) == "hot"

    def test_custom_thresholds_respected(self):
        t = TierThresholds(hot_max_age_s=10.0, warm_max_age_s=60.0)
        assert classify_tier(_snap(age=5.0), now_ts=NOW, thresholds=t) == "hot"
        assert classify_tier(_snap(age=30.0), now_ts=NOW, thresholds=t) == "warm"
        assert classify_tier(_snap(age=120.0), now_ts=NOW, thresholds=t) == "cold"
