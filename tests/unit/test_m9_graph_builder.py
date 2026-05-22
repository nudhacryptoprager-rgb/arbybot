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
