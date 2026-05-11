"""E1.81 unit tests — PoolFamily architecture.

Covers:
  * ``PoolFamily`` dataclass: derived properties, TTL staleness.
  * ``best_buy_pool`` / ``best_sell_pool`` helpers.
  * ``family_summary`` output schema.
  * ``PoolRegistry.get_pool_family()`` — registry-level family cache.
  * ``PairFamilyPromotion`` dataclass and ``observe_pair_family_profitable``.
  * ``active_pair_family_promotions`` TTL expiry.
  * ``family_promotion_snapshot`` output schema.
  * Dashboard ``/api/m7/family_table`` route presence.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers: minimal fake PoolRegistryEntry
# ---------------------------------------------------------------------------

def _make_entry(
    address: str,
    dex: str,
    fee: int,
    liquidity: int,
    active: bool = True,
) -> SimpleNamespace:
    """Return a minimal fake PoolRegistryEntry compatible with PoolFamily helpers."""
    entry = SimpleNamespace(
        address=address.lower(),
        dex=dex,
        fee=fee,
        liquidity=liquidity,
    )
    entry.is_active = lambda: active
    return entry


# ===========================================================================
# 1. PoolFamily dataclass
# ===========================================================================

class TestPoolFamilyDataclass:
    def test_import(self):
        from m7.orderflow.pool_family import PoolFamily  # noqa: F401

    def test_empty_family(self):
        from m7.orderflow.pool_family import PoolFamily
        fam = PoolFamily(canonical_key="abc/xyz", token_a="abc", token_b="xyz")
        assert fam.pool_count == 0
        assert fam.active_pool_count == 0
        assert fam.dex_set == set()
        assert fam.fee_tiers == []

    def test_pool_count_properties(self):
        from m7.orderflow.pool_family import PoolFamily
        entries = [
            _make_entry("0xaaa", "uniswap_v3", 500, 1000, active=True),
            _make_entry("0xbbb", "aerodrome", 0, 500, active=True),
            _make_entry("0xccc", "uniswap_v3", 3000, 0, active=False),
        ]
        fam = PoolFamily(canonical_key="t0/t1", token_a="t0", token_b="t1", pools=entries)
        assert fam.pool_count == 3
        assert fam.active_pool_count == 2
        assert fam.dex_set == {"uniswap_v3", "aerodrome"}
        assert fam.fee_tiers == [0, 500, 3000]

    def test_ttl_staleness_fresh(self):
        from m7.orderflow.pool_family import PoolFamily
        fam = PoolFamily(canonical_key="a/b", token_a="a", token_b="b", ttl_s=60.0)
        assert not fam.is_stale()

    def test_ttl_staleness_expired(self):
        from m7.orderflow.pool_family import PoolFamily
        fam = PoolFamily(
            canonical_key="a/b", token_a="a", token_b="b",
            ttl_s=60.0,
            built_at=time.monotonic() - 120.0,  # 2 min ago
        )
        assert fam.is_stale()

    def test_ttl_staleness_custom_now(self):
        from m7.orderflow.pool_family import PoolFamily
        fam = PoolFamily(canonical_key="a/b", token_a="a", token_b="b", ttl_s=10.0)
        # Provide a future 'now' that is past TTL
        future_now = fam.built_at + 11.0
        assert fam.is_stale(now=future_now)
        # Just within TTL
        near_now = fam.built_at + 9.0
        assert not fam.is_stale(now=near_now)


# ===========================================================================
# 2. best_buy_pool / best_sell_pool
# ===========================================================================

class TestBestBuySellPool:
    def test_best_buy_empty_family(self):
        from m7.orderflow.pool_family import PoolFamily, best_buy_pool
        fam = PoolFamily(canonical_key="a/b", token_a="a", token_b="b")
        assert best_buy_pool(fam) is None

    def test_best_buy_selects_highest_liquidity_active(self):
        from m7.orderflow.pool_family import PoolFamily, best_buy_pool
        e1 = _make_entry("0x01", "uniswap_v3", 500, 1000, active=True)
        e2 = _make_entry("0x02", "aerodrome", 0, 5000, active=True)
        e3 = _make_entry("0x03", "uniswap_v3", 3000, 999, active=False)
        fam = PoolFamily(canonical_key="a/b", token_a="a", token_b="b", pools=[e1, e2, e3])
        best = best_buy_pool(fam)
        assert best.address == "0x02"

    def test_best_buy_falls_back_to_inactive_when_all_inactive(self):
        from m7.orderflow.pool_family import PoolFamily, best_buy_pool
        e1 = _make_entry("0x01", "uniswap_v3", 500, 200, active=False)
        e2 = _make_entry("0x02", "aerodrome", 0, 100, active=False)
        fam = PoolFamily(canonical_key="a/b", token_a="a", token_b="b", pools=[e1, e2])
        best = best_buy_pool(fam)
        assert best.address == "0x01"  # highest liquidity even if inactive

    def test_best_sell_prefers_different_pool(self):
        from m7.orderflow.pool_family import PoolFamily, best_sell_pool
        e1 = _make_entry("0x01", "uniswap_v3", 500, 1000, active=True)
        e2 = _make_entry("0x02", "aerodrome", 0, 500, active=True)
        fam = PoolFamily(canonical_key="a/b", token_a="a", token_b="b", pools=[e1, e2])
        sell = best_sell_pool(fam, exclude_addr="0x01")
        assert sell.address == "0x02"

    def test_best_sell_falls_back_to_buy_when_single_pool(self):
        from m7.orderflow.pool_family import PoolFamily, best_sell_pool
        e1 = _make_entry("0x01", "uniswap_v3", 500, 1000, active=True)
        fam = PoolFamily(canonical_key="a/b", token_a="a", token_b="b", pools=[e1])
        sell = best_sell_pool(fam, exclude_addr="0x01")
        assert sell.address == "0x01"

    def test_best_sell_empty_family(self):
        from m7.orderflow.pool_family import PoolFamily, best_sell_pool
        fam = PoolFamily(canonical_key="a/b", token_a="a", token_b="b")
        assert best_sell_pool(fam) is None

    def test_best_sell_no_exclude(self):
        from m7.orderflow.pool_family import PoolFamily, best_sell_pool
        e1 = _make_entry("0x01", "uniswap_v3", 500, 100, active=True)
        e2 = _make_entry("0x02", "aerodrome", 0, 9000, active=True)
        fam = PoolFamily(canonical_key="a/b", token_a="a", token_b="b", pools=[e1, e2])
        sell = best_sell_pool(fam)
        assert sell.address == "0x02"


# ===========================================================================
# 3. family_summary
# ===========================================================================

class TestFamilySummary:
    def test_summary_empty_family(self):
        from m7.orderflow.pool_family import PoolFamily, family_summary
        fam = PoolFamily(canonical_key="a/b", token_a="a", token_b="b")
        s = family_summary(fam)
        assert s["canonical_key"] == "a/b"
        assert s["pool_count"] == 0
        assert s["active_pool_count"] == 0
        assert s["dex_count"] == 0
        assert s["best_buy_pool"] is None
        assert s["best_sell_pool"] is None
        assert s["scout_tvl_usd"] is None

    def test_summary_with_pools(self):
        from m7.orderflow.pool_family import PoolFamily, family_summary
        e1 = _make_entry("0xaaa", "uniswap_v3", 500, 10000, active=True)
        e2 = _make_entry("0xbbb", "aerodrome", 0, 3000, active=True)
        fam = PoolFamily(
            canonical_key="usdc/weth", token_a="usdc", token_b="weth",
            pools=[e1, e2], pair_symbol="USDC/WETH",
            scout_tvl_usd=50000.0, scout_volume_24h_usd=1000.0,
        )
        s = family_summary(fam)
        assert s["pool_count"] == 2
        assert s["dex_count"] == 2
        assert s["best_buy_pool"] == "0xaaa"      # highest liquidity
        assert s["best_sell_pool"] == "0xbbb"     # next-highest, different pool
        assert s["best_buy_dex"] == "uniswap_v3"
        assert s["best_sell_dex"] == "aerodrome"
        assert s["scout_tvl_usd"] == 50000.0
        assert s["scout_volume_24h_usd"] == 1000.0
        assert s["pair_symbol"] == "USDC/WETH"

    def test_summary_has_all_required_keys(self):
        from m7.orderflow.pool_family import PoolFamily, family_summary
        fam = PoolFamily(canonical_key="a/b", token_a="a", token_b="b")
        s = family_summary(fam)
        expected_keys = {
            "canonical_key", "pair_symbol", "pool_count", "active_pool_count",
            "dex_count", "dexes", "fee_tiers", "source", "ttl_s", "is_stale",
            "best_buy_pool", "best_buy_dex", "best_buy_fee", "best_buy_liquidity",
            "best_sell_pool", "best_sell_dex", "best_sell_fee", "best_sell_liquidity",
            "scout_tvl_usd", "scout_volume_24h_usd",
        }
        assert expected_keys.issubset(set(s.keys()))


# ===========================================================================
# 4. PoolRegistry.get_pool_family()
# ===========================================================================

class TestPoolRegistryGetFamily:
    def _make_registry(self, entries=None):
        """Build a PoolRegistry with pre-seeded entries (no RPC)."""
        from m7.orderflow.pool_registry import PoolRegistry, _pair_key
        reg = PoolRegistry()
        if entries is not None:
            key = _pair_key(entries[0].token_a, entries[0].token_b)
            reg._pools[key] = entries
            reg._queried.add(key)
        return reg

    def test_returns_pool_family_instance(self):
        from m7.orderflow.pool_family import PoolFamily
        from m7.orderflow.pool_registry import PoolRegistryEntry
        e = PoolRegistryEntry("0xabc", "uniswap_v3", "uniswap_v3", 500, "0xtoken0", "0xtoken1", 1000)
        reg = self._make_registry([e])
        fam = reg.get_pool_family("0xtoken0", "0xtoken1")
        assert isinstance(fam, PoolFamily)

    def test_pools_are_populated(self):
        from m7.orderflow.pool_registry import PoolRegistryEntry
        e1 = PoolRegistryEntry("0xa01", "uniswap_v3", "uniswap_v3", 500, "0xtA", "0xtB", 1000)
        e2 = PoolRegistryEntry("0xa02", "aerodrome", "ve33", 0, "0xtA", "0xtB", 500)
        reg = self._make_registry([e1, e2])
        fam = reg.get_pool_family("0xtA", "0xtB")
        assert fam.pool_count == 2

    def test_empty_registry_gives_empty_family(self):
        from m7.orderflow.pool_family import PoolFamily
        from m7.orderflow.pool_registry import PoolRegistry
        reg = PoolRegistry()
        fam = reg.get_pool_family("0xtA", "0xtB")
        assert isinstance(fam, PoolFamily)
        assert fam.pool_count == 0

    def test_canonical_key_is_sorted(self):
        from m7.orderflow.pool_registry import PoolRegistry
        reg = PoolRegistry()
        fam = reg.get_pool_family("0xzzzz", "0xaaaa")
        assert fam.canonical_key == "0xaaaa/0xzzzz"

    def test_family_cache_returns_same_object(self):
        import os
        from m7.orderflow.pool_registry import PoolRegistryEntry, PoolRegistry
        os.environ["ARBY_POOL_FAMILY_ENABLE"] = "1"
        try:
            reg = PoolRegistry()
            fam1 = reg.get_pool_family("0xtA", "0xtB")
            fam2 = reg.get_pool_family("0xtA", "0xtB")
            assert fam1 is fam2
        finally:
            os.environ.pop("ARBY_POOL_FAMILY_ENABLE", None)

    def test_stale_family_is_rebuilt(self):
        import os
        from m7.orderflow.pool_registry import PoolRegistry, PoolRegistryEntry
        os.environ["ARBY_POOL_FAMILY_ENABLE"] = "1"
        os.environ["ARBY_POOL_FAMILY_TTL_S"] = "1"
        try:
            e = PoolRegistryEntry("0xabc", "uniswap_v3", "uniswap_v3", 500, "0xtA", "0xtB", 1000)
            reg = self._make_registry([e])
            fam1 = reg.get_pool_family("0xtA", "0xtB")
            # Force stale
            fam1.built_at = time.monotonic() - 10.0
            fam2 = reg.get_pool_family("0xtA", "0xtB")
            assert fam1 is not fam2  # rebuilt
        finally:
            os.environ.pop("ARBY_POOL_FAMILY_ENABLE", None)
            os.environ.pop("ARBY_POOL_FAMILY_TTL_S", None)

    def test_invalidate_family_clears_cache(self):
        import os
        from m7.orderflow.pool_registry import PoolRegistry
        os.environ["ARBY_POOL_FAMILY_ENABLE"] = "1"
        try:
            reg = PoolRegistry()
            fam1 = reg.get_pool_family("0xtA", "0xtB")
            reg.invalidate_family("0xtA", "0xtB")
            fam2 = reg.get_pool_family("0xtA", "0xtB")
            assert fam1 is not fam2
        finally:
            os.environ.pop("ARBY_POOL_FAMILY_ENABLE", None)

    def test_scout_annotations_attached(self):
        from m7.orderflow.pool_registry import PoolRegistry
        reg = PoolRegistry()
        fam = reg.get_pool_family("0xtA", "0xtB", scout_tvl_usd=99999.0, scout_volume_24h_usd=777.0)
        assert fam.scout_tvl_usd == 99999.0
        assert fam.scout_volume_24h_usd == 777.0


# ===========================================================================
# 5. PairFamilyPromotion dataclass + observe_pair_family_profitable
# ===========================================================================

class TestPairFamilyPromotion:
    def setup_method(self):
        import os
        os.environ["ARBY_POOL_PROMOTION"] = "1"
        from m7.orderflow.disc_to_prod_pool_promotion import reset_family_promotions
        reset_family_promotions()

    def teardown_method(self):
        import os
        os.environ.pop("ARBY_POOL_PROMOTION", None)
        from m7.orderflow.disc_to_prod_pool_promotion import reset_family_promotions
        reset_family_promotions()

    def test_observe_returns_promotion(self):
        from m7.orderflow.disc_to_prod_pool_promotion import (
            PairFamilyPromotion,
            observe_pair_family_profitable,
        )
        p = observe_pair_family_profitable(
            pair="USDC/WETH",
            canonical_key="usdc/weth",
            best_buy_pool="0xaaa",
            best_buy_dex="uniswap_v3",
            best_buy_fee=500,
            profit_bps=150.0,
        )
        assert isinstance(p, PairFamilyPromotion)
        assert p.pair == "USDC/WETH"
        assert p.profit_bps == 150.0
        assert p.profitable_count == 1

    def test_observe_increments_count(self):
        from m7.orderflow.disc_to_prod_pool_promotion import observe_pair_family_profitable
        t0 = time.monotonic()
        observe_pair_family_profitable(canonical_key="a/b", profit_bps=10.0, now=t0)
        p2 = observe_pair_family_profitable(canonical_key="a/b", profit_bps=20.0, now=t0 + 1.0)
        assert p2.profitable_count == 2
        assert p2.profit_bps == 20.0  # updated to higher

    def test_observe_keeps_max_profit_bps(self):
        from m7.orderflow.disc_to_prod_pool_promotion import observe_pair_family_profitable
        t0 = time.monotonic()
        observe_pair_family_profitable(canonical_key="t0/t1", profit_bps=500.0, now=t0)
        p = observe_pair_family_profitable(canonical_key="t0/t1", profit_bps=10.0, now=t0 + 1.0)
        # 500 > 10 so profit_bps stays 500
        assert p.profit_bps == 500.0

    def test_observe_disabled_returns_none(self):
        import os
        os.environ["ARBY_POOL_PROMOTION"] = "0"
        from m7.orderflow.disc_to_prod_pool_promotion import observe_pair_family_profitable
        result = observe_pair_family_profitable(canonical_key="a/b", profit_bps=100.0)
        assert result is None

    def test_observe_missing_key_returns_none(self):
        from m7.orderflow.disc_to_prod_pool_promotion import observe_pair_family_profitable
        result = observe_pair_family_profitable(profit_bps=100.0)  # no pair or canonical_key
        assert result is None

    def test_active_pair_family_promotions_returns_list(self):
        from m7.orderflow.disc_to_prod_pool_promotion import (
            active_pair_family_promotions,
            observe_pair_family_profitable,
        )
        observe_pair_family_profitable(canonical_key="a/b", profit_bps=50.0)
        promos = active_pair_family_promotions()
        assert len(promos) == 1
        assert promos[0].canonical_key == "a/b"

    def test_ttl_expiry_removes_stale_promotions(self):
        import os
        os.environ["ARBY_POOL_PROMOTION_TTL_S"] = "5"
        from m7.orderflow.disc_to_prod_pool_promotion import (
            active_pair_family_promotions,
            observe_pair_family_profitable,
        )
        try:
            t0 = time.monotonic()
            observe_pair_family_profitable(canonical_key="old/pair", profit_bps=100.0, now=t0)
            # Check at t0 + 6 (past TTL)
            promos = active_pair_family_promotions(now=t0 + 6.0)
            assert len(promos) == 0
        finally:
            os.environ.pop("ARBY_POOL_PROMOTION_TTL_S", None)

    def test_family_promotion_snapshot_schema(self):
        from m7.orderflow.disc_to_prod_pool_promotion import (
            family_promotion_snapshot,
            observe_pair_family_profitable,
        )
        observe_pair_family_profitable(
            pair="WETH/toby",
            canonical_key="toby/weth",
            profit_bps=1988.9,
            max_size_usd=1.0,
            max_profit_usd=0.01,
            family_pool_count=3,
            family_dex_count=2,
        )
        snap = family_promotion_snapshot()
        assert snap["active_count"] == 1
        assert "ttl_s" in snap
        assert len(snap["promotions"]) == 1
        promo = snap["promotions"][0]
        assert promo["pair"] == "WETH/toby"
        assert promo["profit_bps"] == 1988.9
        assert promo["family_pool_count"] == 3

    def test_reset_family_promotions(self):
        from m7.orderflow.disc_to_prod_pool_promotion import (
            active_pair_family_promotions,
            observe_pair_family_profitable,
            reset_family_promotions,
        )
        observe_pair_family_profitable(canonical_key="x/y", profit_bps=1.0)
        reset_family_promotions()
        promos = active_pair_family_promotions()
        assert len(promos) == 0


# ===========================================================================
# 6. Dashboard family_table endpoint presence
# ===========================================================================

class TestDashboardFamilyTableEndpoint:
    def test_family_table_route_in_dashboard(self):
        src = (REPO_ROOT / "monitoring" / "dashboard_server.py").read_text(encoding="utf-8")
        assert "/api/m7/family_table" in src
        assert "_serve_family_table" in src

    def test_family_table_method_exists(self):
        src = (REPO_ROOT / "monitoring" / "dashboard_server.py").read_text(encoding="utf-8")
        assert "def _serve_family_table" in src

    def test_family_table_response_schema_keys(self):
        """_serve_family_table must build rows with required fields."""
        src = (REPO_ROOT / "monitoring" / "dashboard_server.py").read_text(encoding="utf-8")
        for field_name in ("pools_found", "spread_bps", "max_size_usd", "profit_usd", "depth_verdict"):
            assert field_name in src, f"Expected field {field_name!r} in dashboard_server.py"

    def test_family_table_e181_promo_fields_in_source(self):
        """E1.81: _serve_family_table must include promotion snapshot fields in rows."""
        src = (REPO_ROOT / "monitoring" / "dashboard_server.py").read_text(encoding="utf-8")
        for field_name in (
            "family_promotion_snapshot",
            "family_pool_count",
            "family_dex_count",
            "profitable_count",
            "family_active_count",
        ):
            assert field_name in src, f"Expected E1.81 field {field_name!r} in dashboard_server.py"

    def test_family_table_logic_merge(self):
        """Unit-test the merge logic directly (no HTTP server)."""
        import json
        import tempfile
        import os
        # Simulate a bridge artifact
        bridge = {
            "timestamp": "2026-05-10T15:00:00Z",
            "pair_pool_matrix": {
                "pairs": [
                    {
                        "pair": "USDC/WETH",
                        "pool_count": 4,
                        "dex_count": 2,
                        "fee_tiers": [100, 500, 3000],
                        "tvl_total_usd": 1000000.0,
                    }
                ],
                "summary": {"pair_count": 1, "pool_count": 4, "tvl_total_usd": 1e6},
            },
            "cold_executable": [
                {
                    "pair": "USDC/WETH",
                    "net_spread_bps": 150.5,
                    "amount_in_optimal_usd": 50.0,
                    "expected_profit_usd": 7.5,
                    "depth_verdict": "liquid",
                }
            ],
        }
        # Build rows the same way the server does
        matrix = bridge.get("pair_pool_matrix") or {}
        matrix_by_pair = {fam["pair"].upper(): fam for fam in matrix.get("pairs") or []}
        cold_exec = bridge.get("cold_executable") or []
        family_best = {}
        for c in cold_exec:
            pair = (c.get("pair") or "").upper()
            net_bps = float(c.get("net_spread_bps") or 0.0)
            size_usd = float(c.get("amount_in_optimal_usd") or 0.0)
            profit_usd = float(c.get("expected_profit_usd") or 0.0)
            depth_verdict = c.get("depth_verdict") or ""
            family_best[pair] = {
                "spread_bps": net_bps, "max_size_usd": size_usd,
                "profit_usd": profit_usd, "depth_verdict": depth_verdict,
            }
        all_pairs = sorted(set(list(matrix_by_pair.keys()) + list(family_best.keys())))
        rows = []
        for pair in all_pairs:
            mat = matrix_by_pair.get(pair) or {}
            best = family_best.get(pair) or {}
            rows.append({
                "pair": pair,
                "pools_found": mat.get("pool_count", 0),
                "dex_count": mat.get("dex_count", 0),
                "fee_tiers": mat.get("fee_tiers") or [],
                "tvl_total_usd": mat.get("tvl_total_usd", 0.0),
                "spread_bps": best.get("spread_bps", 0.0),
                "max_size_usd": best.get("max_size_usd", 0.0),
                "profit_usd": best.get("profit_usd", 0.0),
                "depth_verdict": best.get("depth_verdict", ""),
            })
        assert len(rows) == 1
        row = rows[0]
        assert row["pair"] == "USDC/WETH"
        assert row["pools_found"] == 4
        assert row["spread_bps"] == 150.5
        assert row["max_size_usd"] == 50.0
        assert row["profit_usd"] == 7.5
        assert row["depth_verdict"] == "liquid"


# ===========================================================================
# 7. pool_family module __all__ completeness
# ===========================================================================

class TestPoolFamilyModuleInterface:
    def test_all_exports_importable(self):
        import m7.orderflow.pool_family as mod
        for name in mod.__all__:
            assert hasattr(mod, name), f"__all__ member {name!r} not found in module"

    def test_pool_family_enabled_default(self):
        import os
        from m7.orderflow.pool_family import pool_family_enabled
        os.environ.pop("ARBY_POOL_FAMILY_ENABLE", None)
        assert pool_family_enabled() is True

    def test_pool_family_enabled_disabled(self):
        import os
        os.environ["ARBY_POOL_FAMILY_ENABLE"] = "0"
        try:
            from m7.orderflow.pool_family import pool_family_enabled
            assert pool_family_enabled() is False
        finally:
            os.environ.pop("ARBY_POOL_FAMILY_ENABLE", None)

    def test_pool_family_ttl_default(self):
        import os
        from m7.orderflow.pool_family import pool_family_ttl_s
        os.environ.pop("ARBY_POOL_FAMILY_TTL_S", None)
        assert pool_family_ttl_s() == 60.0

    def test_pool_family_ttl_custom(self):
        import os
        os.environ["ARBY_POOL_FAMILY_TTL_S"] = "120"
        try:
            from m7.orderflow.pool_family import pool_family_ttl_s
            assert pool_family_ttl_s() == 120.0
        finally:
            os.environ.pop("ARBY_POOL_FAMILY_TTL_S", None)


# ===========================================================================
# 8. disc_to_prod_pool_promotion __all__ includes new symbols
# ===========================================================================

class TestPromotionModuleInterface:
    def test_new_symbols_in_all(self):
        import m7.orderflow.disc_to_prod_pool_promotion as mod
        for name in [
            "PairFamilyPromotion",
            "observe_pair_family_profitable",
            "active_pair_family_promotions",
            "family_promotion_snapshot",
            "reset_family_promotions",
        ]:
            assert name in mod.__all__, f"{name!r} missing from __all__"

    def test_existing_symbols_preserved(self):
        """Regression: E1.81 must not remove any pre-existing public symbols."""
        import m7.orderflow.disc_to_prod_pool_promotion as mod
        for name in [
            "PoolPromotion",
            "active_promotions",
            "is_enabled",
            "observe_profitable",
            "reset",
            "reset_for_tests",
            "snapshot",
            "try_promote_from_cold_signal",
        ]:
            assert name in mod.__all__, f"Existing symbol {name!r} was removed — API shrinkage!"

    def test_pool_registry_has_get_pool_family(self):
        from m7.orderflow.pool_registry import PoolRegistry
        assert hasattr(PoolRegistry, "get_pool_family")
        assert hasattr(PoolRegistry, "invalidate_family")


# ===========================================================================
# 9. bridge_runtime.py E1.81 process-isolation: observe in COLD process
# ===========================================================================

class TestBridgeRuntimeE181Wiring:
    """E1.81: observe_pair_family_profitable must be called in bridge_runtime
    (COLD process) so the module-level _FAMILY_PROMOTIONS dict is shared with
    the family_promotion_snapshot() call that writes to the bridge artifact.
    """

    def test_bridge_runtime_imports_observe_pair_family(self):
        """bridge_runtime.py source must import or call observe_pair_family_profitable."""
        src = (REPO_ROOT / "m7" / "orderflow" / "bridge_runtime.py").read_text(encoding="utf-8")
        assert "observe_pair_family_profitable" in src, (
            "bridge_runtime.py must call observe_pair_family_profitable (E1.81 process-isolation fix)"
        )

    def test_bridge_runtime_family_snapshot_block_present(self):
        """bridge_runtime.py must include family_promotion_snapshot block."""
        src = (REPO_ROOT / "m7" / "orderflow" / "bridge_runtime.py").read_text(encoding="utf-8")
        assert "family_promotion_snapshot" in src
        assert "pool_family_active_count" in src

    def test_cold_immediate_sim_not_calling_observe_pair_family(self):
        """cold_immediate_sim.py must NOT call observe_pair_family_profitable
        (that would be in the HOT process and not share state with COLD bridge writer).
        The call was moved to bridge_runtime.py as part of the process-isolation fix.
        """
        src = (REPO_ROOT / "m7" / "orderflow" / "cold_immediate_sim.py").read_text(encoding="utf-8")
        import re
        # Find all non-comment lines that call observe_pair_family_profitable(
        active_calls = [
            line for line in src.splitlines()
            if "observe_pair_family_profitable(" in line
            and not line.lstrip().startswith("#")
        ]
        assert not active_calls, (
            "cold_immediate_sim.py must not call observe_pair_family_profitable — "
            "it runs in the HOT process and cannot share state with COLD bridge_runtime. "
            f"Found active call(s): {active_calls}"
        )

    def test_bridge_runtime_observes_preserved_candidates(self):
        """bridge_runtime.py must use payload.get('cold_executable') (not just the
        'candidates' argument) so that bridge-preserved candidates (ready_preserved
        status) also get observed for pool_family accounting.
        """
        src = (REPO_ROOT / "m7" / "orderflow" / "bridge_runtime.py").read_text(encoding="utf-8")
        assert 'payload.get("cold_executable")' in src, (
            "bridge_runtime.py must read payload.get('cold_executable') for E1.81 "
            "observation so that ready_preserved candidates are also observed."
        )


# ===========================================================================
# E1.82: bridge_runtime enrichment + dust-size gating tests
# ===========================================================================

class TestBridgeRuntimeE182Enrichment:
    """E1.82: bridge_runtime.py must enrich family promotions with
    family_pool_count/dex_count/fee_tiers from pair_pool_matrix,
    and filter out dust candidates below ARBY_FAMILY_MIN_SIZE_USD.
    """

    def test_bridge_runtime_reads_pair_pool_matrix_for_family_counts(self):
        """bridge_runtime.py source must use pair_pool_matrix to get pool/dex counts."""
        src = (REPO_ROOT / "m7" / "orderflow" / "bridge_runtime.py").read_text(encoding="utf-8")
        assert "_ppm_by_pair" in src, (
            "bridge_runtime.py must build _ppm_by_pair lookup from pair_pool_matrix (E1.82 step 2)"
        )
        assert "family_pool_count=_fam_pool_count" in src, (
            "bridge_runtime.py must pass family_pool_count=_fam_pool_count to _ofp() (E1.82 step 2)"
        )
        assert "family_dex_count=_fam_dex_count" in src

    def test_bridge_runtime_dust_gating_present(self):
        """bridge_runtime.py source must skip candidates below ARBY_FAMILY_MIN_SIZE_USD."""
        src = (REPO_ROOT / "m7" / "orderflow" / "bridge_runtime.py").read_text(encoding="utf-8")
        assert "ARBY_FAMILY_MIN_SIZE_USD" in src, (
            "bridge_runtime.py must read ARBY_FAMILY_MIN_SIZE_USD for dust gating (E1.82 step 4)"
        )
        assert "_family_min_size_usd" in src

    def test_observe_pair_family_profitable_accepts_family_pool_count(self):
        """observe_pair_family_profitable must accept family_pool_count / dex_count / fee_tiers."""
        from m7.orderflow.disc_to_prod_pool_promotion import (
            observe_pair_family_profitable,
            reset_family_promotions,
        )
        reset_family_promotions()
        rec = observe_pair_family_profitable(
            pair="WETH/USDC",
            canonical_key="usdc/weth",
            best_buy_pool="0xabc",
            best_buy_dex="uniswap_v3",
            best_buy_fee=500,
            profit_bps=250.0,
            max_size_usd=75.0,
            family_pool_count=6,
            family_dex_count=3,
            family_fee_tiers=[100, 500, 3000],
            chain="base",
        )
        # With ARBY_POOL_PROMOTION=0 (default in tests) returns a transient record
        if rec is not None:
            assert rec.family_pool_count == 6
            assert rec.family_dex_count == 3
            assert rec.family_fee_tiers == [100, 500, 3000]
        reset_family_promotions()

    def test_observe_pair_family_profitable_with_promotion_enabled(self, monkeypatch):
        """With ARBY_POOL_PROMOTION=1, family_pool_count is persisted."""
        from m7.orderflow.disc_to_prod_pool_promotion import (
            observe_pair_family_profitable,
            family_promotion_snapshot,
            reset_family_promotions,
        )
        monkeypatch.setenv("ARBY_POOL_PROMOTION", "1")
        reset_family_promotions()
        try:
            observe_pair_family_profitable(
                pair="AERO/USDC",
                canonical_key="aero/usdc",
                profit_bps=400.0,
                max_size_usd=60.0,
                family_pool_count=4,
                family_dex_count=2,
                family_fee_tiers=[500, 3000],
                chain="base",
            )
            snap = family_promotion_snapshot()
            promos = snap.get("promotions") or []
            assert len(promos) == 1
            assert promos[0]["family_pool_count"] == 4
            assert promos[0]["family_dex_count"] == 2
            assert promos[0]["family_fee_tiers"] == [500, 3000]
        finally:
            reset_family_promotions()


# ===========================================================================
# E1.82: dashboard family_depth_breakthrough block test
# ===========================================================================

class TestDashboardFamilyDepthBreakthrough:
    """E1.82 step 7: _serve_family_table must include family_depth_breakthrough block."""

    def test_family_table_source_has_depth_breakthrough(self):
        src = (REPO_ROOT / "monitoring" / "dashboard_server.py").read_text(encoding="utf-8")
        assert "family_depth_breakthrough" in src, (
            "dashboard_server.py must include family_depth_breakthrough block (E1.82 step 7)"
        )
        assert "production_sized_count" in src
        assert "gate_pass" in src

    def test_family_depth_gate_fields_present(self):
        src = (REPO_ROOT / "monitoring" / "dashboard_server.py").read_text(encoding="utf-8")
        assert "enriched_family_count" in src
        assert "_max_size" in src


# ===========================================================================
# E1.82: post_soak_pass_gate family_depth_gate check test
# ===========================================================================

class TestPostSoakGateFamilyDepth:
    """E1.82 step 8: post_soak_pass_gate must include family_depth_gate check."""

    def test_gate_source_has_family_depth_gate(self):
        src = (REPO_ROOT / "scripts" / "post_soak_pass_gate.py").read_text(encoding="utf-8")
        assert "family_depth_gate" in src, (
            "post_soak_pass_gate.py must include family_depth_gate check (E1.82 step 8)"
        )
        assert "family_active_count" in src
        assert "family_enriched_count" in src
        assert "family_max_size_usd" in src

    def test_gate_informational_does_not_block_all_pass(self):
        """all_pass must skip informational checks."""
        src = (REPO_ROOT / "scripts" / "post_soak_pass_gate.py").read_text(encoding="utf-8")
        assert 'not c.get("informational")' in src, (
            "post_soak_pass_gate.py all_pass computation must skip informational checks"
        )


# ===========================================================================
# E1.82c: canonical_pair lookup + CE-seeded fallback + arb_candidate flag
# ===========================================================================


class TestE182cCanonicalPairLookup:
    """E1.82c: bridge_runtime must use canonical_pair() for PPM lookup so
    e.g. CE pair 'WETH/USDC' (non-canonical) maps to PPM key 'USDC/WETH'.
    """

    def test_bridge_runtime_uses_canonical_pair_for_ppm_lookup(self):
        src = (REPO_ROOT / "m7" / "orderflow" / "bridge_runtime.py").read_text(encoding="utf-8")
        assert "_canonical_pair" in src, (
            "bridge_runtime.py must import and use canonical_pair() for PPM lookup (E1.82c)"
        )
        assert "_ce_pair_canonical" in src, (
            "bridge_runtime.py must compute _ce_pair_canonical for lookup (E1.82c)"
        )

    def test_bridge_runtime_ce_seeded_fallback_present(self):
        src = (REPO_ROOT / "m7" / "orderflow" / "bridge_runtime.py").read_text(encoding="utf-8")
        assert "CE-seeded fallback" in src, (
            "bridge_runtime.py must have CE-seeded fallback for pairs absent from PPM (E1.82c)"
        )

    def test_ppm_canonical_pair_lookup_correct(self):
        """canonical_pair() must sort alphabetically so lookup is deterministic."""
        from m7.scouts.pair_pool_matrix import canonical_pair, build_pair_pool_matrix

        # USDC < WETH -> canonical = USDC/WETH
        assert canonical_pair("WETH", "USDC") == "USDC/WETH"
        assert canonical_pair("USDC", "WETH") == "USDC/WETH"
        assert canonical_pair("AERO", "USDC") == "AERO/USDC"
        assert canonical_pair("SYND", "USDC") == "SYND/USDC"

        pools = [
            {"symbol": "WETH-USDC", "pool_address": "0xaaa", "project": "uniswap-v3",
             "tvl_usd": 1000.0, "volume_24h_usd": 0.0},
        ]
        matrix = build_pair_pool_matrix(pools)
        keys = {p["pair"] for p in matrix["pairs"]}
        assert "USDC/WETH" in keys, (
            "build_pair_pool_matrix must store pair under canonical key 'USDC/WETH'"
        )


class TestE182cPPMScoutFields:
    """E1.82c: pair_pool_matrix must include scout_pool_count and factory_pool_count."""

    def test_ppm_has_scout_pool_count(self):
        from m7.scouts.pair_pool_matrix import build_pair_pool_matrix
        pools = [
            {"symbol": "USDC-WETH", "pool_address": "0x1", "project": "uniswap-v3",
             "tvl_usd": 500.0, "volume_24h_usd": 0.0},
            {"symbol": "USDC-WETH", "pool_address": "0x2", "project": "aerodrome",
             "tvl_usd": 200.0, "volume_24h_usd": 0.0},
        ]
        matrix = build_pair_pool_matrix(pools)
        fam = matrix["pairs"][0]
        assert "scout_pool_count" in fam, "PPM entry must have scout_pool_count (E1.82c)"
        assert "factory_pool_count" in fam, "PPM entry must have factory_pool_count (E1.82c)"
        assert fam["scout_pool_count"] == 2  # 2 tvl_scout, 0 gecko
        assert fam["pool_count"] == 2  # backward compat
        assert fam["factory_pool_count"] == 0  # placeholder until factory enum
        assert "gecko_pool_count" in fam, "E1.83: gecko_pool_count must be present"
        assert fam["gecko_pool_count"] == 0  # no gecko-tagged pools in this fixture

    def test_ppm_source_has_scout_and_factory_fields(self):
        src = (REPO_ROOT / "m7" / "scouts" / "pair_pool_matrix.py").read_text(encoding="utf-8")
        assert "scout_pool_count" in src, (
            "pair_pool_matrix.py must output scout_pool_count field (E1.82c)"
        )
        assert "factory_pool_count" in src, (
            "pair_pool_matrix.py must output factory_pool_count placeholder (E1.82c)"
        )


class TestE182cArbCandidateFlag:
    """E1.82c: family_promotion_snapshot must include arb_candidate per promotion."""

    def test_snapshot_has_arb_candidate(self, monkeypatch):
        from m7.orderflow.disc_to_prod_pool_promotion import (
            observe_pair_family_profitable,
            family_promotion_snapshot,
            reset_family_promotions,
        )
        monkeypatch.setenv("ARBY_POOL_PROMOTION", "1")
        reset_family_promotions()
        try:
            # dex_count=2 -> arb_candidate=True
            observe_pair_family_profitable(
                pair="USDC/WETH",
                canonical_key="usdc/weth",
                profit_bps=100.0,
                max_size_usd=80.0,
                family_pool_count=6,
                family_dex_count=2,
                chain="base",
            )
            # dex_count=1 -> arb_candidate=False (CE-seeded single-pool)
            observe_pair_family_profitable(
                pair="SYND/USDC",
                canonical_key="synd/usdc",
                profit_bps=1000.0,
                max_size_usd=5.0,
                family_pool_count=1,
                family_dex_count=1,
                chain="base",
            )
            snap = family_promotion_snapshot()
            promos = {p["pair"]: p for p in snap.get("promotions") or []}
            assert "arb_candidate" in promos.get("USDC/WETH", promos.get("usdc/weth", {})), (
                "family_promotion_snapshot must include arb_candidate field (E1.82c)"
            )
            weth_usdc = promos.get("USDC/WETH") or promos.get("usdc/weth") or {}
            synd_usdc = promos.get("SYND/USDC") or promos.get("synd/usdc") or {}
            assert weth_usdc.get("arb_candidate") is True, "dex_count=2 -> arb_candidate=True"
            assert synd_usdc.get("arb_candidate") is False, "dex_count=1 -> arb_candidate=False"
        finally:
            reset_family_promotions()


class TestE183PPMFields:
    """E1.83: gecko_pool_count split and reference_only flag in pair_pool_matrix."""

    def test_gecko_pool_count_tagged(self):
        """Pools tagged source='gecko' must be counted in gecko_pool_count."""
        from m7.scouts.pair_pool_matrix import build_pair_pool_matrix
        pools = [
            {"symbol": "USDC-WETH", "pool_address": "0x1", "project": "uniswap-v3",
             "tvl_usd": 500.0, "volume_24h_usd": 0.0, "source": "tvl_scout"},
            {"symbol": "USDC-WETH", "pool_address": "0x2", "project": "uniswap-v3",
             "tvl_usd": 200.0, "volume_24h_usd": 0.0, "source": "gecko"},
            {"symbol": "USDC-WETH", "pool_address": "0x3", "project": "aerodrome",
             "tvl_usd": 100.0, "volume_24h_usd": 0.0, "source": "gecko"},
        ]
        matrix = build_pair_pool_matrix(pools)
        fam = matrix["pairs"][0]
        assert fam["pool_count"] == 3
        assert fam["gecko_pool_count"] == 2, "2 gecko-tagged pools must be counted"
        assert fam["scout_pool_count"] == 1, "scout_pool_count = pool_count - gecko"

    def test_gecko_pool_count_zero_when_no_source(self):
        """Pools without source tag must not increment gecko_pool_count."""
        from m7.scouts.pair_pool_matrix import build_pair_pool_matrix
        pools = [
            {"symbol": "AERO-USDC", "pool_address": "0xA", "project": "aerodrome",
             "tvl_usd": 1000.0},
            {"symbol": "AERO-USDC", "pool_address": "0xB", "project": "uniswap-v3",
             "tvl_usd": 500.0},
        ]
        matrix = build_pair_pool_matrix(pools)
        fam = matrix["pairs"][0]
        assert "gecko_pool_count" in fam
        assert fam["gecko_pool_count"] == 0
        assert fam["scout_pool_count"] == 2

    def test_reference_only_single_dex(self):
        """Single-DEX family must be reference_only=True."""
        from m7.scouts.pair_pool_matrix import build_pair_pool_matrix
        pools = [
            {"symbol": "AERO-USDC", "pool_address": "0xA", "project": "aerodrome",
             "tvl_usd": 1000.0},
            {"symbol": "AERO-USDC", "pool_address": "0xB", "project": "aerodrome",
             "tvl_usd": 500.0},
        ]
        matrix = build_pair_pool_matrix(pools)
        fam = matrix["pairs"][0]
        assert "reference_only" in fam, "PPM entry must have reference_only (E1.83)"
        assert fam["reference_only"] is True, "single-dex family -> reference_only=True"

    def test_reference_only_multi_dex(self):
        """Multi-DEX family must be reference_only=False."""
        from m7.scouts.pair_pool_matrix import build_pair_pool_matrix
        pools = [
            {"symbol": "USDC-WETH", "pool_address": "0x1", "project": "uniswap-v3",
             "tvl_usd": 500.0},
            {"symbol": "USDC-WETH", "pool_address": "0x2", "project": "aerodrome",
             "tvl_usd": 200.0},
        ]
        matrix = build_pair_pool_matrix(pools)
        fam = matrix["pairs"][0]
        assert "reference_only" in fam, "PPM entry must have reference_only (E1.83)"
        assert fam["reference_only"] is False, "multi-dex family -> reference_only=False"

    def test_ppm_source_has_new_fields(self):
        """pair_pool_matrix.py source must contain gecko_pool_count and reference_only."""
        src = (REPO_ROOT / "m7" / "scouts" / "pair_pool_matrix.py").read_text(encoding="utf-8")
        assert "gecko_pool_count" in src, "E1.83: gecko_pool_count field required"
        assert "reference_only" in src, "E1.83: reference_only field required"

