"""Unit tests for anvil_fork backend routing in M9 quoter.

Ensures that BACKEND_ANVIL_FORK never uses the external RPC URL
(e.g. BASE_RPC / dRPC lb.drpc.live) and always routes to
ARBY_ANVIL_RPC_URL or http://127.0.0.1:8545.

GPT step 8: "Додати unit test: --quote-backend anvil_fork не використовує зовнішній RPC URL."
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from m9.graph_arb.quoter import BACKEND_ANVIL_FORK, BACKEND_DIRECT_HTTP, BACKEND_RAW_HTTP, _probe_leg
from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXTERNAL_RPC = "https://lb.drpc.live/base/SomeKey"
_ANVIL_DEFAULT = "http://127.0.0.1:8545"
_ANVIL_CUSTOM = "http://localhost:9999"


def _make_route(dex_id: str = "uniswap_v3") -> DexRoute:
    return DexRoute(
        dex_id=dex_id,
        adapter_type="uniswap_v3",
        quoter="0xdeadbeef" + "0" * 32,
        fee=500,
        tick_spacing=10,
        curve_coin0_sym=None,
    )


def _make_token(sym: str = "USDC", decimals: int = 6) -> TokenInfo:
    addr = "0xabcdef" + "0" * 34
    return TokenInfo(symbol=sym, address=addr, decimals=decimals)


# ---------------------------------------------------------------------------
# Tests: anvil_fork always uses local URL, never external
# ---------------------------------------------------------------------------

class TestAnvilForkRouting:
    """BACKEND_ANVIL_FORK must ignore rpc_url and use local Anvil endpoint."""

    def test_anvil_fork_default_url_when_env_not_set(self):
        """Without ARBY_ANVIL_RPC_URL, must use http://127.0.0.1:8545."""
        route = _make_route()
        token_in = _make_token("USDC")
        token_out = _make_token("WETH", decimals=18)
        w3_mock = MagicMock()

        captured_urls = []

        def mock_probe(rpc_url, route, token_in, token_out, amount_in, **kwargs):
            captured_urls.append(rpc_url)
            r = MagicMock()
            r.ok = True
            r.amount_out = 999
            r.error = None
            return r

        env_no_anvil = {k: v for k, v in os.environ.items() if k != "ARBY_ANVIL_RPC_URL"}

        with patch.dict(os.environ, env_no_anvil, clear=True):
            with patch("m9.graph_arb.raw_http_probe.probe_quote_raw_http", side_effect=mock_probe):
                _probe_leg(w3_mock, route, token_in, token_out, 1_000_000,
                           quote_backend=BACKEND_ANVIL_FORK,
                           rpc_url=_EXTERNAL_RPC)  # external URL passed — must be IGNORED

        assert len(captured_urls) == 1
        assert captured_urls[0] == _ANVIL_DEFAULT, (
            f"Expected {_ANVIL_DEFAULT!r}, got {captured_urls[0]!r}. "
            "anvil_fork must NOT use external RPC even when rpc_url is provided."
        )

    def test_anvil_fork_uses_env_var_when_set(self):
        """ARBY_ANVIL_RPC_URL env var overrides the default localhost:8545."""
        route = _make_route()
        token_in = _make_token("USDC")
        token_out = _make_token("WETH", decimals=18)
        w3_mock = MagicMock()

        captured_urls = []

        def mock_probe(rpc_url, route, token_in, token_out, amount_in, **kwargs):
            captured_urls.append(rpc_url)
            r = MagicMock()
            r.ok = True
            r.amount_out = 999
            r.error = None
            return r

        with patch.dict(os.environ, {"ARBY_ANVIL_RPC_URL": _ANVIL_CUSTOM}):
            with patch("m9.graph_arb.raw_http_probe.probe_quote_raw_http", side_effect=mock_probe):
                _probe_leg(w3_mock, route, token_in, token_out, 1_000_000,
                           quote_backend=BACKEND_ANVIL_FORK,
                           rpc_url=_EXTERNAL_RPC)  # external URL — must be IGNORED

        assert len(captured_urls) == 1
        assert captured_urls[0] == _ANVIL_CUSTOM, (
            f"Expected {_ANVIL_CUSTOM!r} from env var, got {captured_urls[0]!r}"
        )

    def test_anvil_fork_does_not_call_external_rpc(self):
        """The external dRPC URL must never be passed to probe_quote_raw_http for anvil_fork."""
        route = _make_route()
        token_in = _make_token("USDC")
        token_out = _make_token("WETH", decimals=18)
        w3_mock = MagicMock()

        captured_urls = []

        def mock_probe(rpc_url, route, token_in, token_out, amount_in, **kwargs):
            captured_urls.append(rpc_url)
            r = MagicMock()
            r.ok = True
            r.amount_out = 999
            r.error = None
            return r

        env_no_anvil = {k: v for k, v in os.environ.items() if k != "ARBY_ANVIL_RPC_URL"}

        with patch.dict(os.environ, env_no_anvil, clear=True):
            with patch("m9.graph_arb.raw_http_probe.probe_quote_raw_http", side_effect=mock_probe):
                _probe_leg(w3_mock, route, token_in, token_out, 1_000_000,
                           quote_backend=BACKEND_ANVIL_FORK,
                           rpc_url=_EXTERNAL_RPC)

        assert _EXTERNAL_RPC not in captured_urls, (
            "External dRPC URL must NOT be passed to probe_quote_raw_http for anvil_fork backend"
        )

    def test_anvil_fork_does_not_call_web3_probe(self):
        """BACKEND_ANVIL_FORK must not invoke probe_quote (web3 path)."""
        route = _make_route()
        token_in = _make_token("USDC")
        token_out = _make_token("WETH", decimals=18)
        w3_mock = MagicMock()

        env_no_anvil = {k: v for k, v in os.environ.items() if k != "ARBY_ANVIL_RPC_URL"}

        with patch.dict(os.environ, env_no_anvil, clear=True):
            with patch("m9.graph_arb.raw_http_probe.probe_quote_raw_http") as mock_raw:
                with patch("m8_1.stable_anchor.quote_probe.probe_quote") as mock_web3:
                    mock_raw.return_value = MagicMock(ok=True, amount_out=999, error=None)
                    _probe_leg(w3_mock, route, token_in, token_out, 1_000_000,
                               quote_backend=BACKEND_ANVIL_FORK,
                               rpc_url=_EXTERNAL_RPC)

        mock_web3.assert_not_called()
        mock_raw.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: raw_http still uses the provided rpc_url (regression guard)
