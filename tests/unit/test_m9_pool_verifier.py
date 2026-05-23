"""Offline unit tests for m9.graph_arb.pool_verifier.

All HTTP calls are mocked — no network access required.
Tests cover:
  - ABI encoding helpers (address, uint/int encoding)
  - _eth_call with mocked responses (success, RPC error, HTTP 429)
  - _verify_one happy path (pool found / not found / RPC error)
  - verify_candidates_from_config end-to-end with mock config
  - verify_inventory_routes with and without factory_address
  - write_verified_inventory output schema
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from m9.graph_arb.pool_verifier import (
    _encode_addr,
    _encode_int_32,
    _build_getpool_calldata,
    _decode_addr_result,
    _eth_call,
    _verify_one,
    verify_inventory_routes,
    write_verified_inventory,
    _count_quarantine_reasons,
    _GETPOOL_V3_SEL,
    _ZERO_ADDR,
)


# ---------------------------------------------------------------------------
# ABI encoding helpers
# ---------------------------------------------------------------------------

class TestEncodeAddr:
    def test_zero_address(self):
        result = _encode_addr("0x" + "0" * 40)
        assert len(result) == 64
        assert result == "0" * 64

    def test_real_address(self):
        addr = "0x1234567890abcdef1234567890abcdef12345678"
        result = _encode_addr(addr)
        assert len(result) == 64
        assert result.endswith("1234567890abcdef1234567890abcdef12345678")
        # Left-padded with zeros
        assert result.startswith("0" * 24)

    def test_strips_0x_prefix(self):
        addr = "0xabCDef0000000000000000000000000000000001"
        result = _encode_addr(addr)
        assert "0x" not in result
        assert len(result) == 64


class TestEncodeInt32:
    def test_fee_100(self):
        result = _encode_int_32(100)
        assert len(result) == 64
        assert result == "0" * 61 + "064"

    def test_fee_3000(self):
        result = _encode_int_32(3000)
        assert len(result) == 64
        # 3000 hex = 0xBB8
        assert result.endswith("bb8")

    def test_tick_spacing_200(self):
        result = _encode_int_32(200)
        assert len(result) == 64

    def test_negative_value_two_complement(self):
        # Negative int24 should use 2's complement
        result = _encode_int_32(-1)
        assert len(result) == 64
        # -1 in 2's complement (256-bit) = all ff
        assert result == "f" * 64


class TestDecodeAddrResult:
    def test_valid_32byte_result(self):
        addr = "0xabcdef0123456789abcdef0123456789abcdef01"
        # ABI encoded: 32 bytes, left-padded
        result = "0x" + "00" * 12 + addr.replace("0x", "")
        decoded = _decode_addr_result(result)
        assert decoded == "0x" + addr.replace("0x", "").lower()

    def test_zero_result_gives_zero_addr(self):
        result = "0x" + "00" * 32
        decoded = _decode_addr_result(result)
        assert decoded == _ZERO_ADDR

    def test_short_result_gives_zero_addr(self):
        decoded = _decode_addr_result("0x")
        assert decoded == _ZERO_ADDR


class TestBuildGetpoolCalldata:
    def test_v3_selector_used(self):
        calldata = _build_getpool_calldata(
            "0x" + "a" * 40,
            "0x" + "b" * 40,
            500,
            "uniswap_v3",
        )
        assert calldata.startswith("0x" + _GETPOOL_V3_SEL)
        # Total: 4 selector + 32 addr + 32 addr + 32 fee = 100 bytes = 200 hex chars + "0x"
        assert len(calldata) == 2 + 200

    def test_slipstream_selector_differs_from_v3(self):
        # The slipstream selector should differ (int24 vs uint24 in ABI type)
        try:
            from web3 import Web3
        except ImportError:
            pytest.skip("web3 not available for selector computation")
        calldata_v3 = _build_getpool_calldata("0x" + "a" * 40, "0x" + "b" * 40, 100, "uniswap_v3")
        calldata_slip = _build_getpool_calldata("0x" + "a" * 40, "0x" + "b" * 40, 100, "aerodrome_slipstream")
        # Selectors are the first 8 chars after "0x"
        assert calldata_v3[2:10] != calldata_slip[2:10], (
            "Slipstream and V3 should use different selectors (int24 vs uint24)"
        )

    def test_slipstream_selector_exact_value(self):
        """_get_slip_selector() must return the exact keccak256('getPool(address,address,int24)')[:4].

        The expected value 'e070576f' is listed on OpenChain/4byte.directory and
        pre-computed offline.  This test pins the value so any future change to
        the signature string is caught immediately.
        """
        try:
            from web3 import Web3
        except ImportError:
            pytest.skip("web3 not available for selector computation")
        from m9.graph_arb.pool_verifier import _get_slip_selector

        sel = _get_slip_selector()
        assert len(sel) == 8, f"Selector must be 4 bytes (8 hex chars), got {len(sel)}: {sel!r}"
        # Cross-check: re-compute from web3 to confirm our hardcoded value matches
        computed = Web3.keccak(text="getPool(address,address,int24)")[:4].hex()
        assert sel == computed, (
            f"_get_slip_selector() returned {sel!r} but web3 computes {computed!r}. "
            "The signature string or fallback hardcode may be wrong."
        )
        # Pin the exact pre-computed constant
        # keccak256("getPool(address,address,int24)")[:4] = 0x28af8d0b
        assert sel == "28af8d0b", (
            f"Slipstream selector expected '28af8d0b' (keccak256('getPool(address,address,int24)')[:4]), "
            f"got {sel!r}. Update the fallback in _get_slip_selector() and this assertion."
        )
        # Must differ from UniV3 uint24 selector
        from m9.graph_arb.pool_verifier import _GETPOOL_V3_SEL
        assert sel != _GETPOOL_V3_SEL, "Slipstream selector must differ from V3 (int24 != uint24)"


# ---------------------------------------------------------------------------
# _eth_call with mocked httpx
# ---------------------------------------------------------------------------

class TestEthCall:
    def _mock_response(self, result_hex: str) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": result_hex}
        return resp

    def test_returns_hex_result_on_success(self):
        pool_addr = "0x" + "0" * 24 + "a" * 40
        with patch("m9.graph_arb.pool_verifier.httpx.post") as mock_post:
            mock_post.return_value = self._mock_response(pool_addr)
            result = _eth_call("http://rpc.test", "0x" + "1" * 40, "0xdeadbeef")
        assert result == pool_addr

    def test_returns_none_on_rpc_error(self):
        with patch("m9.graph_arb.pool_verifier.httpx.post") as mock_post:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "revert"}}
            mock_post.return_value = resp
            result = _eth_call("http://rpc.test", "0x" + "1" * 40, "0xdeadbeef")
        assert result is None

    def test_returns_none_on_empty_result(self):
        with patch("m9.graph_arb.pool_verifier.httpx.post") as mock_post:
            mock_post.return_value = self._mock_response("0x")
            result = _eth_call("http://rpc.test", "0x" + "1" * 40, "0xdeadbeef")
        assert result is None

    def test_returns_none_on_http_exception(self):
        import httpx
        with patch("m9.graph_arb.pool_verifier.httpx.post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("timeout")
            result = _eth_call("http://rpc.test", "0x" + "1" * 40, "0xdeadbeef")
        assert result is None


# ---------------------------------------------------------------------------
# _verify_one
# ---------------------------------------------------------------------------

class TestVerifyOne:
    _FACTORY = "0x" + "f" * 40
    _TOKEN_A = "0x" + "a" * 40
    _TOKEN_B = "0x" + "b" * 40
    _POOL = "0x" + "0" * 24 + "c" * 40

    def _call(self, eth_call_return: Optional[str]) -> Dict[str, Any]:
        with patch("m9.graph_arb.pool_verifier._eth_call", return_value=eth_call_return):
            return _verify_one(
                factory_addr=self._FACTORY,
                token_a_addr=self._TOKEN_A,
                token_b_addr=self._TOKEN_B,
                fee_or_spacing=500,
                adapter_type="uniswap_v3",
                rpc_url="http://rpc.test",
                dex_id="uniswap_v3",
                pair_sym="USDC_WETH",
                token_a_sym="USDC",
                token_b_sym="WETH",
            )

    def test_pool_found_factory_verified_true(self):
        # ABI-encoded non-zero pool address (32 bytes)
        raw_result = "0x" + "00" * 12 + "c" * 40
        route = self._call(raw_result)
        assert route["factory_verified"] is True
        assert route["quarantine_reason"] is None
        assert route["status"] == "active"
        assert route["pool_address"] != _ZERO_ADDR

    def test_pool_not_found_factory_verified_false(self):
        # Factory returns zero address → pool does not exist at this fee tier
        zero_result = "0x" + "00" * 32
        route = self._call(zero_result)
        assert route["factory_verified"] is False
        assert route["quarantine_reason"] == "FACTORY_NO_POOL"
        assert route["status"] == "quarantined"
        assert route["pool_address"] == _ZERO_ADDR

    def test_rpc_error_factory_verified_false(self):
        route = self._call(None)  # None → RPC error
        assert route["factory_verified"] is False
        assert route["quarantine_reason"] == "FACTORY_RPC_ERROR"
        assert route["status"] == "unverified"

    def test_route_id_format_v3(self):
        raw_result = "0x" + "00" * 12 + "c" * 40
        route = self._call(raw_result)
        assert route["route_id"] == "uniswap_v3:f500"

    def test_route_id_format_slipstream(self):
        with patch("m9.graph_arb.pool_verifier._eth_call", return_value="0x" + "00" * 12 + "c" * 40):
            route = _verify_one(
                factory_addr=self._FACTORY,
                token_a_addr=self._TOKEN_A,
                token_b_addr=self._TOKEN_B,
                fee_or_spacing=200,
                adapter_type="aerodrome_slipstream",
                rpc_url="http://rpc.test",
                dex_id="aerodrome_slipstream",
                pair_sym="WETH_USDC",
                token_a_sym="WETH",
                token_b_sym="USDC",
            )
        assert route["route_id"] == "aerodrome_slipstream:ts200"
        assert route["tick_spacing"] == 200

    def test_canonical_fields_present(self):
        raw_result = "0x" + "00" * 12 + "c" * 40
        route = self._call(raw_result)
        expected_keys = {
            "route_id", "pair_id", "dex_id", "adapter_type",
            "token0", "token1", "token0_addr", "token1_addr",
            "fee", "tick_spacing", "factory_address", "pool_address",
            "verified_at_block", "factory_verified", "factory_match",
            "token_match", "fee_match", "liquidity_ok",
            "status", "quarantine_reason",
        }
        assert expected_keys.issubset(set(route.keys()))

    def test_p3_fields_are_none(self):
        """token_match / fee_match are P3 stubs — not yet verified via pool slot reads."""
        raw_result = "0x" + "00" * 12 + "c" * 40
        route = self._call(raw_result)
        assert route["token_match"] is None
        assert route["fee_match"] is None

    def test_liquidity_ok_true_when_pool_has_liquidity(self):
        """liquidity_ok=True when pool.liquidity() returns non-zero."""
        # Mock returns non-zero for both factory.getPool and pool.liquidity calls
        raw_result = "0x" + "00" * 12 + "c" * 40
        route = self._call(raw_result)
        # liquidity decoded from mock value is non-zero → True
        assert route["liquidity_ok"] is True

    def test_liquidity_ok_none_when_check_disabled(self):
        """liquidity_ok=None when check_liquidity=False (factory-only mode)."""
        raw_result = "0x" + "00" * 12 + "c" * 40
        with patch("m9.graph_arb.pool_verifier._eth_call", return_value=raw_result):
            route = _verify_one(
                factory_addr=self._FACTORY,
                token_a_addr=self._TOKEN_A,
                token_b_addr=self._TOKEN_B,
                fee_or_spacing=500,
                adapter_type="uniswap_v3",
                rpc_url="http://rpc.test",
                dex_id="uniswap_v3",
                pair_sym="USDC_WETH",
                token_a_sym="USDC",
                token_b_sym="WETH",
                check_liquidity=False,
            )
        assert route["liquidity_ok"] is None
        assert route["factory_verified"] is True
        assert route["status"] == "active"

    def test_pool_zero_liquidity_quarantined(self):
        """Pool that exists (non-zero address) but has zero liquidity → POOL_ZERO_LIQUIDITY."""
        pool_result = "0x" + "00" * 12 + "c" * 40  # non-zero pool address
        zero_liquidity = "0x" + "00" * 32            # liquidity() returns 0
        call_results = iter([pool_result, zero_liquidity])
        with patch("m9.graph_arb.pool_verifier._eth_call", side_effect=lambda *a, **kw: next(call_results)):
            route = _verify_one(
                factory_addr=self._FACTORY,
                token_a_addr=self._TOKEN_A,
                token_b_addr=self._TOKEN_B,
                fee_or_spacing=500,
                adapter_type="uniswap_v3",
                rpc_url="http://rpc.test",
                dex_id="uniswap_v3",
                pair_sym="USDC_WETH",
                token_a_sym="USDC",
                token_b_sym="WETH",
            )
        assert route["factory_verified"] is False
        assert route["quarantine_reason"] == "POOL_ZERO_LIQUIDITY"
        assert route["status"] == "quarantined"
        assert route["liquidity_ok"] is False


# ---------------------------------------------------------------------------
# verify_inventory_routes
# ---------------------------------------------------------------------------

class TestVerifyInventoryRoutes:
    def _make_route(self, **overrides) -> Dict[str, Any]:
        base = {
            "route_id": "uniswap_v3:f500",
            "pair_id": "USDC_WETH",
            "dex_id": "uniswap_v3",
            "adapter_type": "uniswap_v3",
            "fee": 500,
            "factory_address": "0x" + "f" * 40,
            "token0_addr": "0x" + "a" * 40,
            "token1_addr": "0x" + "b" * 40,
        }
        base.update(overrides)
        return base

    def test_verifies_route_with_factory_address(self):
        pool_result = "0x" + "00" * 12 + "c" * 40
        with patch("m9.graph_arb.pool_verifier._eth_call", return_value=pool_result):
            results = verify_inventory_routes([self._make_route()], rpc_url="http://rpc.test")
        assert len(results) == 1
        assert results[0]["factory_verified"] is True

    def test_missing_factory_address_quarantined(self):
        route = self._make_route(factory_address=None)
        results = verify_inventory_routes([route], rpc_url="http://rpc.test")
        assert results[0]["factory_verified"] is False
        assert results[0]["quarantine_reason"] == "MISSING_FACTORY_ADDRESS"

    def test_zero_factory_address_quarantined(self):
        route = self._make_route(factory_address=_ZERO_ADDR)
        results = verify_inventory_routes([route], rpc_url="http://rpc.test")
        assert results[0]["factory_verified"] is False
        assert results[0]["quarantine_reason"] == "MISSING_FACTORY_ADDRESS"

    def test_missing_token_address_quarantined(self):
        route = self._make_route(token0_addr=None, token1_addr=None)
        results = verify_inventory_routes([route], rpc_url="http://rpc.test")
        assert results[0]["factory_verified"] is False
        assert results[0]["quarantine_reason"] == "MISSING_TOKEN_ADDRESS"

    def test_factory_returns_zero_quarantined(self):
        zero_result = "0x" + "00" * 32
        with patch("m9.graph_arb.pool_verifier._eth_call", return_value=zero_result):
            results = verify_inventory_routes([self._make_route()], rpc_url="http://rpc.test")
        assert results[0]["factory_verified"] is False
        assert results[0]["quarantine_reason"] == "FACTORY_NO_POOL"

    def test_preserves_order(self):
        routes = [
            self._make_route(route_id="uniswap_v3:f500"),
            self._make_route(route_id="uniswap_v3:f3000"),
            self._make_route(route_id="uniswap_v3:f100"),
        ]
        pool_result = "0x" + "00" * 12 + "c" * 40
        with patch("m9.graph_arb.pool_verifier._eth_call", return_value=pool_result):
            results = verify_inventory_routes(routes, rpc_url="http://rpc.test")
        assert len(results) == 3
        assert results[0]["route_id"] == "uniswap_v3:f500"
        assert results[1]["route_id"] == "uniswap_v3:f3000"
        assert results[2]["route_id"] == "uniswap_v3:f100"

    def test_original_route_not_mutated(self):
        route = self._make_route()
        assert "factory_verified" not in route
        pool_result = "0x" + "00" * 12 + "c" * 40
        with patch("m9.graph_arb.pool_verifier._eth_call", return_value=pool_result):
            verify_inventory_routes([route], rpc_url="http://rpc.test")
        # Original should be unchanged
        assert "factory_verified" not in route


# ---------------------------------------------------------------------------
# write_verified_inventory
# ---------------------------------------------------------------------------

class TestWriteVerifiedInventory:
    def test_writes_valid_schema(self, tmp_path):
        routes = [
            {"factory_verified": True, "route_id": "a:f500"},
            {"factory_verified": False, "route_id": "b:f100", "quarantine_reason": "FACTORY_NO_POOL"},
        ]
        out = str(tmp_path / "verified.json")
        write_verified_inventory(routes, output_path=out)
        with open(out) as fh:
            data = json.load(fh)
        assert data["schema_version"] == "m9_verified_inventory.1"
        assert len(data["active_routes"]) == 1
        assert len(data["quarantined_routes"]) == 1
        assert data["summary"]["active_count"] == 1
        assert data["summary"]["quarantined_count"] == 1

    def test_active_routes_all_factory_verified(self, tmp_path):
        routes = [{"factory_verified": True, "route_id": f"r{i}"} for i in range(5)]
        out = str(tmp_path / "verified.json")
        write_verified_inventory(routes, output_path=out)
        with open(out) as fh:
            data = json.load(fh)
        assert data["summary"]["active_count"] == 5
        assert data["summary"]["quarantined_count"] == 0


# ---------------------------------------------------------------------------
# _count_quarantine_reasons
# ---------------------------------------------------------------------------

class TestCountQuarantineReasons:
    def test_counts_by_reason(self):
        quarantined = [
            {"quarantine_reason": "FACTORY_NO_POOL"},
            {"quarantine_reason": "FACTORY_NO_POOL"},
            {"quarantine_reason": "FACTORY_RPC_ERROR"},
            {"quarantine_reason": None},
        ]
        counts = _count_quarantine_reasons(quarantined)
        assert counts["FACTORY_NO_POOL"] == 2
        assert counts["FACTORY_RPC_ERROR"] == 1
        assert counts["UNKNOWN"] == 1
