"""Unit tests: rpc_throttle.acquire() is called by probe_quote (fix step #7)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from m8_1.stable_anchor.quote_probe import probe_quote
from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute


def _make_route(adapter_type: str = "uniswap_v3") -> DexRoute:
    return DexRoute(
        dex_id="uniswap_v3",
        adapter_type=adapter_type,
        quoter="0x" + "a" * 40,
        fee=500,
        tick_spacing=None,
        curve_coin0_sym=None,
    )


def _make_token(symbol: str = "USDC") -> TokenInfo:
    return TokenInfo(
        symbol=symbol,
        address="0x" + "b" * 40,
        decimals=6,
    )


def _make_w3(result: bytes = b"\x00" * 96) -> MagicMock:
    w3 = MagicMock()
    w3.eth.call.return_value = result
    return w3


class TestProbeQuoteCallsThrottle:
    """probe_quote must call rpc_throttle.acquire() exactly once per invocation."""

    def test_throttle_called_on_success(self):
        w3 = _make_w3(result=b"\x00" * 63 + b"\x01" + b"\x00" * 32)
        with patch("m8_1.stable_anchor.quote_probe.rpc_throttle") as mock_throttle:
            probe_quote(
                w3,
                _make_route("uniswap_v3"),
                _make_token("USDC"),
                _make_token("USDT"),
                1_000_000,
            )
        mock_throttle.acquire.assert_called_once()

    def test_throttle_called_on_rpc_error(self):
        """Even when eth_call raises, acquire() must be called first."""
        w3 = MagicMock()
        w3.eth.call.side_effect = Exception("HTTP 429 Too Many Requests")
        with patch("m8_1.stable_anchor.quote_probe.rpc_throttle") as mock_throttle:
            result = probe_quote(
                w3,
                _make_route("uniswap_v3"),
                _make_token("USDC"),
                _make_token("USDT"),
                1_000_000,
            )
        mock_throttle.acquire.assert_called_once()
        assert result.ok is False
        assert result.reject_reason == "QUOTE_RPC_ERROR"

    def test_throttle_called_for_slipstream(self):
        route = DexRoute(
            dex_id="aerodrome",
            adapter_type="aerodrome_slipstream",
            quoter="0x" + "c" * 40,
            fee=0,
            tick_spacing=100,
            curve_coin0_sym=None,
        )
        w3 = _make_w3(result=b"\x00" * 63 + b"\x01" + b"\x00" * 32)
        with patch("m8_1.stable_anchor.quote_probe.rpc_throttle") as mock_throttle:
            probe_quote(w3, route, _make_token("USDC"), _make_token("WETH"), 1_000_000)
        mock_throttle.acquire.assert_called_once()
