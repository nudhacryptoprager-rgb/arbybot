"""Test shields for the M8/8.1 → M9 bridge cross-DEX wiring.

Covers the adapters wired for the long-tail cross-curve bridge branch:
  - Algebra (Camelot V3 / QuickSwap V3) dynamic-fee quoter encode/decode
  - Algebra → bridge adapter_type mapping
  - Maverick V2 dispatch presence in quote_probe (web3 path)

These are contract tests: they lock the encoder selector, the response decode,
and the dispatch wiring so a future refactor cannot silently drop a DEX family.
"""
from __future__ import annotations

from m8_1.stable_anchor.quote_probe import (
    _ALGEBRA_SELECTOR,
    _decode_algebra_response,
    _encode_algebra_call,
)


class TestAlgebraEncoder:
    def test_selector_is_canonical(self):
        # keccak256("quoteExactInputSingle(address,address,uint256,uint160)")[:4]
        assert _ALGEBRA_SELECTOR.hex() == "2d9ebd1d"

    def test_encode_layout(self):
        token_in = "0x" + "11" * 20
        token_out = "0x" + "22" * 20
        amount_in = 1_000_000
        calldata = _encode_algebra_call(token_in, token_out, amount_in)
        raw = calldata[2:]
        # selector (4 bytes) + 4 * 32-byte words = 8 + 256 hex chars
        assert raw[:8] == "2d9ebd1d"
        assert len(raw) == 8 + 4 * 64
        # tokenIn right-aligned in word 0
        assert raw[8:8 + 64].endswith("11" * 20)
        # tokenOut right-aligned in word 1
        assert raw[8 + 64:8 + 128].endswith("22" * 20)
        # amountIn in word 2
        assert int(raw[8 + 128:8 + 192], 16) == amount_in
        # limitSqrtPrice (word 3) is zero
        assert int(raw[8 + 192:8 + 256], 16) == 0

    def test_decode_amount_out(self):
        amount_out = 987_654_321
        word0 = amount_out.to_bytes(32, "big").hex()
        word1 = (3000).to_bytes(32, "big").hex()  # dynamic fee output, ignored
        assert _decode_algebra_response("0x" + word0 + word1) == amount_out

    def test_decode_rejects_short_response(self):
        import pytest

        with pytest.raises(ValueError):
            _decode_algebra_response("0x" + "00" * 16)


class TestBridgeAdapterMapping:
    def test_algebra_family_mapped(self):
        from m9.graph_arb.bridge_builder import _DEX_ID_TO_ADAPTER_TYPE

        for dex_id in ("algebra", "camelot_v3", "quickswap_v3"):
            assert _DEX_ID_TO_ADAPTER_TYPE.get(dex_id) == "algebra", (
                f"{dex_id} must map to 'algebra' adapter_type so cross-curve "
                "long-tail tokens enter the M9 graph instead of quarantine"
            )

    def test_maverick_still_mapped(self):
        from m9.graph_arb.bridge_builder import _DEX_ID_TO_ADAPTER_TYPE

        assert _DEX_ID_TO_ADAPTER_TYPE.get("maverick_v2") == "maverick_v2"


class TestDispatchBranchesPresent:
    def test_quote_probe_handles_algebra_and_maverick(self):
        import inspect

        from m8_1.stable_anchor import quote_probe

        src = inspect.getsource(quote_probe.probe_quote)
        assert 'route.adapter_type == "algebra"' in src
        assert 'route.adapter_type == "maverick_v2"' in src

    def test_raw_http_probe_handles_algebra(self):
        import inspect

        from m9.graph_arb import raw_http_probe

        src = inspect.getsource(raw_http_probe)
        assert 'route.adapter_type == "algebra"' in src
