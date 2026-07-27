"""Integration tests for P0 wiring: capacity gate, cache, transport QSR, quarantine."""
from __future__ import annotations

from m9.graph_arb.artifacts import build_artifact
from m9.graph_arb.cycle_capacity import apply_economics_capacity_gate
from m9.graph_arb.depth_contract import cycle_contract_hash, evaluate_cycle_economic_capacity
from m9.graph_arb.models import CycleQuoteResult, GraphCycle, GraphEdge, GraphTopology
from m9.graph_arb.pool_scorecard import (
    REASON_TOXIC_STABLE,
    ScorecardConfig,
    build_pool_scorecards,
    load_session_pool_quarantine_addresses,
    materialize_session_pool_quarantine,
    recommend_quarantine,
)


def _edge(route_id="r1", depth=5000.0, pool="0xpool1"):
    return GraphEdge(
        token_in_sym="USDC",
        token_out_sym="DAI",
        token_in_addr="0x0",
        token_out_addr="0x1",
        token_in_decimals=6,
        token_out_decimals=18,
        route_id=route_id,
        dex_id="maverick_v2",
        adapter_type="maverick_v2",
        fee=0,
        tick_spacing=None,
        quoter_addr="0xquoter",
        pool_address=pool,
        fee_bps=0.0,
        factory_class="UNISWAP_V2",
        pair_id="DAI_USDC",
        effective_depth_usd=depth,
    )


def _cycle(edges):
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
        if e2.pool_address.lower() == src.pool_address.lower():
            e2 = GraphEdge(**{**e2.__dict__, "pool_address": "0xpool2"})
        edges = [src, e2]
    return GraphCycle(edges=tuple(edges))


def _qr(cycle, status, size_usd=180.0, *, rpc_dispatched=False, legs=None):
    return CycleQuoteResult(
        cycle=cycle,
        size_usd=size_usd,
        amount_in=0,
        amount_out=0,
        gross_bps=0.0,
        status=status,
        reject_reason=status,
        leg_results=legs or [],
        elapsed_s=0.0,
        rpc_dispatched=rpc_dispatched,
        transport_call_count=1 if rpc_dispatched else 0,
    )


def test_apply_economics_capacity_gate_splits_ready_and_rejects():
    ready = _cycle([_edge(depth=9000.0), _edge(route_id="r2", depth=9000.0, pool="0xpool2")])
    thin = _cycle([_edge(depth=50.0), _edge(route_id="r2", depth=9000.0, pool="0xpool2")])
    live, skipped, meta = apply_economics_capacity_gate([ready, thin], 180.0)
    assert [c.cycle_id for c in live] == [ready.cycle_id]
    assert len(skipped) == 1
    assert skipped[0].status == "DEPTH_BELOW_ECONOMICS_FLOOR"
    assert skipped[0].rpc_dispatched is False
    assert ready.cycle_id in meta["verdicts"]


def test_capacity_contract_hash_mismatch_is_fail_close():
    cycle = _cycle([_edge(depth=9000.0), _edge(route_id="r2", depth=9000.0, pool="0xpool2")])
    verdict = evaluate_cycle_economic_capacity(cycle, 180.0)
    good_hash = cycle_contract_hash(verdict)
    live, skipped, meta = apply_economics_capacity_gate(
        [cycle],
        180.0,
        contract_by_cycle_id={cycle.cycle_id: "deadbeefdeadbeef"},
        require_contract_binding=True,
    )
    assert live == []
    assert skipped[0].status == "CAPACITY_CONTRACT_MISMATCH"
    assert meta["contract_mismatches"] == [cycle.cycle_id]
    live_ok, skipped_ok, _ = apply_economics_capacity_gate(
        [cycle],
        180.0,
        contract_by_cycle_id={cycle.cycle_id: good_hash},
        require_contract_binding=True,
    )
    assert live_ok == [cycle]
    assert skipped_ok == []


def test_missing_contract_is_fail_close_when_binding_required():
    cycle = _cycle([_edge(depth=9000.0), _edge(route_id="r2", depth=9000.0, pool="0xpool2")])
    live, skipped, meta = apply_economics_capacity_gate(
        [cycle],
        180.0,
        contract_by_cycle_id={},
        require_contract_binding=True,
    )
    assert live == []
    assert skipped[0].reject_reason == "CAPACITY_CONTRACT_MISSING"
    assert meta["contract_missing"] == [cycle.cycle_id]
    assert skipped[0].rpc_dispatched is False


def test_capacity_binding_required_independent_of_nonempty_contract_map():
    """Simulates runner: cap doc loaded but cycle_contract_by_id is empty."""
    cycle = _cycle([_edge(depth=9000.0), _edge(route_id="r2", depth=9000.0, pool="0xpool2")])
    cap_path_str = "data/tmp/capacity.json"
    cap_doc = {"cycle_contract_by_id": {}}
    require_binding = bool(cap_path_str and cap_doc is not None)
    assert require_binding is True
    live, skipped, _ = apply_economics_capacity_gate(
        [cycle], 180.0, contract_by_cycle_id={}, require_contract_binding=require_binding
    )
    assert live == []
    assert skipped[0].reject_reason == "CAPACITY_CONTRACT_MISSING"


