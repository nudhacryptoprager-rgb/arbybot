"""Unit tests for M8.2 pending-pair registry (single→multi venue promotion).

Covers:
  - TestSplitTokenAnchor: anchor/exotic leg resolution
  - TestUpdateRegistry: accumulation, dedup, TTL pruning
  - TestMultiVenuePromotion: promotable_events / multi_venue_tokens
  - TestRegistryIO: load/save round-trip + corrupt/missing fallback
  - TestBridgePromotionIntegration: cross-run promotion via build_bridge_inventory
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from m8.discovery import pending_pair_registry as ppr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
_MEME = "0x1111111111111111111111111111111111111111"
_MEME2 = "0x2222222222222222222222222222222222222222"


def _event(
    exotic_sym: str,
    exotic_addr: str,
    dex: str,
    pool: str,
    anchor_sym: str = "USDC",
    anchor_addr: str = _USDC,
) -> Dict[str, Any]:
    return {
        "event_id": f"base:{pool}:0xhash:1",
        "chain": "base",
        "dex": dex,
        "factory": "0xfactory",
        "pool": pool,
        "token0": anchor_addr,
        "token1": exotic_addr,
        "token0_symbol": anchor_sym,
        "token1_symbol": exotic_sym,
        "fee": 3000,
        "tick_spacing": 60,
        "stable": False,
        "hooks": None,
        "block_number": 100,
    }


def _quoteable_all(_dex: str) -> bool:
    return True


# ---------------------------------------------------------------------------
# TestSplitTokenAnchor
# ---------------------------------------------------------------------------
class TestSplitTokenAnchor:
    def test_anchor_is_token0(self):
        ev = _event("MEME", _MEME, "uniswap_v3", "0xpool1")
        res = ppr.split_token_anchor(ev)
        assert res == (_MEME.lower(), "MEME", "USDC")

    def test_anchor_is_token1(self):
        ev = {
            "token0_symbol": "MEME",
            "token1_symbol": "WETH",
            "token0": _MEME,
            "token1": "0xweth",
        }
        res = ppr.split_token_anchor(ev)
        assert res == (_MEME.lower(), "MEME", "WETH")

    def test_no_anchor_returns_none(self):
        ev = {
            "token0_symbol": "MEME",
            "token1_symbol": "GARBAGE",
            "token0": _MEME,
            "token1": _MEME2,
        }
        assert ppr.split_token_anchor(ev) is None

    def test_both_anchor_returns_none(self):
        ev = {
            "token0_symbol": "USDC",
            "token1_symbol": "WETH",
            "token0": _USDC,
            "token1": "0xweth",
        }
        assert ppr.split_token_anchor(ev) is None

    def test_missing_exotic_addr_returns_none(self):
        ev = {
            "token0_symbol": "USDC",
            "token1_symbol": "MEME",
            "token0": _USDC,
            "token1": "",
        }
        assert ppr.split_token_anchor(ev) is None


# ---------------------------------------------------------------------------
# TestUpdateRegistry
# ---------------------------------------------------------------------------
class TestUpdateRegistry:
    def test_single_event_creates_token_and_venue(self):
        reg = ppr._empty_registry()
        stats = ppr.update_registry(
            reg, [_event("MEME", _MEME, "uniswap_v3", "0xpool1")], now_ts=1000.0
        )
        assert stats["tokens_tracked"] == 1
        assert stats["venues_tracked"] == 1
        assert stats["new_tokens"] == 1
        assert stats["new_venues"] == 1
        assert stats["multi_venue_tokens"] == 0
        tok = reg["tokens"][_MEME.lower()]
        assert tok["symbol"] == "MEME"
        assert "USDC" in tok["anchors"]

    def test_second_venue_same_token_marks_multi(self):
        reg = ppr._empty_registry()
        ppr.update_registry(
            reg, [_event("MEME", _MEME, "uniswap_v3", "0xpool1")], now_ts=1000.0
        )
        # Second run: a DIFFERENT venue for the same token (e.g. 90 min later)
        stats = ppr.update_registry(
            reg, [_event("MEME", _MEME, "aerodrome", "0xpool2")], now_ts=6000.0
        )
        assert stats["multi_venue_tokens"] == 1
        tok = reg["tokens"][_MEME.lower()]
        assert len(tok["venues"]) == 2

    def test_same_venue_repeated_does_not_duplicate(self):
        reg = ppr._empty_registry()
        ppr.update_registry(
            reg, [_event("MEME", _MEME, "uniswap_v3", "0xpool1")], now_ts=1000.0
        )
        stats = ppr.update_registry(
            reg, [_event("MEME", _MEME, "uniswap_v3", "0xpool1")], now_ts=2000.0
        )
        assert stats["venues_tracked"] == 1
        assert stats["new_venues"] == 0
        # last_seen_ts advanced
        venue = next(iter(reg["tokens"][_MEME.lower()]["venues"].values()))
        assert venue["last_seen_ts"] == 2000.0

    def test_ttl_prunes_stale_venue(self):
        reg = ppr._empty_registry()
        ppr.update_registry(
            reg, [_event("MEME", _MEME, "uniswap_v3", "0xpool1")],
            now_ts=1000.0, ttl_seconds=100.0,
        )
        # Far in the future: original venue is now older than TTL
        stats = ppr.update_registry(
            reg, [_event("MEME", _MEME, "aerodrome", "0xpool2")],
            now_ts=5000.0, ttl_seconds=100.0,
        )
        assert stats["pruned_venues"] == 1
        # Only the fresh aerodrome venue remains → single venue again
        assert stats["multi_venue_tokens"] == 0
        assert stats["venues_tracked"] == 1

    def test_ttl_prunes_token_with_no_venues(self):
        reg = ppr._empty_registry()
        ppr.update_registry(
            reg, [_event("MEME", _MEME, "uniswap_v3", "0xpool1")],
            now_ts=1000.0, ttl_seconds=100.0,
        )
        stats = ppr.update_registry(
            reg, [], now_ts=5000.0, ttl_seconds=100.0
        )
        assert stats["pruned_tokens"] == 1
        assert stats["tokens_tracked"] == 0

    def test_non_anchor_event_ignored(self):
        reg = ppr._empty_registry()
        ev = {
            "token0_symbol": "MEME",
            "token1_symbol": "GARBAGE",
            "token0": _MEME,
            "token1": _MEME2,
            "dex": "uniswap_v3",
            "pool": "0xpool1",
        }
        stats = ppr.update_registry(reg, [ev], now_ts=1000.0)
        assert stats["tokens_tracked"] == 0


# ---------------------------------------------------------------------------
# TestMultiVenuePromotion
# ---------------------------------------------------------------------------
class TestMultiVenuePromotion:
    def _two_venue_registry(self) -> Dict[str, Any]:
        reg = ppr._empty_registry()
        ppr.update_registry(
            reg, [_event("MEME", _MEME, "uniswap_v3", "0xpool1")], now_ts=1000.0
        )
        ppr.update_registry(
            reg, [_event("MEME", _MEME, "aerodrome", "0xpool2")], now_ts=2000.0
        )
        return reg

    def test_multi_venue_tokens_detected(self):
        reg = self._two_venue_registry()
        out = ppr.multi_venue_tokens(reg, _quoteable_all)
        assert len(out) == 1
        assert out[0][0] == _MEME.lower()

    def test_promotable_events_one_per_venue(self):
        reg = self._two_venue_registry()
        events = ppr.promotable_events(reg, _quoteable_all)
        assert len(events) == 2
        pools = {e["pool"] for e in events}
        assert pools == {"0xpool1", "0xpool2"}
        assert all(e["_registry_promoted"] for e in events)

    def test_single_venue_not_promotable(self):
        reg = ppr._empty_registry()
        ppr.update_registry(
            reg, [_event("MEME", _MEME, "uniswap_v3", "0xpool1")], now_ts=1000.0
        )
        assert ppr.promotable_events(reg, _quoteable_all) == []

    def test_non_quoteable_second_venue_blocks_promotion(self):
        reg = self._two_venue_registry()

        def _only_v3(dex: str) -> bool:
            return dex == "uniswap_v3"

        # Only one quoteable venue → not multi-venue
        assert ppr.multi_venue_tokens(reg, _only_v3) == []
        assert ppr.promotable_events(reg, _only_v3) == []


# ---------------------------------------------------------------------------
# TestRegistryIO
# ---------------------------------------------------------------------------
class TestRegistryIO:
    def test_save_load_round_trip(self, tmp_path):
        reg = ppr._empty_registry()
        ppr.update_registry(
            reg, [_event("MEME", _MEME, "uniswap_v3", "0xpool1")], now_ts=1000.0
        )
        path = str(tmp_path / "reg.json")
        ppr.save_registry(reg, path)
        loaded = ppr.load_registry(path)
        assert loaded["schema_version"] == ppr.SCHEMA_VERSION
        assert _MEME.lower() in loaded["tokens"]

    def test_load_missing_returns_empty(self, tmp_path):
        loaded = ppr.load_registry(str(tmp_path / "nope.json"))
        assert loaded["tokens"] == {}

    def test_load_corrupt_returns_empty(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{ not json", encoding="utf-8")
        loaded = ppr.load_registry(str(path))
        assert loaded["tokens"] == {}


# ---------------------------------------------------------------------------
# TestBridgePromotionIntegration
# ---------------------------------------------------------------------------
class TestBridgePromotionIntegration:
    """Cross-run promotion through build_bridge_inventory with a shared registry."""

    def _sniper(self, events: list) -> Dict[str, Any]:
        from datetime import datetime, timezone
        return {
            "schema_family": "m8_sniper",
            "schema_revision": "1",
            "generated_at_utc": datetime.now(tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "status": "ACTIVE",
            "metrics": {},
            "recent_events": events,
        }

    def _base(self) -> Dict[str, Any]:
        return {
            "schema_version": "m9_verified_inventory.1",
            "generated_at_utc": "2026-05-24T10:00:00",
            "active_routes": [],
            "quarantined_routes": [],
            "summary": {"active_count": 0, "quarantined_count": 0},
        }

    def _write(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_cross_run_promotion(self, tmp_path):
        """Venue A in run 1, venue B in run 2 → promoted in run 2 even though
        neither window alone has 2 venues."""
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        registry = str(tmp_path / "registry.json")
        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge.json"
        self._write(anchor, {"near_miss_routes": [], "active_routes": []})
        self._write(base, self._base())

        # Run 1: only uniswap_v3 venue visible
        sniper1 = tmp_path / "sniper1.json"
        self._write(sniper1, self._sniper([
            _event("MEME", _MEME, "uniswap_v3", "0xpoolA"),
        ]))
        m1 = build_bridge_inventory(
            sniper_path=str(sniper1), anchor_path=str(anchor),
            base_inv_path=str(base), output_path=str(out),
            curve_discovery_path=str(tmp_path / "no_curve.json"),
            registry_path=registry,
        )
        assert m1["registry_promoted_routes"] == 0

        # Run 2: only aerodrome venue visible in the window — but registry
        # remembers uniswap_v3 from run 1 → token becomes multi-venue.
        sniper2 = tmp_path / "sniper2.json"
        self._write(sniper2, self._sniper([
            _event("MEME", _MEME, "aerodrome", "0xpoolB"),
        ]))
        m2 = build_bridge_inventory(
            sniper_path=str(sniper2), anchor_path=str(anchor),
            base_inv_path=str(base), output_path=str(out),
            curve_discovery_path=str(tmp_path / "no_curve.json"),
            registry_path=registry,
        )
        assert m2["registry_enabled"] is True
        assert m2["registry_multi_venue_tokens"] == 1
        # Both venues promoted as routes (poolA + poolB)
        assert m2["registry_promoted_routes"] == 2
        result = json.loads(out.read_text(encoding="utf-8"))
        promoted = [r for r in result["active_routes"] if r.get("promoted_from_registry")]
        assert len(promoted) == 2
        assert all(r["promotion_reason"] == ppr.PROMOTION_REASON for r in promoted)

    def test_registry_disabled_by_default(self, tmp_path):
        from m9.graph_arb.bridge_builder import build_bridge_inventory

        anchor = tmp_path / "anchor.json"
        base = tmp_path / "base.json"
        out = tmp_path / "bridge.json"
        sniper = tmp_path / "sniper.json"
        self._write(anchor, {"near_miss_routes": [], "active_routes": []})
        self._write(base, self._base())
        self._write(sniper, self._sniper([
            _event("MEME", _MEME, "uniswap_v3", "0xpoolA"),
        ]))
        m = build_bridge_inventory(
            sniper_path=str(sniper), anchor_path=str(anchor),
            base_inv_path=str(base), output_path=str(out),
            curve_discovery_path=str(tmp_path / "no_curve.json"),
        )
        assert m["registry_enabled"] is False
        assert m["registry_promoted_routes"] == 0
