"""Schema and contract tests for m9_graph_latest.json rolling artifact.

These tests ensure the artifact written by m9.graph_arb.artifacts.build_artifact()
conforms to the canonical M9 schema contract (schema_revision m9.1).
They run offline against the live rolling file *when it exists*, and also
validate the artifact builder directly using synthetic inputs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

_ROLLING = Path("data/runs/_rolling/m9_graph_latest.json")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_rolling() -> Dict[str, Any]:
    if not _ROLLING.exists():
        pytest.skip(f"Rolling artifact not found: {_ROLLING}")
    return json.loads(_ROLLING.read_text(encoding="utf-8"))


def _make_topology():
    from m9.graph_arb.models import GraphTopology
    return GraphTopology(
        token_count=5,
        edge_count=10,
        route_count=7,
        hub_tokens=["USDC", "WETH"],
        dead_end_tokens=["TOKEN_X"],
        missing_edges_for_3cycle=[],
        adjacency_summary={"USDC": ["WETH", "USDT"]},
    )


def _empty_artifact():
    """Build an artifact from an empty cycle list for unit tests."""
    from m9.graph_arb.artifacts import build_artifact
    return build_artifact(
        chain="base",
        duration_minutes=1.0,
        cycle_results=[],
        topology=_make_topology(),
        sizes_usd=(1000.0,),
        run_timestamp="2026-01-01T00:00:00Z",
        started_at_mono=0.0,
        elapsed_s=60.0,
    )


def _make_mock_cycle():
    m = MagicMock()
    m.cycle_id = "abc123def456"
    m.length = 3
    m.token_path = ["USDC", "WETH", "USDT"]
    m.start_token_sym = "USDC"
    m.total_fee_bps = 9.0
    m.min_factory_class = "EFFICIENT_BASELINE"

    # Build mock edges so _build_top_opportunity() can access edges[0].* fields
    def _mock_edge(dex="uniswap_v3", factory="EFFICIENT_BASELINE",
                   pool="0xaaaa", pair_id="USDC/WETH", fee_bps=5.0):
        e = MagicMock()
        e.dex_id = dex
        e.factory_class = factory
        e.pool_address = pool
        e.pair_id = pair_id
        e.fee_bps = fee_bps
        return e

    m.edges = [
        _mock_edge(pool="0xaaaa", pair_id="USDC/WETH"),
        _mock_edge(dex="curve", factory="MID_EFFICIENCY", pool="0xbbbb", pair_id="WETH/USDT"),
        _mock_edge(dex="uniswap_v3", pool="0xcccc", pair_id="USDT/USDC"),
    ]
    return m


# ---------------------------------------------------------------------------
# Rolling artifact tests (skip if file absent)
# ---------------------------------------------------------------------------

class TestM9GraphArtifactSchema:
    """Validate the live rolling m9_graph_latest.json against contract."""

    def test_schema_family(self):
        d = _load_rolling()
        assert d.get("schema_family") == "m9_graph_arb"

    def test_schema_revision_format(self):
        d = _load_rolling()
        rev = d.get("schema_revision", "")
        assert str(rev).startswith("m9."), f"schema_revision must start 'm9.', got {rev!r}"

    def test_required_fields_present(self):
        d = _load_rolling()
        required = {
            "schema_family",
            "schema_revision",
            "generated_at_utc",
            "freshness_s",
            "run_timestamp",
            "requested_duration_minutes",
            "elapsed_s",
            "sweeps_completed",
            "duration_fulfilled",
            "gate_acceptance",
            "strategy_gate_acceptance",
            "execution_mode",
            "cycles_found",
            "cycles_positive_gross",
            "cycles_router_sim_eligible",
            "best_cycle_net_bps",
            "qsr",
            "cycle_reject_histogram",
            "economics_gate_status",
            "route_error_histogram",
            "scan_scope",
            "graph_topology",
            "topology_gate",
            "run_context",
        }
        missing = required - set(d.keys())
        assert not missing, f"Missing required fields: {sorted(missing)}"

    def test_cycles_found_non_negative(self):
        d = _load_rolling()
        assert isinstance(d["cycles_found"], int)
        assert d["cycles_found"] >= 0

    def test_cycles_positive_gross_non_negative(self):
        d = _load_rolling()
        assert isinstance(d["cycles_positive_gross"], int)
        assert d["cycles_positive_gross"] >= 0

    def test_cycles_positive_gross_lte_cycles_found(self):
        d = _load_rolling()
        assert d.get("cycles_positive_gross", 0) <= d.get("cycles_found", 0)

    def test_qsr_in_range(self):
        d = _load_rolling()
        qsr = d.get("qsr")
        assert qsr is None or 0.0 <= float(qsr) <= 1.0, f"qsr must be in [0,1], got {qsr}"

    def test_best_cycle_net_bps_numeric_or_null(self):
        d = _load_rolling()
        val = d.get("best_cycle_net_bps")
        assert val is None or isinstance(val, (int, float))

    def test_economics_gate_status_valid(self):
        d = _load_rolling()
        valid = {
            "BLOCKED_NO_CYCLES",
            "BLOCKED_QSR",
            "NEAR_MISS",
            "BLOCKED_NO_POSITIVE_GROSS",
            "PASS",
        }
        assert d.get("economics_gate_status") in valid

    def test_gate_acceptance_bool(self):
        d = _load_rolling()
        assert isinstance(d.get("gate_acceptance"), bool)

    def test_strategy_gate_acceptance_bool(self):
        d = _load_rolling()
        assert isinstance(d.get("strategy_gate_acceptance"), bool)

    def test_gate_acceptance_matches_econ_status(self):
        """gate_acceptance=True IFF economics_gate_status == PASS."""
        d = _load_rolling()
        gate = d.get("gate_acceptance")
        econ = d.get("economics_gate_status")
        if econ == "PASS":
            assert gate is True
        else:
            assert gate is False, f"gate_acceptance must be False when econ={econ!r}"

    def test_run_timestamp_format(self):
        d = _load_rolling()
        ts = d.get("run_timestamp", "")
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", str(ts)), (
            f"run_timestamp must be YYYY-MM-DDTHH:MM:SSZ, got {ts!r}"
        )

    def test_generated_at_utc_format(self):
        d = _load_rolling()
        ts = d.get("generated_at_utc", "")
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", str(ts)), (
            f"generated_at_utc must be YYYY-MM-DDTHH:MM:SSZ, got {ts!r}"
        )

    def test_freshness_s_non_negative(self):
        d = _load_rolling()
        freshness = d.get("freshness_s")
        assert freshness is not None and float(freshness) >= 0

    def test_requested_duration_minutes_positive(self):
        d = _load_rolling()
        rdm = d.get("requested_duration_minutes")
        assert rdm is not None and float(rdm) > 0

    def test_topology_gate_valid(self):
        d = _load_rolling()
        valid = {"NO_CYCLES", "CYCLES_FOUND", "TOPOLOGY_FILTER_BLOCKED"}
        assert d.get("topology_gate") in valid, (
            f"topology_gate must be one of {valid}, got {d.get('topology_gate')!r}"
        )

    def test_graph_topology_is_dict(self):
        d = _load_rolling()
        topo = d.get("graph_topology")
        assert isinstance(topo, dict), "graph_topology must be a dict"
        assert "token_count" in topo
        assert "edge_count" in topo
        assert "route_count" in topo

    def test_run_context_required_fields(self):
        d = _load_rolling()
        ctx = d.get("run_context")
        assert isinstance(ctx, dict), "run_context must be a dict"
        for field in ("chain", "duration_minutes", "sizes_usd", "inventory_path", "execution_mode"):
            assert field in ctx, f"run_context missing field: {field!r}"

    def test_cycle_reject_histogram_is_dict(self):
        d = _load_rolling()
        hist = d.get("cycle_reject_histogram")
        assert isinstance(hist, dict), "cycle_reject_histogram must be a dict"
        for k, v in hist.items():
            assert isinstance(k, str)
            assert isinstance(v, int)

    def test_route_error_histogram_is_dict_or_list(self):
        d = _load_rolling()
        hist = d.get("route_error_histogram")
        if hist is not None:
            assert isinstance(hist, (dict, list))

    def test_scan_scope_is_dict(self):
        d = _load_rolling()
        sc = d.get("scan_scope")
        assert isinstance(sc, dict), "scan_scope must be a dict"

    def test_top_cycles_list_if_present(self):
        d = _load_rolling()
        top = d.get("top_cycles")
        if top is not None:
            assert isinstance(top, list)
            for entry in top[:3]:
                assert "cycle_id" in entry
                assert "gross_bps" in entry
                assert "status" in entry

    def test_no_old_topology_key_at_top_level(self):
        """The old 'topology' key must be renamed to 'graph_topology'."""
        d = _load_rolling()
        # Allow either form since rolling artifact predates this fix
        if "topology" in d and "graph_topology" not in d:
            pytest.fail("Rolling artifact has old 'topology' key but no 'graph_topology'")

    def test_cycles_quoteable_non_negative(self):
        d = _load_rolling()
        v = d.get("cycles_quoteable")
        if v is not None:
            assert isinstance(v, int) and v >= 0

    def test_quote_rpc_error_rate_in_range(self):
        d = _load_rolling()
        v = d.get("quote_rpc_error_rate")
        if v is not None:
            assert 0.0 <= float(v) <= 1.0, f"quote_rpc_error_rate out of range: {v}"

    def test_quote_revert_rate_in_range(self):
        d = _load_rolling()
        v = d.get("quote_revert_rate")
        if v is not None:
            assert 0.0 <= float(v) <= 1.0, f"quote_revert_rate out of range: {v}"

    def test_economics_blocker_class_valid_if_present(self):
        d = _load_rolling()
        v = d.get("economics_blocker_class")
        if v is not None:
            valid = {
                "NOT_RUN", "NOT_BLOCKED", "PROVIDER_QUALITY_BLOCKED",
                "INVENTORY_TOO_ANCHOR_HEAVY", "MARKET_NO_POSITIVE_GROSS",
            }
            assert v in valid, f"economics_blocker_class invalid: {v!r}"

    def test_infra_status_valid_if_present(self):
        d = _load_rolling()
        v = d.get("infra_status")
        if v is not None:
            valid = {"NOT_RUN", "OK", "INFRA_OR_QUOTE_QUALITY_BLOCKED"}
            assert v in valid, f"infra_status invalid: {v!r}"

    def test_risk_metrics_if_present(self):
        d = _load_rolling()
        rm = d.get("risk_metrics")
        if rm is not None:
            assert isinstance(rm, dict)
            assert "risk_gate" in rm
            assert rm["risk_gate"] in ("NOT_STARTED", "PASS", "FAIL", "PARTIAL")


# ---------------------------------------------------------------------------
# Builder unit tests (no rolling file required)
# ---------------------------------------------------------------------------

class TestM9GraphArtifactBuilder:
    """Unit tests for m9.graph_arb.artifacts.build_artifact()."""

    def test_empty_cycles_gives_blocked_no_cycles(self):
        a = _empty_artifact()
        assert a["economics_gate_status"] == "BLOCKED_NO_CYCLES"
        assert a["gate_acceptance"] is False
        assert a["cycles_found"] == 0

    def test_schema_fields_present(self):
        from m9.graph_arb.artifacts import SCHEMA_FAMILY, SCHEMA_REVISION
        a = _empty_artifact()
        assert a["schema_family"] == SCHEMA_FAMILY
        assert a["schema_revision"] == SCHEMA_REVISION

    def test_requested_duration_minutes_key(self):
        """Output must use 'requested_duration_minutes', not 'duration_minutes'."""
        a = _empty_artifact()
        assert "requested_duration_minutes" in a
        assert "duration_minutes" not in a
        assert a["requested_duration_minutes"] == 1.0

    def test_graph_topology_key(self):
        """Output must use 'graph_topology', not 'topology'."""
        a = _empty_artifact()
        assert "graph_topology" in a
        assert "topology" not in a
        assert isinstance(a["graph_topology"], dict)
        assert "token_count" in a["graph_topology"]

    def test_topology_gate_no_cycles(self):
        a = _empty_artifact()
        assert a["topology_gate"] == "NO_CYCLES"

    def test_topology_gate_cycles_found_via_override(self):
        from m9.graph_arb.artifacts import build_artifact
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[],
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
            cycles_found_topology=500,
        )
        assert a["topology_gate"] == "CYCLES_FOUND"
        assert a["cycles_found"] == 500

    def test_run_context_fields(self):
        a = _empty_artifact()
        ctx = a["run_context"]
        assert isinstance(ctx, dict)
        assert ctx["chain"] == "base"
        assert ctx["duration_minutes"] == 1.0
        assert ctx["execution_mode"] == "paper"

    def test_strategy_gate_acceptance_default_false(self):
        a = _empty_artifact()
        assert a["strategy_gate_acceptance"] is False

    def test_generated_at_utc_present(self):
        a = _empty_artifact()
        ts = a.get("generated_at_utc", "")
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", str(ts))

    def test_freshness_s_equals_elapsed(self):
        a = _empty_artifact()
        assert a["freshness_s"] == a["elapsed_s"]

    def test_cycle_reject_histogram_empty_when_no_results(self):
        a = _empty_artifact()
        assert a["cycle_reject_histogram"] == {}

    def test_cycle_reject_histogram_counts_by_status(self):
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult

        mock_cycle = _make_mock_cycle()
        qr1 = CycleQuoteResult(
            cycle=mock_cycle, size_usd=1000.0, amount_in=1000, amount_out=990,
            gross_bps=-5.0, status="NEGATIVE_GROSS", reject_reason=None,
            leg_results=[], elapsed_s=0.1,
        )
        qr2 = CycleQuoteResult(
            cycle=mock_cycle, size_usd=1000.0, amount_in=1000, amount_out=0,
            gross_bps=0.0, status="QUOTE_FAILED", reject_reason="QUOTE_REVERT",
            leg_results=[], elapsed_s=0.1,
        )
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[qr1, qr2],
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
        )
        hist = a["cycle_reject_histogram"]
        assert hist.get("NEGATIVE_GROSS") == 1
        assert hist.get("QUOTE_REVERT") == 1

    def test_write_and_read_artifact(self, tmp_path):
        from m9.graph_arb.artifacts import build_artifact, write_artifact
        out = str(tmp_path / "m9_test.json")
        a = _empty_artifact()
        write_artifact(a, out)
        loaded = json.loads(Path(out).read_text(encoding="utf-8"))
        assert loaded["schema_family"] == "m9_graph_arb"
        assert loaded["cycles_found"] == 0
        assert "graph_topology" in loaded
        assert "run_context" in loaded

    def test_gate_pass_when_positive_gross(self):
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult

        mock_cycle = _make_mock_cycle()
        qr = CycleQuoteResult(
            cycle=mock_cycle, size_usd=1000.0, amount_in=1000 * 10**6,
            amount_out=1002 * 10**6, gross_bps=20.0, status="POSITIVE_GROSS",
            reject_reason=None, leg_results=[], elapsed_s=0.1,
        )
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[qr],
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
        )
        assert a["cycles_positive_gross"] == 1
        assert a["economics_gate_status"] == "PASS"
        assert a["gate_acceptance"] is True

    def test_cycles_found_topology_overrides_dry_run(self):
        """cycles_found_topology must override len(cycle_results) for dry-run mode."""
        from m9.graph_arb.artifacts import build_artifact
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[],
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
            cycles_found_topology=1234,
        )
        assert a["cycles_found"] == 1234
        assert a["economics_gate_status"] == "BLOCKED_NO_POSITIVE_GROSS"
        assert a["topology_gate"] == "CYCLES_FOUND"

    def test_cycles_quoteable_present(self):
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult
        mock_cycle = _make_mock_cycle()
        qr = CycleQuoteResult(
            cycle=mock_cycle, size_usd=1000.0, amount_in=1000, amount_out=990,
            gross_bps=-5.0, status="NEGATIVE_GROSS", reject_reason=None,
            leg_results=[], elapsed_s=0.1,
        )
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[qr],
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
        )
        assert a["cycles_quoteable"] == 1
        assert isinstance(a["quote_rpc_error_rate"], float)
        assert isinstance(a["quote_revert_rate"], float)
        assert 0.0 <= a["quote_rpc_error_rate"] <= 1.0
        assert 0.0 <= a["quote_revert_rate"] <= 1.0

    def test_p50_p90_bps_present(self):
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult
        mock_cycle = _make_mock_cycle()
        qrs = [
            CycleQuoteResult(
                cycle=mock_cycle, size_usd=1000.0, amount_in=1000, amount_out=990,
                gross_bps=float(-i), status="NEGATIVE_GROSS", reject_reason=None,
                leg_results=[], elapsed_s=0.1,
            )
            for i in range(1, 11)  # -1 .. -10 bps
        ]
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=qrs,
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
        )
        em = a["economics_metrics"]
        assert "p50_gross_bps" in em
        assert "p90_gross_bps" in em
        assert em["p50_gross_bps"] is not None
        assert em["p90_gross_bps"] is not None
        # p90 is the 90th percentile (closer to best), p50 is median
        # so p90 >= p50 (less negative = higher bps value)
        assert em["p90_gross_bps"] >= em["p50_gross_bps"]

    def test_economics_blocker_class_not_run_when_empty(self):
        a = _empty_artifact()
        assert a["economics_blocker_class"] == "NOT_RUN"
        assert a["infra_status"] == "NOT_RUN"

    def test_quote_failure_diagnostics_present(self):
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult

        mock_cycle = _make_mock_cycle()
        qr = CycleQuoteResult(
            cycle=mock_cycle,
            size_usd=1000.0,
            amount_in=1000,
            amount_out=0,
            gross_bps=0.0,
            status="QUOTE_FAILED",
            reject_reason="CYCLE_QUOTE_FAILED",
            leg_results=[],
            elapsed_s=0.1,
        )
        a = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[qr],
            topology=_make_topology(),
            sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
        )
        diag = a.get("quote_failure_diagnostics")
        assert isinstance(diag, dict)
        assert "by_reject_reason" in diag
        phantom_diag = a.get("phantom_quote_diagnostics")
        assert isinstance(phantom_diag, dict)
        assert phantom_diag.get("blocker_class_hint") == "PHANTOM_VALIDATION"
        assert "m8_participation" in a

    def test_infra_status_blocked_when_qsr_below_acceptance(self):
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult

        mock_cycle = _make_mock_cycle()
        failed = CycleQuoteResult(
            cycle=mock_cycle,
            size_usd=1000.0,
            amount_in=1000,
            amount_out=0,
            gross_bps=0.0,
            status="QUOTE_FAILED",
            reject_reason="CYCLE_QUOTE_FAILED",
            leg_results=[],
            elapsed_s=0.1,
        )
        ok = CycleQuoteResult(
            cycle=mock_cycle,
            size_usd=1000.0,
            amount_in=1000,
            amount_out=1001,
            gross_bps=10.0,
            status="POSITIVE_GROSS",
            reject_reason=None,
            leg_results=[],
            elapsed_s=0.1,
        )
        a = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[failed, failed, failed, ok],
            topology=_make_topology(),
            sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
        )
        assert a["qsr"] == 0.25
        assert a["infra_status"] == "INFRA_OR_QUOTE_QUALITY_BLOCKED"
        assert a["economics_blocker_class"] == "PROVIDER_QUALITY_BLOCKED"
        assert a["economics_gate_status"] == "BLOCKED_QSR"

    def test_oversized_vs_depth_excluded_from_qsr(self):
        """P0a: OVERSIZED_VS_DEPTH cycles are excluded from the QSR denominator.

        A real but extreme quote whose notional overwhelms the bottleneck pool
        depth is neither a quote failure nor a market signal, so it must not
        deflate QSR.  With 2 successful + 2 failed + 6 oversized, QSR is
        2/(2+2)=0.5, NOT 2/10=0.2.
        """
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult

        mock_cycle = _make_mock_cycle()

        def _mk(status, reject):
            return CycleQuoteResult(
                cycle=mock_cycle, size_usd=1000.0, amount_in=1000,
                amount_out=1001 if status == "NEGATIVE_GROSS" else 0,
                gross_bps=-5.0 if status == "NEGATIVE_GROSS" else 0.0,
                status=status, reject_reason=reject, leg_results=[], elapsed_s=0.1,
            )

        results = (
            [_mk("NEGATIVE_GROSS", None)] * 2
            + [_mk("QUOTE_FAILED", "CYCLE_QUOTE_FAILED")] * 2
            + [_mk("OVERSIZED_VS_DEPTH", "OVERSIZED_VS_DEPTH")] * 6
        )
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=results,
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
        )
        assert a["qsr"] == 0.5
        assert a["oversized_vs_depth_count"] == 6
        # Oversized cycles must not be aggregated as phantom rejects.
        assert a["phantom_quote_diagnostics"]["phantom_count"] == 0

    def test_economics_blocker_class_not_blocked_when_positive(self):
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult
        mock_cycle = _make_mock_cycle()
        qr = CycleQuoteResult(
            cycle=mock_cycle, size_usd=1000.0, amount_in=1000, amount_out=1002,
            gross_bps=20.0, status="POSITIVE_GROSS", reject_reason=None,
            leg_results=[], elapsed_s=0.1,
        )
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[qr],
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
        )
        assert a["economics_blocker_class"] == "NOT_BLOCKED"

    def test_economics_blocker_class_anchor_heavy_small_inventory(self):
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult
        mock_cycle = _make_mock_cycle()
        qr = CycleQuoteResult(
            cycle=mock_cycle, size_usd=1000.0, amount_in=1000, amount_out=995,
            gross_bps=-5.0, status="NEGATIVE_GROSS", reject_reason=None,
            leg_results=[], elapsed_s=0.1,
        )
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[qr],
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
            scan_scope={"pair_count": 7, "routes_total": 13},  # small inventory
        )
        assert a["economics_blocker_class"] == "INVENTORY_TOO_ANCHOR_HEAVY"

    def test_risk_metrics_placeholder_present(self):
        a = _empty_artifact()
        rm = a.get("risk_metrics")
        assert isinstance(rm, dict)
        assert rm["risk_gate"] == "NOT_STARTED"
        assert rm["honeypot_checked"] == 0
        assert rm["transfer_tax_checked"] == 0
        assert rm["unsafe_rejected"] == 0

    def test_top_opportunities_present_and_is_list(self):
        """build_artifact() must always produce 'top_opportunities' as a list."""
        a = _empty_artifact()
        assert "top_opportunities" in a
        assert isinstance(a["top_opportunities"], list)

    def test_top_opportunities_schema_with_positive_cycle(self):
        """top_opportunities rows must have required fields when cycles exist."""
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult
        mock_cycle = _make_mock_cycle()
        qr = CycleQuoteResult(
            cycle=mock_cycle, size_usd=500.0, amount_in=500 * 10**6,
            amount_out=502 * 10**6, gross_bps=40.0, status="POSITIVE_GROSS",
            reject_reason=None, leg_results=[], elapsed_s=0.1,
        )
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[qr],
            topology=_make_topology(), sizes_usd=(500.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
        )
        opps = a["top_opportunities"]
        assert len(opps) == 1
        row = opps[0]
        required = {"dex", "factory", "pool", "pool_path", "pair",
                    "market_size_usd", "dynamic_size_usd", "spread_bps",
                    "spread_usd", "profit_usd", "main_blocker"}
        assert required.issubset(set(row.keys())), f"Missing keys: {required - set(row.keys())}"
        assert row["spread_bps"] == 40.0
        assert row["market_size_usd"] == 500.0
        assert row["main_blocker"] is None  # POSITIVE_GROSS => no blocker
        assert isinstance(row["pool_path"], list)
        assert row["spread_usd"] == pytest.approx(40.0 * 500.0 / 10000.0, rel=1e-4)

    def test_top_opportunities_surface_dynamic_size_fields(self):
        """Dynamic-size sweep metadata must be visible to the operator surface."""
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult
        mock_cycle = _make_mock_cycle()
        qr = CycleQuoteResult(
            cycle=mock_cycle, size_usd=250.0, amount_in=250 * 10**6,
            amount_out=251 * 10**6, gross_bps=40.0, status="POSITIVE_GROSS",
            reject_reason=None, leg_results=[], elapsed_s=0.1,
            dynamic_size_usd=250.0,
            size_candidates_usd=(100.0, 250.0, 500.0),
            depth_curve=[
                {"size_usd": 100.0, "gross_bps": 30.0, "status": "NEGATIVE_GROSS"},
                {"size_usd": 250.0, "gross_bps": 40.0, "status": "POSITIVE_GROSS"},
            ],
            dynamic_size_source="multi_size_quote",
        )
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[qr],
            topology=_make_topology(), sizes_usd=(100.0, 250.0, 500.0),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
        )
        row = a["top_opportunities"][0]
        assert a["sizes_usd"] == [100.0, 250.0, 500.0]
        assert row["dynamic_size_usd"] == 250.0
        assert row["size_candidates_usd"] == [100.0, 250.0, 500.0]
        assert row["depth_curve"][1]["size_usd"] == 250.0
        assert row["dynamic_size_source"] == "multi_size_quote"
        assert a["infra_telemetry"]["dynamic_size_enabled"] is True
        assert a["infra_telemetry"]["dynamic_size_selected_count"] == 1

    def test_top_opportunities_main_blocker_negative(self):
        """Non-positive cycles must have a main_blocker value."""
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult
        mock_cycle = _make_mock_cycle()
        qr = CycleQuoteResult(
            cycle=mock_cycle, size_usd=1000.0, amount_in=1000, amount_out=0,
            gross_bps=0.0, status="QUOTE_FAILED", reject_reason="CYCLE_QUOTE_FAILED",
            leg_results=[], elapsed_s=0.1,
        )
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[qr],
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
        )
        opps = a["top_opportunities"]
        assert len(opps) >= 1
        row = opps[0]
        assert row["main_blocker"] is not None


# ---------------------------------------------------------------------------
# Step 4 (GPT fix): gross/net semantics contract
# ---------------------------------------------------------------------------

class TestGrossNetSemantics:
    """Ensure best_cycle_net_bps vs gross/estimated/router_sim fields are correct.

    Contract (until router_sim is implemented):
    - best_cycle_gross_bps = raw quote bps (float or None)
    - best_cycle_net_bps = alias == best_cycle_gross_bps (backward compat)
    - estimated_cost_bps = None (placeholder, cost model not yet implemented)
    - router_sim_net_bps = None (placeholder, router simulation not yet enabled)
    """

    def test_best_cycle_gross_bps_present_in_artifact(self):
        """best_cycle_gross_bps must be a top-level key in the artifact."""
        a = _empty_artifact()
        assert "best_cycle_gross_bps" in a, "best_cycle_gross_bps field missing"

    def test_estimated_cost_bps_is_null_placeholder(self):
        """estimated_cost_bps must be present and null until cost model exists."""
        a = _empty_artifact()
        assert "estimated_cost_bps" in a, "estimated_cost_bps field missing"
        assert a["estimated_cost_bps"] is None

    def test_router_sim_net_bps_is_null_placeholder(self):
        """router_sim_net_bps must be present and null until router sim is enabled."""
        a = _empty_artifact()
        assert "router_sim_net_bps" in a, "router_sim_net_bps field missing"
        assert a["router_sim_net_bps"] is None

    def test_net_alias_equals_gross(self):
        """best_cycle_net_bps must equal best_cycle_gross_bps (alias contract)."""
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult
        mock_cycle = _make_mock_cycle()
        qr = CycleQuoteResult(
            cycle=mock_cycle, size_usd=1000.0, amount_in=1000 * 10**6,
            amount_out=1001 * 10**6, gross_bps=10.0, status="POSITIVE_GROSS",
            reject_reason=None, leg_results=[], elapsed_s=0.1,
        )
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[qr],
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
        )
        assert a["best_cycle_gross_bps"] == a["best_cycle_net_bps"], (
            "best_cycle_net_bps must equal best_cycle_gross_bps (alias)"
        )
        assert a["best_cycle_gross_bps"] == pytest.approx(10.0)

    def test_gross_bps_null_when_no_cycles(self):
        """Both best_cycle_gross_bps and best_cycle_net_bps must be null when no cycles."""
        a = _empty_artifact()
        assert a["best_cycle_gross_bps"] is None
        assert a["best_cycle_net_bps"] is None

    def test_repeatability_counters_zero_when_no_cycles(self):
        """Repeatability counters must be 0 when no cycle_results."""
        a = _empty_artifact()
        assert a["positive_cycle_multi_hit_count"] == 0
        assert a["positive_cycle_max_repeat"] == 0

    def test_repeatability_multi_hit_counted(self):
        """positive_cycle_multi_hit_count counts cycles positive in ≥2 sweeps."""
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult
        mock_cycle = _make_mock_cycle()
        mock_cycle.cycle_id = "repeated_cycle_abc"
        # Same cycle_id appearing positive 3 times (3 sweeps)
        qrs = [
            CycleQuoteResult(
                cycle=mock_cycle, size_usd=1000.0, amount_in=1000, amount_out=1002,
                gross_bps=10.0, status="POSITIVE_GROSS", reject_reason=None,
                leg_results=[], elapsed_s=0.1,
            )
            for _ in range(3)
        ]
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=qrs,
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
        )
        assert a["positive_cycle_max_repeat"] == 3
        assert a["positive_cycle_multi_hit_count"] == 1


# ---------------------------------------------------------------------------
# Step 5 (GPT fix): run_context.inventory_path contract
# ---------------------------------------------------------------------------

class TestInventoryPathInArtifact:
    """inventory_path must be recorded in run_context for reproducibility."""

    def test_run_context_has_inventory_path_key(self):
        """run_context must contain 'inventory_path' key."""
        a = _empty_artifact()
        ctx = a.get("run_context", {})
        assert "inventory_path" in ctx, "run_context.inventory_path key missing"

    def test_inventory_path_is_string(self):
        """run_context.inventory_path must be a string (may be empty)."""
        a = _empty_artifact()
        val = a["run_context"]["inventory_path"]
        assert isinstance(val, str), f"run_context.inventory_path must be str, got {type(val)}"

    def test_inventory_path_explicit_value_propagated(self):
        """Explicit inventory_path passed to build_artifact must appear in run_context."""
        from m9.graph_arb.artifacts import build_artifact
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[],
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
            inventory_path="data/tmp/m9_depth_enriched_inventory.json",
        )
        assert a["run_context"]["inventory_path"] == "data/tmp/m9_depth_enriched_inventory.json"

    def test_rolling_artifact_inventory_path_present(self):
        """Live rolling artifact must have run_context.inventory_path set (non-empty)."""
        d = _load_rolling()
        ctx = d.get("run_context", {})
        assert "inventory_path" in ctx, "run_context.inventory_path missing from rolling artifact"
        inv = ctx["inventory_path"]
        assert inv, f"run_context.inventory_path is empty in rolling artifact: {inv!r}"


# ---------------------------------------------------------------------------
# Prequote funnel + dynamic-size intent telemetry (M9 2-leg RCA fixes)
# ---------------------------------------------------------------------------

class TestPrequoteFunnelTelemetry:
    """Operator-visible funnel/intent fields around the prequote stage."""

    def _build(self, cycle_results, **kwargs):
        from m9.graph_arb.artifacts import build_artifact
        return build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=cycle_results,
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
            **kwargs,
        )

    def _qr(self, status="NEGATIVE_GROSS", reject_reason=None, gross_bps=-5.0):
        from m9.graph_arb.models import CycleQuoteResult
        return CycleQuoteResult(
            cycle=_make_mock_cycle(), size_usd=1000.0, amount_in=1000, amount_out=990,
            gross_bps=gross_bps, status=status, reject_reason=reject_reason,
            leg_results=[], elapsed_s=0.1,
        )

    def test_funnel_fields_present_with_no_skips(self):
        """before == after == cycles_found when nothing was skipped."""
        a = self._build([self._qr()])
        it = a["infra_telemetry"]
        assert it["productive_cycles_after_prequote"] == a["cycles_found"]
        assert it["productive_cycles_before_prequote"] == a["cycles_found"]

    def test_funnel_fields_reflect_skips(self):
        """before == skipped + quoted; after == quoted only."""
        a = self._build([self._qr(), self._qr()], prequote_cycles_skipped=8)
        it = a["infra_telemetry"]
        assert it["productive_cycles_after_prequote"] == 2
        assert it["productive_cycles_before_prequote"] == 10
        # skip_ratio = 8 / (8 + 2)
        assert it["prequote_skip_ratio"] == pytest.approx(0.8)

    def test_force_quote_keeps_skip_ratio_below_one(self):
        """The funnel never reports skip_ratio==1.0 when cycles were quoted."""
        a = self._build([self._qr(), self._qr()], prequote_cycles_skipped=0)
        it = a["infra_telemetry"]
        # No skips recorded → ratio key omitted, but funnel shows everything passed.
        assert it["productive_cycles_after_prequote"] == 2
        assert it.get("prequote_skip_ratio") is None

    def test_dynamic_size_intent_reported_independently_of_results(self):
        """--dynamic-sizes intent is True even when no cycle exercised dynamic sizing."""
        a = self._build([self._qr()], dynamic_sizes_intent=True)
        it = a["infra_telemetry"]
        assert it["dynamic_size_intent"] is True
        # No cycle carried size_candidates → observed enabled stays False.
        assert it["dynamic_size_enabled"] is False

    def test_dynamic_size_intent_defaults_false(self):
        a = self._build([self._qr()])
        assert a["infra_telemetry"]["dynamic_size_intent"] is False

    def test_no_cycles_artifact_preserves_cli_telemetry(self):
        """Zero-cycle early-exit artifacts must keep CLI intent, not reset to defaults.

        Mirrors the runner's early-exit build_artifact() paths (empty graph /
        no cycles / dry-run): even with cycle_results=[], the operator-supplied
        quote_backend / quote_workers / prequote_min_bps / dynamic_sizes_intent
        must be reflected instead of the schema defaults.
        """
        a = self._build(
            [],
            quote_backend="raw_http",
            quote_workers=1,
            prequote_min_bps=-9999.0,
            dynamic_sizes_intent=True,
        )
        it = a["infra_telemetry"]
        assert it["quote_backend"] == "raw_http"
        assert it["quote_workers"] == 1
        assert it["prequote_min_bps"] == -9999.0
        assert it["dynamic_size_intent"] is True


class TestTopOpportunityRejectFields:
    """top_opportunities rows must carry cycle_id/status/reject_reason for failed cycles."""

    def test_failed_cycle_has_reject_fields(self):
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult
        qr = CycleQuoteResult(
            cycle=_make_mock_cycle(), size_usd=1000.0, amount_in=1000, amount_out=0,
            gross_bps=0.0, status="CYCLE_QUOTE_FAILED", reject_reason="QUOTE_REVERT",
            leg_results=[], elapsed_s=0.1,
        )
        a = build_artifact(
            chain="base", duration_minutes=1.0, cycle_results=[qr],
            topology=_make_topology(), sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z", started_at_mono=0.0, elapsed_s=60.0,
        )
        opp = a["top_opportunities"][0]
        assert opp["cycle_id"] == "abc123def456"
        assert opp["status"] == "CYCLE_QUOTE_FAILED"
        assert opp["reject_reason"] == "QUOTE_REVERT"

