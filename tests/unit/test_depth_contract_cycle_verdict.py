"""Tests for the cycle-level economic capacity verdict (Step 2 P0)."""
from __future__ import annotations

from m9.graph_arb.depth_contract import (
    REASON_BELOW_FLOOR,
    REASON_EMPTY_CYCLE,
    REASON_READY,
    REASON_UNKNOWN_DEPTH,
    cycle_contract_hash,
    evaluate_cycle_economic_capacity,
    evaluate_cycles_economic_capacity,
    required_route_depth_usd,
)
from m9.graph_arb.models import GraphCycle, GraphEdge


def _edge(
    route_id="r1",
    dex_id="maverick_v2",
    adapter_type="maverick_v2",
    depth=10.0,
    depth_probe_status=None,
    token_in="USDC",
    token_out="DAI",
):
    return GraphEdge(
        token_in_sym=token_in,
        token_out_sym=token_out,
        token_in_addr="0x0",
        token_out_addr="0x1",
        token_in_decimals=6,
        token_out_decimals=18,
        route_id=route_id,
        dex_id=dex_id,
        adapter_type=adapter_type,
        fee=0,
        tick_spacing=None,
        quoter_addr="0xquoter",
        pool_address="0xpool",
        fee_bps=0.0,
        factory_class="UNISWAP_V2",
        pair_id="DAI_USDC",
        effective_depth_usd=depth,
        depth_probe_status=depth_probe_status,
    )


def _cycle(edges):
    # GraphCycle is a dataclass with only `edges`; cycle_id/length/etc are
    # computed properties. We need >= 2 distinct-pool edges forming a closed
    # path: token_out_sym/addr of edge[i] == token_in_sym/addr of edge[i+1].
    # For a 2-leg cycle A->B->A, the second edge must go B->A (sym + addr).
    if len(edges) == 2:
        src = edges[0]
        e2 = GraphEdge(
            **{
                **edges[1].__dict__,
                "token_in_sym": src.token_out_sym,
                "token_out_sym": src.token_in_sym,
                "token_in_addr": src.token_out_addr,
                "token_out_addr": src.token_in_addr,
            }
        )
        # ensure distinct pools
        if e2.pool_address.lower() == src.pool_address.lower():
            e2 = GraphEdge(**{**e2.__dict__, "pool_address": "0xpool2"})
        edges = [src, e2]
    return GraphCycle(edges=tuple(edges))


def test_required_route_depth_maverick_fallback():
    # Maverick fallback fraction = 0.02 → floor 180 / 0.02 = 9000
    req = required_route_depth_usd(180.0, "maverick_v2", depth_probe_status=None)
    assert req == 9000.0


def test_required_route_depth_maverick_measured():
    # Maverick measured fraction = 0.15 → floor 180 / 0.15 = 1200
    req = required_route_depth_usd(180.0, "maverick_v2", depth_probe_status="MEASURED_CAPACITY")
    assert req == 1200.0


def test_required_route_depth_zero_floor():
    assert required_route_depth_usd(0.0, "v2_fork") == 0.0


def test_evaluate_ready_cycle():
    # depth 2000, measured → usable = 2000 * 0.15 = 300 >= 180
    e = _edge(depth=2000.0, depth_probe_status="MEASURED_CAPACITY")
    c = _cycle([e, e])
    v = evaluate_cycle_economic_capacity(c, 180.0)
    assert v.ready is True
    assert v.reason == REASON_READY


def test_evaluate_below_floor():
    # depth 10, fallback maverick → usable = 10 * 0.02 = 0.2 < 180
    e = _edge(depth=10.0, depth_probe_status=None)
    c = _cycle([e, e])
    v = evaluate_cycle_economic_capacity(c, 180.0)
    assert v.ready is False
    assert v.reason == REASON_BELOW_FLOOR
    assert v.usable_capacity_usd is not None and v.usable_capacity_usd < 180.0


