"""RPC resolver contract for m9_quote_route_diagnostic (must match M9 runner)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "m9_quote_route_diagnostic.py"


def _load_diagnostic_module():
    spec = importlib.util.spec_from_file_location("m9_quote_route_diagnostic", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["m9_quote_route_diagnostic"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestResolveDiagnosticRpc:
    def test_uses_base_rpc_env_not_mainnet_fallback(self):
        mod = _load_diagnostic_module()
        env = {
            "BASE_RPC": "https://base.publicnode.com",
        }
        url, provider, diag = mod.resolve_diagnostic_rpc("base", env=env)
        assert "publicnode.com" in url
        assert url != "https://mainnet.base.org"
        assert diag.get("source", "").startswith("chain_env_")

    def test_network_only_without_base_rpc_hits_mainnet_fallback(self):
        """Empty env + network only skips BASE_RPC and uses public fallback list."""
        from core.rpc_urls import resolve_rpc_http

        url, _provider, _diag = resolve_rpc_http(network="base", env={})
        assert url == "https://mainnet.base.org"

    def test_positional_string_chain_id_is_invalid(self):
        from core.rpc_urls import resolve_rpc_http

        with pytest.raises(ValueError):
            resolve_rpc_http("base")  # noqa: old diagnostic bug shape

    def test_chain_id_kwarg_matches_runner(self):
        mod = _load_diagnostic_module()
        from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID

        env = {"BASE_RPC": "https://base.publicnode.com"}
        url_diag, _, _ = mod.resolve_diagnostic_rpc("base", env=env)
        url_ref, _, _ = resolve_rpc_http(
            chain_id=_CHAIN_KEY_TO_ID["base"],
            network="base",
            env=env,
        )
        assert url_diag == url_ref
