"""Unit tests for M9 shadow lane filtering and unified ranking."""
from __future__ import annotations

from unittest.mock import MagicMock

from m9.graph_arb.shadow_lane import (
    BLOCKER_NO_LONG_TAIL_TARGET_CYCLES,
    SHADOW_LANE_CAPACITY_ONLY,
    SHADOW_LANE_LONG_TAIL_TARGET,
    filter_cycles_for_shadow_lane,
    rank_shadow_cycles,
)


def _cycle(cycle_id: str, pools: list[str]) -> MagicMock:
    c = MagicMock()
    c.cycle_id = cycle_id
    c.total_fee_bps = 10.0
    c.edges = []
    for pool in pools:
        e = MagicMock()
        e.pool_address = pool
        c.edges.append(e)
    return c


_DIRECT = frozenset({"0xdirect"})
_VERIFIED_MIRROR = frozenset({"0xderived"})


class TestShadowLaneFilter:
    def test_long_tail_target_filters_non_target_cycles(self):
        cycles = [
            _cycle("broad", ["0xother"]),
            _cycle("target", ["0xdirect"]),
        ]
        filtered, blocker = filter_cycles_for_shadow_lane(
            cycles,
            mode=SHADOW_LANE_LONG_TAIL_TARGET,
            capacity_ids=set(),
            direct_pool_addrs=_DIRECT,
            verified_mirror_pool_addrs=_VERIFIED_MIRROR,
        )
        assert blocker is None
        assert [c.cycle_id for c in filtered] == ["target"]

    def test_long_tail_target_empty_returns_blocker(self):
        cycles = [_cycle("broad", ["0xother"])]
        filtered, blocker = filter_cycles_for_shadow_lane(
            cycles,
            mode=SHADOW_LANE_LONG_TAIL_TARGET,
            capacity_ids=set(),
            direct_pool_addrs=_DIRECT,
            verified_mirror_pool_addrs=_VERIFIED_MIRROR,
        )
        assert filtered == []
        assert blocker == BLOCKER_NO_LONG_TAIL_TARGET_CYCLES

    def test_capacity_only_keeps_capacity_ids(self):
        cycles = [_cycle("cap", ["0xother"]), _cycle("other", ["0xother"])]
        filtered, blocker = filter_cycles_for_shadow_lane(
            cycles,
            mode=SHADOW_LANE_CAPACITY_ONLY,
            capacity_ids={"cap"},
            direct_pool_addrs=_DIRECT,
            verified_mirror_pool_addrs=_VERIFIED_MIRROR,
        )
        assert blocker is None
        assert [c.cycle_id for c in filtered] == ["cap"]


class TestShadowLaneRanking:
    def test_capacity_priority_not_overridden_by_target_rank(self):
        cycles = [
            _cycle("broad_cap", ["0xother"]),
            _cycle("target_noncap", ["0xdirect"]),
        ]
        ranked = rank_shadow_cycles(
            cycles,
            capacity_ids={"broad_cap"},
            route_meta={},
            mode=SHADOW_LANE_LONG_TAIL_TARGET,
            direct_pool_addrs=_DIRECT,
            verified_mirror_pool_addrs=_VERIFIED_MIRROR,
            capacity_prioritized=True,
        )
        assert ranked[0].cycle_id == "broad_cap"

    def test_full_capacity_set_beyond_sample_limit(self):
        cap_ids = {f"cap_{i}" for i in range(20)}
        cycles = [_cycle(f"cap_{i}", ["0xother"]) for i in range(20)]
        cycles.append(_cycle("noncap", ["0xother"]))
        filtered, blocker = filter_cycles_for_shadow_lane(
            cycles,
            mode=SHADOW_LANE_CAPACITY_ONLY,
            capacity_ids=cap_ids,
            direct_pool_addrs=_DIRECT,
            verified_mirror_pool_addrs=_VERIFIED_MIRROR,
        )
        assert blocker is None
        assert len(filtered) == 20
