"""E1.76 unit tests for pair_pool_matrix, depth_ladder, gecko & defillama scouts."""

from __future__ import annotations

import json

from m7.scouts.pair_pool_matrix import (
    build_pair_pool_matrix,
    canonical_pair,
    infer_fee_tier_bps,
    split_symbol,
)
from m7.orderflow.depth_ladder import (
    DEFAULT_DEPTH_LADDER_USD,
    build_depth_ladder,
    expected_profit_at_depth,
    lag_score,
    mav_estimate_usd,
)
from m7.scouts.gecko_scout import (
    GeckoPoolEntry,
    parse_geckoterminal_pools,
    rank_pools_by_volume,
)
from m7.scouts.defillama_volume_scout import (
    DexVolumeEntry,
    parse_dex_volumes,
    rank_dexes_by_24h_volume,
)


# -----------------------------------------------------------------------------
# pair_pool_matrix
# -----------------------------------------------------------------------------

def test_split_symbol_separators():
    assert split_symbol("WETH-USDC") == ("WETH", "USDC")
    assert split_symbol("usdc/weth") == ("USDC", "WETH")
    assert split_symbol("WETH_USDC") == ("WETH", "USDC")
    assert split_symbol("WETH USDC") == ("WETH", "USDC")
    assert split_symbol("WETH") == ("WETH", "")
    assert split_symbol("") == ("", "")


def test_canonical_pair_alphabetical():
    assert canonical_pair("WETH", "USDC") == "USDC/WETH"
    assert canonical_pair("USDC", "WETH") == "USDC/WETH"
    assert canonical_pair("usdc", "weth") == "USDC/WETH"
    assert canonical_pair("", "") == ""
    assert canonical_pair("WETH", "") == "WETH"


def test_infer_fee_tier_bps():
    assert infer_fee_tier_bps({"fee_tier_bps": 5}) == 5
    assert infer_fee_tier_bps({"fee_tier": 500}) == 5     # 500 ppm = 5 bps
    assert infer_fee_tier_bps({"fee_tier": 3000}) == 30
    assert infer_fee_tier_bps({"fee": 0.0005}) == 5
    assert infer_fee_tier_bps({"fee": 30}) == 30
    assert infer_fee_tier_bps({}) is None


def test_build_pair_pool_matrix_groups_pools():
    pools = [
        {"symbol": "WETH-USDC", "pool_address": "0xa1", "project": "uniswap-v3",
         "tvl_usd": 1_000_000.0, "volume_24h_usd": 50_000.0, "fee_tier": 500},
        {"symbol": "USDC-WETH", "pool_address": "0xa2", "project": "uniswap-v3",
         "tvl_usd": 200_000.0, "volume_24h_usd": 5_000.0, "fee_tier": 3000},
        {"symbol": "WETH/USDC", "pool_address": "0xa3", "project": "aerodrome-v1",
         "tvl_usd": 500_000.0, "volume_24h_usd": 10_000.0},
        {"symbol": "VIRTUAL-WETH", "pool_address": "0xb1", "project": "uniswap-v3",
         "tvl_usd": 50_000.0, "volume_24h_usd": 2_000.0, "fee_tier": 3000},
    ]
    out = build_pair_pool_matrix(pools)
    assert out["summary"]["pair_count"] == 2
    assert out["summary"]["pool_count"] == 4
    # Largest family first.
    families_by_pair = {p["pair"]: p for p in out["pairs"]}
    weth_usdc = families_by_pair["USDC/WETH"]
    assert weth_usdc["pool_count"] == 3
    assert weth_usdc["dex_count"] == 2
    assert 5 in weth_usdc["fee_tiers"] and 30 in weth_usdc["fee_tiers"]
    assert weth_usdc["best_pool"]["pool_address"] == "0xa1"
    assert "VIRTUAL/WETH" in families_by_pair


