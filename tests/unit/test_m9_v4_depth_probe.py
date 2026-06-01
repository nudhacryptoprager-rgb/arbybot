"""Unit tests for V4 depth probe support in pool_depth_probe.py.

Covers:
  - _encode_v4_call_depth: selector, sort order, hookData
  - _decode_v4_response_depth: V4 Quoter amountOut decoding
  - probe_pool_depth with uniswap_v4 adapter (happy path, missing tick_spacing, revert)
  - probe_route_marginal_depth with uniswap_v4 adapter (no longer returns V4_DEPTH_UNSUPPORTED)
"""
from __future__ import annotations

import pytest

from m8_1.stable_anchor import quote_probe as stable_quote_probe
from m9.graph_arb import pool_depth_probe as probe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Token addresses: addr_a < addr_b ensures deterministic sort in tests
_ADDR_A = "0x" + "00" * 19 + "aa"  # lower address → currency0 when zeroForOne
_ADDR_B = "0x" + "00" * 19 + "bb"  # higher address → currency1

_QUOTER = "0x" + "cc" * 20
_POOL   = "0x" + "dd" * 20
_FEE    = 3000
_TS     = 60


def _build_v4_response(amount_out: int, gas_estimate: int = 12345) -> str:
    """Build a minimal valid V4 Quoter response hex string.

    V4Quoter.quoteExactInputSingle returns ``(uint256 amountOut, uint256 gasEstimate)``.
    """
    raw = amount_out.to_bytes(32, "big") + gas_estimate.to_bytes(32, "big")
    return "0x" + raw.hex()


# ---------------------------------------------------------------------------
# Tests: _encode_v4_call_depth
# ---------------------------------------------------------------------------

class TestEncodeV4CallDepth:
    def test_selector_prefix(self):
        calldata, _ = probe._encode_v4_call_depth(_ADDR_A, _ADDR_B, _FEE, _TS, None, 100)
        # First 4 bytes (8 hex chars) after '0x' = aa9d21cb
        assert calldata.startswith("0xaa9d21cb"), f"wrong selector: {calldata[:10]}"

    def test_zero_for_one_when_addr_a_lower(self):
        # _ADDR_A < _ADDR_B by construction → zeroForOne = True
        _, zfo = probe._encode_v4_call_depth(_ADDR_A, _ADDR_B, _FEE, _TS, None, 100)
        assert zfo is True

    def test_one_for_zero_when_addr_b_lower(self):
        # swapped: token_in has higher address → zeroForOne = False
        _, zfo = probe._encode_v4_call_depth(_ADDR_B, _ADDR_A, _FEE, _TS, None, 100)
        assert zfo is False

    def test_hooks_none_uses_zero_address(self):
        calldata, _ = probe._encode_v4_call_depth(_ADDR_A, _ADDR_B, _FEE, _TS, None, 100)
        # hooks word is at offset 4 (selector) + 4*32 = 132 bytes = 264 hex chars from 0x
        # Position in payload: bytes 4 + 4*32 = 132 → hex chars 8 + 256 = 264
        # word 4 (0-based) of payload = hooks
        payload_hex = calldata[2 + 8:]  # strip 0x and selector
        assert payload_hex[:64] == (32).to_bytes(32, "big").hex()
        # word0 is the top-level offset; struct word4 is hooks, so hooks is word5.
        hooks_word = payload_hex[5 * 64: 6 * 64]
        assert hooks_word == "0" * 64, f"hooks word not zero: {hooks_word}"

    def test_hooks_address_encoded(self):
        hooks = "0x" + "ee" * 20
        calldata, _ = probe._encode_v4_call_depth(_ADDR_A, _ADDR_B, _FEE, _TS, hooks, 100)
        payload_hex = calldata[2 + 8:]
        hooks_word = payload_hex[5 * 64: 6 * 64]
        expected = ("00" * 12) + "ee" * 20
        assert hooks_word.lower() == expected.lower()


# ---------------------------------------------------------------------------
# Tests: _decode_v4_response_depth
# ---------------------------------------------------------------------------

class TestDecodeV4ResponseDepth:
    def test_decodes_amount_out_first_word(self):
        resp = _build_v4_response(amount_out=490)
        result = probe._decode_v4_response_depth(resp, zero_for_one=True)
        assert result == 490

    def test_zero_for_one_does_not_change_uint_response(self):
        resp = _build_v4_response(amount_out=480)
        result = probe._decode_v4_response_depth(resp, zero_for_one=False)
        assert result == 480

    def test_short_response_raises(self):
        with pytest.raises(ValueError, match="too short"):
            probe._decode_v4_response_depth("0x" + "ab" * 10, zero_for_one=True)


class TestStableAnchorV4Abi:
    def test_stable_anchor_encoder_uses_top_level_struct_offset(self):
        calldata, _ = stable_quote_probe._encode_v4_call(
            _ADDR_A, _ADDR_B, _FEE, _TS, None, 100
        )
        payload_hex = calldata[2 + 8:]
        assert payload_hex[:64] == (32).to_bytes(32, "big").hex()

    def test_stable_anchor_decoder_returns_amount_and_gas(self):
        amount_out, gas_estimate = stable_quote_probe._decode_v4_response(
            _build_v4_response(amount_out=123, gas_estimate=456),
            zero_for_one=True,
        )
        assert amount_out == 123
        assert gas_estimate == 456


# ---------------------------------------------------------------------------
# Tests: probe_pool_depth with uniswap_v4 adapter
# ---------------------------------------------------------------------------

