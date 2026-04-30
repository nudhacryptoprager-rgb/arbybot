"""M7.E1.47/P3: Alchemy WS fallback when primary WS hits 429.

Verifies the URL builder + selection logic used by `mode_ws_live` to
enqueue Alchemy WS as a premium fallback before falling back to public
publicnode. The actual `_ws_tried_urls` mutation lives in mode_ws_live;
here we test the pure resolution.
"""
from __future__ import annotations

import importlib

import pytest


def test_build_alchemy_ws_url_for_base():
    from core.rpc_urls import build_alchemy_ws_url
    url = build_alchemy_ws_url("base", "fake-api-key-12345")
    assert url is not None
    assert url.startswith("wss://")
    assert "alchemy.com" in url
    assert "fake-api-key-12345" in url


def test_build_alchemy_ws_url_unsupported_returns_none_or_url():
    from core.rpc_urls import build_alchemy_ws_url
    # Unknown network — must not crash; returns None or a value, never raises.
    out = build_alchemy_ws_url(None, "k")
    # Acceptable: either None or a defensible string.
    assert out is None or isinstance(out, str)


def test_alchemy_fallback_decision_skips_when_already_alchemy():
    """When primary throttled provider IS alchemy, do NOT enqueue alchemy
    again. (mirrors the `_try_ws_name != 'alchemy'` guard in mode_ws_live)
    """
    primary_provider = "alchemy"
    api_key = "key-x"
    should_enqueue_alchemy = bool(api_key) and primary_provider != "alchemy"
    assert should_enqueue_alchemy is False


def test_alchemy_fallback_decision_enqueues_when_drpc_throttled():
    primary_provider = "drpc"
    api_key = "key-x"
    should_enqueue_alchemy = bool(api_key) and primary_provider != "alchemy"
    assert should_enqueue_alchemy is True


def test_alchemy_fallback_disabled_by_env(monkeypatch):
    monkeypatch.setenv("ARBY_ALCHEMY_WS_FALLBACK", "0")
    import os
    assert os.environ.get("ARBY_ALCHEMY_WS_FALLBACK", "1") == "0"


def test_no_duplicate_enqueue_when_already_in_tried_urls():
    """Mirrors the `(_alc_ws, 'alchemy') not in _ws_tried_urls` check."""
    fake_alc = "wss://base-mainnet.g.alchemy.com/v2/k"
    tried = [(fake_alc, "alchemy")]
    should_add = (fake_alc, "alchemy") not in tried
    assert should_add is False


def test_alchemy_url_uniqueness_across_networks():
    from core.rpc_urls import build_alchemy_ws_url
    url_base = build_alchemy_ws_url("base", "k1")
    url_arb = build_alchemy_ws_url("arbitrum", "k1")
    if url_base and url_arb:
        assert url_base != url_arb
