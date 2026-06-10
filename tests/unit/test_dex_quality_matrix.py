"""Tests for per-DEX quality matrix and lane acceptance."""
from __future__ import annotations

from m9.graph_arb.adapter_families import (
    FAMILY_BALANCER_VAULT,
    balancer_route_metadata_complete,
    family_for_dex,
)
from m9.graph_arb.dex_quality_matrix import build_dex_quality_matrix
from m9.graph_arb.per_dex_sizing import cap_sizes_to_depth_per_family
from scripts.m9_dex_lane_acceptance import evaluate_lane_acceptance


def test_family_for_dex_v2_v3_split():
    assert family_for_dex("uniswap_v2") == "v2_fork"
    assert family_for_dex("pancakeswap_v3") == "v3_fork"
    assert family_for_dex("aerodrome_v2_stable") == "aerodrome_ve33_stable"
    assert family_for_dex("uniswap_v4") == "v4_pool_manager"


def test_balancer_metadata_complete_requires_pool_id():
    incomplete = {"dex_id": "balancer_vault", "adapter_type": "balancer_stable"}
    complete = {
        **incomplete,
        "pool_id": "0x" + "a" * 64,
        "vault_address": "0xba12222222228d8ba445958a75a0704d566bf2c8",
        "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "token1_addr": "0x4200000000000000000000000000000000000006",
    }
    assert balancer_route_metadata_complete(incomplete) is False
    assert balancer_route_metadata_complete(complete) is True


def test_build_dex_quality_matrix_counts_bridge_routes():
    bridge = {
        "active_routes": [
            {
                "dex_id": "uniswap_v3",
                "factory_verified": True,
                "quote_smoke_status": "QUOTE_OK",
                "productive_quote_status": "QUOTE_OK_PRODUCTIVE",
            },
            {
                "dex_id": "balancer_vault",
                "factory_verified": True,
                "quote_smoke_status": "QUOTE_OK_BALANCER",
                "productive_quote_status": "QUOTE_OK_PRODUCTIVE",
                "pool_id": "0x" + "b" * 64,
                "vault_address": "0xba12222222228d8ba445958a75a0704d566bf2c8",
                "token0_addr": "0x1",
                "token1_addr": "0x2",
            },
        ],
        "bridge_source_metrics": {"curve_lane_ready": True},
    }
    expansion = {
        "summary": {
            "dex_ids_checked": ["uniswap_v3", "balancer_vault", "curve_stable"],
            "pools_found_by_dex": {"uniswap_v3": 5, "balancer_vault": 94},
            "quoteable_by_dex": {"balancer_vault": 79},
            "curve_lane_ready": False,
            "curve_routes_ready": 0,
        }
    }
    shadow = {
        "cycles_found": 100,
        "cycles_quoteable": 0,
        "qsr": 0.0,
        "edge_error_histogram": [
            {
                "route_id": "maverick_v2:TOK-TOK@0",
                "errors": {"QUOTE_RPC_ERROR": 10},
            }
        ],
    }
    config = {
        "dexes": {
            "uniswap_v3": {"enabled": True},
            "balancer_vault": {"enabled": True},
            "curve_stable": {"enabled": True},
            "pancakeswap_v3": {"enabled": True},
        }
    }
    doc = build_dex_quality_matrix(
        config=config, bridge=bridge, expansion=expansion, shadow=shadow
    )
    assert doc["visible_in_bridge_count"] == 2
    assert doc["matrix"]["uniswap_v3"]["productive_quote_ok"] == 1
    assert doc["matrix"]["balancer_vault"]["discovered"] == 94
    assert "NO_QUOTEABLE_CYCLES" in doc["blockers"]


def test_lane_acceptance_fails_verified_without_productive():
    matrix_doc = {
        "matrix": {
            "maverick_v2": {
                "verified": 10,
                "productive_quote_ok": 0,
                "route_quote_ok": 5,
                "discovered": 10,
                "bridge_active_routes": 5,
                "metadata_complete": True,
                "adapter_family": "maverick_v2",
            }
        },
        "expansion_dex_ids_checked": ["maverick_v2"],
        "global_shadow": {"cycles_quoteable": 0},
        "expansion_distinct_lane": {"curve_lane_ready": False},
        "blockers": [],
    }
    result = evaluate_lane_acceptance(matrix_doc)
    assert result["passed"] is False
    assert any("maverick_v2" in v for v in result["violations"])


def test_per_dex_sizing_tighter_for_maverick():
    class _Edge:
        def __init__(self, dex_id: str, adapter_type: str):
            self.dex_id = dex_id
            self.adapter_type = adapter_type

    edges = [_Edge("maverick_v2", "maverick_v2")]
    capped = cap_sizes_to_depth_per_family(
        (1.0, 5.0, 10.0, 100.0), depth_usd=100.0, edges=edges
    )
    assert max(capped) <= 6.1
