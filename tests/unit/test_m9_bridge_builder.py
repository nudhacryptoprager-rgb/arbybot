"""Unit tests for M8в†’M9 bridge_builder module.

Tests:
  - BridgeBuilderUnit: pure-logic tests (no filesystem)
  - BridgeBuilderIntegration: end-to-end with temp files
  - BridgeArtifactContract: bridge_source_metrics appears in M9 artifact
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sniper_artifact(events: list) -> Dict[str, Any]:
    return {
        "schema_family": "m8_sniper",
        "schema_revision": "1",
        "generated_at_utc": "2026-05-24T10:00:00",
        "status": "ACTIVE",
        "metrics": {},
        "recent_events": events,
    }


def _make_anchor_artifact(near_miss_count: int = 2) -> Dict[str, Any]:
    near_miss = [
        {
            "pair_id": "AERO_USDC",
            "route_a_id": "uniswap_v3:f500",
            "route_b_id": "pancakeswap_v3:f500",
            "verdict": "REJECT",
            "reject_reason": "EXCESSIVE_PRICE_IMPACT",
            "gross_bps": -160.0,
        }
        for _ in range(near_miss_count)
    ]
    return {
        "schema_family": "stable_anchor",
        "generated_at_utc": "2026-05-24T10:00:00",
        "status": "ACTIVE",
        "metrics": {},
        "top_routes": [],
        "near_miss_routes": near_miss,
        "pairs_probed": ["AERO_USDC"],
    }


def _make_base_inv(n_active: int = 5) -> Dict[str, Any]:
    active = [
        {
            "route_id": f"uniswap_v3:f3000",
            "pair_id": "USDC_WETH",
            "dex_id": "uniswap_v3",
            "adapter_type": "uniswap_v3",
            "token0": "USDC",
            "token1": "WETH",
            "token0_addr": "0xabc",
            "token1_addr": "0xdef",
            "fee": 3000,
            "pool_address": f"0xpool{i:04d}",
            "factory_verified": True,
            "depth_probe_ok": True,
            "status": "active",
        }
        for i in range(n_active)
    ]
    return {
        "schema_version": "m9_verified_inventory.1",
        "generated_at_utc": "2026-05-24T10:00:00",
        "active_routes": active,
        "quarantined_routes": [],
        "summary": {"active_count": n_active, "quarantined_count": 0},
    }


def _sniper_event(
    token0: str,
    token1: str,
    dex: str = "uniswap_v4",
    pool: str = "0xabc123",
    verdict: str = "SKIP",
) -> Dict[str, Any]:
    return {
        "event_id": f"base:{pool}:0xhash:1",
        "chain": "base",
        "dex": dex,
        "pool": pool,
        "token0_symbol": token0,
        "token1_symbol": token1,
        "pair": f"{token0}/{token1}",
        "phase2_decision": {"verdict": verdict, "reject_reason": "INSUFFICIENT_DATA"},
    }


# ---------------------------------------------------------------------------
# BridgeBuilderUnit: pure-logic (no file I/O)
# ---------------------------------------------------------------------------

class TestBridgeBuilderUnit:
    """Tests for internal bridge_builder helpers."""

    def test_is_symbol_valid_ok(self):
        from m9.graph_arb.bridge_builder import _is_symbol_valid
        assert _is_symbol_valid("USDC") is True
        assert _is_symbol_valid("WETH") is True
        assert _is_symbol_valid("cbBTC") is True

    def test_is_symbol_valid_rejects_empty(self):
        from m9.graph_arb.bridge_builder import _is_symbol_valid
        assert _is_symbol_valid("") is False
        assert _is_symbol_valid(None) is False  # type: ignore

    def test_is_symbol_valid_rejects_too_long(self):
        from m9.graph_arb.bridge_builder import _is_symbol_valid
        assert _is_symbol_valid("A" * 16) is False

    def test_is_symbol_valid_rejects_pure_digits(self):
        from m9.graph_arb.bridge_builder import _is_symbol_valid
        assert _is_symbol_valid("12345") is False

    def test_is_anchor_connected_direct(self):
        from m9.graph_arb.bridge_builder import _is_anchor_connected
        assert _is_anchor_connected("AERO", "USDC") is True
        assert _is_anchor_connected("WETH", "NEWTOKEN") is True
        assert _is_anchor_connected("EURC", "AERO") is True

    def test_is_anchor_connected_both_non_anchor(self):
        from m9.graph_arb.bridge_builder import _is_anchor_connected
        assert _is_anchor_connected("AERO", "BRETT") is False

    def test_artifact_age_seconds_fresh(self):
        from m9.graph_arb.bridge_builder import _artifact_age_seconds
        import time
        now = time.time()
        artifact = {"generated_at_utc": "2099-12-31T00:00:00Z"}
        age = _artifact_age_seconds(artifact, now)
        assert age is not None
        assert age < 0  # future timestamp

    def test_artifact_age_seconds_missing(self):
        from m9.graph_arb.bridge_builder import _artifact_age_seconds
        age = _artifact_age_seconds({}, 0.0)
        assert age is None


# ---------------------------------------------------------------------------
# BridgeBuilderIntegration: end-to-end with temp files
# ---------------------------------------------------------------------------

class TestBridgeBuilderIntegration:
    """End-to-end tests using temp JSON files."""

    def _write_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_empty_sniper_produces_base_inventory(self, tmp_path):
        """When sniper has no events, output contains base inventory routes."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(sniper, _make_sniper_artifact([]))
        self._write_json(anchor, _make_anchor_artifact(2))
        self._write_json(base, _make_base_inv(5))

        metrics = build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        assert out.exists()
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["schema_version"] == "m9_bridge_inventory.1"
        assert len(result["active_routes"]) == 5
        assert metrics["graph_ready_total"] == 5
        assert metrics["m8_new_pools_input"] == 0

    def test_funnel_counts_anchor_connected(self, tmp_path):
        """Events with USDC/WETH pair are counted as anchor_connected."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        events = [
            _sniper_event("NEWTOKEN", "USDC", pool="0xpool001"),
            _sniper_event("AERO", "USDC", pool="0xpool002"),
            _sniper_event("GARBAGE1", "GARBAGE2", pool="0xpool003"),  # not anchor
        ]
        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(sniper, _make_sniper_artifact(events))
        self._write_json(anchor, _make_anchor_artifact(0))
        self._write_json(base, _make_base_inv(3))

        metrics = build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        assert metrics["m8_new_pools_input"] == 3
        assert metrics["token_verified_count"] == 3
        assert metrics["anchor_connected_count"] == 2  # only USDC-paired events

    def test_bridge_metrics_schema_keys_present(self, tmp_path):
        """All required bridge_source_metrics keys are present in output."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(sniper, _make_sniper_artifact([]))
        self._write_json(anchor, _make_anchor_artifact(1))
        self._write_json(base, _make_base_inv(2))

        metrics = build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        required_keys = [
            "m8_new_pools_input",
            "m8_1_anchor_routes_input",
            "token_verified_count",
            "anchor_connected_count",
            "cross_dex_seen_count",
            "factory_verified_count",
            "depth_ok_count",
            "anchor_connected_from_base",
            "graph_ready_from_m8",
            "graph_ready_total",
            "m8_stale",
            "m8_1_stale",
        ]
        for key in required_keys:
            assert key in metrics, f"Missing key: {key}"

    def test_output_artifact_has_bridge_source_metrics(self, tmp_path):
        """bridge_source_metrics is embedded in the output artifact."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(sniper, _make_sniper_artifact([]))
        self._write_json(anchor, _make_anchor_artifact(0))
        self._write_json(base, _make_base_inv(4))

        build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        result = json.loads(out.read_text(encoding="utf-8"))
        assert "bridge_source_metrics" in result
        bsm = result["bridge_source_metrics"]
        assert bsm["graph_ready_total"] == 4
        assert isinstance(bsm["m8_stale"], bool)
        assert isinstance(bsm["m8_1_stale"], bool)

    def test_missing_sniper_marks_m8_stale(self, tmp_path):
        """When sniper file doesn't exist, m8_stale=True."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(anchor, _make_anchor_artifact(1))
        self._write_json(base, _make_base_inv(2))

        metrics = build_bridge_inventory(
            sniper_path=str(tmp_path / "nonexistent_sniper.json"),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        assert metrics["m8_stale"] is True
        assert metrics["m8_new_pools_input"] == 0

    def test_graph_ready_from_m8_pool_in_base(self, tmp_path):
        """M8 event whose pool address exists in base inventory is graph_ready_from_m8."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        # Base inventory with a known pool
        base_data = _make_base_inv(2)
        base_data["active_routes"][0]["pool_address"] = "0xknownpool"
        # Sniper event for same pool вЂ” appears twice (cross_dex_seen); use supported dex
        events = [
            _sniper_event("AERO", "USDC", dex="uniswap_v2", pool="0xknownpool"),
            _sniper_event("AERO", "USDC", dex="aerodrome", pool="0xknownpool"),
        ]

        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(sniper, _make_sniper_artifact(events))
        self._write_json(anchor, _make_anchor_artifact(0))
        self._write_json(base, base_data)

        metrics = build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        assert metrics["cross_dex_seen_count"] == 2  # AERO seen in 2 events
        assert metrics["graph_ready_from_m8"] == 2   # both events' pool in base

    def test_pair_id_uses_underscore_not_slash(self, tmp_path):
        """M8 bridge pair_id must use '_' separator вЂ” required by M9 _parse_pair_symbols().

        Old bug: pair_id='WETH/YLDKT' в†’ _parse_pair_symbols splits by '_' в†’ 1 part
        в†’ ValueError в†’ route silently skipped в†’ graph_edges_from_m8=0.
        """
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        events = [
            _sniper_event("WETH", "YLDKT", dex="uniswap_v2", pool="0xpool001"),
            _sniper_event("USDC", "YLDKT", dex="uniswap_v2", pool="0xpool002"),
        ]
        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(sniper, _make_sniper_artifact(events))
        self._write_json(anchor, _make_anchor_artifact(0))
        self._write_json(base, _make_base_inv(2))

        build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        result = json.loads(out.read_text(encoding="utf-8"))
        m8_routes = [r for r in result["active_routes"] if r.get("source") == "m8_sniper"]
        assert m8_routes, "Expected at least one M8 sniper route in output"
        for route in m8_routes:
            pair_id = route["pair_id"]
            assert "/" not in pair_id, f"pair_id must use '_', got slash: {pair_id!r}"
            assert "_" in pair_id, f"pair_id must use '_' separator, got: {pair_id!r}"

    def test_pair_id_is_sorted_alphabetically(self, tmp_path):
        """M8 bridge pair_id must be alphabetically sorted (canonical form)."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        # WETH > USDC alphabetically, so pair_id must be USDC_WETH not WETH_USDC
        events = [
            _sniper_event("WETH", "USDC", dex="uniswap_v2", pool="0xpool001"),
            _sniper_event("WETH", "USDC", dex="uniswap_v4", pool="0xpool002"),
        ]
        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(sniper, _make_sniper_artifact(events))
        self._write_json(anchor, _make_anchor_artifact(0))
        self._write_json(base, _make_base_inv(2))

        build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        result = json.loads(out.read_text(encoding="utf-8"))
        m8_routes = [r for r in result["active_routes"] if r.get("source") == "m8_sniper"]
        for route in m8_routes:
            pair_id = route["pair_id"]
            parts = pair_id.split("_")
            assert len(parts) == 2, f"pair_id must have exactly 2 parts: {pair_id!r}"
            assert parts == sorted(parts), (
                f"pair_id must be alphabetically sorted: {pair_id!r}"
            )

    def test_m8_pair_id_parseable_by_m9_graph_builder(self, tmp_path):
        """M8 bridge pair_id must be parseable by M9 graph _parse_pair_symbols().

        This is the graph integration contract: graph_ready_from_m8 > 0 must imply
        graph_edges_from_m8 > 0 (routes actually enter graph, not silently skipped).
        """
        from m9.graph_arb.bridge_builder import build_bridge_inventory
        from m9.graph_arb.builder import _parse_pair_symbols

        events = [
            _sniper_event("WETH", "YLDKT", dex="uniswap_v2", pool="0xpool_new_001"),
            _sniper_event("USDC", "YLDKT", dex="uniswap_v2", pool="0xpool_new_002"),
        ]
        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(sniper, _make_sniper_artifact(events))
        self._write_json(anchor, _make_anchor_artifact(0))
        self._write_json(base, _make_base_inv(2))

        metrics = build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        result = json.loads(out.read_text(encoding="utf-8"))
        m8_routes = [r for r in result["active_routes"] if r.get("source") == "m8_sniper"]
        assert metrics["graph_ready_from_m8"] > 0, (
            "graph_ready_from_m8 must be > 0 to test graph integration"
        )
        # Every M8 route pair_id must be parseable вЂ” no ValueError в†’ no silent skip
        parsed_count = 0
        for route in m8_routes:
            pair_id = route["pair_id"]
            try:
                sym0, sym1 = _parse_pair_symbols(pair_id)
                assert sym0 and sym1, f"Parsed empty symbol from pair_id: {pair_id!r}"
                parsed_count += 1
            except ValueError as exc:
                raise AssertionError(
                    f"M8 route pair_id={pair_id!r} is not parseable by M9 graph builder: {exc}"
                ) from exc
        assert parsed_count > 0, "No M8 routes were parseable вЂ” graph_edges_from_m8 would be 0"


# ---------------------------------------------------------------------------
# BridgeArtifactContract: bridge_source_metrics in M9 artifact
# ---------------------------------------------------------------------------

class TestBridgeArtifactContract:
    """Ensures build_artifact() accepts and propagates bridge_source_metrics."""

    def _make_topology(self):
        from m9.graph_arb.models import GraphTopology
        return GraphTopology(
            token_count=3,
            edge_count=4,
            route_count=3,
            hub_tokens=["USDC"],
            dead_end_tokens=[],
            missing_edges_for_3cycle=[],
            adjacency_summary={},
        )

    def test_bridge_source_metrics_absent_by_default(self):
        """Without bridge_source_metrics kwarg, key is absent in artifact."""
        from m9.graph_arb.artifacts import build_artifact
        art = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[],
            topology=self._make_topology(),
            sizes_usd=(100.0,),
            run_timestamp="2026-05-24T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
        )
        assert "bridge_source_metrics" not in art


