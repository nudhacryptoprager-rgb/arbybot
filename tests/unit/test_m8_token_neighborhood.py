"""Token-neighborhood expansion (3-leg subgraph) tests."""
from __future__ import annotations

from m8.discovery.cross_dex_expand import expand_cross_dex
from m8.discovery.hot_path_mirror import (
    candidate_tokens_from_event,
    resolve_best_neighborhood_for_event,
)

_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
_T = "0xtttt000000000000000000000000000000000001"
_AERO = "0xaeee000000000000000000000000000000000001"


def _neighborhood_cfg() -> dict:
    return {
        "chain": "base",
        "tokens": {
            "USDC": {"address": _USDC},
            "AERO": {"address": _AERO},
            "LONG": {"address": _T},
        },
        "dexes": {
            "uniswap_v3": {"adapter_type": "uniswap_v3", "enabled": True},
            "aerodrome": {"adapter_type": "ve33", "enabled": True},
        },
        "m9_dex_productivity": {
            "uniswap_v3": {
                "enabled_for_discovery": True,
                "enabled_for_productive": True,
            },
            "aerodrome": {
                "enabled_for_discovery": True,
                "enabled_for_productive": True,
            },
        },
    }


def _three_leg_registry() -> dict:
    return {
        "tokens": {
            _T: {
                "symbol": "LONG",
                "anchors": ["USDC"],
                "venues": {
                    "u::p1": {
                        "dex": "uniswap_v3",
                        "pool": "0xpool1",
                        "token0_symbol": "LONG",
                        "token1_symbol": "USDC",
                        "token0": _T,
                        "token1": _USDC,
                    },
                    "a::p2": {
                        "dex": "aerodrome",
                        "pool": "0xpool2",
                        "token0_symbol": "LONG",
                        "token1_symbol": "AERO",
                        "token0": _T,
                        "token1": _AERO,
                    },
                },
            },
            _AERO: {
                "symbol": "AERO",
                "anchors": ["USDC"],
                "venues": {
                    "a::p3": {
                        "dex": "aerodrome",
                        "pool": "0xpool3",
                        "token0_symbol": "AERO",
                        "token1_symbol": "USDC",
                        "token0": _AERO,
                        "token1": _USDC,
                    },
                    "u::p4": {
                        "dex": "uniswap_v3",
                        "pool": "0xpool4",
                        "token0_symbol": "AERO",
                        "token1_symbol": "USDC",
                        "token0": _AERO,
                        "token1": _USDC,
                    },
                },
            },
        }
    }


def test_token_neighborhood_admits_3leg_subgraph():
    art = expand_cross_dex(
        chain="base",
        config=_neighborhood_cfg(),
        registry=_three_leg_registry(),
        anchor_artifact=None,
        dry_run=True,
        exotic_address_filter=_T,
        expansion_mode="token_neighborhood",
    )
    summary = art["summary"]
    assert summary["expansion_mode"] == "token_neighborhood"
    assert summary["token_seen_on_dexes"] >= 2
    assert summary["connector_token_count"] >= 1
    assert summary["routes_admitted_count"] >= 4
    assert summary["unique_tokens"] >= 3
    assert summary["subgraph_ready"] is True
    assert len(art["same_pair_routes"]) >= 1
    assert len(art["token_presence_routes"]) >= 1
    assert len(art["connector_routes"]) >= 1
    assert "AERO" in art["connector_tokens"]
    kinds = {r.get("expansion_route_kind") for r in art["routes_admitted"]}
    assert "connector_graph" in kinds
    assert "TOKEN_NOT_SEEN_ELSEWHERE" not in art.get("reject_reason_histogram", {})


def test_pair_anchor_mode_unchanged_without_neighborhood_flag():
    registry = {
        "tokens": {
            _T: {
                "symbol": "LONG",
                "anchors": ["USDC"],
                "venues": {
                    "u::p1": {
                        "dex": "uniswap_v3",
                        "pool": "0xpool1",
                        "token0_symbol": "LONG",
                        "token1_symbol": "USDC",
                        "token0": _T,
                        "token1": _USDC,
                    },
                },
            }
        }
    }
    art = expand_cross_dex(
        chain="base",
        config=_neighborhood_cfg(),
        registry=registry,
        anchor_artifact=None,
        dry_run=True,
    )
    assert art["summary"]["expansion_mode"] == "pair_anchor"


def test_non_anchor_event_t_aero_resolves_via_neighborhood():
    """T-AERO pool event (no USDC/WETH) should still build connector subgraph."""
    registry = _three_leg_registry()
    cfg = _neighborhood_cfg()
    event = {
        "token0": _T,
        "token1": _AERO,
        "token0_symbol": "LONG",
        "token1_symbol": "AERO",
    }
    cands = candidate_tokens_from_event(event, cfg)
    assert len(cands) == 2
    row, reason = resolve_best_neighborhood_for_event(
        event,
        chain="base",
        config=cfg,
        registry=registry,
        dry_run=True,
    )
    assert row is not None
    assert row["selected_focus_token"] == _T
    assert row["subgraph_ready"] is True
    assert "AERO" in (row.get("connector_tokens") or [])
    assert row.get("connector_routes_count", 0) >= 1
    assert row.get("event_candidate_tokens")