def test_cycle_contract_hash_includes_non_bottleneck_leg():
    c1 = _cycle([_edge(depth=9000.0, route_id="r1"), _edge(route_id="r2", depth=9000.0, pool="0xpool2")])
    c2 = _cycle([_edge(depth=9000.0, route_id="r1"), _edge(route_id="r3", depth=8000.0, pool="0xpool3")])
    h1 = cycle_contract_hash(evaluate_cycle_economic_capacity(c1, 180.0))
    h2 = cycle_contract_hash(evaluate_cycle_economic_capacity(c2, 180.0))
    assert h1 != h2


def test_transport_qsr_ignores_pre_rpc_policy_rejects():
    c = _cycle([_edge(), _edge(route_id="r2", pool="0xpool2")])
    results = [
        _qr(c, "DEPTH_BELOW_ECONOMICS_FLOOR", rpc_dispatched=False),
        _qr(c, "CYCLE_QUOTE_FAILED", rpc_dispatched=False),
        _qr(c, "NEGATIVE_GROSS", rpc_dispatched=True),
        _qr(c, "QUOTE_FAILED", rpc_dispatched=True),
    ]
    topo = GraphTopology(
        token_count=2,
        edge_count=2,
        route_count=2,
        hub_tokens=["USDC"],
        dead_end_tokens=[],
        missing_edges_for_3cycle=[],
        adjacency_summary={},
    )
    art = build_artifact(
        chain="base",
        duration_minutes=1.0,
        cycle_results=results,
        topology=topo,
        sizes_usd=(0.25, 180.0),
        run_timestamp="2026-07-26T13:04:06Z",
        started_at_mono=0.0,
        elapsed_s=1.0,
        sweeps_completed=1,
        process_id=1,
        python_executable="python",
        venv_active=False,
        pool_quality_lane="productive",
    )
    assert art["transport_qsr"] == 0.5


def test_productive_all_pass_requires_economics():
    c = _cycle([_edge(), _edge(route_id="r2", pool="0xpool2")])
    topo = GraphTopology(
        token_count=2,
        edge_count=2,
        route_count=2,
        hub_tokens=["USDC"],
        dead_end_tokens=[],
        missing_edges_for_3cycle=[],
        adjacency_summary={},
    )
    art = build_artifact(
        chain="base",
        duration_minutes=1.0,
        cycle_results=[_qr(c, "DEPTH_BELOW_ECONOMICS_FLOOR")],
        topology=topo,
        sizes_usd=(180.0,),
        run_timestamp="2026-07-26T13:04:06Z",
        started_at_mono=0.0,
        elapsed_s=1.0,
        sweeps_completed=1,
        process_id=1,
        python_executable="python",
        venv_active=False,
        pool_quality_lane="productive",
    )
    rg = art["runtime_gates"]
    assert rg["economics_all_pass"] is False
    assert rg["all_pass"] is False


