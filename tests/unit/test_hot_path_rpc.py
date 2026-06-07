"""Hot-path quote RPC wiring."""
from __future__ import annotations

from unittest.mock import MagicMock


def test_setup_quote_rpc_uses_productive_primary_rpc(monkeypatch):
    from m8.discovery.hot_path_common import setup_quote_rpc

    calls: list = []
    productive_env = {"BASE_RPC_PRIMARY": "https://rpc.example/base"}

    monkeypatch.setattr(
        "core.rpc_urls.apply_productive_rpc_env",
        lambda chain: productive_env,
    )

    def _fake_resolve_productive(chain, *, env=None):
        calls.append({"chain": chain, "env": env})
        return "https://rpc.example/base"

    monkeypatch.setattr(
        "core.rpc_urls.resolve_productive_http_rpc",
        _fake_resolve_productive,
    )
    monkeypatch.setattr("core.rpc_urls.classify_provider", lambda url: "alchemy")

    class _FakeWeb3:
        def __init__(self, provider):
            self.provider = provider

        HTTPProvider = staticmethod(lambda url, **kw: {"url": url, **kw})

    monkeypatch.setattr("web3.Web3", _FakeWeb3)

    w3, url, provider = setup_quote_rpc("base")
    assert w3 is not None
    assert url == "https://rpc.example/base"
    assert provider == "alchemy"
    assert calls and calls[0]["chain"] == "base"
    assert calls[0]["env"] is productive_env


def test_run_live_ws_session_imports_setup_quote_rpc_for_quote_mode():
    """Guard: live WS quote path must use hot_path_common.setup_quote_rpc."""
    import inspect

    from m8.discovery.hot_path_ws import run_live_ws_session

    src = inspect.getsource(run_live_ws_session)
    assert "setup_quote_rpc" in src
