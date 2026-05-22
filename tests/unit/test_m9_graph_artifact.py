"""Schema and contract tests for m9_graph_latest.json rolling artifact.

These tests ensure the artifact written by m9.graph_arb.artifacts.build_artifact()
conforms to the canonical M9 schema contract.  They run offline against the
live rolling file *when it exists*, and also validate the artifact builder
directly using synthetic inputs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

_ROLLING = Path("data/runs/_rolling/m9_graph_latest.json")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_rolling() -> Dict[str, Any]:
    if not _ROLLING.exists():
        pytest.skip(f"Rolling artifact not found: {_ROLLING}")
    return json.loads(_ROLLING.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Rolling artifact tests (skip if file absent)
# ---------------------------------------------------------------------------

class TestM9GraphArtifactSchema:
    """Validate the live rolling m9_graph_latest.json against contract."""

    def test_schema_family(self):
        d = _load_rolling()
        assert d.get("schema_family") == "m9_graph_arb", (
            f"schema_family must be 'm9_graph_arb', got {d.get('schema_family')!r}"
        )

    def test_schema_revision_format(self):
        d = _load_rolling()
        rev = d.get("schema_revision", "")
        assert str(rev).startswith("m9."), (
            f"schema_revision must start with 'm9.', got {rev!r}"
        )

    def test_required_fields_present(self):
        d = _load_rolling()
        required = {
            "schema_family",
            "schema_revision",
            "run_timestamp",
            "cycles_found",
            "cycles_positive_gross",
            "best_cycle_net_bps",
            "qsr",
            "economics_gate_status",
            "gate_acceptance",
        }
        missing = required - set(d.keys())
        assert not missing, f"Missing required fields: {missing}"

    def test_cycles_found_non_negative(self):
        d = _load_rolling()
        cycles_found = d.get("cycles_found")
        assert isinstance(cycles_found, int), "cycles_found must be int"
        assert cycles_found >= 0, f"cycles_found must be >= 0, got {cycles_found}"

    def test_cycles_positive_gross_non_negative(self):
        d = _load_rolling()
        cpg = d.get("cycles_positive_gross")
        assert isinstance(cpg, int), "cycles_positive_gross must be int"
        assert cpg >= 0, f"cycles_positive_gross must be >= 0, got {cpg}"

    def test_cycles_positive_gross_lte_cycles_found(self):
        d = _load_rolling()
        assert d.get("cycles_positive_gross", 0) <= d.get("cycles_found", 0), (
            "cycles_positive_gross cannot exceed cycles_found"
        )

    def test_qsr_in_range(self):
        d = _load_rolling()
        qsr = d.get("qsr")
        assert qsr is None or 0.0 <= float(qsr) <= 1.0, (
            f"qsr must be in [0, 1], got {qsr}"
        )

    def test_best_cycle_net_bps_numeric_or_null(self):
        d = _load_rolling()
        val = d.get("best_cycle_net_bps")
        assert val is None or isinstance(val, (int, float)), (
            f"best_cycle_net_bps must be numeric or null, got {type(val)}"
        )

    def test_economics_gate_status_valid(self):
        d = _load_rolling()
        valid = {
            "BLOCKED_NO_CYCLES",
            "BLOCKED_QSR",
            "NEAR_MISS",
            "BLOCKED_NO_POSITIVE_GROSS",
            "PASS",
        }
        status = d.get("economics_gate_status")
        assert status in valid, (
            f"economics_gate_status must be one of {valid}, got {status!r}"
        )

    def test_gate_acceptance_bool(self):
        d = _load_rolling()
        ga = d.get("gate_acceptance")
        assert isinstance(ga, bool), f"gate_acceptance must be bool, got {type(ga)}"

    def test_gate_acceptance_matches_econ_status(self):
        """gate_acceptance=True IFF economics_gate_status == PASS."""
        d = _load_rolling()
        gate = d.get("gate_acceptance")
        econ = d.get("economics_gate_status")
        if econ == "PASS":
            assert gate is True, "gate_acceptance must be True when economics_gate_status=PASS"
        else:
            assert gate is False, (
                f"gate_acceptance must be False when economics_gate_status={econ!r}"
            )

    def test_run_timestamp_format(self):
        """run_timestamp must be ISO 8601 UTC like 2026-05-22T08:10:29Z."""
        import re
        d = _load_rolling()
        ts = d.get("run_timestamp", "")
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", str(ts)), (
            f"run_timestamp must be YYYY-MM-DDTHH:MM:SSZ, got {ts!r}"
        )

    def test_cycle_reject_histogram_is_dict_if_present(self):
        d = _load_rolling()
        hist = d.get("cycle_reject_histogram")
        if hist is not None:
            assert isinstance(hist, dict), "cycle_reject_histogram must be a dict"
            for k, v in hist.items():
                assert isinstance(k, str), f"histogram key must be str, got {k!r}"
                assert isinstance(v, int), f"histogram value must be int, got {v!r}"

    def test_top_cycles_list_if_present(self):
        d = _load_rolling()
        top = d.get("top_cycles")
        if top is not None:
            assert isinstance(top, list), "top_cycles must be a list"
            for entry in top[:3]:
                assert "cycle_id" in entry, "top_cycles entry missing cycle_id"
                assert "gross_bps" in entry, "top_cycles entry missing gross_bps"
                assert "status" in entry, "top_cycles entry missing status"


# ---------------------------------------------------------------------------
# Builder unit tests (no file required)
# ---------------------------------------------------------------------------

class TestM9GraphArtifactBuilder:
    """Unit tests for m9.graph_arb.artifacts.build_artifact()."""

    def _make_topology(self):
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

    def test_empty_cycles_gives_blocked_no_cycles(self):
        from m9.graph_arb.artifacts import build_artifact
        artifact = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[],
            topology=self._make_topology(),
            sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
        )
        assert artifact["economics_gate_status"] == "BLOCKED_NO_CYCLES"
        assert artifact["gate_acceptance"] is False
        assert artifact["cycles_found"] == 0

    def test_schema_fields_present(self):
        from m9.graph_arb.artifacts import build_artifact, SCHEMA_FAMILY, SCHEMA_REVISION
        artifact = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[],
            topology=self._make_topology(),
            sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
        )
        assert artifact["schema_family"] == SCHEMA_FAMILY
        assert artifact["schema_revision"] == SCHEMA_REVISION

    def test_write_and_read_artifact(self, tmp_path):
        from m9.graph_arb.artifacts import build_artifact, write_artifact
        out = str(tmp_path / "m9_test.json")
        artifact = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[],
            topology=self._make_topology(),
            sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
        )
        write_artifact(artifact, out)
        loaded = json.loads(Path(out).read_text(encoding="utf-8"))
        assert loaded["schema_family"] == "m9_graph_arb"
        assert loaded["cycles_found"] == 0

    def test_gate_pass_when_positive_gross(self):
        """Simulate a CycleQuoteResult with positive gross_bps and check gate."""
        from unittest.mock import MagicMock
        from m9.graph_arb.artifacts import build_artifact
        from m9.graph_arb.models import CycleQuoteResult

        mock_cycle = MagicMock()
        mock_cycle.cycle_id = "abc123def456"
        mock_cycle.length = 3
        mock_cycle.token_path = ["USDC", "WETH", "USDT"]
        mock_cycle.start_token_sym = "USDC"
        mock_cycle.total_fee_bps = 9.0
        mock_cycle.min_factory_class = "EFFICIENT_BASELINE"

        qr = CycleQuoteResult(
            cycle=mock_cycle,
            size_usd=1000.0,
            amount_in=1000 * 10**6,
            amount_out=1002 * 10**6,
            gross_bps=20.0,
            status="POSITIVE_GROSS",
            reject_reason=None,
            leg_results=[],
            elapsed_s=0.1,
        )

        artifact = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[qr],
            topology=self._make_topology(),
            sizes_usd=(1000.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
        )
        assert artifact["cycles_positive_gross"] == 1
        assert artifact["economics_gate_status"] == "PASS"
        assert artifact["gate_acceptance"] is True
