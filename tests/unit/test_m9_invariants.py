"""Invariant tests for M9 artifact schema (Step 5 — GPT fix).

Tests that `runtime_gates`, `infra_telemetry`, and critical top-level keys
are always present in the artifact regardless of how `build_artifact` is called
(varying duration, max_cycles, chunk_size, multicall_stats, etc.).
"""
from __future__ import annotations

import pytest

from m9.graph_arb.artifacts import build_artifact
from m9.graph_arb.models import GraphTopology


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_topology() -> GraphTopology:
    return GraphTopology(
        token_count=3,
        edge_count=6,
        route_count=2,
        hub_tokens=["USDC"],
        dead_end_tokens=[],
        missing_edges_for_3cycle=[],
        adjacency_summary={},
    )


def _base_kwargs(**overrides) -> dict:
    base = dict(
        chain="base",
        duration_minutes=1.0,
        cycle_results=[],
        topology=_make_topology(),
        sizes_usd=(1000.0,),
        run_timestamp="2025-01-01T00:00:00Z",
        started_at_mono=0.0,
        elapsed_s=60.0,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# runtime_gates block invariants
# ---------------------------------------------------------------------------

class TestRuntimeGatesInvariant:
    """runtime_gates must always be present with all 4 gate keys + all_pass."""

    _REQUIRED_GATE_KEYS = {
        "multicall_success_rate",
        "data_completeness",
        "unverified_active_routes",
        "qsr",
        "quote_revert_rate",
    }

    def test_runtime_gates_always_present(self):
        """runtime_gates is in artifact even with no optional params."""
        art = build_artifact(**_base_kwargs())
        assert "runtime_gates" in art, "runtime_gates block missing from artifact"

    def test_runtime_gates_has_all_keys(self):
        """All 4 gate keys + all_pass are present."""
        art = build_artifact(**_base_kwargs())
        rg = art["runtime_gates"]
        for key in self._REQUIRED_GATE_KEYS:
            assert key in rg, f"runtime_gates missing key: {key}"
        assert "all_pass" in rg

    def test_all_pass_is_bool(self):
        """all_pass field is a boolean, not None or missing."""
        art = build_artifact(**_base_kwargs())
        assert isinstance(art["runtime_gates"]["all_pass"], bool)

    def test_each_gate_has_value_threshold_pass(self):
        """Each gate sub-dict has value, threshold, pass fields."""
        art = build_artifact(**_base_kwargs())
        rg = art["runtime_gates"]
        for key in self._REQUIRED_GATE_KEYS:
            g = rg[key]
            assert "value" in g, f"{key}: missing 'value'"
            assert "threshold" in g, f"{key}: missing 'threshold'"
            assert "pass" in g and isinstance(g["pass"], bool), f"{key}: 'pass' must be bool"

    def test_all_pass_logic_consistent(self):
        """all_pass == all individual pass values."""
        art = build_artifact(**_base_kwargs())
        rg = art["runtime_gates"]
        expected = all(v["pass"] for k, v in rg.items() if isinstance(v, dict) and "pass" in v)
        assert rg["all_pass"] == expected

    def test_runtime_gates_with_multicall_stats_high_success(self):
        """When multicall_stats shows 100% success rate, gate passes."""
        mc = {"attempted": 10, "success": 10, "http_429": 0, "retry_count": 0,
              "fetched_total": 100, "requested_total": 100, "subchunk_splits": 0}
        art = build_artifact(**_base_kwargs(multicall_stats=mc))
        rg = art["runtime_gates"]
        assert rg["multicall_success_rate"]["pass"] is True
        assert rg["multicall_success_rate"]["value"] == 1.0
        # Step 7: data_completeness gate should pass at 100% completeness
        assert rg["data_completeness"]["pass"] is True
        assert rg["data_completeness"]["value"] == 1.0

    def test_runtime_gates_with_multicall_stats_low_success(self):
        """When multicall_stats shows 70% success rate, gate fails."""
        mc = {"attempted": 10, "success": 7, "http_429": 5, "retry_count": 3,
              "fetched_total": 70, "requested_total": 100, "subchunk_splits": 2}
        art = build_artifact(**_base_kwargs(multicall_stats=mc))
        rg = art["runtime_gates"]
        assert rg["multicall_success_rate"]["pass"] is False

    def test_runtime_gates_no_multicall_stats(self):
        """When multicall_stats=None, multicall_success_rate and data_completeness gates have value=None and pass=False."""
        art = build_artifact(**_base_kwargs())
        rg = art["runtime_gates"]
        assert rg["multicall_success_rate"]["value"] is None
        assert rg["multicall_success_rate"]["pass"] is False
        # Step 7: data_completeness also None / fail without multicall_stats
        assert rg["data_completeness"]["value"] is None
        assert rg["data_completeness"]["pass"] is False

    def test_runtime_gates_unverified_zero_passes(self):
        """When unverified_active_routes=0, gate passes."""
        art = build_artifact(**_base_kwargs(unverified_active_routes=0))
        assert art["runtime_gates"]["unverified_active_routes"]["pass"] is True

    def test_runtime_gates_unverified_nonzero_fails(self):
        """When unverified_active_routes=51, gate fails."""
        art = build_artifact(**_base_kwargs(unverified_active_routes=51))
        assert art["runtime_gates"]["unverified_active_routes"]["pass"] is False


# ---------------------------------------------------------------------------
# infra_telemetry invariants
# ---------------------------------------------------------------------------

class TestInfraTelemetryInvariant:

    def test_infra_telemetry_always_present(self):
        """infra_telemetry must always be in artifact."""
        for duration in (1.0, 5.0, 30.0, 60.0):
            art = build_artifact(**_base_kwargs(duration_minutes=duration))
            assert "infra_telemetry" in art, f"infra_telemetry missing for duration={duration}"

    def test_verified_inventory_exists_defaults_false(self):
        """verified_inventory_exists defaults to False in infra_telemetry."""
        art = build_artifact(**_base_kwargs())
        assert art["infra_telemetry"]["verified_inventory_exists"] is False

    def test_verified_inventory_exists_true_when_passed(self):
        """verified_inventory_exists=True propagates into infra_telemetry."""
        art = build_artifact(**_base_kwargs(verified_inventory_exists=True))
        assert art["infra_telemetry"]["verified_inventory_exists"] is True

    def test_multicall_subchunk_splits_in_infra_when_nonzero(self):
        """multicall_subchunk_splits appears in infra_telemetry when > 0."""
        mc = {"attempted": 5, "success": 3, "http_429": 2, "retry_count": 2,
              "fetched_total": 30, "requested_total": 50, "subchunk_splits": 3}
        art = build_artifact(**_base_kwargs(multicall_stats=mc))
        assert art["infra_telemetry"].get("multicall_subchunk_splits") == 3

    def test_multicall_subchunk_splits_absent_when_zero(self):
        """multicall_subchunk_splits is omitted from infra_telemetry when 0."""
        mc = {"attempted": 5, "success": 5, "http_429": 0, "retry_count": 0,
              "fetched_total": 50, "requested_total": 50, "subchunk_splits": 0}
        art = build_artifact(**_base_kwargs(multicall_stats=mc))
        assert "multicall_subchunk_splits" not in art["infra_telemetry"]

    # ------------------------------------------------------------------
    # sizes_usd_source tracking (Fix 7)
    # ------------------------------------------------------------------

    def test_sizes_usd_source_default_is_cli_default(self):
        """sizes_usd_source defaults to 'cli_default' when not passed."""
        art = build_artifact(**_base_kwargs())
        assert art["infra_telemetry"].get("sizes_usd_source") == "cli_default"

    def test_sizes_usd_source_config_scan_params(self):
        """sizes_usd_source='config.scan_params' propagates into infra_telemetry."""
        art = build_artifact(**_base_kwargs(sizes_usd_source="config.scan_params"))
        assert art["infra_telemetry"]["sizes_usd_source"] == "config.scan_params"

    def test_sizes_usd_source_cli_override(self):
        """sizes_usd_source='cli_override' propagates into infra_telemetry."""
        art = build_artifact(**_base_kwargs(sizes_usd_source="cli_override"))
        assert art["infra_telemetry"]["sizes_usd_source"] == "cli_override"

    # ------------------------------------------------------------------
    # Normalized 429 counters (Fix 4)
    # ------------------------------------------------------------------

    def test_normalized_429_counters_zero_by_default(self):
        """raw_http_429_count, multicall_429_count, quote_429_count default to 0."""
        art = build_artifact(**_base_kwargs())
        it = art["infra_telemetry"]
        assert it.get("raw_http_429_count") == 0
        assert it.get("multicall_429_count") == 0
        assert it.get("quote_429_count") == 0

    def test_multicall_429_count_from_multicall_stats(self):
        """multicall_429_count reads http_429 from multicall_stats dict."""
        mc = {"attempted": 10, "success": 8, "http_429": 5, "retry_count": 2,
              "fetched_total": 80, "requested_total": 100, "subchunk_splits": 0}
        art = build_artifact(**_base_kwargs(multicall_stats=mc))
        assert art["infra_telemetry"]["multicall_429_count"] == 5

    # ------------------------------------------------------------------
    # provider_router_snapshot passthrough (Fix 3)
    # ------------------------------------------------------------------

    def test_provider_router_snapshot_absent_by_default(self):
        """provider_router_snapshot is absent when not passed."""
        art = build_artifact(**_base_kwargs())
        assert "provider_router_snapshot" not in art["infra_telemetry"]

    def test_provider_router_snapshot_propagated_when_passed(self):
        """provider_router_snapshot passthrough into infra_telemetry."""
        snap = {
            "primary": "https://lb.drpc.live/...",
            "secondary": "",
            "is_failed_over": False,
            "providers": {}
        }
        art = build_artifact(**_base_kwargs(provider_router_snapshot=snap))
        assert art["infra_telemetry"]["provider_router_snapshot"] == snap


# ---------------------------------------------------------------------------
# Schema stability: top-level keys don't disappear across parameter variations
# ---------------------------------------------------------------------------

class TestSchemaStabilityInvariant:
    """Top-level artifact keys must be present regardless of call variation."""

    _REQUIRED_TOPLEVEL = {
        "schema_family", "schema_revision", "generated_at_utc", "run_timestamp",
        "sweeps_completed", "elapsed_s", "duration_fulfilled",
        "cycles_found", "cycles_positive_gross", "qsr",
        "infra_telemetry", "runtime_gates", "run_context",
    }

    def test_required_keys_with_no_optional_params(self):
        """All required keys present when only mandatory params supplied."""
        art = build_artifact(**_base_kwargs())
        missing = self._REQUIRED_TOPLEVEL - set(art.keys())
        assert not missing, f"Missing top-level keys: {missing}"

    def test_schema_stable_across_durations(self):
        """Same top-level keys for duration=5 and duration=60."""
        art5 = build_artifact(**_base_kwargs(duration_minutes=5.0))
        art60 = build_artifact(**_base_kwargs(duration_minutes=60.0))
        keys5 = set(art5.keys())
        keys60 = set(art60.keys())
        assert keys5 == keys60, f"Key diff: only in 5m={keys5 - keys60}, only in 60m={keys60 - keys5}"

    def test_schema_stable_with_without_multicall(self):
        """Same runtime_gates keys whether multicall_stats is provided or not."""
        mc = {"attempted": 10, "success": 9, "http_429": 1, "retry_count": 1,
              "fetched_total": 90, "requested_total": 100, "subchunk_splits": 0}
        art_with = build_artifact(**_base_kwargs(multicall_stats=mc))
        art_without = build_artifact(**_base_kwargs())
        assert set(art_with["runtime_gates"].keys()) == set(art_without["runtime_gates"].keys())


# ---------------------------------------------------------------------------
# factory_verified propagation invariants (Step 3+4)
# ---------------------------------------------------------------------------

from m9.graph_arb.models import CycleQuoteResult, GraphCycle, GraphEdge

_ADDR_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_ADDR_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
_ADDR_C = "0xcccccccccccccccccccccccccccccccccccccccc"
_POOL1  = "0x1111111111111111111111111111111111111111"
_POOL2  = "0x2222222222222222222222222222222222222222"
_POOL3  = "0x3333333333333333333333333333333333333333"
_QUOTER = "0x0000000000000000000000000000000000000001"


def _make_edge(sym_in: str, addr_in: str, sym_out: str, addr_out: str, pool: str,
               factory_verified: bool = False) -> GraphEdge:
    return GraphEdge(
        token_in_sym=sym_in, token_out_sym=sym_out,
        token_in_addr=addr_in, token_out_addr=addr_out,
        token_in_decimals=18, token_out_decimals=18,
        route_id=f"{sym_in}_{sym_out}",
        dex_id="uniswap_v3", adapter_type="uniswap_v3",
        fee=500, tick_spacing=10,
        quoter_addr=_QUOTER, pool_address=pool,
        fee_bps=5.0, factory_class="UNKNOWN",
        pair_id=f"{sym_in}_{sym_out}",
        factory_verified=factory_verified,
    )


def _make_cycle(factory_verified: bool = False) -> GraphCycle:
    return GraphCycle(edges=(
        _make_edge("A", _ADDR_A, "B", _ADDR_B, _POOL1, factory_verified=factory_verified),
        _make_edge("B", _ADDR_B, "C", _ADDR_C, _POOL2, factory_verified=factory_verified),
        _make_edge("C", _ADDR_C, "A", _ADDR_A, _POOL3, factory_verified=factory_verified),
    ))


def _make_qr(cycle: GraphCycle, gross_bps: float = -100.0) -> CycleQuoteResult:
    return CycleQuoteResult(
        cycle=cycle, size_usd=1000.0, amount_in=1_000_000, amount_out=990_000,
        gross_bps=gross_bps, status="NEGATIVE_GROSS", reject_reason=None,
        leg_results=[], elapsed_s=0.05,
    )


class TestFactoryVerifiedInvariant:
    """Step 3+4: factory_verified propagation and invariant checks."""

    def test_factory_verified_true_in_top_opp_when_all_edges_verified(self):
        """When all edges have factory_verified=True, top_opportunities show factory_verified=True."""
        cycle = _make_cycle(factory_verified=True)
        qr = _make_qr(cycle)
        art = build_artifact(**_base_kwargs(cycle_results=[qr], unverified_active_routes=0))
        opps = art.get("top_opportunities", [])
        assert opps, "Expected at least one top_opportunity"
        assert opps[0]["factory_verified"] is True

    def test_factory_verified_false_in_top_opp_when_edges_unverified(self):
        """When edges have factory_verified=False (default), factory_verified=False in opportunity."""
        cycle = _make_cycle(factory_verified=False)
        qr = _make_qr(cycle)
        art = build_artifact(**_base_kwargs(cycle_results=[qr]))
        opps = art.get("top_opportunities", [])
        assert opps
        assert opps[0]["factory_verified"] is False

    def test_unverified_zero_with_verified_edges_consistent(self):
        """Invariant: unverified_active_routes=0 AND edges factory_verified=True → opp factory_verified=True."""
        cycle = _make_cycle(factory_verified=True)
        qr = _make_qr(cycle)
        art = build_artifact(**_base_kwargs(cycle_results=[qr], unverified_active_routes=0))
        rg = art["runtime_gates"]
        assert rg["unverified_active_routes"]["pass"] is True
        opps = art.get("top_opportunities", [])
        assert all(opp["factory_verified"] is True for opp in opps), \
            "If unverified_active_routes=0 and edges verified, all top_opps must have factory_verified=True"

    def test_factory_class_unknown_does_not_block_factory_verified(self):
        """factory_class='UNKNOWN' is independent from factory_verified=True (separate fields)."""
        # All 119 routes in real inventory have factory_class=UNKNOWN but factory_verified=True
        cycle = _make_cycle(factory_verified=True)  # factory_class is "UNKNOWN" in _make_edge
        qr = _make_qr(cycle)
        art = build_artifact(**_base_kwargs(cycle_results=[qr], unverified_active_routes=0))
        opp = art["top_opportunities"][0]
        # factory_verified=True even though factory_class="UNKNOWN"
        assert opp["factory_verified"] is True
        assert opp["factory"] == "UNKNOWN"  # factory (class) stays "UNKNOWN"


# ---------------------------------------------------------------------------
# Economics metrics invariants (Steps 5+6)
# ---------------------------------------------------------------------------

class TestEconomicsMetricsInvariant:
    """loss_reason_histogram + TOXIC_ROUTE_PRICE_IMPACT gate (Steps 5+6)."""

    def test_loss_reason_histogram_always_present(self):
        """loss_reason_histogram is always present in economics_metrics."""
        art = build_artifact(**_base_kwargs())
        assert "loss_reason_histogram" in art["economics_metrics"]

    def test_toxic_route_count_always_present(self):
        """toxic_route_count is always present in economics_metrics."""
        art = build_artifact(**_base_kwargs())
        assert "toxic_route_count" in art["economics_metrics"]
        assert art["economics_metrics"]["toxic_route_count"] == 0

    def test_toxic_route_classified_when_pre_fee_gross_below_500(self):
        """Cycles with pre_fee_gross_bps < -500 get TOXIC_ROUTE_PRICE_IMPACT in histogram."""
        # fee_drag for cycle = 3 × 5.0 = 15 bps; gross_bps = -9000 → pre_fee = -8985 < -500
        cycle = _make_cycle(factory_verified=True)
        qr = _make_qr(cycle, gross_bps=-9000.0)
        art = build_artifact(**_base_kwargs(cycle_results=[qr]))
        hist = art["economics_metrics"]["loss_reason_histogram"]
        assert hist.get("TOXIC_ROUTE_PRICE_IMPACT", 0) == 1
        assert art["economics_metrics"]["toxic_route_count"] == 1

    def test_unfavorable_prices_when_pre_fee_gross_between_500_and_0(self):
        """Cycles with -500 < pre_fee_gross_bps < 0 get UNFAVORABLE_PRICES."""
        # fee = 15 bps; gross_bps = -100 → pre_fee = -85 (between -500 and 0)
        cycle = _make_cycle(factory_verified=True)
        qr = _make_qr(cycle, gross_bps=-100.0)
        art = build_artifact(**_base_kwargs(cycle_results=[qr]))
        hist = art["economics_metrics"]["loss_reason_histogram"]
        assert hist.get("UNFAVORABLE_PRICES", 0) == 1
        assert art["economics_metrics"]["toxic_route_count"] == 0

    def test_fee_drag_when_gross_negative_but_pre_fee_positive(self):
        """Cycles with pre_fee_gross_bps > 0 but spread_bps < 0 get FEE_DRAG."""
        # fee = 15 bps; gross_bps = -5 → pre_fee = 10 > 0 → FEE_DRAG
        cycle = _make_cycle(factory_verified=True)
        qr = _make_qr(cycle, gross_bps=-5.0)
        art = build_artifact(**_base_kwargs(cycle_results=[qr]))
        hist = art["economics_metrics"]["loss_reason_histogram"]
        assert hist.get("FEE_DRAG", 0) == 1

    def test_top_opportunity_loss_reason_toxic_for_catastrophic_spread(self):
        """top_opportunities[0].loss_reason == TOXIC_ROUTE_PRICE_IMPACT for -9000 bps."""
        cycle = _make_cycle(factory_verified=True)
        qr = _make_qr(cycle, gross_bps=-9000.0)
        art = build_artifact(**_base_kwargs(cycle_results=[qr]))
        opp = art["top_opportunities"][0]
        assert opp["loss_reason"] == "TOXIC_ROUTE_PRICE_IMPACT"

    def test_per_leg_rca_present_in_top_opportunity(self):
        """top_opportunities entries have a 'legs' list with per-leg RCA data."""
        cycle = _make_cycle(factory_verified=True)
        qr = _make_qr(cycle, gross_bps=-100.0)
        art = build_artifact(**_base_kwargs(cycle_results=[qr]))
        opp = art["top_opportunities"][0]
        assert "legs" in opp, "top_opportunity missing 'legs' per-leg RCA field"
        assert len(opp["legs"]) == 3  # 3-hop cycle
        leg0 = opp["legs"][0]
        assert leg0["leg_idx"] == 0
        assert leg0["token_in"] == "A"
        assert leg0["token_out"] == "B"
        assert leg0["fee_bps"] == 5.0
        assert leg0["factory_verified"] is True
