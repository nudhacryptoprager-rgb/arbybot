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

    bridge = {
        "hot_seen_unresolved_pools": [
            {"pool_address": pool, "seen_count": 9, "resolved": False},
        ],
        "pool_token_transport": {},
    }

    fake_w3 = MagicMock()
    fake_w3.eth.call.side_effect = [t0, t1]

    with patch("web3.Web3") as _W3:
        _W3.return_value = fake_w3
        _W3.to_checksum_address.side_effect = lambda a: a
        n = _rehydrate_hot_unresolved_pools(bridge, "http://rpc", 123, max_pools=5)

    assert n == 1
    assert pool in bridge["pool_token_transport"]
    t0_hex, t1_hex, fee = bridge["pool_token_transport"][pool]
    assert t0_hex == "0x" + "11" * 20
    assert t1_hex == "0x" + "22" * 20
    assert fee == 0
