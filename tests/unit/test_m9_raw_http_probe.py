"""Unit tests for m9.graph_arb.raw_http_probe — direct JSON-RPC quote backend.

Tests are fully offline: httpx calls are mocked via unittest.mock.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute
from m9.graph_arb.raw_http_probe import probe_quote_raw_http, _eth_call_raw


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_route(adapter: str = "uniswap_v3", fee: int = 500) -> DexRoute:
    return DexRoute(
        dex_id="test_dex",
        adapter_type=adapter,
        quoter="0xdeadbeef" + "0" * 32,
        fee=fee,
        tick_spacing=10 if adapter == "aerodrome_slipstream" else None,
        curve_coin0_sym=None,
    )


def _make_token(sym: str, addr: str = "0xabcdef" + "0" * 34, decimals: int = 18) -> TokenInfo:
    return TokenInfo(symbol=sym, address=addr, decimals=decimals)


def _mock_httpx_response(result_hex: str, status: int = 200) -> MagicMock:
    """Build a mock httpx.Response that returns a JSON-RPC result."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": result_hex}
    resp.raise_for_status = MagicMock()
    return resp


def _encode_uint256(n: int) -> str:
    """Encode a uint256 as a 64-char hex string (no 0x prefix)."""
    return format(n, "064x")


# ---------------------------------------------------------------------------
# Tests: _eth_call_raw helper
# ---------------------------------------------------------------------------

class TestEthCallRaw:
    def test_returns_hex_result(self):
        client = MagicMock()
        result_hex = "0x" + _encode_uint256(1234)
        client.post.return_value = _mock_httpx_response(result_hex)
        result = _eth_call_raw("https://example.com/rpc", "0xTO", "0xDATA", client)
        assert result == result_hex

    def test_raises_on_rpc_error(self):
        client = MagicMock()
        client.post.return_value.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32000, "message": "execution reverted"},
        }
        client.post.return_value.raise_for_status = MagicMock()
        with pytest.raises(ValueError, match="eth_call error"):
            _eth_call_raw("https://example.com/rpc", "0xTO", "0xDATA", client)


# ---------------------------------------------------------------------------
# Tests: probe_quote_raw_http — happy-path adapter types
# ---------------------------------------------------------------------------

