"""Unit tests for M8.3 per-DEX route metadata workers."""
from __future__ import annotations

from m8.metadata.contracts import MetadataTask
from m8.metadata.dex.balancer import BalancerDexWorker
from m8.metadata.dex.curve import CurveDexWorker
from m8.metadata.dex.maverick import MaverickDexWorker
from m8.metadata.dex.uniswap_v4 import UniswapV4DexWorker


def _route_task(worker, route):
    task = worker.build_task(route)
    assert task is not None
    return worker.process(task)


def test_uniswap_v4_worker_pool_key_ready():
    route = {
        "route_id": "v4_1",
        "adapter_type": "uniswap_v4",
        "pool_address": "0x" + "a" * 40,
        "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "token1_addr": "0x4200000000000000000000000000000000000006",
        "fee": 500,
        "tick_spacing": 10,
        "hooks": "0x" + "0" * 40,
    }
    result = _route_task(UniswapV4DexWorker(), route)
    assert result.ready is True
    assert result.metadata["pool_key"]["fee"] == 500
    assert result.metadata["hooks_class"] == "no_hooks"


def test_balancer_worker_token_order():
    route = {
        "route_id": "bal_1",
        "adapter_type": "balancer_stable",
        "pool_address": "0x" + "b" * 40,
        "balancer_assets": [
            "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "0x4200000000000000000000000000000000000006",
        ],
        "rate_providers": [],
    }
    result = _route_task(BalancerDexWorker(), route)
    assert result.ready is True
    assert len(result.metadata["token_order"]) == 2


def test_maverick_worker_direction_metadata():
    route = {
        "route_id": "mav_1",
        "adapter_type": "maverick_v2",
        "pool_address": "0x" + "c" * 40,
        "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "token1_addr": "0x4200000000000000000000000000000000000006",
        "token_a_address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "token_b_address": "0x4200000000000000000000000000000000000006",
        "maverick_probe_by_token_in": {"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": True},
    }
    result = _route_task(MaverickDexWorker(), route)
    assert result.ready is True
    assert result.metadata["direction_support"] == "directional"


def test_curve_worker_coin_indices():
    route = {
        "route_id": "crv_1",
        "adapter_type": "curve_stable",
        "pool_address": "0x" + "d" * 40,
        "coin_indices": {"USDC": 0, "DAI": 1},
    }
    result = _route_task(CurveDexWorker(), route)
    assert result.ready is True
    assert result.metadata["coin_indices"]["USDC"] == 0


def test_dex_worker_does_not_set_decimals():
    route = {
        "route_id": "v4_2",
        "adapter_type": "uniswap_v4",
        "pool_address": "0x" + "e" * 40,
        "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "token1_addr": "0x4200000000000000000000000000000000000006",
        "fee": 3000,
        "tick_spacing": 60,
        "hooks": "0x" + "0" * 40,
    }
    result = UniswapV4DexWorker().process(
        MetadataTask(
            task_id="t",
            kind="dex_route",
            worker_id="uniswap_v4",
            route_id="v4_2",
            route=route,
        )
    )
    assert "decimals" not in result.metadata
    assert "token0_decimals" not in result.metadata
