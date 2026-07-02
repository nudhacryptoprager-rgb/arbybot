"""Hot-path mirror resolve (single-token filter)."""
from __future__ import annotations

from m8.discovery.cross_dex_expand import expand_cross_dex
from m8.discovery.hot_path_mirror import resolve_mirrors_for_token


def _cfg():
    return {
        "chain": "base",
        "dexes": {
            "uniswap_v3": {"adapter_type": "uniswap_v3", "enabled": True},
            "aerodrome": {"adapter_type": "ve33", "enabled": True},
        },
        "m9_dex_productivity": {
            "uniswap_v3": {"enabled_for_discovery": True, "enabled_for_productive": True},
            "aerodrome": {"enabled_for_discovery": True, "enabled_for_productive": True},
        },
    }


def test_exotic_address_filter_limits_pairs():
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
                },
            },
            "0xdef": {
                "symbol": "BAR",
                "anchors": ["USDC"],
                "venues": {
                    "u::0xpool9": {
                        "dex": "uniswap_v3",
                        "pool": "0xpool9",
                        "token0_symbol": "BAR",
                        "token1_symbol": "USDC",
                        "token0": "0xdef",
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                    },
                },
            },
        }
    }
    full = expand_cross_dex(chain="base", config=_cfg(), registry=registry, anchor_artifact=None, dry_run=True)
    one = expand_cross_dex(
        chain="base",
        config=_cfg(),
        registry=registry,
        anchor_artifact=None,
        dry_run=True,
        exotic_address_filter="0xabc",
    )
    assert full["summary"]["tokens_in"] >= one["summary"]["tokens_in"]
    assert one["summary"]["tokens_in"] == 1


def test_resolve_mirrors_returns_latency():
    # Use a valid 40-hex-char address; expand_token_neighborhood rejects
    # short addresses via is_valid_eth_address (len == 42).
    _exotic = "0x" + "0a" * 20
    registry = {
        "tokens": {
            _exotic: {
                "symbol": "FOO",
                "anchors": ["USDC"],
                "venues": {
                    "u::0xpool1": {
                        "dex": "uniswap_v3",
                        "pool": "0xpool1",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                        "token0": _exotic,
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                    },
                    "a::0xpool2": {
                        "dex": "aerodrome",
                        "pool": "0xpool2",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                        "token0": _exotic,
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                    },
                },
            }
        }
    }
    row = resolve_mirrors_for_token(
        chain="base",
        config=_cfg(),
        registry=registry,
        exotic_address=_exotic,
        exotic_symbol="FOO",
        anchor_symbol="USDC",
        dry_run=True,
    )
    assert row["hot_path_mirror_resolve_latency_ms"] >= 0
    assert row["routes_admitted_count"] >= 1