def test_build_pair_pool_matrix_min_tvl_filter():
    pools = [
        {"symbol": "A-B", "pool_address": "0x1", "tvl_usd": 100.0},
        {"symbol": "A-B", "pool_address": "0x2", "tvl_usd": 50_001.0},
    ]
    out = build_pair_pool_matrix(pools, min_tvl_usd=10_000.0)
    assert out["summary"]["pool_count"] == 1


def test_build_pair_pool_matrix_empty_and_bad_input():
    assert build_pair_pool_matrix([]) == {
        "pairs": [],
        "summary": {"pair_count": 0, "pool_count": 0, "tvl_total_usd": 0.0},
    }
    out = build_pair_pool_matrix([{"symbol": "", "pool_address": "0x"}, None, "x"])
    assert out["summary"]["pool_count"] == 0


# -----------------------------------------------------------------------------
# depth_ladder
# -----------------------------------------------------------------------------

def _curve():
    return [
        {"size_usd": 10, "net_bps": 30, "expected_profit_usd": 0.30},
        {"size_usd": 50, "net_bps": 25, "expected_profit_usd": 1.25},
        {"size_usd": 100, "net_bps": 20, "expected_profit_usd": 2.00},
        {"size_usd": 500, "net_bps": 10, "expected_profit_usd": 5.00},
    ]


def test_expected_profit_at_depth_interpolation():
    c = _curve()
    # below smallest rung
    assert expected_profit_at_depth(c, 5) == 0.0
    # exact rung
    assert abs(expected_profit_at_depth(c, 50) - 1.25) < 1e-9
    # interpolated 75 between (50, 1.25) and (100, 2.00) -> 1.625
    assert abs(expected_profit_at_depth(c, 75) - 1.625) < 1e-6
    # above largest rung clamps to its value
    assert expected_profit_at_depth(c, 1000) == 5.00
    # empty
    assert expected_profit_at_depth([], 100) == 0.0


def test_build_depth_ladder_default_rungs():
    c = _curve()
    ladder = build_depth_ladder(c)
    assert [r["size_usd"] for r in ladder] == list(DEFAULT_DEPTH_LADDER_USD)
    by_size = {r["size_usd"]: r["expected_profit_usd"] for r in ladder}
    assert by_size[50.0] == 1.25
    assert by_size[100.0] == 2.0
    assert by_size[500.0] == 5.0


def test_mav_estimate_usd():
    c = _curve()
    mav = mav_estimate_usd(c)
    assert mav["mav_usd"] == 5.0
    assert mav["best_size_usd"] == 500.0
    # With curve missing high rungs, MAV scales down.
    short = [{"size_usd": 10, "expected_profit_usd": 0.3}]
    mav2 = mav_estimate_usd(short)
    assert mav2["mav_usd"] == 0.3
    assert mav2["best_size_usd"] == 10.0


def test_mav_estimate_handles_empty_and_negative():
    assert mav_estimate_usd([]) == {"mav_usd": 0.0, "best_size_usd": 0.0}
    neg = [{"size_usd": 50, "expected_profit_usd": -1.0}]
    assert mav_estimate_usd(neg)["mav_usd"] == 0.0  # clamped


def test_lag_score_components():
    # All three components: stale=1, imbalance=0.5, divergence=0.5 -> mean 0.667
    s = lag_score(seconds_since_last_swap=600, volume_imbalance_ratio=0.5,
                  price_divergence_bps=50)
    assert 60.0 < s < 70.0
    # Empty -> 0
    assert lag_score() == 0.0
    # Single component
    assert lag_score(seconds_since_last_swap=0) == 0.0
    assert lag_score(seconds_since_last_swap=300) == 100.0


# -----------------------------------------------------------------------------
# GeckoTerminal scout
# -----------------------------------------------------------------------------

