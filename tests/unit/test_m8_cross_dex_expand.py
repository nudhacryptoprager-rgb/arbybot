"""Unit tests for M8.2 cross-DEX expansion."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from m8.discovery.cross_dex_expand import (
    SCHEMA_VERSION,
    _build_route,
    _registry_pools_for_pair,
    collect_token_anchor_pairs,
    discovery_dexes_from_config,
    expand_cross_dex,
    tag_cross_mechanic_routes,
)
from m9.graph_arb.depth_capacity_probe import (
    DEPTH_PROBE_MEASURED_CAPACITY,
)
from m9.graph_arb.expansion_admission import expansion_productive_admit


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
    cfg = _minimal_config()
    cfg["dexes"]["aerodrome"] = {"adapter_type": "ve33", "enabled": True}
    cfg["m9_dex_productivity"]["aerodrome"] = {
        "enabled_for_discovery": True,
        "enabled_for_productive": True,
    }
    art = expand_cross_dex(
        chain="base",
        config=cfg,
        registry=registry,
        anchor_artifact=None,
        dry_run=True,
    )
    assert art["schema_version"] == SCHEMA_VERSION
    assert art["summary"]["tokens_in"] == 1
    assert art["summary"]["multi_venue_tokens"] == 1
    assert art["summary"]["routes_admitted_count"] >= 2
    assert all(r["source"] == "m8_cross_dex_expansion" for r in art["routes_admitted"])


def test_registry_venues_outside_config_are_ignored():
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

    assert art["summary"]["dex_ids_checked"] == ["uniswap_v3", "curve_stable"]
    assert art["summary"]["multi_venue_tokens"] == 0
    assert art["summary"]["routes_admitted_count"] == 0
    assert art["summary"]["pools_found_by_dex"] == {"uniswap_v3": 1}


def test_cross_mechanic_scoring_clmm_vs_solidly():
    # uniswap_v3 (clmm_ticks) + aerodrome (solidly_volatile_xyk) = 2 distinct
    # pricing models => cross_mechanic, mirror_score=2.
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
    cfg = _minimal_config()
    cfg["dexes"]["aerodrome"] = {"adapter_type": "ve33", "enabled": True}
    cfg["m9_dex_productivity"]["aerodrome"] = {
        "enabled_for_discovery": True,
        "enabled_for_productive": True,
    }
    art = expand_cross_dex(
        chain="base",
        config=cfg,
        registry=registry,
        anchor_artifact=None,
        dry_run=True,
    )
    assert art["summary"]["cross_mechanic_tokens"] == 1
    assert art["summary"]["same_mechanic_tokens"] == 0
    assert art["summary"]["pricing_model_pairs"]
    for r in art["routes_admitted"]:
        assert r["cross_mechanic"] is True
        assert r["mirror_score"] >= 2.0
        assert len(r["mirror_pricing_models"]) >= 2


def test_token_freshness_signal_from_registry():
    import time

    registry = {
        "tokens": {
            "0xabc": {
                "symbol": "FOO",
                "anchors": ["USDC"],
                "first_seen_ts": time.time(),  # just observed => fresh
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
    cfg = _minimal_config()
    cfg["dexes"]["aerodrome"] = {"adapter_type": "ve33", "enabled": True}
    cfg["m9_dex_productivity"]["aerodrome"] = {
        "enabled_for_discovery": True,
        "enabled_for_productive": True,
    }
    art = expand_cross_dex(
        chain="base",
        config=cfg,
        registry=registry,
        anchor_artifact=None,
        dry_run=True,
    )
    assert art["summary"]["fresh_token_admitted"] == 1
    assert any(r.get("token_is_fresh") for r in art["routes_admitted"])


def test_registry_pools_for_pair_filters_dex_outside_config():
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
                    },
                    "x::0xpool2": {
                        "dex": "phantom_dex",
                        "pool": "0xpool2",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                    },
                },
            }
        }
    }
    pools = _registry_pools_for_pair(
        registry,
        "0xabc",
        "FOO",
        "USDC",
        allowed_dex_ids={"uniswap_v3"},
    )
    assert len(pools) == 1
    assert pools[0]["dex_id"] == "uniswap_v3"


def test_discovery_dexes_respects_productivity_flags():
    cfg = _minimal_config()
    cfg["m9_dex_productivity"]["curve_stable"]["enabled_for_discovery"] = False
    rows = discovery_dexes_from_config(cfg)
    assert [r["dex_id"] for r in rows] == ["uniswap_v3"]


def test_build_route_keeps_symbol_address_alignment_when_canonicalizing_pair():
    route = _build_route(
        {"exotic_symbol": "AIOS", "anchor_symbol": "USDC"},
        {
            "dex_id": "uniswap_v3",
            "pool_address": "0xbf81d227adc490f5dcacfda7b050336f6924f9f6",
            "factory_address": "0x33128a8fc17869897dce68ed026d694621f6fdfd",
            "token0_symbol": "USDC",
            "token1_symbol": "AIOS",
            "token0_addr": "0xusdc",
            "token1_addr": "0xaios",
            "fee": 3000,
            "tick_spacing": 60,
            "factory_verified": True,
        },
        productive=True,
    )

    assert route["pair_id"] == "AIOS_USDC"
    assert route["token0"] == "AIOS"
    assert route["token0_addr"] == "0xaios"
    assert route["token1"] == "USDC"
    assert route["token1_addr"] == "0xusdc"


def test_build_route_carries_provenance_from_registry_venue():
    cfg = _minimal_config()
    cfg["dexes"]["sushiswap_v3"] = {"adapter_type": "uniswap_v3", "enabled": True}
    cfg["m9_dex_productivity"]["sushiswap_v3"] = {
        "enabled_for_discovery": True,
        "enabled_for_productive": True,
    }
    registry = {
        "tokens": {
            "0xabc": {
                "symbol": "FOO",
                "first_seen_ts": 1710000000.0,
                "anchors": ["USDC"],
                "venues": {
                    "u::0xpool1": {
                        "dex": "uniswap_v3",
                        "pool": "0xpool1",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                        "token0": "0xabc",
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                        "block_number": 12345,
                        "source_event_block": 12345,
                        "pool_first_seen_block": 12345,
                    },
                    "s::0xpool2": {
                        "dex": "sushiswap_v3",
                        "pool": "0xpool2",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                        "token0": "0xabc",
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                        "block_number": 12350,
                    },
                },
            }
        }
    }
    art = expand_cross_dex(
        chain="base",
        config=cfg,
        registry=registry,
        anchor_artifact=None,
        dry_run=True,
    )
    routes = art["routes_admitted"]
    assert routes
    r = routes[0]
    assert r.get("pool_first_seen_block") in (12345, 12350)
    assert r.get("token_first_seen_ts") == 1710000000.0


def test_v4_measured_depth_admitted_despite_productive_false():
    productive_dexes = {"uniswap_v3"}
    entry = {
        "dex_id": "uniswap_v4",
        "pool_address": "0xpoolv4",
        "depth_probe_status": DEPTH_PROBE_MEASURED_CAPACITY,
        "effective_depth_usd": 5000.0,
        "factory_verified": True,
    }
    assert expansion_productive_admit(entry, productive_dexes) is True


def test_v4_without_depth_not_admitted_when_productive_false():
    productive_dexes = {"uniswap_v3"}
    entry = {
        "dex_id": "uniswap_v4",
        "pool_address": "0xpoolv4",
        "factory_verified": True,
    }
    assert expansion_productive_admit(entry, productive_dexes) is False


def test_tag_cross_mechanic_routes_by_focus_token():
    focus = "0xabc0000000000000000000000000000000000001"
    routes = [
        {
            "dex_id": "uniswap_v3",
            "pool_address": "0xpool1",
            "focus_token_address": focus,
            "quote_smoke_status": "QUOTE_OK",
        },
        {
            "dex_id": "curve_stable",
            "pool_address": "0xpool2",
            "focus_token_address": focus,
            "quote_smoke_status": "QUOTE_OK_INT128",
        },
        {
            "dex_id": "uniswap_v3",
            "pool_address": "0xpool3",
            "focus_token_address": "0xother",
            "quote_smoke_status": "QUOTE_OK",
        },
    ]
    tagged = tag_cross_mechanic_routes(routes)
    assert tagged == 2
    assert routes[0]["cross_mechanic"] is True
    assert routes[1]["cross_mechanic"] is True
    assert routes[2].get("cross_mechanic") is not True