# ---------------------------------------------------------------------------

class TestRawHttpRouting:
    """BACKEND_RAW_HTTP must still use the passed rpc_url."""

    def test_raw_http_uses_provided_rpc_url(self):
        route = _make_route()
        token_in = _make_token("USDC")
        token_out = _make_token("WETH", decimals=18)
        w3_mock = MagicMock()

        captured_urls = []

        def mock_probe(rpc_url, route, token_in, token_out, amount_in, **kwargs):
            captured_urls.append(rpc_url)
            r = MagicMock()
            r.ok = True
            r.amount_out = 999
            r.error = None
            return r

        with patch("m9.graph_arb.raw_http_probe.probe_quote_raw_http", side_effect=mock_probe):
            _probe_leg(w3_mock, route, token_in, token_out, 1_000_000,
                       quote_backend=BACKEND_RAW_HTTP,
                       rpc_url=_EXTERNAL_RPC)

        assert captured_urls == [_EXTERNAL_RPC], (
            "raw_http must use the provided rpc_url (not override with localhost)"
        )

    def test_raw_http_raises_if_no_rpc_url(self):
        route = _make_route()
        token_in = _make_token("USDC")
        token_out = _make_token("WETH", decimals=18)
        w3_mock = MagicMock()

        with pytest.raises(ValueError, match="rpc_url is required for raw_http"):
            _probe_leg(w3_mock, route, token_in, token_out, 1_000_000,
                       quote_backend=BACKEND_RAW_HTTP,
                       rpc_url=None)


# ---------------------------------------------------------------------------
# Tests: direct_http uses web3 probe (regression guard)
# ---------------------------------------------------------------------------

class TestDirectHttpRouting:
    """BACKEND_DIRECT_HTTP must use probe_quote (web3 path)."""

    def test_direct_http_calls_web3_probe(self):
        route = _make_route()
        token_in = _make_token("USDC")
        token_out = _make_token("WETH", decimals=18)
        w3_mock = MagicMock()

        with patch("m9.graph_arb.quoter.probe_quote") as mock_web3:
            mock_web3.return_value = MagicMock(ok=True, amount_out=999, error=None)
            _probe_leg(w3_mock, route, token_in, token_out, 1_000_000,
                       quote_backend=BACKEND_DIRECT_HTTP,
                       rpc_url=_EXTERNAL_RPC)

        mock_web3.assert_called_once()

    def test_direct_http_does_not_call_raw_http_probe(self):
        route = _make_route()
        token_in = _make_token("USDC")
        token_out = _make_token("WETH", decimals=18)
        w3_mock = MagicMock()

        with patch("m9.graph_arb.quoter.probe_quote") as mock_web3:
            with patch("m9.graph_arb.raw_http_probe.probe_quote_raw_http") as mock_raw:
                mock_web3.return_value = MagicMock(ok=True, amount_out=999, error=None)
                _probe_leg(w3_mock, route, token_in, token_out, 1_000_000,
                           quote_backend=BACKEND_DIRECT_HTTP,
                           rpc_url=_EXTERNAL_RPC)

        mock_raw.assert_not_called()
