"""Tests for strategy expansion lanes (event stream, launchpad, anchors, batch DS)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from m8.discovery.dex_coverage_gate import validate_dex_package
from m8.discovery.dexscreener_hints import DEXSCREENER_BATCH_MAX, fetch_token_hints_batch
from m8.discovery.event_stream_lane import parse_alchemy_webhook_events
from m8.discovery.launchpad_classifier import classify_launchpad
from m8.discovery.mirror_anchors import ALL_MIRROR_ANCHOR_SYMS, is_approved_anchor_symbol
from m8.discovery.mirror_quote_smoke import is_cross_anchor_mirror_route
from m8.discovery.patient_lane_diagnostics import build_patient_lane_diagnostics
from m8.discovery.radar_fast_pipeline import sources_for_lane
from m8.discovery.time_to_mirror_lane import build_pending_queue_payload


def test_virtual_is_launchpad_anchor():
    assert "VIRTUAL" in ALL_MIRROR_ANCHOR_SYMS
    assert is_approved_anchor_symbol("VIRTUAL")


def test_cross_anchor_mirror_route_accepts_virtual():
    route = {
        "focus_token_symbol": "AGENT",
        "token0": "AGENT",
        "token1": "VIRTUAL",
    }
    assert is_cross_anchor_mirror_route(route) is True


def test_classify_launchpad_virtuals_hint():
    profile = classify_launchpad(
        "0xabc",
        entry={"token_class": "fresh_long_tail"},
        hints=[{"token0": "FOO", "token1": "VIRTUAL"}],
    )
    assert profile["launchpad"] == "virtuals"


def test_pending_queue_buckets():
    watchlist = {
        "tokens": {
            "0xaaa": {
                "first_pool": "p1",
                "second_pool_verified": False,
                "token_class": "fresh_long_tail",
            },
            "0xbbb": {
                "first_pool": "p2",
                "second_pool_hint": True,
                "token_class": "fresh_long_tail",
            },
        }
    }
    payload = build_pending_queue_payload(watchlist)
    queues = payload["queues"]
    assert queues["second_venue_seen"]["count"] == 1
    assert queues["single_venue_watch"]["count"] + queues["patient_candidate"]["count"] == 1


def test_sources_for_lane_hot_vs_warm():
    assert sources_for_lane("hot_delta") == ("dexscreener",)
    assert "geckoterminal" in sources_for_lane("warm_recall")
    assert "coingecko_onchain" in sources_for_lane("audit_full")


def test_parse_alchemy_webhook_events():
    payload = {
        "event": {
            "data": {
                "block": {
                    "logs": [
                        {
                            "topics": ["0xtopic"],
                            "address": "0xFactory",
                            "blockNumber": 123,
                        }
                    ]
                }
            }
        }
    }
    events = parse_alchemy_webhook_events(payload)
    assert len(events) == 1
    assert events[0]["source"] == "alchemy_webhook"


def test_dex_coverage_gate_blocks_missing_factory():
    verdict = validate_dex_package("fake_dex", {"dexes": {"fake_dex": {"enabled": True}}})
    assert verdict["package_complete"] is False
    assert "factory" in verdict["missing"]


def test_patient_lane_diagnostics_single_venue():
    watchlist = {
        "tokens": {
            "0xaaa": {
                "first_pool": "p1",
                "first_dex": "uniswap_v3",
                "token_class": "fresh_long_tail",
            }
        }
    }
    payload = build_patient_lane_diagnostics(watchlist)
    assert payload["single_venue_count"] == 1
    assert payload["tokens"][0]["profit_claim_allowed"] is False


def test_fetch_token_hints_batch_uses_batch_endpoint():
    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        return []

    with patch("m8.discovery.dexscreener_hints._get_json", side_effect=fake_get):
        with patch("m8.discovery.dexscreener_hints.get_cached_pairs", return_value=None):
            with patch("m8.discovery.dexscreener_hints.set_cached_pairs"):
                addrs = [f"0x{'a' * 40}", f"0x{'b' * 40}"]
                fetch_token_hints_batch(addrs, use_cache=True)
    assert any("/tokens/v1/base/" in u for u in calls)


def test_dexscreener_batch_max_is_30():
    assert DEXSCREENER_BATCH_MAX == 30
