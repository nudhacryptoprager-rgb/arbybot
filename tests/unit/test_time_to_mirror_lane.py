"""Tests for time-to-mirror lane helpers."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from m8.discovery.mirror_quote_smoke import classify_mirror_smoke_exit
from m8.discovery.time_to_mirror_lane import (
    build_narrow_m9_bridge_inventory,
    build_pending_queue_payload,
    build_time_to_mirror_sla,
    score_pending_token,
)


def test_score_pending_token_fresh_delta_ranks_higher():
    fresh = {
        "token_class": "fresh_long_tail",
        "refresh_lane": "fresh_delta_lane",
        "first_seen_ts": 1_700_000_000.0,
        "transitions_1_to_2": 1,
        "second_pool_hint": True,
    }
    stale = {
        "token_class": "known_major",
        "refresh_lane": "audit_lane",
        "first_seen_ts": 1_600_000_000.0,
    }
    now = 1_700_010_000.0
    assert score_pending_token(fresh, now_ts=now) > score_pending_token(stale, now_ts=now)


def test_build_pending_queue_payload_sorted_by_priority():
    watchlist = {
        "tokens": {
            "0xaaa": {
                "first_pool": "p1",
                "second_pool_verified": False,
                "token_class": "fresh_long_tail",
            },
            "0xbbb": {
                "first_pool": "p2",
                "second_pool_verified": False,
                "token_class": "known_major",
            },
        }
    }
    payload = build_pending_queue_payload(watchlist)
    assert payload["schema_version"] == "m8_time_to_mirror_pending_queue_v2"
    assert payload["pending_count"] == 2
    assert payload["tokens"][0]["priority_score"] >= payload["tokens"][1]["priority_score"]


def test_classify_mirror_smoke_exit_codes():
    assert classify_mirror_smoke_exit(quote_ok=1, reason="OK") == (0, "quote_ready")
    assert classify_mirror_smoke_exit(quote_ok=0, reason="OK") == (2, "no_quote_ready")
    assert classify_mirror_smoke_exit(quote_ok=0, reason="RPC_CONFIG_MISSING") == (
        1,
        "infra",
    )


def test_build_time_to_mirror_sla_uses_second_venue_not_first_pool_count(
    monkeypatch, tmp_path: Path
):
    expansion = tmp_path / "expansion.json"
    expansion.write_text(
        json.dumps(
            {
                "summary": {
                    "mirror_quote_ready_tokens": 9,
                    "verified_second_pool_count": 4,
                    "tokens_in": 50,
                },
                "routes_admitted": [],
            }
        ),
        encoding="utf-8",
    )
    scan = tmp_path / "scan.json"
    scan.write_text(
        json.dumps(
            {
                "first_pool_found": 4,
                "second_venue_found": 0,
                "verified_pool_count": 4,
                "verified_second_pool_count": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "m8.discovery.onchain_factory_mirror_discovery.load_onchain_scan_funnel_fields",
        lambda scan_path=None: json.loads(scan.read_text(encoding="utf-8")),
    )
    payload = build_time_to_mirror_sla(expansion_path=expansion)
    assert payload["first_pool_found"] == 4
    assert payload["second_venue_found"] == 0
    assert payload["verified_pool_count"] == 4
    assert payload["verified_second_pool_count"] == 0
    assert payload["mirror_yield_funnel"]["first_pool_found"] == 4
    assert payload["mirror_yield_funnel"]["second_venue_found"] == 0


def test_build_time_to_mirror_sla_preserves_separate_mirror_checkpoints():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        reprobe = root / "reprobe.json"
        verify = root / "verify.json"
        reprobe.write_text(
            json.dumps(
                {
                    "processed_routes": 210,
                    "quote_ok": 42,
                    "quote_fail": 168,
                    "exit_code": 0,
                    "exit_class": "quote_ready",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        verify.write_text(
            json.dumps(
                {
                    "processed_routes": 0,
                    "quote_ok": 0,
                    "quote_fail": 0,
                    "exit_code": 2,
                    "exit_class": "no_quote_ready",
                    "updated_at": "2026-01-01T00:01:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        payload = build_time_to_mirror_sla(
            mirror_reprobe_checkpoint_path=reprobe,
            mirror_verify_checkpoint_path=verify,
        )
        assert payload["mirror_reprobe_exit"] == 0
        assert payload["mirror_verify_exit"] == 2
        assert payload["mirror_reprobe_checkpoint"]["quote_ok"] == 42
        assert payload["mirror_verify_checkpoint"]["exit_class"] == "no_quote_ready"


def test_mirror_readiness_requires_two_quoteable_legs():
    from m8.discovery.time_to_mirror_lane import mirror_readiness_by_focus

    routes = [
        {
            "dex_id": "uniswap_v3",
            "pool_address": "0x1",
            "focus_token_address": "0xabc",
            "focus_token_symbol": "FOO",
            "token0": "FOO",
            "token1": "USDC",
            "token0_addr": "0xabc",
            "token1_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "quote_smoke_status": "QUOTE_OK_MIRROR_SMOKE",
        },
        {
            "dex_id": "uniswap_v4",
            "pool_address": "0x2",
            "focus_token_address": "0xabc",
            "focus_token_symbol": "FOO",
            "token0": "FOO",
            "token1": "USDC",
            "token0_addr": "0xabc",
            "token1_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "quote_smoke_status": "QUOTE_FAIL_ZERO_OUT",
        },
    ]
    ready = mirror_readiness_by_focus(routes)
    assert ready["0xabc"]["mirror_topology_ready"] is True
    assert ready["0xabc"]["mirror_quote_ready"] is False
    assert ready["0xabc"]["quoteable_legs"] == 1


def test_narrow_bridge_excludes_known_major_only_quote_ready():
    import tempfile
    from pathlib import Path

    exotic = "0x" + "f" * 40
    with tempfile.TemporaryDirectory() as tmp:
        expansion = Path(tmp) / "exp.json"
        out = Path(tmp) / "narrow.json"
        expansion.write_text(
            json.dumps(
                {
                    "routes_admitted": [
                        {
                            "dex_id": "uniswap_v3",
                            "focus_token_address": exotic,
                            "focus_token_symbol": "FOO",
                            "token0": "FOO",
                            "token1": "USDC",
                            "token0_addr": exotic,
                            "token1_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                            "token_class": "known_major",
                            "refresh_lane": "audit_lane",
                            "quote_smoke_status": "QUOTE_OK_MIRROR_SMOKE",
                        },
                        {
                            "dex_id": "aerodrome",
                            "focus_token_address": exotic,
                            "focus_token_symbol": "FOO",
                            "token0": "FOO",
                            "token1": "USDC",
                            "token0_addr": exotic,
                            "token1_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                            "token_class": "known_major",
                            "refresh_lane": "audit_lane",
                            "quote_smoke_status": "QUOTE_OK_MIRROR_SMOKE",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        payload, rc = build_narrow_m9_bridge_inventory(
            expansion_path=expansion,
            output_path=out,
        )
        assert rc == 2
        assert payload["quote_ready_token_count"] == 0
        assert payload["fresh_long_tail_quote_ready_tokens"] == 0
        assert payload.get("excluded_known_major_route_count", 0) >= 2
        assert payload.get("target_universe_gate_blocked") is True


def test_build_narrow_m9_bridge_inventory_no_quote_ready_returns_2():
    with tempfile.TemporaryDirectory() as tmp:
        expansion = Path(tmp) / "exp.json"
        out = Path(tmp) / "narrow.json"
        expansion.write_text(
            json.dumps(
                {
                    "routes_admitted": [
                        {
                            "focus_token_address": "0xabc",
                            "focus_token_symbol": "FOO",
                            "token0": "FOO",
                            "token1": "WETH",
                            "quote_smoke_status": "QUOTE_FAIL_REVERT",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        payload, rc = build_narrow_m9_bridge_inventory(
            expansion_path=expansion,
            output_path=out,
        )
        assert rc == 2
        assert payload["quote_ready_token_count"] == 0
        assert out.is_file()


def test_build_time_to_mirror_expand_subset_unions_pending():
    import tempfile
    from pathlib import Path

    from m8.discovery.time_to_mirror_lane import build_time_to_mirror_expand_subset

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fresh = root / "fresh.json"
        fresh.write_text(
            json.dumps({"tokens": ["0x" + "1" * 40, "0x" + "2" * 40]}),
            encoding="utf-8",
        )
        wl = root / "wl.json"
        wl.write_text(
            json.dumps(
                {
                    "tokens": {
                        "0x" + "3" * 40: {
                            "first_pool": "p",
                            "second_pool_verified": False,
                            "token_class": "fresh_long_tail",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        out = root / "subset.json"
        rc = build_time_to_mirror_expand_subset(
            max_tokens=10,
            fresh_subset_path=fresh,
            watchlist_path=wl,
            output_path=out,
        )
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        addrs = {r["token"] for r in doc["tokens"]}
        assert "0x" + "3" * 40 in addrs
        meta = doc["lane_meta"]
        assert meta["pending_quota"] == 5
        assert meta["fresh_quota"] == 5
        assert meta["pending_merged_count"] >= 1


def test_build_second_pool_transition_subset_filters_1_to_2():
    import tempfile
    from pathlib import Path

    from m8.discovery.time_to_mirror_lane import build_second_pool_transition_subset

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wl = root / "wl.json"
        wl.write_text(
            json.dumps(
                {
                    "tokens": {
                        "0x" + "a" * 40: {
                            "transitions_1_to_2": 1,
                            "second_pool_verified": False,
                        },
                        "0x" + "b" * 40: {
                            "transitions_1_to_2": 0,
                            "second_pool_verified": False,
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        out = root / "trans.json"
        rc = build_second_pool_transition_subset(watchlist_path=wl, output_path=out)
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert len(doc["tokens"]) == 1
        assert doc["tokens"][0]["token"] == "0x" + "a" * 40


def test_build_second_pool_transition_subset_empty_writes_zero_tokens():
    import tempfile
    from pathlib import Path

    from m8.discovery.time_to_mirror_lane import build_second_pool_transition_subset

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wl = root / "wl.json"
        wl.write_text(json.dumps({"tokens": {"0x" + "b" * 40: {}}}), encoding="utf-8")
        out = root / "trans.json"
        rc = build_second_pool_transition_subset(
            watchlist_path=wl,
            expansion_path=root / "missing_expansion.json",
            hints_path=root / "missing_hints.json",
            output_path=out,
        )
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["token_count"] == 0
        assert doc.get("lane_meta", {}).get("market_state") == "MARKET_NO_1_TO_2_TRANSITION"


def test_narrow_inventory_tags_quote_ready_same_pair_legs():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        expansion = Path(tmp) / "exp.json"
        out = Path(tmp) / "narrow.json"
        expansion.write_text(
            json.dumps(
                {
                    "routes_admitted": [
                        {
                            "dex_id": "uniswap_v3",
                            "focus_token_address": "0xabc",
                            "focus_token_symbol": "FOO",
                            "token0": "FOO",
                            "token1": "USDC",
                            "token0_addr": "0xabc",
                            "token1_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                            "token_class": "fresh_long_tail",
                            "refresh_lane": "fresh_delta_lane",
                            "quote_smoke_status": "QUOTE_OK_MIRROR_SMOKE",
                        },
                        {
                            "dex_id": "aerodrome",
                            "focus_token_address": "0xabc",
                            "focus_token_symbol": "FOO",
                            "token0": "FOO",
                            "token1": "USDC",
                            "token0_addr": "0xabc",
                            "token1_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                            "token_class": "fresh_long_tail",
                            "refresh_lane": "fresh_delta_lane",
                            "quote_smoke_status": "QUOTE_OK_MIRROR_SMOKE",
                        },
                        {
                            "dex_id": "curve",
                            "focus_token_address": "0xabc",
                            "focus_token_symbol": "FOO",
                            "token0": "FOO",
                            "token1": "WETH",
                            "quote_smoke_status": "QUOTE_FAIL",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        payload, rc = build_narrow_m9_bridge_inventory(
            expansion_path=expansion,
            output_path=out,
        )
        assert rc == 0
        reasons = {r.get("include_reason") for r in payload["active_routes"]}
        assert "quote_ready_same_pair_leg" in reasons
        assert all(
            r.get("include_reason") == "quote_ready_same_pair_leg"
            for r in payload["active_routes"]
        )
        assert payload["quote_ready_token_count"] == 1


def test_transition_subset_topology_fallback(tmp_path: Path):
    from m8.discovery.time_to_mirror_lane import build_second_pool_transition_subset

    watchlist_path = tmp_path / "wl.json"
    expansion_path = tmp_path / "exp.json"
    out_path = tmp_path / "subset.json"
    exotic = "0x" + "d" * 40
    watchlist_path.write_text(
        json.dumps(
            {
                "tokens": {
                    exotic: {
                        "token_class": "fresh_long_tail",
                        "refresh_lane": "fresh_delta_lane",
                        "first_pool": "p1",
                        "second_pool_verified": False,
                        "transitions_1_to_2": 0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    expansion_path.write_text(
        json.dumps(
            {
                "routes_admitted": [
                    {
                        "focus_token_address": exotic,
                        "focus_token_symbol": "FOO",
                        "exotic_address": exotic,
                        "dex_id": "uniswap_v3",
                        "pool_address": "0x" + "1" * 40,
                        "token0": "FOO",
                        "token1": "USDC",
                        "token0_addr": exotic,
                        "token1_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                        "quote_smoke_status": "QUOTE_OK_MIRROR_SMOKE",
                    },
                    {
                        "focus_token_address": exotic,
                        "focus_token_symbol": "FOO",
                        "exotic_address": exotic,
                        "dex_id": "aerodrome",
                        "pool_address": "0x" + "2" * 40,
                        "token0": "FOO",
                        "token1": "USDC",
                        "token0_addr": exotic,
                        "token1_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                        "quote_smoke_status": "QUOTE_FAIL",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    rc = build_second_pool_transition_subset(
        watchlist_path=watchlist_path,
        expansion_path=expansion_path,
        hints_path=tmp_path / "missing_hints.json",
        output_path=out_path,
    )
    assert rc == 0
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(doc.get("tokens") or []) >= 1
    assert doc["tokens"][0]["source"] == "same_pair_mirror_topology_fallback"
    assert doc["lane_meta"]["fallback"] == "same_pair_mirror_topology"
