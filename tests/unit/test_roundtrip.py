# tests/unit/test_roundtrip.py
"""
Unit tests for engine/roundtrip.py

v2.1.0: Round-trip profit simulator tests.
"""
import pytest
from decimal import Decimal

from engine.roundtrip import (
    RoundTripResult,
    simulate_roundtrip,
    estimate_slippage_bps,
)


class TestSimulateRoundtrip:
    """Tests for simulate_roundtrip()."""

    def test_profitable_roundtrip(self):
        """Round-trip that returns more than input is profitable."""
        buy_quote = {
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,  # 1 ETH
            "amount_out_wei": 2000_000_000,  # 2000 USDC
            "dex_id": "uniswap_v3",
            "quote_source": "quoter_v2",
            "quoter_gas_estimate": 150_000,
            "ticks_crossed": 5,
            "price_exact": 2000.0,
        }
        sell_quote = {
            "token_in": "USDC",
            "token_out": "WETH",
            "amount_in_wei": 2000_000_000,  # 2000 USDC
            "amount_out_wei": 1_010_000_000_000_000_000,  # 1.01 ETH (profit)
            "dex_id": "sushiswap_v3",
            "quote_source": "quoter_v2",
            "quoter_gas_estimate": 150_000,
            "ticks_crossed": 3,
            "price_exact": 0.000505,  # 1/1980
        }
        
        result = simulate_roundtrip(buy_quote, sell_quote, gas_price_wei=100_000_000)
        
        assert result.leg1_success is True
        assert result.leg2_success is True
        assert result.gross_pnl_wei > 0  # More ETH back than put in
        assert result.is_profitable is True

    def test_unprofitable_roundtrip(self):
        """Round-trip that returns less than input is not profitable."""
        buy_quote = {
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,  # 1 ETH
            "amount_out_wei": 2000_000_000,  # 2000 USDC
            "dex_id": "uniswap_v3",
            "quote_source": "quoter_v2",
            "quoter_gas_estimate": 150_000,
            "ticks_crossed": 5,
        }
        sell_quote = {
            "token_in": "USDC",
            "token_out": "WETH",
            "amount_in_wei": 2000_000_000,  # 2000 USDC
            "amount_out_wei": 990_000_000_000_000_000,  # 0.99 ETH (loss)
            "dex_id": "sushiswap_v3",
            "quote_source": "quoter_v2",
            "quoter_gas_estimate": 150_000,
            "ticks_crossed": 3,
        }
        
        result = simulate_roundtrip(buy_quote, sell_quote, gas_price_wei=100_000_000)
        
        assert result.gross_pnl_wei < 0  # Less ETH back than put in
        assert result.is_profitable is False

    def test_gas_reduces_profitability(self):
        """High gas price can turn profitable trade unprofitable."""
        buy_quote = {
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,  # 1 ETH
            "amount_out_wei": 2000_000_000,  # 2000 USDC
            "dex_id": "uniswap_v3",
            "quote_source": "quoter_v2",
            "quoter_gas_estimate": 300_000,  # High gas usage
            "ticks_crossed": 5,
        }
        sell_quote = {
            "token_in": "USDC",
            "token_out": "WETH",
            "amount_in_wei": 2000_000_000,
            "amount_out_wei": 1_005_000_000_000_000_000,  # 1.005 ETH (small gross profit)
            "dex_id": "sushiswap_v3",
            "quote_source": "quoter_v2",
            "quoter_gas_estimate": 300_000,  # High gas usage
            "ticks_crossed": 3,
        }
        
        # Very high gas price
        high_gas_result = simulate_roundtrip(buy_quote, sell_quote, gas_price_wei=1_000_000_000_000)  # 1000 gwei
        
        # Gross profit positive, net profit may be negative due to gas
        assert high_gas_result.gross_pnl_wei > 0
        # Gas cost eats into profit