# ---------------------------------------------------------------------------
# TestAdapterTypePropagation: M8 routes must carry adapter_type
# ---------------------------------------------------------------------------

class TestAdapterTypePropagation:
    """Tests that bridge_builder propagates adapter_type correctly for M8 routes.

    Contract:
    - uniswap_v2 events в†’ active_routes with adapter_type='uniswap_v2'
    - uniswap_v4 events в†’ quarantined_routes with quarantine_reason='UNSUPPORTED_DEX_TYPE'
    - no M8 active route may have adapter_type=None
    - dex_coverage_matrix key present in bridge_source_metrics
    """

    def _write_json(self, path, data) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_v2_routes_have_adapter_type_in_active(self, tmp_path):
        """uniswap_v2 sniper events produce active M8 routes with adapter_type='uniswap_v2'."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        events = [
            _sniper_event("MEME", "USDC", dex="uniswap_v2", pool="0xv2pool001"),
            _sniper_event("MEME", "WETH", dex="uniswap_v2", pool="0xv2pool002"),
        ]
        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(sniper, _make_sniper_artifact(events))
        self._write_json(anchor, _make_anchor_artifact(0))
        self._write_json(base, _make_base_inv(2))

        build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        result = json.loads(out.read_text(encoding="utf-8"))
        m8_routes = [r for r in result["active_routes"] if r.get("source") == "m8_sniper"]
        assert m8_routes, "Expected active M8 sniper routes for uniswap_v2 events"
        for route in m8_routes:
            assert route.get("adapter_type") == "uniswap_v2", (
                f"Expected adapter_type='uniswap_v2', got {route.get('adapter_type')!r}"
            )

    def test_v4_routes_quarantined_not_active(self, tmp_path):
        """uniswap_v4 vanilla (hooks=None) sniper events go to active_routes (V4 quote adapter active)."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        events = [
            _sniper_event("NEWTKN", "USDC", dex="uniswap_v4", pool="0xv4pool001"),
            _sniper_event("NEWTKN", "WETH", dex="uniswap_v4", pool="0xv4pool002"),
        ]
        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(sniper, _make_sniper_artifact(events))
        self._write_json(anchor, _make_anchor_artifact(0))
        self._write_json(base, _make_base_inv(2))

        build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        result = json.loads(out.read_text(encoding="utf-8"))
        # V4 vanilla routes (hooks=None) now go to active_routes вЂ” V4 quote adapter is active
        m8_active = [r for r in result["active_routes"] if r.get("source") == "m8_sniper"]
        assert len(m8_active) == 2, (
            f"Expected 2 uniswap_v4 vanilla routes in active_routes, got {len(m8_active)}"
        )
        for r in m8_active:
            assert r.get("adapter_type") == "uniswap_v4", (
                f"Expected adapter_type='uniswap_v4', got {r.get('adapter_type')!r}"
            )
        # No V4 routes in pending_routes (V4 is now fully supported)
        pending = result.get("pending_routes", [])
        m8_pend = [r for r in pending if r.get("source") == "m8_sniper"]
        assert len(m8_pend) == 0, (
            f"Expected 0 pending M8 v4 routes, got {len(m8_pend)} вЂ” V4 is now active"
        )

    def test_no_none_adapter_type_in_active_m8_routes(self, tmp_path):
        """Every active M8 route must have a non-None adapter_type."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        events = [
            _sniper_event("TKNA", "USDC", dex="uniswap_v2", pool="0xpool_v2_a"),
            _sniper_event("TKNA", "WETH", dex="uniswap_v2", pool="0xpool_v2_b"),
            _sniper_event("TKNB", "USDC", dex="uniswap_v4", pool="0xpool_v4_a"),
            _sniper_event("TKNB", "WETH", dex="uniswap_v4", pool="0xpool_v4_b"),
        ]
        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(sniper, _make_sniper_artifact(events))
        self._write_json(anchor, _make_anchor_artifact(0))
        self._write_json(base, _make_base_inv(2))

        build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        result = json.loads(out.read_text(encoding="utf-8"))
        m8_active = [r for r in result["active_routes"] if r.get("source") == "m8_sniper"]
        for route in m8_active:
            assert route.get("adapter_type") is not None, (
                f"adapter_type must not be None for M8 route: {route['route_id']!r}"
            )
            assert route.get("adapter_type") != "unsupported", (
                f"unsupported routes must be quarantined, not active: {route['route_id']!r}"
            )

    def test_dex_coverage_matrix_in_bridge_source_metrics(self, tmp_path):
        """bridge_source_metrics must contain dex_coverage_matrix with per-dex breakdown."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        events = [
            _sniper_event("TKNA", "USDC", dex="uniswap_v2", pool="0xpool_v2_a"),
            _sniper_event("TKNA", "WETH", dex="uniswap_v2", pool="0xpool_v2_b"),
            _sniper_event("TKNB", "USDC", dex="uniswap_v4", pool="0xpool_v4_a"),
            _sniper_event("TKNB", "WETH", dex="uniswap_v4", pool="0xpool_v4_b"),
        ]
        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"

        self._write_json(sniper, _make_sniper_artifact(events))
        self._write_json(anchor, _make_anchor_artifact(0))
        self._write_json(base, _make_base_inv(2))

        metrics = build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        assert "dex_coverage_matrix" in metrics, "dex_coverage_matrix must be in bridge_source_metrics"
        dcm = metrics["dex_coverage_matrix"]
        assert "uniswap_v2" in dcm
        assert "uniswap_v4" in dcm
        assert dcm["uniswap_v2"]["adapter_type"] == "uniswap_v2"
        assert dcm["uniswap_v2"]["adapter_supported"] is True
        # V4 is fully active вЂ” adapter_type correct and quote adapter enabled
        assert dcm["uniswap_v4"]["adapter_type"] == "uniswap_v4"
        assert dcm["uniswap_v4"]["adapter_supported"] is True
        assert dcm["uniswap_v4"]["adapter_pending"] is False
        assert dcm["uniswap_v4"]["quarantine_reason"] is None
        assert dcm["uniswap_v2"]["event_count"] == 2
        assert dcm["uniswap_v4"]["event_count"] == 2