class TestProbePoolDepthV4:
    """Integration-style tests that mock _raw_eth_call."""

    _CONFIG_TOKENS = {
        "USDC": {"address": _ADDR_A, "decimals": 6},
        "WETH": {"address": _ADDR_B, "decimals": 18},
    }

    def _route(self, **overrides):
        base = {
            "pair_id": "USDC_WETH",
            "dex_id": "uniswap_v4_base",
            "adapter_type": "uniswap_v4",
            "fee": _FEE,
            "tick_spacing": _TS,
            "quoter_addr": _QUOTER,
            "pool_address": _POOL,
            "hooks": None,
        }
        base.update(overrides)
        return base

    def test_v4_happy_path_probe_ok(self, monkeypatch):
        """V4 depth probe succeeds when RPC returns valid response."""
        # USDC→WETH: amount_in ≈ 100 USDC (1e6 raw = tiny).
        # Build response: zeroForOne=True (USDC addr < WETH addr).
        # Simulate minimal price impact: return ~0.0000285 WETH for 100 USDC
        # at ETH=$3500 → expected_out ≈ 100/3500 * 1e18 ≈ 2.857e13
        expected_out_raw = int(100 / 3500 * 1e18)
        response = _build_v4_response(amount_out=expected_out_raw)

        monkeypatch.setattr(probe, "_raw_eth_call", lambda *a, **kw: response)
        result = probe.probe_pool_depth(self._route(), self._CONFIG_TOKENS, "http://rpc")

        assert result["probe_ok"] is True
        assert result["probe_error"] is None
        assert result["probe_amount_out"] == expected_out_raw

    def test_v4_missing_tick_spacing_returns_error(self, monkeypatch):
        monkeypatch.setattr(probe, "_raw_eth_call", lambda *a, **kw: "0x")
        route = self._route(tick_spacing=None)
        result = probe.probe_pool_depth(route, self._CONFIG_TOKENS, "http://rpc")
        assert result["probe_ok"] is False
        assert result["probe_error"] == "V4_MISSING_TICK_SPACING"

    def test_v4_rpc_revert_returns_quote_failed(self, monkeypatch):
        monkeypatch.setattr(probe, "_raw_eth_call", lambda *a, **kw: "0x")
        result = probe.probe_pool_depth(self._route(), self._CONFIG_TOKENS, "http://rpc")
        assert result["probe_ok"] is False
        assert result["probe_error"] == "QUOTE_FAILED_OR_REVERT"

    def test_v4_no_quoter_returns_no_quoter(self, monkeypatch):
        monkeypatch.setattr(probe, "_raw_eth_call", lambda *a, **kw: "0x")
        route = self._route(quoter_addr="", pool_address="")
        result = probe.probe_pool_depth(route, self._CONFIG_TOKENS, "http://rpc")
        assert result["probe_ok"] is False
        assert result["probe_error"] == "NO_QUOTER"


# ---------------------------------------------------------------------------
# Tests: probe_route_marginal_depth — V4 no longer returns V4_DEPTH_UNSUPPORTED
# ---------------------------------------------------------------------------

class TestProbeRouteMarginalDepthV4:
    """V4 adapter should now be quoted via marginal depth probe, not skipped."""

    _ROUTE = {
        "adapter_type": "uniswap_v4",
        "fee": _FEE,
        "tick_spacing": _TS,
        "quoter_addr": _QUOTER,
        "pool_address": _POOL,
        "hooks": None,
        "token0": "WETH",
        "token1": "EXOTIC",
        "token0_addr": _ADDR_B,  # WETH is anchor (higher addr here, but anchor by symbol)
        "token1_addr": "0x" + "ff" * 20,
    }

    def test_v4_no_longer_returns_v4_depth_unsupported(self, monkeypatch):
        """After the fix, V4 routes do NOT return V4_DEPTH_UNSUPPORTED."""
        # Mock RPC: return a valid V4 response for both ref and probe quotes
        weth_decimals = 18
        weth_price = 3500.0
        ref_size_usd = 2.0
        probe_size_usd = 100.0
        ref_in = int(ref_size_usd / weth_price * 1e18)
        probe_in = int(probe_size_usd / weth_price * 1e18)

        # Build ref and probe responses: WETH→EXOTIC, WETH addr is _ADDR_B (higher),
        # so zeroForOne depends on sort. Just return plausible non-zero amounts.
        call_count = [0]

        def _mock_call(rpc_url, to, data):
            call_count[0] += 1
            # Alternating ref / probe calls
            if call_count[0] % 2 == 1:
                # ref call: 10_000 exotic tokens out
                return _build_v4_response(amount_out=10_000)
            else:
                # probe call: 480_000 exotic tokens out (slight impact)
                return _build_v4_response(amount_out=480_000)

        monkeypatch.setattr(probe, "_raw_eth_call", _mock_call)
        result = probe.probe_route_marginal_depth(
            self._ROUTE, rpc_url="http://rpc"
        )
        # Must not return old unsupported error
        assert result.get("probe_error") != "V4_DEPTH_UNSUPPORTED", (
            "V4 depth should now be supported, got V4_DEPTH_UNSUPPORTED"
        )

    def test_v4_missing_tick_spacing_fails_gracefully(self, monkeypatch):
        """When tick_spacing is missing, probe returns None from _quote() → REF_QUOTE_FAILED."""
        monkeypatch.setattr(probe, "_raw_eth_call", lambda *a, **kw: "0x")
        route = dict(self._ROUTE)
        route["tick_spacing"] = None
        result = probe.probe_route_marginal_depth(route, rpc_url="http://rpc")
        assert result["probe_ok"] is False
        # tick_spacing=None → _quote returns None → REF_QUOTE_FAILED
        assert result["probe_error"] in ("REF_QUOTE_FAILED", "NO_QUOTER")