class TestProbeQuoteRawHttp:

    def _call(self, adapter: str, result_hex: str, amount_in: int = 1_000_000) -> "QuoteResult":  # type: ignore[name-defined]
        route = _make_route(adapter)
        token_in = _make_token("USDC", decimals=6)
        token_out = _make_token("WETH", decimals=18)

        mock_resp = _mock_httpx_response(result_hex)
        with patch("m9.graph_arb.raw_http_probe._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_get_client.return_value = mock_client
            with patch("m9.graph_arb.raw_http_probe.rpc_throttle") as mock_throttle:
                mock_throttle.acquire = MagicMock()
                with patch("m9.graph_arb.raw_http_probe.provider_throttle") as mock_pt:
                    mock_pt.acquire.return_value = True
                    mock_pt.record_response = MagicMock()
                    return probe_quote_raw_http(
                        "https://rpc.example.com",
                        route, token_in, token_out, amount_in,
                    )

    def test_uniswap_v3_success(self):
        # Return 128 bytes: amount_out=5000, gas_estimate=100000
        amount_out_hex = _encode_uint256(5000)
        gas_hex = _encode_uint256(100_000)
        result_hex = "0x" + amount_out_hex + gas_hex
        result = self._call("uniswap_v3", result_hex)
        assert result.ok is True
        assert result.amount_out == 5000
        assert result.gas_estimate == 100_000
        assert result.reject_reason is None

    def test_aerodrome_v2_stable_success(self):
        amount_out_hex = "0x" + _encode_uint256(999_000)
        result = self._call("aerodrome_v2_stable", amount_out_hex)
        assert result.ok is True
        assert result.amount_out == 999_000

    def test_uniswap_v2_success(self):
        # getReserves returns [r0, r1, blockTimestamp] — we need 128 hex chars minimum
        r0 = 1_000_000_000
        r1 = 2_000_000_000
        result_hex = "0x" + _encode_uint256(r0) + _encode_uint256(r1) + _encode_uint256(0)
        amount_in = 1_000
        result = self._call("uniswap_v2", result_hex, amount_in=amount_in)
        assert result.ok is True
        # constant product: (1000 * 997 * r1) // (r0 * 1000 + 1000 * 997)
        expected = (amount_in * 997 * r1) // (r0 * 1000 + amount_in * 997)
        assert result.amount_out == expected

    def test_zero_output_returns_failed(self):
        result_hex = "0x" + _encode_uint256(0)
        result = self._call("uniswap_v3", result_hex)
        assert result.ok is False
        assert result.reject_reason == "QUOTE_ZERO_OUTPUT"

    def test_acquire_called_once_with_n1(self):
        """raw_http probe must call rpc_throttle.acquire(n=1), NOT n=2."""
        from m8_1.stable_anchor.pairs import TokenInfo as TI
        from m8_1.stable_anchor.pool_discovery import DexRoute as DR
        route = _make_route("uniswap_v3")
        token_in = _make_token("USDC", decimals=6)
        token_out = _make_token("WETH", decimals=18)
        result_hex = "0x" + _encode_uint256(1000) + _encode_uint256(50000)

        mock_resp = _mock_httpx_response(result_hex)
        with patch("m9.graph_arb.raw_http_probe._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_get_client.return_value = mock_client
            with patch("m9.graph_arb.raw_http_probe.rpc_throttle") as mock_throttle:
                mock_throttle.acquire = MagicMock()
                with patch("m9.graph_arb.raw_http_probe.provider_throttle") as mock_pt:
                    mock_pt.acquire.return_value = True
                    mock_pt.record_response = MagicMock()
                    probe_quote_raw_http(
                        "https://rpc.example.com",
                        route, token_in, token_out, 1_000_000,
                    )
                    mock_throttle.acquire.assert_called_once_with(n=1)

    def test_http_429_triggers_provider_throttle(self):
        """HTTP 429 response must be recorded in provider_throttle breaker."""
        import httpx as _httpx
        route = _make_route("uniswap_v3")
        token_in = _make_token("USDC", decimals=6)
        token_out = _make_token("WETH", decimals=18)

        with patch("m9.graph_arb.raw_http_probe._get_client") as mock_get_client:
            mock_client = MagicMock()
            # Simulate 429
            err_resp = MagicMock()
            err_resp.status_code = 429
            http_error = _httpx.HTTPStatusError("429", request=MagicMock(), response=err_resp)
            mock_client.post.side_effect = http_error
            mock_get_client.return_value = mock_client
            with patch("m9.graph_arb.raw_http_probe.rpc_throttle") as mock_throttle:
                mock_throttle.acquire = MagicMock()
                with patch("m9.graph_arb.raw_http_probe.provider_throttle") as mock_pt:
                    mock_pt.acquire.return_value = True
                    mock_pt.record_response = MagicMock()
                    result = probe_quote_raw_http(
                        "https://rpc.example.com",
                        route, token_in, token_out, 1_000_000,
                    )
                    assert result.ok is False
                    assert result.reject_reason == "QUOTE_RPC_ERROR"
                    mock_pt.record_response.assert_called_once_with(
                        "calls", status_code=429, ok=False
                    )

    def test_provider_throttle_cooldown_skips_probe(self):
        """When provider_throttle.acquire returns False (cooldown), probe returns error immediately."""
        route = _make_route("uniswap_v3")
        token_in = _make_token("USDC", decimals=6)
        token_out = _make_token("WETH", decimals=18)

        with patch("m9.graph_arb.raw_http_probe.provider_throttle") as mock_pt:
            mock_pt.acquire.return_value = False  # cooldown active
            with patch("m9.graph_arb.raw_http_probe._get_client") as mock_get_client:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client
                result = probe_quote_raw_http(
                    "https://rpc.example.com",
                    route, token_in, token_out, 1_000_000,
                )
                assert result.ok is False
                assert result.raw_error == "provider_throttle_cooldown"
                # httpx should NOT have been called
                mock_client.post.assert_not_called()

    def test_unsupported_adapter_returns_rpc_error(self):
        route = DexRoute(
            dex_id="x",
            adapter_type="balancer_stable",
            quoter="0xdeadbeef" + "0" * 32,
            fee=100,
            tick_spacing=None,
            curve_coin0_sym=None,
        )
        token_in = _make_token("USDC", decimals=6)
        token_out = _make_token("WETH", decimals=18)

        with patch("m9.graph_arb.raw_http_probe._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            with patch("m9.graph_arb.raw_http_probe.rpc_throttle") as mock_throttle:
                mock_throttle.acquire = MagicMock()
                with patch("m9.graph_arb.raw_http_probe.provider_throttle") as mock_pt:
                    mock_pt.acquire.return_value = True
                    mock_pt.record_response = MagicMock()
                    result = probe_quote_raw_http(
                        "https://rpc.example.com",
                        route, token_in, token_out, 1_000_000,
                    )
                    assert result.ok is False
                    # balancer_stable with no pool_id → config missing error
                    assert result.reject_reason == "QUOTE_CONFIG_MISSING__BALANCER_POOL_ID"

    def test_unsupported_adapter_does_not_trigger_provider_throttle(self):
        """NotImplementedError (unsupported adapter) must NOT record failure in provider_throttle.

        Recording code-level errors as HTTP failures causes the circuit-breaker
        to open prematurely and block 22k+ subsequent calls (smoke9 regression).
        """
        route = DexRoute(
            dex_id="x",
            adapter_type="balancer_stable",
            quoter="0xdeadbeef" + "0" * 32,
            fee=100,
            tick_spacing=None,
            curve_coin0_sym=None,
        )
        token_in = _make_token("USDC", decimals=6)
        token_out = _make_token("WETH", decimals=18)

        with patch("m9.graph_arb.raw_http_probe._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            with patch("m9.graph_arb.raw_http_probe.rpc_throttle") as mock_throttle:
                mock_throttle.acquire = MagicMock()
                with patch("m9.graph_arb.raw_http_probe.provider_throttle") as mock_pt:
                    mock_pt.acquire.return_value = True
                    mock_pt.record_response = MagicMock()
                    result = probe_quote_raw_http(
                        "https://rpc.example.com",
                        route, token_in, token_out, 1_000_000,
                    )
                    assert result.ok is False
                    # Circuit breaker MUST NOT be triggered for code-level errors
                    mock_pt.record_response.assert_not_called()

    def test_execution_revert_does_not_trigger_provider_throttle(self):
        """JSON-RPC execution reverted (ValueError) must NOT record failure in provider_throttle."""
        route = _make_route("uniswap_v3")
        token_in = _make_token("USDC", decimals=6)
        token_out = _make_token("WETH", decimals=18)

        with patch("m9.graph_arb.raw_http_probe._get_client") as mock_get_client:
            mock_client = MagicMock()
            # Simulate eth_call error (execution reverted)
            rpc_resp = MagicMock()
            rpc_resp.status_code = 200
            rpc_resp.raise_for_status = MagicMock()
            rpc_resp.json.return_value = {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32000, "message": "execution reverted"},
            }
            mock_client.post.return_value = rpc_resp
            mock_get_client.return_value = mock_client
            with patch("m9.graph_arb.raw_http_probe.rpc_throttle") as mock_throttle:
                mock_throttle.acquire = MagicMock()
                with patch("m9.graph_arb.raw_http_probe.provider_throttle") as mock_pt:
                    mock_pt.acquire.return_value = True
                    mock_pt.record_response = MagicMock()
                    result = probe_quote_raw_http(
                        "https://rpc.example.com",
                        route, token_in, token_out, 1_000_000,
                    )
                    assert result.ok is False
                    assert result.reject_reason == "QUOTE_REVERT"
                    # Execution revert is a contract error, NOT an HTTP/network error
                    mock_pt.record_response.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: module-level imports are stable
# ---------------------------------------------------------------------------

def test_raw_http_probe_module_importable():
    import m9.graph_arb.raw_http_probe as mod
    assert hasattr(mod, "probe_quote_raw_http")
    assert hasattr(mod, "_eth_call_raw")


def test_raw_http_probe_exports_callable():
    from m9.graph_arb.raw_http_probe import probe_quote_raw_http
    assert callable(probe_quote_raw_http)
