"""
E1.50 / TD-003 — minimal test shield for in-process WS-target refresh bridge.

Covers:
  * _remember_last_working_ws / _peek_last_working_ws — module-level
    cache that persists the last-working WS endpoint across hot iterations.
  * Public-fallback never wins memorization (strict provider policy intent).

These are pure in-process helpers and do not touch network, RPC, or files.
"""
from __future__ import annotations

import importlib


def test_remember_and_peek_roundtrip():
    mod = importlib.import_module("m7.orderflow.mode_ws_live")
    # Reset state
    mod._LAST_WORKING_WS.clear()
    assert mod._peek_last_working_ws("base") is None

    mod._remember_last_working_ws("base", "wss://eth-mainnet.g.alchemy.com/v2/key", "alchemy")
    snap = mod._peek_last_working_ws("base")
    assert snap is not None
    assert snap["url"].startswith("wss://eth-mainnet.g.alchemy.com")
    assert snap["provider"] == "alchemy"


def test_remember_is_chain_scoped():
    mod = importlib.import_module("m7.orderflow.mode_ws_live")
    mod._LAST_WORKING_WS.clear()
    mod._remember_last_working_ws("base", "wss://a/", "alchemy")
    mod._remember_last_working_ws("arbitrum_one", "wss://b/", "drpc")
    assert mod._peek_last_working_ws("base")["url"] == "wss://a/"
    assert mod._peek_last_working_ws("arbitrum_one")["url"] == "wss://b/"


def test_remember_overwrites_same_chain():
    mod = importlib.import_module("m7.orderflow.mode_ws_live")
    mod._LAST_WORKING_WS.clear()
    mod._remember_last_working_ws("base", "wss://drpc/", "drpc")
    mod._remember_last_working_ws("base", "wss://alchemy/", "alchemy")
    snap = mod._peek_last_working_ws("base")
    assert snap["url"] == "wss://alchemy/"
    assert snap["provider"] == "alchemy"


def test_peek_unknown_chain_is_none():
    mod = importlib.import_module("m7.orderflow.mode_ws_live")
    mod._LAST_WORKING_WS.clear()
    assert mod._peek_last_working_ws("zksync") is None
    assert mod._peek_last_working_ws("") is None


def test_remember_ignores_empty_inputs():
    mod = importlib.import_module("m7.orderflow.mode_ws_live")
    mod._LAST_WORKING_WS.clear()
    mod._remember_last_working_ws("", "wss://x/", "alchemy")
    mod._remember_last_working_ws("base", "", "alchemy")
    assert mod._LAST_WORKING_WS == {}
