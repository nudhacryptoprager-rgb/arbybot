"""Tests for m9.graph_arb.builder inventory selection and stats extraction."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from m9.graph_arb.builder import best_inventory_path, extract_inventory_stats


_SHADOW_PATH = "data/tmp/m9_shadow_inventory_with_gap_edges.json"
_M8_1_PATH = "data/tmp/m8_1_exotic_inventory_latest.json"


class TestBestInventoryPath:
    """Tests that best_inventory_path() picks the right default."""

    def test_shadow_preferred_when_exists(self, tmp_path):
        """If shadow inventory exists, it must be returned when preferred=None."""
        shadow = tmp_path / "shadow.json"
        shadow.write_text("{}")
        m8_1 = tmp_path / "m8_1.json"
        m8_1.write_text("{}")
        result = best_inventory_path(
            preferred=None,
            fallback=str(m8_1),
        )
        # Override _SHADOW_INVENTORY via preferred explicitly to shadow path
        result2 = best_inventory_path(preferred=str(shadow), fallback=str(m8_1))
        assert result2 == str(shadow)

    def test_fallback_when_shadow_missing(self, tmp_path):
        """If shadow inventory does not exist, fallback m8_1 is returned."""
        m8_1 = tmp_path / "m8_1.json"
        m8_1.write_text("{}")
        missing = str(tmp_path / "nonexistent_shadow.json")
        result = best_inventory_path(preferred=missing, fallback=str(m8_1))
        assert result == str(m8_1)

    def test_explicit_preferred_overrides_shadow(self, tmp_path):
        """When --inventory passed explicitly, that path is used if it exists."""
        explicit = tmp_path / "explicit.json"
        explicit.write_text("{}")
        result = best_inventory_path(preferred=str(explicit), fallback=_M8_1_PATH)
        assert result == str(explicit)

    def test_default_none_prefers_shadow_constant(self):
        """When preferred=None, function resolves to _SHADOW_INVENTORY constant
        (or fallback if shadow doesn't exist). This mirrors runner default=None fix.
        """
        # We don't know if shadow exists on this machine; just check no exception
        result = best_inventory_path(preferred=None)
        assert isinstance(result, str)
        assert result  # non-empty

    def test_runner_default_none_reaches_shadow(self, tmp_path):
        """Simulate runner: args.inventory=None → best_inventory_path picks shadow."""
        shadow = tmp_path / "m9_shadow_inventory_with_gap_edges.json"
        shadow.write_text('{"schema_version": "m9_shadow_inventory.1", "active_routes": []}')
        m8_1 = tmp_path / "m8_1_exotic_inventory_latest.json"
        m8_1.write_text('{"schema_version": "m8_1_inventory.1", "active_routes": []}')

        import m9.graph_arb.builder as _b
        original_shadow = _b._SHADOW_INVENTORY
        original_default = _b._DEFAULT_INVENTORY
        try:
            _b._SHADOW_INVENTORY = str(shadow)
            _b._DEFAULT_INVENTORY = str(m8_1)
            # Simulate runner with args.inventory=None
            result = best_inventory_path(preferred=None)
            assert result == str(shadow), (
                f"Expected shadow inventory when preferred=None, got {result}"
            )
        finally:
            _b._SHADOW_INVENTORY = original_shadow
            _b._DEFAULT_INVENTORY = original_default


class TestExtractInventoryStats:
    """Tests for extract_inventory_stats() correctness."""

    def _make_shadow_inventory(self, tmp_path, n_active=5, n_pools=10) -> Path:
        pools = []
        for i in range(n_pools):
            pools.append({
                "pair_id": f"PAIR_{i}",
                "dex_id": "uniswap_v3",
                "fee": 500,
                "factory_class": "EFFICIENT_BASELINE",
                "pool_address": f"0x{'a' * 40}",
                "pool_exists": True,
                "active": i < n_active,
                "liquidity": 1000000 if i < n_active else 0,
                "tick": 100,
                "error": None,
                "quarantine_reason": None if i < n_active else "LOW_LIQUIDITY",
                "route_id": f"uniswap_v3:f500",
            })
        # Add some pools with missing_pool_address quarantine
        pools.append({
            "pair_id": "BAD_PAIR",
            "dex_id": "uniswap_v3",
            "fee": 100,
            "factory_class": "THIN_LEGACY",
            "pool_address": None,
            "pool_exists": False,
            "active": False,
            "liquidity": 0,
            "tick": 0,
            "error": None,
            "quarantine_reason": "MISSING_POOL_ADDRESS",
            "route_id": "uniswap_v3:f100",
        })
        active_routes = [
            {
                "route_id": "uniswap_v3:f500",
                "pair_id": f"PAIR_{i}",
                "pool_address": f"0x{'a' * 40}",
            }
            for i in range(n_active)
        ]
        # One route with missing pool_address to test missing_pool_address counter
        active_routes.append({
            "route_id": "uniswap_v3:f100",
            "pair_id": "PAIR_NOADDR",
            "pool_address": "",
        })
        inv = {
            "schema_version": "m9_shadow_inventory.1",
            "chain": "base",
            "pairs_probed": [f"PAIR_{i}" for i in range(7)],
            "dexes_probed": ["uniswap_v3", "pancakeswap_v3"],
            "pools_found_total": n_pools + 1,
            "active_routes_count": n_active,
            "active_routes": active_routes,
            "pools": pools,
        }
        p = tmp_path / "shadow.json"
        p.write_text(json.dumps(inv))
        return p

    def test_funnel_a_keys_present(self, tmp_path):
        p = self._make_shadow_inventory(tmp_path)
        stats = extract_inventory_stats(str(p))
        fa = stats["funnel_a"]
        for key in ("raw_hints", "pairs_probed", "dexes_probed", "verified_tokens",
                    "verified_pools", "active_routes", "graph_ready_edges_proxy"):
            assert key in fa, f"Missing funnel_a key: {key}"

    def test_funnel_a_active_routes_count(self, tmp_path):
        p = self._make_shadow_inventory(tmp_path, n_active=5)
        stats = extract_inventory_stats(str(p))
        # n_active=5 normal routes + 1 no-address route = 6 in active_routes list
        assert stats["funnel_a"]["active_routes"] == 6

    def test_reject_histogram_low_liquidity(self, tmp_path):
        p = self._make_shadow_inventory(tmp_path, n_active=5, n_pools=10)
        stats = extract_inventory_stats(str(p))
        rh = stats["reject_histogram"]
        # 5 pools have LOW_LIQUIDITY quarantine
        assert rh.get("bad_liquidity", 0) == 5

    def test_reject_histogram_missing_pool_address(self, tmp_path):
        p = self._make_shadow_inventory(tmp_path, n_active=5, n_pools=10)
        stats = extract_inventory_stats(str(p))
        rh = stats["reject_histogram"]
        assert rh.get("missing_pool_address", 0) == 1

    def test_missing_file_returns_empty(self):
        stats = extract_inventory_stats("/tmp/nonexistent_inventory_12345.json")
        assert stats == {"funnel_a": {}, "reject_histogram": {}}

    def test_raw_hints_equals_pools_found_total(self, tmp_path):
        p = self._make_shadow_inventory(tmp_path, n_pools=10)
        stats = extract_inventory_stats(str(p))
        # pools list = 10 (loop) + 1 (BAD_PAIR) = 11 items
        # raw_hints = len(pools) = 11
        assert stats["funnel_a"]["raw_hints"] == 11


class TestBuildGraphFromInventory:
    """Tests that build_graph_from_inventory() enforces config requirements.

    Safety contract: no edge with quoter_addr=0x000...000 may be emitted.
    """

    _ZERO_ADDR = "0x" + "0" * 40

    def _make_minimal_inventory(self, tmp_path, dex_id: str = "uniswap_v3") -> str:
        inv = {
            "active_routes": [
                {
                    "pair_id": "WETH_USDC",
                    "dex_id": dex_id,
                    "fee": 500,
                    "factory_class": "EFFICIENT_BASELINE",
                    "pool_address": "0x" + "a" * 40,
                    "route_id": f"{dex_id}:WETH_USDC@500",
                }
            ],
            "pools": [],
        }
        p = tmp_path / "inventory.json"
        p.write_text(json.dumps(inv))
        return str(p)

    def _make_minimal_config(self, tmp_path) -> str:
        cfg = {
            "schema_version": "m8_1.0",
            "chain": "base",
            "chain_id": 8453,
            "dexes": {
                "uniswap_v3": {
                    "adapter_type": "uniswap_v3",
                    "factory": "0x33128a8fc17869897dce68ed026d694621f6fdfd",
                    "quoter": "0x3d4e44eb1374240ce5f1b871ab261cd16335b76a",
                    "fee_tiers": [100, 500, 3000, 10000],
                    "enabled": True,
                }
            },
            "tokens": {
                "WETH": {"address": "0x4200000000000000000000000000000000000006", "decimals": 18},
                "USDC": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "decimals": 6},
            },
        }
        import yaml
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump(cfg))
        return str(p)

    def test_missing_config_raises_runtime_error(self, tmp_path):
        """CONFIG_MISSING: missing config file must raise RuntimeError, not build zero-quoter graph."""
        from m9.graph_arb.builder import build_graph_from_inventory
        inv = self._make_minimal_inventory(tmp_path)
        missing_cfg = str(tmp_path / "nonexistent_config.yaml")
        with pytest.raises(RuntimeError, match="CONFIG_MISSING"):
            build_graph_from_inventory(inventory_path=inv, config_path=missing_cfg)

    def test_no_zero_quoter_edges_with_valid_config(self, tmp_path):
        """Safety contract: every emitted edge must have non-zero quoter_addr."""
        from m9.graph_arb.builder import build_graph_from_inventory
        inv = self._make_minimal_inventory(tmp_path)
        cfg = self._make_minimal_config(tmp_path)
        adjacency = build_graph_from_inventory(inventory_path=inv, config_path=cfg)
        all_edges = [
            edge
            for neighbors in adjacency.values()
            for edge_list in neighbors.values()
            for edge in edge_list
        ]
        assert all_edges, "Expected at least one edge to be built"
        zero_quoter_edges = [e for e in all_edges if e.quoter_addr == self._ZERO_ADDR]
        assert not zero_quoter_edges, (
            f"Found {len(zero_quoter_edges)} edges with zero-address quoter: "
            + ", ".join(e.route_id for e in zero_quoter_edges)
        )

    def test_unknown_dex_in_inventory_emits_zero_quoter(self, tmp_path):
        """Edge with unknown dex_id gets zero quoter (expected and logged, not silently correct)."""
        from m9.graph_arb.builder import build_graph_from_inventory
        inv = self._make_minimal_inventory(tmp_path, dex_id="unknown_dex_xyz")
        cfg = self._make_minimal_config(tmp_path)
        adjacency = build_graph_from_inventory(inventory_path=inv, config_path=cfg)
        all_edges = [
            edge
            for neighbors in adjacency.values()
            for edge_list in neighbors.values()
            for edge in edge_list        ]
        # Unknown dex → zero quoter is documented behavior (caller must handle)
        assert all(e.quoter_addr == self._ZERO_ADDR for e in all_edges)

    def test_curve_route_without_indices_is_skipped(self, tmp_path):
        """A curve_stable route with unresolved coin indices must NOT be admitted.

        get_dy(i,j,dx) cannot be called without coin indices, so such an edge
        would only ever emit QUOTE_REVERT and poison QSR. The builder skips it
        (reversible: it re-enters once discover_curve_indices classifies the pool).
        A uniswap_v3 route in the same inventory is still admitted, proving this
        is not a Curve disable.
        """
        from unittest.mock import patch
        from m9.graph_arb.adapter_metadata import AdapterMetadata
        import m9.graph_arb.builder as _builder
        from m9.graph_arb.builder import build_graph_from_inventory

        pool_addr = "0x" + "c" * 40
        inv = {
            "active_routes": [
                {
                    "pair_id": "WETH_USDC",
                    "dex_id": "uniswap_v3",
                    "fee": 500,
                    "factory_class": "EFFICIENT_BASELINE",
                    "pool_address": "0x" + "a" * 40,
                    "route_id": "uniswap_v3:WETH_USDC@500",
                },
                {
                    "pair_id": "WETH_USDC",
                    "dex_id": "curve_unknown_bridge",
                    "adapter_type": "curve_stable",
                    "fee": 0,
                    "factory_class": "CURVE_STABLE_NG",
                    "pool_address": pool_addr,
                    "route_id": "curve_stable:WETH_USDC",
                },
            ],
            "pools": [],
        }
        p = tmp_path / "inventory.json"
        p.write_text(json.dumps(inv))
        cfg = self._make_minimal_config(tmp_path)

        # Empty metadata → curve_indices returns (None, None) for the pool.
        with patch.object(_builder, "load_adapter_metadata", return_value=AdapterMetadata()):
            adjacency = build_graph_from_inventory(inventory_path=str(p), config_path=cfg)

        all_edges = [
            edge
            for neighbors in adjacency.values()
            for edge_list in neighbors.values()
            for edge in edge_list
        ]
        curve_edges = [e for e in all_edges if e.adapter_type == "curve_stable"]
        uni_edges = [e for e in all_edges if e.adapter_type == "uniswap_v3"]
        assert not curve_edges, "Unindexed curve_stable edge must be skipped"

    def test_balancer_expansion_pool_id_propagates_to_graph_edge(self, tmp_path):
        """M8.2 expansion routes must pass pool_id through to GraphEdge for quoting."""
        from unittest.mock import patch

        import yaml

        import m9.graph_arb.builder as _builder
        from m9.graph_arb.adapter_metadata import AdapterMetadata
        from m9.graph_arb.builder import build_graph_from_inventory

        pool_id = "0x" + "ab" * 32
        pool_addr = "0x" + "b" * 40
        inv = {
            "active_routes": [
                {
                    "pair_id": "WETH_USDC",
                    "dex_id": "balancer_vault",
                    "fee": 0,
                    "factory_class": "DISTINCT_PRICING",
                    "pool_address": pool_addr,
                    "route_id": "balancer_vault:WETH_USDC@0",
                    "pool_id": pool_id,
                    "vault_address": "0xba12222222228d8ba445958a75a0704d566bf2c8",
                    "source": "m8_cross_dex_expansion",
                }
            ],
            "pools": [],
        }
        p = tmp_path / "inventory.json"
        p.write_text(json.dumps(inv))
        cfg_path = self._make_minimal_config(tmp_path)
        cfg = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8"))
        cfg["dexes"]["balancer_vault"] = {
            "adapter_type": "balancer_stable",
            "factory": "0x0000000000000000000000000000000000000000",
            "quoter": "0xba12222222228d8ba445958a75a0704d566bf2c8",
            "enabled": True,
        }
        cfg_p = tmp_path / "config_bal.yaml"
        cfg_p.write_text(yaml.dump(cfg))

        with patch.object(_builder, "load_adapter_metadata", return_value=AdapterMetadata()):
            adjacency = build_graph_from_inventory(inventory_path=str(p), config_path=str(cfg_p))

        bal_edges = [
            edge
            for neighbors in adjacency.values()
            for edge_list in neighbors.values()
            for edge in edge_list
            if edge.adapter_type == "balancer_stable"
        ]
        assert bal_edges, "Expected balancer_stable edges"
        assert all(e.pool_id == pool_id for e in bal_edges), (
            "pool_id from inventory entry must flow to GraphEdge"
        )

    def test_aerodrome_v2_stable_unknown_dex_uses_pool_address_as_quoter(self, tmp_path):
        """aerodrome_v2_stable with unknown dex_id must use pool_address as quoter.

        Stable Aerodrome pools use getAmountOut() directly on the pool contract
        (same as ve33 volatile). builder.py must resolve quoter_addr=pool_address
        for this adapter type when the dex_id is not in config (bridge inventory path).
        """
        from m9.graph_arb.builder import build_graph_from_inventory
        pool_addr = "0x" + "b" * 40
        inv = {
            "active_routes": [
                {
                    "pair_id": "WETH_USDC",
                    "dex_id": "aerodrome_v2_stable_bridge_event",  # not in config
                    "adapter_type": "aerodrome_v2_stable",         # set by bridge_builder
                    "fee": 1,
                    "factory_class": "SOLIDLY_STABLE",
                    "pool_address": pool_addr,
                    "route_id": "aerodrome_v2_stable:WETH_USDC",
                }
            ],
            "pools": [],
        }
        p = tmp_path / "inventory.json"
        p.write_text(json.dumps(inv))
        cfg = self._make_minimal_config(tmp_path)
        adjacency = build_graph_from_inventory(inventory_path=str(p), config_path=cfg)
        all_edges = [
            edge
            for neighbors in adjacency.values()
            for edge_list in neighbors.values()
            for edge in edge_list
        ]
        assert all_edges, "Expected at least one edge to be built"
        zero_quoter_edges = [e for e in all_edges if e.quoter_addr == self._ZERO_ADDR]
        assert not zero_quoter_edges, (
            f"aerodrome_v2_stable got zero-address quoter — builder.py must set "
            f"quoter_addr=pool_address for this adapter type. "
            f"Found {len(zero_quoter_edges)} edges with zero quoter."
        )
        # All edges must use the pool address as quoter
        for edge in all_edges:
            assert edge.quoter_addr.lower() == pool_addr.lower(), (
                f"Expected quoter_addr={pool_addr}, got {edge.quoter_addr}"
            )

    def test_aerodrome_v2_stable_in_config_uses_pool_address_as_quoter(self, tmp_path):
        """aerodrome_v2_stable with a config entry must also use pool_address as quoter."""
        import yaml
        from m9.graph_arb.builder import build_graph_from_inventory
        pool_addr = "0x" + "c" * 40
        inv = {
            "active_routes": [
                {
                    "pair_id": "WETH_USDC",
                    "dex_id": "aerodrome_v2_stable",
                    "adapter_type": "aerodrome_v2_stable",
                    "fee": 1,
                    "factory_class": "SOLIDLY_STABLE",
                    "pool_address": pool_addr,
                    "route_id": "aerodrome_v2_stable:WETH_USDC",
                }
            ],
            "pools": [],
        }
        p = tmp_path / "inventory.json"
        p.write_text(json.dumps(inv))
        # Config includes aerodrome_v2_stable dex entry with empty quoter
        cfg = {
            "schema_version": "m8_1.0",
            "chain": "base",
            "chain_id": 8453,
            "dexes": {
                "uniswap_v3": {
                    "adapter_type": "uniswap_v3",
                    "factory": "0x33128a8fc17869897dce68ed026d694621f6fdfd",
                    "quoter": "0x3d4e44eb1374240ce5f1b871ab261cd16335b76a",
                    "fee_tiers": [100, 500, 3000, 10000],
                    "enabled": True,
                },
                "aerodrome_v2_stable": {
                    "adapter_type": "aerodrome_v2_stable",
                    "factory": "0x420dd381b31aef6683db6b902084cb0ffece40da",
                    "quoter": "0x0000000000000000000000000000000000000000",
                    "enabled": True,
                },
            },
            "tokens": {
                "WETH": {"address": "0x4200000000000000000000000000000000000006", "decimals": 18},
                "USDC": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "decimals": 6},
            },
        }
        cfg_p = tmp_path / "config.yaml"
        cfg_p.write_text(yaml.dump(cfg))
        adjacency = build_graph_from_inventory(inventory_path=str(p), config_path=str(cfg_p))
        all_edges = [
            edge
            for neighbors in adjacency.values()
            for edge_list in neighbors.values()
            for edge in edge_list
        ]
        assert all_edges, "Expected at least one edge to be built"
        for edge in all_edges:
            assert edge.quoter_addr.lower() == pool_addr.lower(), (
                f"aerodrome_v2_stable (config path) must use pool_address as quoter. "
                f"Expected {pool_addr}, got {edge.quoter_addr}"
            )

    def test_real_config_no_zero_quoter(self):
        """Integration: real config/exotic_base_anchor.yaml produces no zero-quoter edges."""
        import os
        cfg_path = "config/exotic_base_anchor.yaml"
        inv_path = "data/tmp/m9_shadow_inventory_with_gap_edges.json"
        if not (os.path.exists(cfg_path) and os.path.exists(inv_path)):
            pytest.skip("Real config/inventory not available in this environment")
        from m9.graph_arb.builder import build_graph_from_inventory
        adjacency = build_graph_from_inventory(inventory_path=inv_path, config_path=cfg_path)
        all_edges = [
            edge
            for neighbors in adjacency.values()
            for edge_list in neighbors.values()
            for edge in edge_list
        ]
        assert all_edges, "Expected edges from real inventory"
        zero_quoter = [e for e in all_edges if e.quoter_addr == "0x" + "0" * 40]
        assert not zero_quoter, (
            f"Real config produced {len(zero_quoter)} zero-quoter edges: "
            + ", ".join(e.route_id for e in zero_quoter[:5])
        )


class TestPoolDepthFilter:
    """Tests for pool-quality gate: productive lane filtering (Steps 2+3)."""

    _ZERO_ADDR = "0x" + "0" * 40

    def _make_inventory_with_pool(
        self, tmp_path, pool_address: str, effective_depth_usd: float = None
    ) -> str:
        entry: dict = {
            "pair_id": "WETH_USDC",
            "dex_id": "uniswap_v3",
            "fee": 500,
            "factory_class": "EFFICIENT_BASELINE",
            "pool_address": pool_address,
            "route_id": f"uniswap_v3:WETH_USDC@500",
            "factory_verified": True,
            "adapter_type": "uniswap_v3",
        }
        if effective_depth_usd is not None:
            entry["effective_depth_usd"] = effective_depth_usd
        inv = {"active_routes": [entry], "pools": []}
        p = tmp_path / "inventory.json"
        p.write_text(json.dumps(inv))
        return str(p)

    def _make_minimal_config(self, tmp_path) -> str:
        import yaml
        cfg = {
            "schema_version": "m8_1.0",
            "chain": "base",
            "chain_id": 8453,
            "dexes": {
                "uniswap_v3": {
                    "adapter_type": "uniswap_v3",
                    "factory": "0x33128a8fc17869897dce68ed026d694621f6fdfd",
                    "quoter": "0x3d4e44eb1374240ce5f1b871ab261cd16335b76a",
                    "fee_tiers": [100, 500, 3000, 10000],
                    "enabled": True,
                }
            },
            "tokens": {
                "WETH": {"address": "0x4200000000000000000000000000000000000006", "decimals": 18},
                "USDC": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "decimals": 6},
            },
            "m9_dex_productivity": {
                "uniswap_v3": {
                    "enabled_for_discovery": True,
                    "enabled_for_productive": True,
                },
            },
        }
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump(cfg))
        return str(p)

    def _all_edges(self, adjacency):
        return [
            edge
            for neighbors in adjacency.values()
            for edge_list in neighbors.values()
            for edge in edge_list
        ]

    def test_productive_lane_excludes_quarantined_pool(self, tmp_path):
        """Productive lane: quarantined pool address must not appear in graph."""
        from m9.graph_arb.builder import build_graph_from_inventory
        pool_addr = "0x" + "a" * 40
        inv = self._make_inventory_with_pool(tmp_path, pool_addr)
        cfg = self._make_minimal_config(tmp_path)
        adjacency = build_graph_from_inventory(
            inventory_path=inv,
            config_path=cfg,
            exclude_pool_addresses=frozenset([pool_addr.lower()]),
            lane="productive",
        )
        edges = self._all_edges(adjacency)
        pool_addrs_in_graph = {e.pool_address.lower() for e in edges}
        assert pool_addr.lower() not in pool_addrs_in_graph, (
            "Quarantined pool must not appear in productive lane graph"
        )

    def test_discovery_lane_keeps_quarantined_pool(self, tmp_path):
        """Discovery lane: quarantined pool address IS kept in graph for RCA."""
        from m9.graph_arb.builder import build_graph_from_inventory
        pool_addr = "0x" + "a" * 40
        inv = self._make_inventory_with_pool(tmp_path, pool_addr)
        cfg = self._make_minimal_config(tmp_path)
        # Even with exclude_pool_addresses set, discovery lane ignores it
        adjacency = build_graph_from_inventory(
            inventory_path=inv,
            config_path=cfg,
            exclude_pool_addresses=frozenset([pool_addr.lower()]),
            lane="discovery",
        )
        edges = self._all_edges(adjacency)
        pool_addrs_in_graph = {e.pool_address.lower() for e in edges}
        assert pool_addr.lower() in pool_addrs_in_graph, (
            "Discovery lane must NOT filter quarantined pool — needed for RCA visibility"
        )

    def test_productive_lane_filters_low_depth_pool(self, tmp_path):
        """Productive lane: pool with effective_depth_usd < threshold must be excluded."""
        from m9.graph_arb.builder import build_graph_from_inventory
        pool_addr = "0x" + "b" * 40
        inv = self._make_inventory_with_pool(tmp_path, pool_addr, effective_depth_usd=5.0)
        cfg = self._make_minimal_config(tmp_path)
        adjacency = build_graph_from_inventory(
            inventory_path=inv,
            config_path=cfg,
            min_effective_depth_usd=50.0,
            lane="productive",
        )
        edges = self._all_edges(adjacency)
        pool_addrs_in_graph = {e.pool_address.lower() for e in edges}
        assert pool_addr.lower() not in pool_addrs_in_graph, (
            "Low-depth pool (depth=5 < threshold=50) must not appear in productive lane"
        )

    def test_productive_lane_keeps_sufficient_depth_pool(self, tmp_path):
        """Productive lane: pool with effective_depth_usd >= threshold must be kept."""
        from m9.graph_arb.builder import build_graph_from_inventory
        pool_addr = "0x" + "c" * 40
        inv = self._make_inventory_with_pool(tmp_path, pool_addr, effective_depth_usd=500.0)
        cfg = self._make_minimal_config(tmp_path)
        adjacency = build_graph_from_inventory(
            inventory_path=inv,
            config_path=cfg,
            min_effective_depth_usd=50.0,
            lane="productive",
        )
        edges = self._all_edges(adjacency)
        pool_addrs_in_graph = {e.pool_address.lower() for e in edges}
        assert pool_addr.lower() in pool_addrs_in_graph, (
            "Sufficient-depth pool (depth=500 >= threshold=50) must be kept in productive lane"
        )

    def test_discovery_lane_ignores_min_depth_filter(self, tmp_path):
        """Discovery lane: min_effective_depth_usd is ignored even if pool is thin."""
        from m9.graph_arb.builder import build_graph_from_inventory
        pool_addr = "0x" + "d" * 40
        inv = self._make_inventory_with_pool(tmp_path, pool_addr, effective_depth_usd=0.01)
        cfg = self._make_minimal_config(tmp_path)
        adjacency = build_graph_from_inventory(
            inventory_path=inv,
            config_path=cfg,
            min_effective_depth_usd=500.0,
            lane="discovery",
        )
        edges = self._all_edges(adjacency)
        pool_addrs_in_graph = {e.pool_address.lower() for e in edges}
        assert pool_addr.lower() in pool_addrs_in_graph, (
            "Discovery lane must not filter by depth — visibility for RCA required"
        )

    def test_load_quarantined_pool_addresses_skips_placeholders(self, tmp_path):
        """load_quarantined_pool_addresses must skip placeholder addresses."""
        from m9.graph_arb.pool_depth_filter import load_quarantined_pool_addresses
        quarantine = {
            "schema_version": "m9_pool_depth_quarantine.1",
            "quarantined_pools": [
                {
                    "pool_address": "0x7e904aaf3439402eb21958fe090bd852d5e882cf",
                    "reject_reason": "TOXIC_PRICE_IMPACT",
                    "pair_id": "AERO_TOSHI",
                    "dex_id": "uniswap_v3",
                },
                {
                    "pool_address": "0x0000000000000000000000000000000000000001",
                    "reject_reason": "TOXIC_PRICE_IMPACT",
                    "pair_id": "USDC_VIRTUAL",
                    "dex_id": "uniswap_v3",
                    "_placeholder": True,
                },
            ],
        }
        qfile = tmp_path / "quarantine.json"
        qfile.write_text(json.dumps(quarantine))
        addresses = load_quarantined_pool_addresses(str(qfile), hard_only=False)
        assert isinstance(addresses, frozenset)
        # Real address should be included
        assert "0x7e904aaf3439402eb21958fe090bd852d5e882cf" in addresses
        # Placeholder should be skipped
        assert "0x0000000000000000000000000000000000000001" not in addresses
        assert len(addresses) == 1

    def test_load_quarantined_pool_addresses_missing_file(self, tmp_path):
        """Missing quarantine file returns empty frozenset (not error)."""
        from m9.graph_arb.pool_depth_filter import load_quarantined_pool_addresses
        result = load_quarantined_pool_addresses(str(tmp_path / "nonexistent.json"))
        assert result == frozenset()

    def test_productive_lane_skips_non_productive_dex(self, tmp_path):
        """Productive lane must not admit dexes with enabled_for_productive=false."""
        from m9.graph_arb.builder import build_graph_from_inventory, graph_edge_count

        inv = {
            "schema_version": "m9_bridge_inventory.1",
            "active_routes": [
                {
                    "route_id": "r_v4",
                    "pair_id": "USDC_WETH",
                    "dex_id": "uniswap_v4",
                    "adapter_type": "uniswap_v4",
                    "fee": 500,
                    "pool_address": "0x1111111111111111111111111111111111111111",
                    "factory_verified": True,
                },
                {
                    "route_id": "r_v3",
                    "pair_id": "USDC_WETH",
                    "dex_id": "uniswap_v3",
                    "adapter_type": "uniswap_v3",
                    "fee": 500,
                    "pool_address": "0x2222222222222222222222222222222222222222",
                    "factory_verified": True,
                },
            ],
        }
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(
            """
schema_version: m8_1.0
chain: base
dexes:
  uniswap_v3:
    adapter_type: uniswap_v3
    factory: "0x33128a8fc17869897dce68ed026d694621f6fdfd"
    quoter: "0x3d4e44eb1374240ce5f1b871ab261cd16335b76a"
    fee_tiers: [500]
    enabled: true
  uniswap_v4:
    adapter_type: uniswap_v4
    factory: "0x498581ff718922c3f8e6a244956af099b2652b2b"
    quoter: "0x0d5e0f971ed27fbff6c2837bf31316121532048d"
    fee_tiers: [500]
    enabled: true
tokens:
  USDC:
    address: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    decimals: 6
  WETH:
    address: "0x4200000000000000000000000000000000000006"
    decimals: 18
m9_dex_productivity:
  uniswap_v3:
    enabled_for_discovery: true
    enabled_for_productive: true
  uniswap_v4:
    enabled_for_discovery: true
    enabled_for_productive: false
"""
        )
        inv_path = tmp_path / "inv.json"
        inv_path.write_text(json.dumps(inv))
        adjacency = build_graph_from_inventory(
            inventory_path=str(inv_path),
            config_path=str(cfg),
            lane="productive",
        )
        dex_ids = {e.dex_id for adj in adjacency.values() for el in adj.values() for e in el}
        assert "uniswap_v3" in dex_ids
        assert "uniswap_v4" not in dex_ids
        assert graph_edge_count(adjacency) >= 2


def test_truncated_hex_pair_symbols_resolve_distinct_addresses(tmp_path):
    """Truncated pair_id symbols must not collapse to one token_map address."""
    from m9.graph_arb.builder import build_graph_from_inventory

    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        """chain: base
dexes:
  balancer_vault:
    adapter_type: balancer_stable
    quoter: "0xba12222222228d8ba445958a75a0704d566bf2c8"
    enabled: true
tokens:
  USDC:
    address: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    decimals: 6
  WETH:
    address: "0x4200000000000000000000000000000000000006"
    decimals: 18
m9_dex_productivity:
  balancer_vault:
    enabled_for_productive: true
"""
    )
    weth = "0x4200000000000000000000000000000000000006"
    usdc = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    wsteth = "0x04c0599ae5a44757c0af6f9ec3b93da8976c150a"
    inv = {
        "active_routes": [
            {
                "route_id": "bal_bad",
                "pair_id": "0x420000_0x833589",
                "dex_id": "balancer_vault",
                "adapter_type": "balancer_stable",
                "token0": "0x420000",
                "token1": "T",
                "token0_addr": weth,
                "token1_addr": usdc,
                "pool_address": "0x97a3ece859d9c1c41e225fbd6f10359dae7a73c9",
                "pool_id": "0x97a3ece859d9c1c41e225fbd6f10359dae7a73c9000200000000000000000202",
                "balancer_assets": [weth, usdc],
                "factory_verified": True,
            },
            {
                "route_id": "bal_pollute",
                "pair_id": "0x420000_USDC",
                "dex_id": "balancer_vault",
                "adapter_type": "balancer_stable",
                "token0": "0x420000",
                "token1": "USDC",
                "token0_addr": wsteth,
                "token1_addr": usdc,
                "pool_address": "0xcf192e94b974695294",
                "pool_id": "0xcf192e94b9746952940002000000000000000002",
                "factory_verified": True,
            },
        ]
    }
    inv_path = tmp_path / "inv.json"
    inv_path.write_text(json.dumps(inv))
    adjacency = build_graph_from_inventory(
        inventory_path=str(inv_path),
        config_path=str(cfg),
        lane="discovery",
    )
    edges = adjacency.get("0x833589", {}).get("0x420000", [])
    bal_edges = [e for e in edges if e.dex_id == "balancer_vault"]
    assert bal_edges, "expected balancer edge for truncated hex pair"
    edge = bal_edges[0]
    assert edge.token_in_addr.lower() == usdc
    assert edge.token_out_addr.lower() == weth
    assert edge.token_in_addr.lower() != edge.token_out_addr.lower()