def test_session_quarantine_materialize_and_load(tmp_path):
    from datetime import datetime, timedelta, timezone

    active = (datetime.now(timezone.utc) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recs = [
        {
            "pool_address": "0xabc",
            "pair_id": "DAI_USDC",
            "fee": 0,
            "reject_reason": REASON_TOXIC_STABLE,
            "retry_after_utc": active,
            "source": "pool_scorecard",
            "samples": 8,
            "valid_rate": 0.0,
        }
    ]
    path = materialize_session_pool_quarantine(
        recs, session_id="sess-1", output_path=str(tmp_path / "q.json")
    )
    assert path is not None
    pools = load_session_pool_quarantine_addresses("sess-1", output_path=path)
    assert pools == {"0xabc"}


def test_capacity_contract_trace_marks_not_selected_blocker():
    c1 = _cycle([_edge(), _edge(route_id="r2", pool="0xpool2")])
    c2 = _cycle([_edge(pool="0xpool3"), _edge(route_id="r4", pool="0xpool4")])
    topo = GraphTopology(
        token_count=2,
        edge_count=2,
        route_count=2,
        hub_tokens=["USDC"],
        dead_end_tokens=[],
        missing_edges_for_3cycle=[],
        adjacency_summary={},
    )
    art = build_artifact(
        chain="base",
        duration_minutes=1.0,
        cycle_results=[_qr(c1, "DEPTH_BELOW_ECONOMICS_FLOOR")],
        topology=topo,
        sizes_usd=(180.0,),
        run_timestamp="2026-07-26T13:04:06Z",
        started_at_mono=0.0,
        elapsed_s=1.0,
        sweeps_completed=1,
        process_id=1,
        python_executable="python",
        venv_active=False,
        capacity_scope={
            "capacity_valid_cycle_ids": [c1.cycle_id, c2.cycle_id],
            "shadow_selected_cycle_ids": [c1.cycle_id],
        },
    )
    trace = {row["cycle_id"]: row for row in art["scan_scope"]["capacity_contract_trace"]}
    assert trace[c2.cycle_id]["block_reason"] == "NOT_SELECTED_BY_SCHEDULER"


def test_capacity_contract_trace_cache_hit_selected_no_rpc():
    c1 = _cycle([_edge(), _edge(route_id="r2", pool="0xpool2")])
    topo = GraphTopology(
        token_count=2,
        edge_count=2,
        route_count=2,
        hub_tokens=["USDC"],
        dead_end_tokens=[],
        missing_edges_for_3cycle=[],
        adjacency_summary={},
    )
    art = build_artifact(
        chain="base",
        duration_minutes=1.0,
        cycle_results=[],
        topology=topo,
        sizes_usd=(180.0,),
        run_timestamp="2026-07-26T13:04:06Z",
        started_at_mono=0.0,
        elapsed_s=1.0,
        sweeps_completed=2,
        process_id=1,
        python_executable="python",
        venv_active=False,
        capacity_scope={
            "capacity_valid_cycle_ids": [c1.cycle_id],
            "shadow_selected_cycle_ids": [c1.cycle_id],
            "deterministic_reject_cache_hit_cycle_ids": [c1.cycle_id],
        },
    )
    row = art["scan_scope"]["capacity_contract_trace"][0]
    assert row["selected"] is True
    assert row["cache_hit"] is True
    assert row["rpc_dispatched"] is False
    assert row["quoted"] is False
    assert row["block_reason"] == "DETERMINISTIC_REJECT_CACHE_HIT"
    assert art["scan_scope"]["capacity_contract_mismatches"] == []


def test_capacity_contract_trace_session_quarantine_blocker():
    c1 = _cycle([_edge(pool="0xmaverick"), _edge(route_id="r2", pool="0xpool2")])
    topo = GraphTopology(
        token_count=2,
        edge_count=2,
        route_count=2,
        hub_tokens=["USDC"],
        dead_end_tokens=[],
        missing_edges_for_3cycle=[],
        adjacency_summary={},
    )
    art = build_artifact(
        chain="base",
        duration_minutes=1.0,
        cycle_results=[],
        topology=topo,
        sizes_usd=(180.0,),
        run_timestamp="2026-07-26T13:04:06Z",
        started_at_mono=0.0,
        elapsed_s=1.0,
        sweeps_completed=1,
        process_id=1,
        python_executable="python",
        venv_active=False,
        capacity_scope={
            "capacity_valid_cycle_ids": [c1.cycle_id],
            "shadow_selected_cycle_ids": [],
            "session_quarantine_filtered_cycle_ids": [c1.cycle_id],
        },
    )
    row = art["scan_scope"]["capacity_contract_trace"][0]
    assert row["session_quarantine"] is True
    assert row["selected"] is False
    assert row["rpc_dispatched"] is False
    assert row["block_reason"] == "SESSION_POOL_QUARANTINE"
    assert art["scan_scope"]["capacity_contract_mismatches"] == []


def test_load_session_quarantine_skips_expired_entries(tmp_path):
    from datetime import datetime, timedelta, timezone

    expired = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    active = (datetime.now(timezone.utc) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = tmp_path / "q.json"
    path.write_text(
        """{
  "schema_version": "m9_pool_depth_quarantine_session.1",
  "session_id": "sess-ttl",
  "routes": [
    {"pool_address": "0xexpired", "retry_after_utc": "%s"},
    {"pool_address": "0xactive", "retry_after_utc": "%s"}
  ]
}"""
        % (expired, active),
        encoding="utf-8",
    )
    pools = load_session_pool_quarantine_addresses("sess-ttl", output_path=str(path))
    assert pools == {"0xactive"}


def test_refresh_session_quarantine_filters_next_batch(tmp_path):
    from dataclasses import dataclass

    from m9.graph_arb.pool_scorecard import refresh_session_pool_quarantine

    c = _cycle([_edge(pool="0xmaverick"), _edge(route_id="r2", pool="0xpool2")])
    cfg = ScorecardConfig(min_samples=8, min_blocks_for_toxic_stable=3)

    @dataclass
    class _Leg:
        ok: bool = False
        amount_in: int = 0
        amount_out: int = 0
        reject_reason: str = "TOXIC_STABLE_POOL"
        raw_error: str = "stable_ratio_outlier"
        elapsed_s: float = 0.0

    results = [
        CycleQuoteResult(
            cycle=c,
            size_usd=0.25,
            amount_in=0,
            amount_out=0,
            gross_bps=0.0,
            status="CYCLE_QUOTE_FAILED",
            reject_reason="TOXIC_STABLE_POOL",
            leg_results=[_Leg()],
            elapsed_s=0.0,
        )
        for _ in range(24)
    ]
    qpath = str(tmp_path / "q.json")
    pools = refresh_session_pool_quarantine(
        results,
        session_id="sess-toxic",
        config=cfg,
        output_path=qpath,
    )
    assert "0xmaverick" in pools
    batch = [c]
    filtered = [
        cycle
        for cycle in batch
        if not any(
            str(getattr(edge, "pool_address", "") or "").lower() in pools
            for edge in cycle.edges
        )
    ]
    assert filtered == []
