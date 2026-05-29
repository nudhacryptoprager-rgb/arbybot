"""Unit tests for Maverick V2 adapter skeleton (dex/adapters/maverick_v2.py).

Verified contracts:
  - ADAPTER_TYPE == "maverick_v2"
  - MAVERICK_V2_FACTORY_ADDRESS is a valid checksummed-style hex address
  - MAVERICK_V2_POOL_INFO_ADDRESS is a valid checksummed-style hex address
  - MaverickV2Adapter initialises without raising when enabled=False
  - get_quote() raises QuoteError(POOL_DISABLED) in disabled mode
  - supports_fee_tiers() returns False
  - cost_model knows maverick_v2 with cost 9 bps
  - adapter_pricing_model() returns "maverick_directional"
"""
from __future__ import annotations

import pytest

from dex.adapters.maverick_v2 import (
    MaverickV2Adapter,
    MAVERICK_V2_FACTORY_ADDRESS,
    MAVERICK_V2_POOL_INFO_ADDRESS,
)
from core.exceptions import QuoteError


_POOL_ADDR = "0x" + "a" * 40
_TOKEN_IN = "0x" + "1" * 40
_TOKEN_OUT = "0x" + "2" * 40


class TestMaverickV2AdapterConstants:
    """Verify module-level constants are sane."""

    def test_factory_address_format(self):
        assert MAVERICK_V2_FACTORY_ADDRESS.startswith("0x")
        assert len(MAVERICK_V2_FACTORY_ADDRESS) == 42

    def test_pool_info_address_format(self):
        assert MAVERICK_V2_POOL_INFO_ADDRESS.startswith("0x")
        assert len(MAVERICK_V2_POOL_INFO_ADDRESS) == 42


class TestMaverickV2AdapterInit:
    """Verify adapter initialises cleanly in disabled state."""

    def test_adapter_type_constant(self):
        assert MaverickV2Adapter.ADAPTER_TYPE == "maverick_v2"

    def test_init_disabled_no_raise(self):
        adapter = MaverickV2Adapter(provider=None, enabled=False)
        assert adapter.enabled is False

    def test_init_default_is_disabled(self):
        adapter = MaverickV2Adapter(provider=None)
        assert adapter.enabled is False

    def test_supports_fee_tiers_false(self):
        adapter = MaverickV2Adapter(provider=None)
        assert adapter.supports_fee_tiers() is False


class TestMaverickV2AdapterGetQuoteDisabled:
    """Verify get_quote() raises POOL_DISABLED in skeleton mode."""

    def test_get_quote_raises_pool_disabled(self):
        adapter = MaverickV2Adapter(provider=None, enabled=False)
        with pytest.raises(QuoteError) as exc_info:
            adapter.get_quote(
                pool_address=_POOL_ADDR,
                token_in=_TOKEN_IN,
                token_out=_TOKEN_OUT,
                amount_in=1_000_000,
            )
        from core.exceptions import ErrorCode
        assert exc_info.value.code == ErrorCode.POOL_DISABLED

    def test_get_quote_raises_with_block_number(self):
        adapter = MaverickV2Adapter(provider=None, enabled=False)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address=_POOL_ADDR,
                token_in=_TOKEN_IN,
                token_out=_TOKEN_OUT,
                amount_in=500_000,
                block_number=12345678,
            )


class TestMaverickV2CostModel:
    """Verify cost_model.py includes maverick_v2 with correct values."""

    def test_cost_model_knows_maverick_v2(self):
        from m9.graph_arb.cost_model import adapter_cost_bps
        cost = adapter_cost_bps("maverick_v2")
        assert cost == 9.0, f"Expected maverick_v2 cost=9.0 bps, got {cost}"

    def test_pricing_model_is_maverick_directional(self):
        from m9.graph_arb.cost_model import adapter_pricing_model
        pm = adapter_pricing_model("maverick_v2")
        assert pm == "maverick_directional", (
            f"Expected pricing model 'maverick_directional', got {pm!r}"
        )