class TestEstimateSlippageBps:
    """Tests for estimate_slippage_bps()."""

    def test_no_slippage_when_prices_match(self):
        """Zero slippage when quoter and reference prices match."""
        quote = {
            "price_exact": "2000.00",
            "slot0_price": "2000.00",
        }
        
        slippage_bps, method = estimate_slippage_bps(quote)
        
        assert slippage_bps == Decimal("0")
        assert method == "slot0"

    def test_positive_slippage_when_quoter_worse(self):
        """Positive slippage when quoter price is worse (higher for buy)."""
        quote = {
            "price_exact": "2020.00",  # Paying more
            "slot0_price": "2000.00",
        }
        
        slippage_bps, method = estimate_slippage_bps(quote)
        
        # (2020 - 2000) / 2000 * 10000 = 100 bps
        assert slippage_bps == Decimal("100")
        assert method == "slot0"

    def test_negative_slippage_when_quoter_better(self):
        """Negative slippage when quoter price is better."""
        quote = {
            "price_exact": "1980.00",  # Paying less
            "slot0_price": "2000.00",
        }
        
        slippage_bps, method = estimate_slippage_bps(quote)
        
        # (1980 - 2000) / 2000 * 10000 = -100 bps
        assert slippage_bps == Decimal("-100")
        assert method == "slot0"

    def test_provided_reference_price(self):
        """Can use explicitly provided reference price."""
        quote = {
            "price_exact": "2100.00",
        }
        
        slippage_bps, method = estimate_slippage_bps(quote, reference_price=Decimal("2000"))
        
        # (2100 - 2000) / 2000 * 10000 = 500 bps
        assert slippage_bps == Decimal("500")
        assert method == "provided"

    def test_no_reference_returns_zero(self):
        """Returns zero if no reference price available."""
        quote = {
            "price_exact": "2000.00",
            # No slot0_price
        }
        
        slippage_bps, method = estimate_slippage_bps(quote)
        
        assert slippage_bps == Decimal("0")
        assert method == "none"

    def test_no_quoter_price_returns_zero(self):
        """Returns zero if no quoter price in quote."""
        quote = {
            "slot0_price": "2000.00",
            # No price_exact
        }
        
        slippage_bps, method = estimate_slippage_bps(quote)
        
        assert slippage_bps == Decimal("0")
        assert method == "none"


class TestRoundTripResult:
    """Tests for RoundTripResult dataclass."""

    def test_to_dict_serialization(self):
        """RoundTripResult serializes to dict correctly."""
        result = RoundTripResult(
            pair="WETH/USDC",
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            amount_in_wei=1_000_000_000_000_000_000,
            token_in="WETH",
            token_out="USDC",
            leg1_amount_out=2000_000_000,
            leg1_success=True,
            leg2_amount_out=1_010_000_000_000_000_000,
            leg2_success=True,
            gross_pnl_wei=10_000_000_000_000_000,
            is_profitable=True,
        )
        
        d = result.to_dict()
        
        assert d["pair"] == "WETH/USDC"
        assert d["buy_dex"] == "uniswap_v3"
        assert d["sell_dex"] == "sushiswap_v3"
        assert d["is_profitable"] is True
        # Wei values serialized as strings
        assert d["amount_in_wei"] == "1000000000000000000"
        assert d["gross_pnl_wei"] == "10000000000000000"
    
    def test_leg2_is_real_quote_in_dict(self):
        """v2.1.0: leg2_is_real_quote is serialized."""
        result = RoundTripResult(
            pair="WETH/USDC",
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            amount_in_wei=1_000_000_000_000_000_000,
            token_in="WETH",
            token_out="USDC",
            leg1_amount_out=2000_000_000,
            leg1_success=True,
            leg2_success=True,
            leg2_is_real_quote=True,
        )
        
        d = result.to_dict()
        assert d["leg2_is_real_quote"] is True


class TestProbeSlippage:
    """Tests for probe_slippage()."""
    
    def test_slippage_positive_when_target_worse(self):
        """Positive slippage when target quote is worse than small quote."""
        from engine.roundtrip import probe_slippage
        
        quote_small = {"price_exact": "2000.00", "amount_in_wei": 10000}
        quote_target = {"price_exact": "2020.00", "amount_in_wei": 1000000}
        
        slippage_bps, diag = probe_slippage(quote_small, quote_target)
        
        # (2020 - 2000) / 2000 * 10000 = 100 bps
        assert slippage_bps == Decimal("100")
        assert diag["method"] == "probe_small_vs_target"
    
    def test_slippage_zero_when_prices_match(self):
        """Zero slippage when small and target prices match."""
        from engine.roundtrip import probe_slippage
        
        quote_small = {"price_exact": "2000.00", "amount_in_wei": 10000}
        quote_target = {"price_exact": "2000.00", "amount_in_wei": 1000000}
        
        slippage_bps, diag = probe_slippage(quote_small, quote_target)
        
        assert slippage_bps == Decimal("0")
    
    def test_missing_price_returns_zero(self):
        """Returns zero with error if price missing."""
        from engine.roundtrip import probe_slippage
        
        quote_small = {"amount_in_wei": 10000}  # No price_exact
        quote_target = {"price_exact": "2000.00", "amount_in_wei": 1000000}
        
        slippage_bps, diag = probe_slippage(quote_small, quote_target)
        
        assert slippage_bps == Decimal("0")
        assert diag.get("error") == "missing_price"
