"""Unit tests for M9 pool depth probe pricing helpers."""
from __future__ import annotations

from m9.graph_arb import pool_depth_probe as probe


def _encoded_reserves(reserve0: int, reserve1: int) -> str:
    return "0x" + reserve0.to_bytes(32, "big").hex() + reserve1.to_bytes(32, "big").hex() + (0).to_bytes(32, "big").hex()


class TestV2FeeAwareAmountOut:
    def test_v2_fee_bps_changes_amount_out(self, monkeypatch):
        monkeypatch.setattr(
            probe,
            "_raw_eth_call",
            lambda rpc_url, to, data: _encoded_reserves(1_000_000, 2_000_000),
        )

        token0 = "0x" + "00" * 19 + "01"
        token1 = "0x" + "00" * 19 + "02"

        out_30_bps = probe._v2_amount_out_from_reserves(
            "0x" + "aa" * 20,
            token0,
            token1,
            10_000,
            "http://rpc",
            fee_bps=30,
        )
        out_20_bps = probe._v2_amount_out_from_reserves(
            "0x" + "aa" * 20,
            token0,
            token1,
            10_000,
            "http://rpc",
            fee_bps=20,
        )

        assert out_20_bps is not None
        assert out_30_bps is not None
        assert out_20_bps > out_30_bps

    def test_v2_reverse_token_order_uses_reverse_reserves(self, monkeypatch):
        monkeypatch.setattr(
            probe,
            "_raw_eth_call",
            lambda rpc_url, to, data: _encoded_reserves(1_000_000, 2_000_000),
        )

        token0 = "0x" + "00" * 19 + "01"
        token1 = "0x" + "00" * 19 + "02"

        forward = probe._v2_amount_out_from_reserves(
            "0x" + "aa" * 20,
            token0,
            token1,
            10_000,
            "http://rpc",
            fee_bps=30,
        )
        reverse = probe._v2_amount_out_from_reserves(
            "0x" + "aa" * 20,
            token1,
            token0,
            10_000,
            "http://rpc",
            fee_bps=30,
        )

        assert forward is not None
        assert reverse is not None
        assert forward > reverse

    def test_invalid_v2_fee_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            probe,
            "_raw_eth_call",
            lambda rpc_url, to, data: _encoded_reserves(1_000_000, 2_000_000),
        )

        amount_out = probe._v2_amount_out_from_reserves(
            "0x" + "aa" * 20,
            "0x" + "00" * 19 + "01",
            "0x" + "00" * 19 + "02",
            10_000,
            "http://rpc",
            fee_bps=10_000,
        )

        assert amount_out is None


class TestRouteV2FeeBps:
    def test_route_fee_takes_precedence(self):
        assert probe._route_v2_fee_bps({"fee": 25, "fee_bps": 30.0}) == 25

    def test_route_fee_bps_fallback(self):
        assert probe._route_v2_fee_bps({"fee": 0, "fee_bps": 20.0}) == 20

    def test_route_fee_default(self):
        assert probe._route_v2_fee_bps({"fee": 0}) == 30

    def test_route_fee_adapter_type_lookup(self):
        """Per-adapter-type map used when neither fee nor fee_bps present."""
        assert probe._route_v2_fee_bps({"adapter_type": "uniswap_v2"}) == 30
        assert probe._route_v2_fee_bps({"adapter_type": "sushiswap_v2"}) == 30
        assert probe._route_v2_fee_bps({"adapter_type": "baseswap_v2"}) == 30

    def test_route_fee_unknown_adapter_uses_global_default(self):
        """Unknown adapter type falls back to _DEFAULT_V2_FEE_BPS."""
        assert probe._route_v2_fee_bps({"adapter_type": "some_v2_fork"}) == 30


class TestVe33AdapterTypes:
    """Verify that _VE33_ADAPTER_TYPES includes all Solidly variants."""

    def test_generic_ve33_in_set(self):
        assert "ve33" in probe._VE33_ADAPTER_TYPES

    def test_ve33_stable_in_set(self):
        assert "ve33_stable" in probe._VE33_ADAPTER_TYPES

    def test_aerodrome_stable_in_set(self):
        """aerodrome_stable pools use the same getAmountOut(amount, tokenIn) interface."""
        assert "aerodrome_stable" in probe._VE33_ADAPTER_TYPES

    def test_solidly_stable_in_set(self):
        assert "solidly_stable" in probe._VE33_ADAPTER_TYPES

    def test_uniswap_v3_not_in_ve33_set(self):
        """uniswap_v3 uses a different quoter; must not be in VE33 adapter set."""
        assert "uniswap_v3" not in probe._VE33_ADAPTER_TYPES

    def test_uniswap_v2_not_in_ve33_set(self):
        """uniswap_v2 uses getReserves; must not be in VE33 adapter set."""
        assert "uniswap_v2" not in probe._VE33_ADAPTER_TYPES