class TestM8ContextTokenPoolBreakdown:
    """m8_context_token_pool_breakdown tracks per-token pool counts in base inventory."""

    def test_breakdown_populated_when_context_token_exists(self, tmp_path):
        """Token seen in M8 events that also has base routes -> breakdown entry."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        base_routes = [
            {
                "route_id": "r1",
                "pair_id": "VIRAL_WETH",
                "dex_id": "uniswap_v3",
                "adapter_type": "uniswap_v3",
                "token0": "VIRAL",
                "token1": "WETH",
                "token0_addr": "0xviral",
                "token1_addr": "0xweth",
                "fee": 3000,
                "pool_address": "0xpool_viral_weth",
                "factory_verified": True,
                "depth_probe_ok": True,
            },
            {
                "route_id": "r2",
                "pair_id": "VIRAL_USDC",
                "dex_id": "uniswap_v3",
                "adapter_type": "uniswap_v3",
                "token0": "VIRAL",
                "token1": "USDC",
                "token0_addr": "0xviral",
                "token1_addr": "0xusdc",
                "fee": 3000,
                "pool_address": "0xpool_viral_usdc",
                "factory_verified": True,
                "depth_probe_ok": True,
            },
        ]
        base_inv = {
            "schema_version": "m9_verified_inventory.1",
            "generated_at_utc": "2026-05-24T10:00:00",
            "active_routes": base_routes,
            "quarantined_routes": [],
            "summary": {"active_count": 2, "quarantined_count": 0},
        }
        events = [
            {
                "event_id": "base:0xnewpool:0xhash:1",
                "chain": "base",
                "dex": "uniswap_v2",
                "pool": "0xnewpool_viral",
                "token0_symbol": "VIRAL",
                "token1_symbol": "WETH",
                "pair": "VIRAL/WETH",
                "phase2_decision": {"verdict": "SKIP"},
            },
            {
                "event_id": "base:0xnewpool2:0xhash:2",
                "chain": "base",
                "dex": "uniswap_v3",
                "pool": "0xnewpool_viral2",
                "token0_symbol": "VIRAL",
                "token1_symbol": "USDC",
                "pair": "VIRAL/USDC",
                "phase2_decision": {"verdict": "SKIP"},
            },
        ]
        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"
        sniper.write_text(
            __import__("json").dumps(_make_sniper_artifact(events)), encoding="utf-8"
        )
        anchor.write_text(
            __import__("json").dumps(_make_anchor_artifact(0)), encoding="utf-8"
        )
        base.write_text(__import__("json").dumps(base_inv), encoding="utf-8")

        metrics = build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        breakdown = metrics.get("m8_context_token_pool_breakdown")
        assert isinstance(breakdown, dict), "m8_context_token_pool_breakdown must be a dict"
        assert "VIRAL" in breakdown, f"Expected VIRAL in breakdown, got keys={list(breakdown.keys())}"
        assert breakdown["VIRAL"] == 2, f"Expected 2 VIRAL base pools, got {breakdown['VIRAL']}"

    def test_breakdown_empty_when_no_context_tokens(self, tmp_path):
        """No M8-context tokens -> empty breakdown dict (not absent)."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"
        sniper.write_text(
            __import__("json").dumps(_make_sniper_artifact([])), encoding="utf-8"
        )
        anchor.write_text(
            __import__("json").dumps(_make_anchor_artifact(0)), encoding="utf-8"
        )
        base.write_text(__import__("json").dumps(_make_base_inv(3)), encoding="utf-8")

        metrics = build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        breakdown = metrics.get("m8_context_token_pool_breakdown")
        assert isinstance(breakdown, dict), "m8_context_token_pool_breakdown must be a dict"
        assert breakdown == {}, f"Expected empty dict, got {breakdown}"

        from m9.graph_arb.bridge_builder import build_bridge_inventory

        # Base inventory has VIRAL/WETH and VIRAL/USDC routes
        base_routes = [
            {
                "route_id": "r1",
                "pair_id": "VIRAL_WETH",
                "dex_id": "uniswap_v3",
                "adapter_type": "uniswap_v3",
                "token0": "VIRAL",
                "token1": "WETH",
                "token0_addr": "0xviral",
                "token1_addr": "0xweth",
                "fee": 3000,
                "pool_address": "0xpool_viral_weth",
                "factory_verified": True,
                "depth_probe_ok": True,
            },
            {
                "route_id": "r2",
                "pair_id": "VIRAL_USDC",
                "dex_id": "uniswap_v3",
                "adapter_type": "uniswap_v3",
                "token0": "VIRAL",
                "token1": "USDC",
                "token0_addr": "0xviral",
                "token1_addr": "0xusdc",
                "fee": 3000,
                "pool_address": "0xpool_viral_usdc",
                "factory_verified": True,
                "depth_probe_ok": True,
            },
        ]
        base_inv = {
            "schema_version": "m9_verified_inventory.1",
            "generated_at_utc": "2026-05-24T10:00:00",
            "active_routes": base_routes,
            "quarantined_routes": [],
            "summary": {"active_count": 2, "quarantined_count": 0},
        }
        # M8 sniper events: new pools for VIRAL (non-anchor token that also exists in base)
        events = [
            {
                "event_id": "base:0xnewpool:0xhash:1",
                "chain": "base",
                "dex": "uniswap_v2",
                "pool": "0xnewpool_viral",  # NOT in base
                "token0_symbol": "VIRAL",
                "token1_symbol": "WETH",
                "pair": "VIRAL/WETH",
                "phase2_decision": {"verdict": "SKIP"},
            },
            # Second VIRAL event for cross_dex_seen (freq >= 2)
            {
                "event_id": "base:0xnewpool2:0xhash:2",
                "chain": "base",
                "dex": "uniswap_v3",
                "pool": "0xnewpool_viral2",
                "token0_symbol": "VIRAL",
                "token1_symbol": "USDC",
                "pair": "VIRAL/USDC",
                "phase2_decision": {"verdict": "SKIP"},
            },
        ]
        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"
        sniper.write_text(
            __import__("json").dumps(_make_sniper_artifact(events)), encoding="utf-8"
        )
        anchor.write_text(
            __import__("json").dumps(_make_anchor_artifact(0)), encoding="utf-8"
        )
        base.write_text(__import__("json").dumps(base_inv), encoding="utf-8")

        metrics = build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        breakdown = metrics.get("m8_context_token_pool_breakdown")
        assert isinstance(breakdown, dict), "m8_context_token_pool_breakdown must be a dict"
        assert "VIRAL" in breakdown, f"Expected VIRAL in breakdown, got keys={list(breakdown.keys())}"
        assert breakdown["VIRAL"] == 2, f"Expected 2 VIRAL base pools, got {breakdown['VIRAL']}"

    def test_breakdown_empty_when_no_context_tokens(self, tmp_path):
        """No M8-context tokens в†’ empty breakdown dict (not absent)."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"
        sniper.write_text(
            __import__("json").dumps(_make_sniper_artifact([])), encoding="utf-8"
        )
        anchor.write_text(
            __import__("json").dumps(_make_anchor_artifact(0)), encoding="utf-8"
        )
        base.write_text(__import__("json").dumps(_make_base_inv(3)), encoding="utf-8")

        metrics = build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
        )

        breakdown = metrics.get("m8_context_token_pool_breakdown")
        assert isinstance(breakdown, dict), "m8_context_token_pool_breakdown must be a dict"
        assert breakdown == {}, f"Expected empty dict, got {breakdown}"