def test_parse_geckoterminal_pools_v2_shape():
    payload = {
        "data": [
            {
                "id": "base_0xabc",
                "type": "pool",
                "attributes": {
                    "name": "WETH / USDC",
                    "address": "0xABC",
                    "reserve_in_usd": "1234567.89",
                    "volume_usd": {"h24": "98765.4"},
                },
                "relationships": {
                    "dex": {"data": {"id": "uniswap_v3_base"}},
                },
            },
            {
                "id": "base_0xdef",
                "type": "pool",
                "attributes": {
                    "name": "VIRTUAL / WETH",
                    "address": "0xdef",
                    "reserve_in_usd": "5000",
                    "volume_usd": {"h24": "100"},
                },
            },
            "garbage",
            {"id": "no-attrs"},
        ]
    }
    pools = parse_geckoterminal_pools(payload)
    assert len(pools) == 2
    p0 = pools[0]
    assert isinstance(p0, GeckoPoolEntry)
    assert p0.pool_address == "0xabc"
    assert p0.symbol == "WETH-USDC"
    assert p0.tvl_usd == 1234567.89
    assert p0.volume_24h_usd == 98765.4
    assert p0.project == "uniswap_v3_base"


def test_parse_geckoterminal_handles_garbage():
    assert parse_geckoterminal_pools(None) == []
    assert parse_geckoterminal_pools({"data": "nope"}) == []
    assert parse_geckoterminal_pools({}) == []


def test_rank_pools_by_volume():
    pools = [
        GeckoPoolEntry("base", "u3", "0x1", "A-B", 1.0, 100.0),
        GeckoPoolEntry("base", "u3", "0x2", "A-B", 1.0, 5.0),
        GeckoPoolEntry("base", "u3", "0x3", "A-B", 1.0, 1000.0),
    ]
    ranked = rank_pools_by_volume(pools, top_n=2)
    assert [p.pool_address for p in ranked] == ["0x3", "0x1"]
    filtered = rank_pools_by_volume(pools, min_volume_usd=50.0)
    assert len(filtered) == 2


# -----------------------------------------------------------------------------
# DefiLlama volume scout
# -----------------------------------------------------------------------------

def test_parse_dex_volumes_protocols_shape():
    payload = {
        "protocols": [
            {"name": "Uniswap V3", "chains": ["Base", "Ethereum"],
             "total24h": 1_000_000.0, "total7d": 7_000_000.0},
            {"name": "Aerodrome V1", "chains": ["Base"],
             "total24h": 500_000.0},
            {"name": "Curve", "chains": ["Ethereum"], "total24h": 9.9},
            "garbage",
        ]
    }
    rows = parse_dex_volumes(payload, chain_filter="Base")
    names = [r.project for r in rows]
    assert "uniswap v3" in names
    assert "aerodrome v1" in names
    # Curve excluded — no Base chain
    assert all("curve" not in n for n in names)


def test_parse_dex_volumes_dexes_shape():
    payload = {
        "dexes": [
            {"name": "u3", "chain": "Base", "volume24hUSD": 500.0},
            {"name": "u3", "chain": "Optimism", "volume24hUSD": 50.0},
        ]
    }
    rows = parse_dex_volumes(payload, chain_filter="Base")
    assert len(rows) == 1
    assert rows[0].volume_24h_usd == 500.0


def test_rank_dexes_by_24h_volume():
    rows = [
        DexVolumeEntry("Base", "a", 100.0),
        DexVolumeEntry("Base", "b", 1000.0),
        DexVolumeEntry("Base", "c", 50.0),
    ]
    ranked = rank_dexes_by_24h_volume(rows, min_volume_usd=80.0, top_n=2)
    assert [r.project for r in ranked] == ["b", "a"]


def test_serialisable_to_json():
    """Sanity-check that all dataclasses round-trip through json.dumps."""
    pools_json = json.dumps([
        GeckoPoolEntry("base", "u3", "0x1", "A-B", 1.0, 2.0).to_dict()
    ])
    assert "0x1" in pools_json
    dexes_json = json.dumps([DexVolumeEntry("Base", "u3", 1.0).to_dict()])
    assert "Base" in dexes_json
