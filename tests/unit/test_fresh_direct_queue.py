"""Tests for fresh-direct cohort queue transitions."""
from __future__ import annotationsimport pytestfrom m8.discovery.fresh_direct_queue import (    FreshDirectQueue,    FreshDirectState,    build_fresh_direct_queue_snapshot,    max_snapshot_state,    transition_fresh_direct_state,)def test_transition_rejects_backward_path():
    with pytest.raises(ValueError):
        transition_fresh_direct_state(
            FreshDirectState.QUOTED,
            FreshDirectState.DISCOVERED,
        )


def test_max_snapshot_state_order_independent():
    assert max_snapshot_state(
        FreshDirectState.ANCHOR_VALID,
        FreshDirectState.METADATA_READY,
    ) == FreshDirectState.METADATA_READY
    assert max_snapshot_state(
        FreshDirectState.METADATA_READY,
        FreshDirectState.ANCHOR_VALID,
    ) == FreshDirectState.METADATA_READY


def _same_pool_routes(order_anchor_first: bool) -> list[dict]:
    anchor = {
        "route_id": "r_anchor",
        "pool_address": "0xabc",
        "source": "m8_sniper",
        "factory_verified": True,
    }
    meta = {
        "route_id": "r_meta",
        "pool_address": "0xabc",
        "source": "m8_sniper",
        "m8_3_preflight_applied": True,
    }
    return [anchor, meta] if order_anchor_first else [meta, anchor]


@pytest.mark.parametrize("order_anchor_first", [True, False])
def test_same_pool_anchor_and_metadata_both_orders(order_anchor_first: bool):
    routes = _same_pool_routes(order_anchor_first)
    snap_a = build_fresh_direct_queue_snapshot(bridge={"active_routes": routes})
    snap_b = build_fresh_direct_queue_snapshot(bridge={"active_routes": list(reversed(routes))})
    assert snap_a["by_state"] == snap_b["by_state"]
    assert snap_a["by_state"]["metadata_ready"] == 1
    assert snap_a["by_state"]["anchor_valid"] == 0


def test_snapshot_metadata_ready_route_from_discovered():
    snap = build_fresh_direct_queue_snapshot(
        bridge={
            "active_routes": [
                {
                    "route_id": "r_meta",
                    "pool_address": "0xabc",
                    "token0": "0xt0",
                    "token1": "0xt1",
                    "source": "m8_sniper",
                    "m8_3_preflight_applied": True,
                }
            ]
        }
    )
    assert snap["by_state"]["metadata_ready"] == 1


def test_snapshot_mirror_verified_route():
    snap = build_fresh_direct_queue_snapshot(
        bridge={
            "active_routes": [
                {
                    "route_id": "r_mirror",
                    "pool_address": "0xdef",
                    "source": "m8_sniper",
                    "mirror_of": "0xparent",
                }
            ]
        }
    )
    assert snap["by_state"]["mirror_verified"] == 1


def test_live_queue_still_advances_via_transition():
    queue = FreshDirectQueue()
    queue.assign_from_route_snapshot("0xabc", state=FreshDirectState.ANCHOR_VALID)
    queue.assign_from_route_snapshot("0xabc", state=FreshDirectState.METADATA_READY)
    snap = queue.snapshot()
    assert snap["by_state"]["metadata_ready"] == 1


def test_routes_in_different_order_produce_same_counts():
    routes_a = [
        {"route_id": "r1", "pool_address": "0x1", "source": "m8_sniper", "factory_verified": True},
        {
            "route_id": "r2",
            "pool_address": "0x2",
            "source": "m8_sniper",
            "m8_3_preflight_applied": True,
        },
    ]
    routes_b = list(reversed(routes_a))
    snap_a = build_fresh_direct_queue_snapshot(bridge={"active_routes": routes_a})
    snap_b = build_fresh_direct_queue_snapshot(bridge={"active_routes": routes_b})
    assert snap_a["by_state"] == snap_b["by_state"]
