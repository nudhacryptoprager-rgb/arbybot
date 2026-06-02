"""Unit tests for M8.2 cross-DEX expansion."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from m8.discovery.cross_dex_expand import (
    SCHEMA_VERSION,
    collect_token_anchor_pairs,
    discovery_dexes_from_config,
    expand_cross_dex,
)


def _minimal_config() -> dict:
    return {
        "chain": "base",
        "dexes": {
            "uniswap_v3": {"adapter_type": "uniswap_v3", "enabled": True},
            "curve_stable": {"adapter_type": "curve_stable", "enabled": True},
        },
        "m9_dex_productivity": {
            "uniswap_v3": {
                "enabled_for_discovery": True,
                "enabled_for_productive": True,
            },
            "curve_stable": {
                "enabled_for_discovery": True,
                "enabled_for_productive": True,
            },
        },
    }


def test_collect_candidates_from_registry():
    registry = {
        "tokens": {
            "0xabc": {
                "symbol": "FOO",
                "anchors": ["USDC"],
                "venues": {
                    "u::0xpool1": {
                        "dex": "uniswap_v3",
                        "pool": "0xpool1",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                        "token0": "0xabc",
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                    },
                    "a::0xpool2": {
                        "dex": "aerodrome",
                        "pool": "0xpool2",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                        "token0": "0xabc",
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                    },
                },
            }
        }
    }
    pairs = collect_token_anchor_pairs(registry, None)
    assert len(pairs) == 1
    assert pairs[0]["anchor_symbol"] == "USDC"


def test_expand_dry_run_multi_venue(tmp_path):
    registry = {
        "tokens": {
            "0xabc": {
                "symbol": "FOO",
                "anchors": ["USDC"],
                "venues": {
                    "u::0xpool1": {
                        "dex": "uniswap_v3",
                        "pool": "0xpool1",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                        "token0": "0xabc",
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                    },
                    "a::0xpool2": {
                        "dex": "aerodrome",
                        "pool": "0xpool2",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                        "token0": "0xabc",
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                    },
                },
            }
        }
    }
    art = expand_cross_dex(
        chain="base",
        config=_minimal_config(),
        registry=registry,
        anchor_artifact=None,
        dry_run=True,
    )
    assert art["schema_version"] == SCHEMA_VERSION
    assert art["summary"]["tokens_in"] == 1
    assert art["summary"]["multi_venue_tokens"] == 1
    assert art["summary"]["routes_admitted_count"] >= 2
    assert all(r["source"] == "m8_cross_dex_expansion" for r in art["routes_admitted"])


def test_discovery_dexes_respects_productivity_flags():
    cfg = _minimal_config()
    cfg["m9_dex_productivity"]["curve_stable"]["enabled_for_discovery"] = False
    rows = discovery_dexes_from_config(cfg)
    assert [r["dex_id"] for r in rows] == ["uniswap_v3"]
