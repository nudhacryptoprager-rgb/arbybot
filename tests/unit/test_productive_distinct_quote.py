"""Productive quote path parity: discovery smoke vs M9 raw_http_probe."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dex.adapters.maverick_v2 import _SELECTOR_QUOTER_CALCULATE_SWAP
from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute
from m9.graph_arb.productive_distinct_quote import (
    balancer_index_row_tokens,
    quote_balancer_productive,
    quote_maverick_productive,
)
from m9.graph_arb.raw_http_probe import probe_quote_raw_http


_POOL_ID = "0x" + "ab" * 32
_TOKEN_A = "0x4200000000000000000000000000000000000006"
_TOKEN_B = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
_MAV_POOL = "0x" + "c" * 40


def _balancer_ok_hex(amount_in: int, amount_out: int) -> str:
    offset = 32
    length = 2
    d0 = amount_in % (2**256)
    d1 = (-amount_out) % (2**256)
    raw = (
        offset.to_bytes(32, "big")
        + length.to_bytes(32, "big")
        + d0.to_bytes(32, "big")
        + d1.to_bytes(32, "big")
    )
    return "0x" + raw.hex()


def _maverick_quoter_ok_hex(amount_in: int, amount_out: int, gas: int = 50_000) -> str:
    raw = (
        amount_in.to_bytes(32, "big")
        + amount_out.to_bytes(32, "big")
        + gas.to_bytes(32, "big")
    )
    return "0x" + raw.hex()


class TestProductiveDistinctQuote:
    def test_balancer_index_row_tokens_from_assets(self):
        row = {
            "assets": [_TOKEN_A, _TOKEN_B],
            "balances": [10**20, 10**12],
        }
        tin, tout, assets = balancer_index_row_tokens(row)
        assert tin == _TOKEN_A.lower()
        assert tout == _TOKEN_B.lower()
        assert assets == [_TOKEN_A.lower(), _TOKEN_B.lower()]

    def test_balancer_productive_uses_queries_contour(self):
        calls = []

        def eth_call(to: str, data: str) -> str:
            calls.append((to.lower(), data[:10]))
            if to.lower().endswith("548833"):
                return _balancer_ok_hex(10**6, 999_000)
            raise ValueError("vault revert")

        with patch(
            "m9.graph_arb.productive_distinct_quote._contract_has_code",
            return_value=True,
        ):
            amount_out, debug = quote_balancer_productive(
                eth_call,
                pool_id=_POOL_ID,
                token_in=_TOKEN_A,
                token_out=_TOKEN_B,
                amount_in=10**6,
                rpc_url="http://rpc.test",
            )
        assert amount_out == 999_000
        assert debug["quote_contour"] == "balancer_queries"
        assert debug["quote_selector"] == "0xf84d066e"
        assert calls[0][0].endswith("548833")

    def test_maverick_productive_uses_quoter_selector(self):
        calls = []

        def eth_call(to: str, data: str) -> str:
            calls.append(data[2:10])
            return _maverick_quoter_ok_hex(10_000, 8_000_000)

        amount_out, gas, debug = quote_maverick_productive(
            eth_call,
            pool_address=_MAV_POOL,
            amount_in=10_000,
            token_a_in=True,
        )
        assert amount_out == 8_000_000
        assert debug["quote_contour"] == "maverick_quoter"
        assert bytes.fromhex(calls[0]) == _SELECTOR_QUOTER_CALCULATE_SWAP

    @staticmethod
    def _maverick_token_a_in_flag(data: str) -> bool:
        body = data[2:] if data.startswith("0x") else data
        # selector(4) + pool(32) + amount(32) + tokenAIn(32)
        slot = body[8 + 64 + 64 : 8 + 64 + 64 + 64]
        return int(slot, 16) == 1

    def test_maverick_direction_token_in_equals_token_a(self):
        calls: list[bool] = []

        def eth_call(to: str, data: str) -> str:
            calls.append(self._maverick_token_a_in_flag(data))
            return _maverick_quoter_ok_hex(10_000, 1_000)

        quote_maverick_productive(
            eth_call,
            pool_address=_MAV_POOL,
            amount_in=10_000,
            token_a_in=False,
            token_in=_TOKEN_A,
            token_a=_TOKEN_A,
        )
        assert calls[0] is True

    def test_maverick_direction_token_in_not_token_a(self):
        calls: list[bool] = []

        def eth_call(to: str, data: str) -> str:
            calls.append(self._maverick_token_a_in_flag(data))
            return _maverick_quoter_ok_hex(10_000, 1_000)

        quote_maverick_productive(
            eth_call,
            pool_address=_MAV_POOL,
            amount_in=10_000,
            token_a_in=True,
            token_in=_TOKEN_B,
            token_a=_TOKEN_A,
        )
        assert calls[0] is False

    @patch("m9.graph_arb.raw_http_probe._eth_call_raw")
    def test_raw_http_maverick_matches_productive_path(self, mock_call):
        mock_call.return_value = _maverick_quoter_ok_hex(10_000, 5_000_000)
        route = DexRoute(
            dex_id="maverick_v2",
            adapter_type="maverick_v2",
            quoter=_MAV_POOL,
            fee=0,
            tick_spacing=0,
            curve_coin0_sym="",
            token_in_index=1,
        )
        result = probe_quote_raw_http(
            "http://rpc.test",
            route,
            TokenInfo(address=_TOKEN_A, symbol="WETH", decimals=18),
            TokenInfo(address=_TOKEN_B, symbol="USDC", decimals=6),
            10_000,
        )
        assert result.ok is True
        assert result.amount_out == 5_000_000
        assert result.quote_abi_path == "MaverickV2Quoter.calculateSwap"
        assert result.quote_selector == "0x" + _SELECTOR_QUOTER_CALCULATE_SWAP.hex()

    @patch("m9.graph_arb.raw_http_probe._eth_call_raw")
    def test_raw_http_balancer_matches_productive_path(self, mock_call):
        mock_call.return_value = _balancer_ok_hex(10**6, 500_000)

        def _side_effect(url, to, data, client):
            if to.lower().endswith("548833") or to.lower().startswith("0xba12"):
                return _balancer_ok_hex(10**6, 500_000)
            raise ValueError("no code")

        mock_call.side_effect = _side_effect
        route = DexRoute(
            dex_id="balancer_vault",
            adapter_type="balancer_weighted",
            quoter="0xba12222222228d8ba445958a75a0704d566bf2c8",
            fee=0,
            tick_spacing=0,
            curve_coin0_sym="",
            pool_id=_POOL_ID,
            vault_address="0xba12222222228d8ba445958a75a0704d566bf2c8",
        )
        with patch(
            "m9.graph_arb.productive_distinct_quote._contract_has_code",
            return_value=True,
        ):
            result = probe_quote_raw_http(
                "http://rpc.test",
                route,
                TokenInfo(address=_TOKEN_A, symbol="WETH", decimals=18),
                TokenInfo(address=_TOKEN_B, symbol="USDC", decimals=6),
                10**6,
            )
        assert result.ok is True
        assert result.amount_out == 500_000
        assert result.quote_abi_path == "queryBatchSwap"
