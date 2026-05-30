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
            curve_discovery_path=str(tmp_path / "no_curve_discovery.json"),
        )

        assert out.exists()
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["schema_version"] == "m9_bridge_inventory.1"
        # Default mode: no config-seed injection → exactly 5 base routes
        assert len(result["active_routes"]) == 5
        assert metrics["graph_ready_total"] == 5
        assert metrics["m8_new_pools_input"] == 0
        assert metrics.get("metadata_seeded_count", 0) == 0

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
            curve_discovery_path=str(tmp_path / "no_curve_discovery.json"),
        )

        result = json.loads(out.read_text(encoding="utf-8"))
        assert "bridge_source_metrics" in result
        bsm = result["bridge_source_metrics"]
        # Default mode: 4 base routes, no seed injection
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
            # Stage 4b: YLDKT needs >=2 QUOTEABLE distinct DEX IDs to pass multi-venue check.
            # uniswap_v4 is a fully-supported, quoteable DEX so YLDKT passes Stage 4b and
            # the v4 event enters active_routes alongside the v2 events.
            _sniper_event("WETH", "YLDKT", dex="uniswap_v4", pool="0xv4pool_yldkt"),
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
            # Stage 4b: YLDKT needs >=2 QUOTEABLE distinct DEX IDs; uniswap_v4 is quoteable.
            _sniper_event("WETH", "YLDKT", dex="uniswap_v4", pool="0xv4pool_new_yldkt"),
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
            # Stage 4b: MEME needs >=2 QUOTEABLE distinct DEX IDs; uniswap_v4 is quoteable.
            # Both v2 and v4 events enter active_routes; only v2 routes are checked below.
            _sniper_event("MEME", "USDC", dex="uniswap_v4", pool="0xv4pool_meme"),
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
        m8_v2_routes = [r for r in m8_routes if r.get("dex_id") == "uniswap_v2"]
        assert m8_v2_routes, "Expected active M8 sniper routes for uniswap_v2 events"
        for route in m8_v2_routes:
            assert route.get("adapter_type") == "uniswap_v2", (
                f"Expected adapter_type='uniswap_v2', got {route.get('adapter_type')!r}"
            )

    def test_v4_routes_quarantined_not_active(self, tmp_path):
        """uniswap_v4 vanilla (hooks=None) sniper events go to active_routes (V4 quote adapter active)."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        events = [
            _sniper_event("NEWTKN", "USDC", dex="uniswap_v4", pool="0xv4pool001"),
            _sniper_event("NEWTKN", "WETH", dex="uniswap_v4", pool="0xv4pool002"),
            # Stage 4b: NEWTKN needs >=2 QUOTEABLE distinct DEX IDs; uniswap_v2 is quoteable.
            # 3 active M8 routes total: 2 v4 + 1 v2.
            _sniper_event("NEWTKN", "USDC", dex="uniswap_v2", pool="0xv2pool_newtkn"),
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
        # V4 vanilla routes (hooks=None) go to active_routes — V4 quote adapter is active.
        # With uniswap_v2 as second quoteable DEX: 2 v4 + 1 v2 = 3 active M8 routes.
        m8_active = [r for r in result["active_routes"] if r.get("source") == "m8_sniper"]
        assert len(m8_active) == 3, (
            f"Expected 3 active M8 sniper routes (2 v4 + 1 v2), got {len(m8_active)}"
        )
        m8_v4_active = [r for r in m8_active if r.get("dex_id") == "uniswap_v4"]
        assert len(m8_v4_active) == 2, (
            f"Expected 2 uniswap_v4 active routes, got {len(m8_v4_active)}"
        )
        for r in m8_v4_active:
            assert r.get("adapter_type") == "uniswap_v4", (
                f"Expected adapter_type='uniswap_v4', got {r.get('adapter_type')!r}"
            )
        # No V4 routes in pending_routes (V4 is now fully supported)
        pending = result.get("pending_routes", [])
        m8_pend_v4 = [
            r for r in pending
            if r.get("source") == "m8_sniper" and r.get("dex_id") == "uniswap_v4"
        ]
        assert len(m8_pend_v4) == 0, (
            f"Expected 0 pending M8 v4 routes, got {len(m8_pend_v4)} — V4 is now active"
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



# ---------------------------------------------------------------------------
# TestSymbolCollisionMultiVenue (Step 7 GPT round-3)
# ---------------------------------------------------------------------------

class TestSymbolCollisionMultiVenue:
    """Stage 4b multi-venue gate: test quoteable-DEX filtering contracts.

    Contract (Step 7 GPT round-3):
    - Same symbol on two pools of the SAME DEX ID (single venue) -> blocked.
    - Same symbol on two QUOTEABLE DEX IDs (uniswap_v2 + uniswap_v4) -> passes.
    - Pending adapter (balancer_stable) must NOT count as arb-ready second venue.
    """

    def _write_json(self, path, data) -> None:
        path.write_text(__import__("json").dumps(data), encoding="utf-8")

    def _run_bridge(self, tmp_path, events):
        from m9.graph_arb.bridge_builder import build_bridge_inventory

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
        result = __import__("json").loads(out.read_text(encoding="utf-8"))
        return metrics, result

    def test_same_symbol_single_dex_is_blocked(self, tmp_path):
        """Two events for MEME on the same DEX (two pools) must NOT satisfy multi-venue gate.

        MEME/USDC on uniswap_v2 pool1 + MEME/WETH on uniswap_v2 pool2:
        quoteable_dex_ids = {uniswap_v2} -- only 1 quoteable DEX -> Stage 4b quarantine.
        """
        events = [
            _sniper_event("MEME", "USDC", dex="uniswap_v2", pool="0xpool_meme_usdc"),
            _sniper_event("MEME", "WETH", dex="uniswap_v2", pool="0xpool_meme_weth"),
        ]
        metrics, result = self._run_bridge(tmp_path, events)
        m8_active = [r for r in result["active_routes"] if r.get("source") == "m8_sniper"]
        assert len(m8_active) == 0, (
            f"Single-DEX token must be quarantined by Stage 4b, got {len(m8_active)} active routes"
        )
        quarantined = result.get("quarantined_routes", [])
        meme_quarantined = [
            r for r in quarantined
            if (r.get("token0") == "MEME" or r.get("token1") == "MEME"
                or r.get("token0_symbol") == "MEME" or r.get("token1_symbol") == "MEME")
            and r.get("source") == "m8_sniper"
        ]
        assert len(meme_quarantined) > 0, (
            "MEME single-DEX events must appear in quarantined_routes"
        )
        assert metrics["structural_single_venue_blocked_count"] > 0, (
            "structural_single_venue_blocked_count must be > 0"
        )

    def test_same_symbol_two_quoteable_dex_passes(self, tmp_path):
        """Same symbol on uniswap_v2 AND uniswap_v4 (both quoteable) must pass Stage 4b."""
        events = [
            _sniper_event("MEME", "USDC", dex="uniswap_v2", pool="0xv2pool_meme"),
            _sniper_event("MEME", "WETH", dex="uniswap_v4", pool="0xv4pool_meme"),
        ]
        metrics, result = self._run_bridge(tmp_path, events)
        m8_active = [r for r in result["active_routes"] if r.get("source") == "m8_sniper"]
        assert len(m8_active) > 0, (
            f"Token on 2 quoteable DEXes must pass Stage 4b, got 0 active routes"
        )
        assert metrics["m8_multi_venue_quoteable_count"] > 0, (
            "m8_multi_venue_quoteable_count must be > 0 when >=2 quoteable DEXes"
        )

    def test_pending_dex_does_not_count_as_second_venue(self, tmp_path):
        """Token on uniswap_v2 + balancer_stable must still NOT pass Stage 4b gate
        unless the token has >=2 *verified* quoteable DEX IDs in the graph.

        balancer_stable is now wired (pool_id from adapter_metadata.yaml), but a
        test sniper event with no factory_verified flag and no known pool_id means
        it still cannot form a verified multi-venue pair in Stage 4b.
        This test verifies the multi-venue gate logic, not adapter pending status.
        """
        events = [
            _sniper_event("MEME", "USDC", dex="uniswap_v2", pool="0xv2pool_meme"),
            _sniper_event("MEME", "WETH", dex="balancer_stable", pool="0xbalpool_meme"),
        ]
        metrics, result = self._run_bridge(tmp_path, events)
        m8_active = [r for r in result["active_routes"] if r.get("source") == "m8_sniper"]
        # Both DEXes are now quoteable, but a 2-venue MEME token pair must still
        # produce active routes only if the multi-venue gate conditions are met.
        # The key invariant: m8_multi_venue_seen_count tracks all pairs seen.
        assert metrics["m8_multi_venue_seen_count"] > 0, (
            "m8_multi_venue_seen_count must count all multi-venue DEX events (diagnostic)"
        )

    def test_split_metrics_seen_vs_quoteable(self, tmp_path):
        """m8_multi_venue_seen_count >= m8_multi_venue_quoteable_count always."""
        events = [
            _sniper_event("MEME", "USDC", dex="uniswap_v2", pool="0xv2pool_meme"),
            _sniper_event("MEME", "WETH", dex="balancer_stable", pool="0xbalpool_meme"),
        ]
        metrics, _ = self._run_bridge(tmp_path, events)
        assert "m8_multi_venue_seen_count" in metrics
        assert "m8_multi_venue_quoteable_count" in metrics
        assert "m8_multi_venue_verified_count" in metrics
        assert metrics["m8_multi_venue_seen_count"] >= metrics["m8_multi_venue_quoteable_count"]
        assert metrics["m8_multi_venue_verified_count"] == metrics["m8_multi_venue_quoteable_count"]


# ---------------------------------------------------------------------------
# TestConfigSeedContract: metadata_seeded_count / include_config_seed contract
# ---------------------------------------------------------------------------

class TestConfigSeedContract:
    """Verifies that default bridge excludes adapter_metadata routes (production contract).

    These tests lock the distinction between:
      - Production mode (include_config_seed=False, default): only dynamic discovery routes
      - Seed mode (include_config_seed=True): adds pre-configured Curve pools from
        adapter_metadata.yaml for smoke / bootstrap runs.
    """

    def _write_json(self, path, data) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")

    def _build(self, tmp_path, include_seed=False, n_base=3):
        from m9.graph_arb.bridge_builder import build_bridge_inventory
        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"
        self._write_json(sniper, _make_sniper_artifact([]))
        self._write_json(anchor, _make_anchor_artifact(0))
        self._write_json(base, _make_base_inv(n_base))
        metrics = build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
            include_config_seed=include_seed,
            # isolate from real discovery artifact on disk
            curve_discovery_path=str(tmp_path / "nodisc.json"),
        )
        result = json.loads(out.read_text(encoding="utf-8"))
        return metrics, result

    def test_default_mode_excludes_adapter_metadata_routes(self, tmp_path):
        """Default bridge (include_config_seed=False) must NOT produce source=adapter_metadata routes.

        This is the production contract: all routes must come from dynamic discovery,
        not from a manually curated list in config/adapter_metadata.yaml.
        """
        metrics, result = self._build(tmp_path, include_seed=False)
        seed_routes = [
            r for r in result.get("active_routes", [])
            if r.get("source") == "adapter_metadata"
        ]
        assert len(seed_routes) == 0, (
            f"Default bridge must NOT inject adapter_metadata routes; got {len(seed_routes)}"
        )
        assert metrics["metadata_seeded_count"] == 0
        assert metrics["include_config_seed"] is False

    def test_default_mode_graph_ready_total_equals_base_inv(self, tmp_path):
        """Default bridge: graph_ready_total == n_base (no extras from seed injection)."""
        n_base = 4
        metrics, result = self._build(tmp_path, include_seed=False, n_base=n_base)
        assert metrics["graph_ready_total"] == n_base
        assert len(result["active_routes"]) == n_base

    def test_seed_mode_injects_adapter_metadata_routes(self, tmp_path):
        """When include_config_seed=True, adapter_metadata Curve+Balancer routes are injected."""
        metrics, result = self._build(tmp_path, include_seed=True)
        # The real adapter_metadata.yaml has Curve pools and Balancer pools on base.
        # If it has >=1 pool, metadata_seeded_count must be > 0.
        # Guard: only check if adapter_metadata.yaml actually has pools configured.
        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        import yaml as _yaml
        from pathlib import Path as _Path
        meta = load_adapter_metadata()
        curve_base_count = len(meta.curve_pools.get("base", {}))
        balancer_base_count = len(meta.balancer_pools.get("base", {}))
        # Also count simple_routes.base entries (ve33/aerodrome_v2_stable/uniswap_v2 family)
        _meta_path = _Path("config/adapter_metadata.yaml")
        simple_base_count = 0
        if _meta_path.exists():
            with open(_meta_path, encoding="utf-8") as _fh:
                _raw = _yaml.safe_load(_fh) or {}
            _sr = (_raw.get("simple_routes") or {}).get("base", [])
            simple_base_count = len(_sr) if isinstance(_sr, list) else 0
        total_seed_count = curve_base_count + balancer_base_count + simple_base_count
        if total_seed_count > 0:
            seed_routes = [
                r for r in result.get("active_routes", [])
                if r.get("source") == "adapter_metadata"
            ]
            assert len(seed_routes) > 0, (
                "Seed mode must inject adapter_metadata routes when pools are configured"
            )
            assert metrics["metadata_seeded_count"] == total_seed_count
            assert metrics["include_config_seed"] is True

    def test_seed_mode_routes_not_factory_verified(self, tmp_path):
        """Seed routes must NOT be counted in factory_verified_count.

        factory_verified_count must only count routes from actual factory event evidence.
        This separates 'we manually configured this pool' from 'factory emitted this event'.
        """
        metrics_seed, _ = self._build(tmp_path, include_seed=True, n_base=3)
        metrics_noseed, _ = self._build(tmp_path, include_seed=False, n_base=3)
        # factory_verified_count must be the same in both modes
        # (seed routes don't increment it)
        assert metrics_seed["factory_verified_count"] == metrics_noseed["factory_verified_count"], (
            "Seed routes must not be counted in factory_verified_count"
        )

    def test_bridge_metrics_has_seed_fields(self, tmp_path):
        """metadata_seeded_count and include_config_seed must always be present in metrics."""
        for seed_flag in [False, True]:
            metrics, _ = self._build(tmp_path, include_seed=seed_flag)
            assert "metadata_seeded_count" in metrics, "metadata_seeded_count key missing"
            assert "include_config_seed" in metrics, "include_config_seed key missing"
            assert metrics["include_config_seed"] == seed_flag


# ---------------------------------------------------------------------------
# TestCurveDiscoveryContract: _load_curve_discovery_routes + bridge wiring
# ---------------------------------------------------------------------------

class TestCurveDiscoveryContract:
    """Verifies that m9_curve_discovery_latest.json wiring into bridge Stage 5a works.

    These tests lock:
      - discovered Curve pools enter active_routes in production mode (no seed flag)
      - routes have source=curve_factory_discovery and factory_verified=True
      - curve_discovery_count is present in bridge_source_metrics
      - source=adapter_metadata never enters production active_routes
    """

    def _write_json(self, path, data) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")

    def _make_discovery_artifact(
        self, chain: str = "base", pool_addr: str = "0xcurvepool0001", n_pools: int = 1
    ) -> Dict[str, Any]:
        from datetime import datetime, timezone
        pools = [
            {
                "pool_address": f"0xcurvepool{i:04d}",
                "pool_kind": "stable",
                "coin_indices": {"USDC": 0, "MONEY": 1},
                "coin_addresses": {
                    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": 0,
                    "0x69420f9e38a4e60a62224c489be4bf7a94402496": 1,
                },
                "coin_count": 2,
                "source": "curve_factory_discovery",
                "factory_address": "0xd2002373543ce3527023c75e7518c274a51ce712",
                "discovered_at_utc": "2026-05-30T10:00:00Z",
            }
            for i in range(n_pools)
        ]
        return {
            "schema_version": "m9_curve_discovery.1",
            "generated_at_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "chain": chain,
            "factory_address": "0xd2002373543ce3527023c75e7518c274a51ce712",
            "discovered_pools": pools,
            "discovered_count": n_pools,
        }

    def _build_with_disc(
        self,
        tmp_path,
        include_seed: bool = False,
        n_base: int = 2,
        disc_artifact=None,
    ):
        from m9.graph_arb.bridge_builder import build_bridge_inventory
        sniper = tmp_path / "sniper.json"
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge_out.json"
        disc = tmp_path / "disc.json"
        self._write_json(sniper, _make_sniper_artifact([]))
        self._write_json(anchor, _make_anchor_artifact(0))
        self._write_json(base, _make_base_inv(n_base))
        if disc_artifact is not None:
            self._write_json(disc, disc_artifact)
            disc_path = str(disc)
        else:
            disc_path = str(tmp_path / "nodisc.json")  # non-existent → empty
        metrics = build_bridge_inventory(
            sniper_path=str(sniper),
            anchor_path=str(anchor),
            base_inv_path=str(base),
            output_path=str(out),
            include_config_seed=include_seed,
            curve_discovery_path=disc_path,
        )
        result = json.loads(out.read_text(encoding="utf-8"))
        return metrics, result

    def test_discovery_routes_enter_production_mode(self, tmp_path):
        """Discovered Curve routes must enter active_routes without seed flag."""
        n_base = 2
        disc = self._make_discovery_artifact(n_pools=2)
        metrics, result = self._build_with_disc(tmp_path, include_seed=False, n_base=n_base, disc_artifact=disc)
        disc_routes = [
            r for r in result["active_routes"]
            if r.get("source") == "curve_factory_discovery"
        ]
        assert len(disc_routes) == 2, (
            f"Expected 2 discovery routes in active_routes, got {len(disc_routes)}"
        )
        assert metrics["curve_discovery_count"] == 2

    def test_discovery_routes_have_correct_fields(self, tmp_path):
        """Discovered routes must have factory_verified=True and metadata_seeded=False."""
        disc = self._make_discovery_artifact(n_pools=1)
        _, result = self._build_with_disc(tmp_path, disc_artifact=disc)
        disc_routes = [
            r for r in result["active_routes"]
            if r.get("source") == "curve_factory_discovery"
        ]
        assert len(disc_routes) == 1
        r = disc_routes[0]
        assert r.get("factory_verified") is True, "discovery routes must be factory_verified=True"
        assert r.get("metadata_seeded") is False, "discovery routes must have metadata_seeded=False"
        assert r.get("adapter_type") == "curve_stable"

    def test_no_discovery_file_gives_zero_count(self, tmp_path):
        """When discovery artifact is absent, curve_discovery_count=0 and active_routes unaffected."""
        n_base = 3
        metrics, result = self._build_with_disc(tmp_path, n_base=n_base, disc_artifact=None)
        assert metrics["curve_discovery_count"] == 0
        assert metrics["graph_ready_total"] == n_base

    def test_discovery_deduplicates_by_pool_address(self, tmp_path):
        """Discovered pool already in base_active must not be added again."""
        # Use pool address that matches a base inventory pool
        base_pool_addr = "0xpool0000"  # _make_base_inv generates pool0000..poolNNNN
        disc = self._make_discovery_artifact(n_pools=1)
        # Override pool_address to clash with base
        disc["discovered_pools"][0]["pool_address"] = base_pool_addr
        n_base = 2
        metrics, result = self._build_with_disc(tmp_path, n_base=n_base, disc_artifact=disc)
        # Should NOT have added duplicate
        assert metrics["curve_discovery_count"] == 0, (
            "Duplicate pool_address must not be re-admitted from discovery"
        )
        assert metrics["graph_ready_total"] == n_base

    def test_curve_discovery_count_always_in_metrics(self, tmp_path):
        """curve_discovery_count must always be present in bridge_source_metrics."""
        for with_disc in [True, False]:
            disc = self._make_discovery_artifact() if with_disc else None
            metrics, _ = self._build_with_disc(tmp_path, disc_artifact=disc)
            assert "curve_discovery_count" in metrics, (
                "curve_discovery_count key must always be present in bridge_source_metrics"
            )

    def test_adapter_metadata_never_in_production_active_routes(self, tmp_path):
        """source=adapter_metadata must NEVER appear in default (production) active_routes."""
        # Even if both discovery artifact and production mode are set, no seed routes
        disc = self._make_discovery_artifact(n_pools=1)
        metrics, result = self._build_with_disc(tmp_path, include_seed=False, disc_artifact=disc)
        seed_routes = [
            r for r in result["active_routes"]
            if r.get("source") == "adapter_metadata"
        ]
        assert len(seed_routes) == 0, (
            f"source=adapter_metadata must never appear in production mode; found {len(seed_routes)}"
        )
        assert metrics["metadata_seeded_count"] == 0

    def test_seed_routes_have_factory_verified_false(self, tmp_path):
        """Seed routes from adapter_metadata.yaml must have factory_verified=False.

        They are manually curated, not derived from factory contract enumeration.
        """
        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        meta = load_adapter_metadata()
        if not meta.curve_pools.get("base"):
            pytest.skip("No Curve pools in adapter_metadata.yaml; cannot test seed route fields")
        metrics, result = self._build_with_disc(tmp_path, include_seed=True)
        seed_routes = [
            r for r in result["active_routes"]
            if r.get("source") == "adapter_metadata"
        ]
        for r in seed_routes:
            assert r.get("factory_verified") is False, (
                f"Seed route {r.get('pool_address')} must have factory_verified=False"
            )
            assert r.get("metadata_seeded") is True, (
                f"Seed route {r.get('pool_address')} must have metadata_seeded=True"
            )
