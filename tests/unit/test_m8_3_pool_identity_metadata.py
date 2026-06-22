"""M8.3 pool identity preflight tests."""
from __future__ import annotations

from m8.metadata.pool_identity import build_pool_identity_entry, build_pool_identity_metadata
from m8.metadata.registry import apply_registry_to_route


def test_pool_identity_entry_from_route_and_dex_row():
    route = {
        "route_id": "bal_1",
        "adapter_type": "balancer_stable",
        "pool_address": "0x" + "a" * 40,
        "factory_verified": True,
        "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "token1_addr": "0x4200000000000000000000000000000000000006",
    }
    dex_row = {
        "ready": True,
        "worker_id": "balancer",
        "metadata": {
            "tokens_order": [route["token0_addr"], route["token1_addr"]],
            "pool_type": "balancer_stable",
        },
    }
    entry = build_pool_identity_entry(route, dex_route_row=dex_row)
    assert entry["token_order_verified"] is True
    assert entry["factory_verified"] is True
    assert entry["dex_worker_id"] == "balancer"


def test_apply_registry_stamps_preflight_without_recompute():
    rid = "mav_1"
    registry = {
        "token_registry": {
            "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": {
                "decimals": 6,
                "source": "core_config",
                "economics_grade": "config_verified",
            },
            "0x4200000000000000000000000000000000000006": {
                "decimals": 18,
                "source": "known_address",
                "economics_grade": "config_verified",
            },
        },
        "token_risk_metadata": {
            "by_address": {
                "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": {
                    "non_erc20_reason": None,
                    "token_behavior_flags": {},
                }
            }
        },
        "dex_route_metadata": {
            "by_route_id": {
                rid: {
                    "ready": True,
                    "worker_id": "maverick",
                    "metadata": {"token_a": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"},
                }
            }
        },
        "pool_identity_metadata": {
            "by_route_id": {
                rid: {"route_id": rid, "token_order_verified": True, "dex_metadata_ready": True}
            }
        },
    }
    route = {
        "route_id": rid,
        "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "token1_addr": "0x4200000000000000000000000000000000000006",
    }
    apply_registry_to_route(route, registry)
    assert route["m8_3_preflight_applied"] is True
    assert route["m8_3_dex_worker_id"] == "maverick"
    assert route["m8_3_pool_identity"]["route_id"] == rid
    assert route["token0_decimals"] == 6


def test_pool_identity_coverage_aggregate():
    routes = [
        {
            "route_id": "r1",
            "adapter_type": "uniswap_v3",
            "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "token1_addr": "0x4200000000000000000000000000000000000006",
            "pool_address": "0x" + "b" * 40,
        }
    ]
    dex_by = {
        "r1": {
            "ready": True,
            "worker_id": "uniswap_v3",
            "metadata": {"fee": 500},
        }
    }
    doc = build_pool_identity_metadata(routes, dex_by, scopes={"all_routes": {"r1"}})
    assert doc["by_route_id"]["r1"]["dex_metadata_ready"] is True
    assert doc["coverage"]["all_routes"]["pool_identity_verified_rate"] == 1.0
