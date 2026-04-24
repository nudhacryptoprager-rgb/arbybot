"""P2: tests for _rehydrate_hot_unresolved_pools — token0/token1 rehydrate."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


def test_rehydrate_empty_bridge_returns_zero():
    from m7.orderflow.bridge_runtime import _rehydrate_hot_unresolved_pools

    assert _rehydrate_hot_unresolved_pools({}, "http://rpc", 1) == 0


def test_rehydrate_no_unresolved_returns_zero():
    from m7.orderflow.bridge_runtime import _rehydrate_hot_unresolved_pools

    bridge = {
        "hot_seen_unresolved_pools": [
            {"pool_address": "0x" + "aa" * 20, "seen_count": 5, "resolved": True},
        ],
    }
    assert _rehydrate_hot_unresolved_pools(bridge, "http://rpc", 1) == 0


def test_rehydrate_respects_limit_zero():
    from m7.orderflow.bridge_runtime import _rehydrate_hot_unresolved_pools

    bridge = {
        "hot_seen_unresolved_pools": [
            {"pool_address": "0x" + "ab" * 20, "seen_count": 5, "resolved": False},
        ],
    }
    assert _rehydrate_hot_unresolved_pools(bridge, "http://rpc", 1, max_pools=0) == 0


def test_rehydrate_populates_ptt_on_success():
    from m7.orderflow.bridge_runtime import _rehydrate_hot_unresolved_pools

    pool = "0x" + "cd" * 20
    t0 = b"\x00" * 12 + b"\x11" * 20
    t1 = b"\x00" * 12 + b"\x22" * 20
    fee_bytes = (500).to_bytes(32, "big")

    bridge = {
        "hot_seen_unresolved_pools": [
            {"pool_address": pool, "seen_count": 9, "resolved": False},
        ],
        "pool_token_transport": {},
    }

    fake_w3 = MagicMock()
    # Soak13: sequential fallback now fetches t0, t1, fee per pool.
    fake_w3.eth.call.side_effect = [t0, t1, fee_bytes]

    fake_batcher = MagicMock()
    fake_batcher.batch_token_info.return_value = {}  # force fallback

    with patch("web3.Web3") as _W3, patch(
        "core.multicall.get_multicall_batcher", return_value=fake_batcher
    ):
        _W3.return_value = fake_w3
        _W3.to_checksum_address.side_effect = lambda a: a
        n = _rehydrate_hot_unresolved_pools(bridge, "http://rpc", 123, max_pools=5)

    assert n == 1
    assert pool in bridge["pool_token_transport"]
    t0_hex, t1_hex, fee = bridge["pool_token_transport"][pool]
    assert t0_hex == "0x" + "11" * 20
    assert t1_hex == "0x" + "22" * 20
    assert fee == 500


def test_rehydrate_uses_multicall_fee_tier():
    """Soak13: multicall3 batch_token_info returns (t0, t1, fee) in one RPC."""
    from m7.orderflow.bridge_runtime import _rehydrate_hot_unresolved_pools

    pool = "0x" + "ef" * 20
    t0_hex = "0x" + "33" * 20
    t1_hex = "0x" + "44" * 20

    bridge = {
        "hot_seen_unresolved_pools": [
            {"pool_address": pool, "seen_count": 12, "resolved": False},
        ],
        "pool_token_transport": {},
    }

    fake_batcher = MagicMock()
    fake_batcher.batch_token_info.return_value = {pool: (t0_hex, t1_hex, 3000)}

    with patch("web3.Web3"), patch(
        "core.multicall.get_multicall_batcher", return_value=fake_batcher
    ):
        n = _rehydrate_hot_unresolved_pools(bridge, "http://rpc", 99, max_pools=5)

    assert n == 1
    assert bridge["pool_token_transport"][pool] == (t0_hex.lower(), t1_hex.lower(), 3000)
    # multicall was invoked exactly once with the candidate list.
    fake_batcher.batch_token_info.assert_called_once_with([pool])
