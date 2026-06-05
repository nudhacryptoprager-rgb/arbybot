"""Hot-path quote RPC wiring."""
from __future__ import annotations

from unittest.mock import MagicMock


def test_setup_quote_rpc_uses_resolve_rpc_http(monkeypatch):
    from m8.discovery.hot_path_common import setup_quote_rpc

    calls: list = []

    def _fake_resolve(*, network=None, chain_id=None, env=None):
        calls.append({"network": network, "chain_id": chain_id})
        return "https://rpc.example/base", "alchemy", {"source": "productive_pool"}

    monkeypatch.setattr("core.rpc_urls.resolve_rpc_http", _fake_resolve)

    class _FakeWeb3:
        def __init__(self, provider):
            self.provider = provider

        HTTPProvider = staticmethod(lambda url, **kw: {"url": url, **kw})

    monkeypatch.setattr("web3.Web3", _FakeWeb3)

    w3, url, provider = setup_quote_rpc("base")
    assert w3 is not None
    assert url == "https://rpc.example/base"
    assert provider == "alchemy"
    assert calls and calls[0]["network"] == "base"


def test_run_live_ws_session_imports_setup_quote_rpc_for_quote_mode():
    """Guard: live WS quote path must use hot_path_common.setup_quote_rpc."""
    import inspect

    from m8.discovery.hot_path_ws import run_live_ws_session

    src = inspect.getsource(run_live_ws_session)
    assert "setup_quote_rpc" in src