def test_evaluate_unknown_depth():
    e1 = _edge(route_id="r1", depth=2000.0, depth_probe_status="MEASURED_CAPACITY")
    e2 = _edge(route_id="r2", depth=None)
    c = _cycle([e1, e2])
    v = evaluate_cycle_economic_capacity(c, 180.0)
    assert v.ready is False
    assert v.reason == REASON_UNKNOWN_DEPTH
    assert v.raw_depth_usd is None


def test_evaluate_empty_cycle():
    # GraphCycle requires >=2 edges at construction, but the verdict function
    # must still handle an empty edge list defensively (e.g. if called with a
    # synthetic cycle). We bypass GraphCycle by constructing a minimal stub.
    class _StubCycle:
        cycle_id = "empty"
        length = 0
        edges = ()
    v = evaluate_cycle_economic_capacity(_StubCycle(), 180.0)
    assert v.ready is False
    assert v.reason == REASON_EMPTY_CYCLE


def test_bottleneck_identified():
    e1 = _edge(route_id="deep", depth=5000.0, depth_probe_status="MEASURED_CAPACITY")
    e2 = _edge(route_id="shallow", depth=10.0, depth_probe_status=None)
    c = _cycle([e1, e2])
    v = evaluate_cycle_economic_capacity(c, 180.0)
    assert v.bottleneck_route_id == "shallow"


def test_cycle_contract_hash_stable():
    e = _edge(depth=2000.0, depth_probe_status="MEASURED_CAPACITY")
    c = _cycle([e, e])
    v = evaluate_cycle_economic_capacity(c, 180.0)
    h1 = cycle_contract_hash(v)
    h2 = cycle_contract_hash(v)
    assert h1 == h2 and len(h1) == 16


def test_evaluate_cycles_batch():
    e = _edge(depth=2000.0, depth_probe_status="MEASURED_CAPACITY")
    c = _cycle([e, e])
    verdicts = evaluate_cycles_economic_capacity([c, c], 180.0)
    assert len(verdicts) == 2
    assert all(v.ready for v in verdicts)


def test_cycle_contract_hash_changes_when_any_leg_changes():
    e1 = _edge(depth=9000.0, route_id="r1")
    e2 = _edge(depth=9000.0, route_id="r2")
    e3 = _edge(depth=7000.0, route_id="r3")
    c_same = _cycle([e1, e2])
    c_diff = _cycle([e1, e3])
    h_same = cycle_contract_hash(evaluate_cycle_economic_capacity(c_same, 180.0))
    h_diff = cycle_contract_hash(evaluate_cycle_economic_capacity(c_diff, 180.0))
    assert h_same != h_diff


def test_cycle_contract_hash_distinguishes_zero_from_none():
    from m9.graph_arb.depth_contract import CycleCapacityVerdict

    base = {
        "cycle_id": "c1",
        "ready": False,
        "reason": "BELOW_FLOOR",
        "bottleneck_route_id": "r1",
        "bottleneck_dex_id": "maverick_v2",
        "bottleneck_adapter_type": "maverick_v2",
        "family_fraction": 0.02,
        "usable_capacity_usd": 0.0,
        "required_depth_usd": 9000.0,
        "economics_floor_usd": 180.0,
        "length": 2,
        "leg_verdicts": (
            {
                "route_id": "r1",
                "dex_id": "maverick_v2",
                "adapter_type": "maverick_v2",
                "family": "maverick",
                "raw_depth_usd": 0,
                "family_fraction": 0.02,
                "usable_capacity_usd": 0.0,
                "required_depth_usd": 9000.0,
                "reason": "BELOW_FLOOR",
            },
        ),
    }
    v_zero = CycleCapacityVerdict(**{**base, "raw_depth_usd": 0})
    v_none = CycleCapacityVerdict(**{**base, "raw_depth_usd": None})
    assert cycle_contract_hash(v_zero) != cycle_contract_hash(v_none)


def test_to_dict_roundtrip():
    e = _edge(depth=10.0)
    c = _cycle([e, e])
    v = evaluate_cycle_economic_capacity(c, 180.0)
    d = v.to_dict()
    assert d["ready"] is False
    assert "leg_verdicts" in d and len(d["leg_verdicts"]) == 2
