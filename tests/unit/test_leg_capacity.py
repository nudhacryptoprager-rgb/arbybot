"""Universal leg capacity + continuity contract tests."""
from __future__ import annotations

from types import SimpleNamespace

from m9.graph_arb.leg_capacity import (
    REJECT_LEG_AMOUNT_EXCEEDS_POOL_CAPACITY,
    REJECT_ONE_DIRECTION_ONLY,
    maverick_has_direction_probe,
    resolve_leg_amount_in,
    route_probe_direction_status,
)


def _edge(**kwargs):
    defaults = {
        "adapter_type": "maverick_v2",
        "token_in_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "maverick_max_quoteable_amount_raw": 10**15,
        "maverick_probe_by_token_in": {
            "0x4200000000000000000000000000000000000006": {
                "maverick_max_quoteable_amount_raw": 10**15,
            }
        },
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestLegCapacityContinuity:
    def test_leg_gt_zero_never_caps_to_probe_amount(self):
        propagated = 11837802819199971
        resolved, reject = resolve_leg_amount_in(
            _edge(token_in_addr="0x4200000000000000000000000000000000000006"),
            propagated,
            leg_index=1,
        )
        assert resolved == propagated
        assert reject == REJECT_LEG_AMOUNT_EXCEEDS_POOL_CAPACITY

    def test_leg_gt_zero_without_direction_probe_one_direction_only(self):
        edge = _edge(
            token_in_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            maverick_probe_by_token_in={
                "0x4200000000000000000000000000000000000006": {
                    "maverick_max_quoteable_amount_raw": 10**15,
                }
            },
        )
        assert not maverick_has_direction_probe(edge)
        _resolved, reject = resolve_leg_amount_in(edge, 10**12, leg_index=1)
        assert reject == REJECT_ONE_DIRECTION_ONLY

    def test_leg_zero_still_bootstraps_maverick_probe(self):
        edge = _edge(
            maverick_min_quoteable_amount_raw=10_000,
            maverick_pool_lane_probe_amount=10**15,
            maverick_max_quoteable_amount_raw=10**15,
        )
        resolved, reject = resolve_leg_amount_in(edge, 10**18, leg_index=0)
        assert reject is None
        assert resolved == 10_000

    def test_route_probe_direction_status_bidirectional(self):
        route = {
            "adapter_type": "maverick_v2",
            "maverick_probe_by_token_in": {
                "0xaaa": {},
                "0xbbb": {},
            },
        }
        assert route_probe_direction_status(route) == "BIDIRECTIONAL"

    def test_route_probe_direction_status_one_direction(self):
        route = {
            "adapter_type": "maverick_v2",
            "maverick_probe_by_token_in": {"0xaaa": {}},
        }
        assert route_probe_direction_status(route) == "ONE_DIRECTION_ONLY"
