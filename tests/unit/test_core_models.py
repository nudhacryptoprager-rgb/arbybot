# PATH: tests/unit/test_core_models.py
"""
Unit tests for core data models.
"""

import unittest
from decimal import Decimal

from core.models import Quote, Opportunity, Trade, PnLBreakdown
from core.constants import RejectReason, TradeOutcome


class TestQuote(unittest.TestCase):
    """Tests for Quote model."""
    
    def test_create_quote(self):
        """Can create a Quote."""
        quote = Quote(
            pool_address="0x1234",
            token_in="USDC",
            token_out="WETH",
            amount_in="1000000",
            amount_out="500000000000000000",
        )
        
        self.assertEqual(quote.pool_address, "0x1234")
        self.assertEqual(quote.token_in, "USDC")
    
    def test_quote_has_timestamp(self):
        """Quote auto-generates timestamp."""
        quote = Quote(
            pool_address="0x1234",
            token_in="USDC",
            token_out="WETH",
            amount_in="1000000",
            amount_out="500000000000000000",
        )
        
        self.assertIsNotNone(quote.timestamp)
        self.assertIn("T", quote.timestamp)  # ISO format
    
    def test_quote_to_dict(self):
        """to_dict returns complete dict."""
        quote = Quote(
            pool_address="0x1234",
            token_in="USDC",
            token_out="WETH",
            amount_in="1000000",
            amount_out="500000000000000000",
            block_number=12345,
        )
        
        d = quote.to_dict()
        
        self.assertEqual(d["pool_address"], "0x1234")
        self.assertEqual(d["block_number"], 12345)


class TestOpportunity(unittest.TestCase):
    """Tests for Opportunity model."""
    
    def test_create_opportunity(self):
        """Can create an Opportunity."""
        quote_buy = Quote(
            pool_address="0xAAA",
            token_in="USDC",
            token_out="WETH",
            amount_in="1000000",
            amount_out="500000000000000000",
        )
        quote_sell = Quote(
            pool_address="0xBBB",
            token_in="WETH",
            token_out="USDC",
            amount_in="500000000000000000",
            amount_out="1010000",
        )
        
        opp = Opportunity(
            spread_id="spread_001",
            quote_buy=quote_buy,
            quote_sell=quote_sell,
            net_pnl_usdc="10.000000",
        )
        
        self.assertEqual(opp.spread_id, "spread_001")
        self.assertEqual(opp.net_pnl_usdc, "10.000000")
    
    def test_opportunity_money_fields_are_strings(self):
        """Money fields are strings."""
        quote = Quote(
            pool_address="0x1234",
            token_in="A",
            token_out="B",
            amount_in="1",
            amount_out="1",
        )
        
        opp = Opportunity(
            spread_id="test",
            quote_buy=quote,
            quote_sell=quote,
        )
        
        self.assertIsInstance(opp.gross_pnl_usdc, str)
        self.assertIsInstance(opp.net_pnl_usdc, str)
        self.assertIsInstance(opp.fees_usdc, str)


class TestTrade(unittest.TestCase):
    """Tests for Trade model."""
    
    def test_create_trade(self):
        """Can create a Trade."""
        trade = Trade(
            trade_id="trade_001",
            spread_id="spread_001",
            outcome=TradeOutcome.EXECUTED,
            realized_pnl_usdc="5.000000",
        )
        
        self.assertEqual(trade.trade_id, "trade_001")
        self.assertEqual(trade.outcome, TradeOutcome.EXECUTED)
    
    def test_trade_to_dict(self):
        """to_dict returns outcome as string value."""
        trade = Trade(
            trade_id="trade_001",
            spread_id="spread_001",
            outcome=TradeOutcome.WOULD_EXECUTE,
        )
        
        d = trade.to_dict()
        
        self.assertEqual(d["outcome"], "WOULD_EXECUTE")


class TestPnLBreakdown(unittest.TestCase):
    """Tests for PnLBreakdown model."""
    
    def test_calculate_net(self):
        """calculate_net computes correctly."""
        breakdown = PnLBreakdown(
            gross_pnl="10.000000",
            dex_fees="0.500000",
            cex_fees="0.300000",
            gas_cost="0.100000",
            slippage_cost="0.050000",
            currency_basis="0.000000",
        )
        
        net = breakdown.calculate_net()
        
        # 10 - 0.5 - 0.3 - 0.1 - 0.05 - 0 = 9.05
        self.assertEqual(Decimal(net), Decimal("9.050000"))
    
    def test_all_fields_are_strings(self):
        """All money fields are strings."""
        breakdown = PnLBreakdown()
        
        self.assertIsInstance(breakdown.gross_pnl, str)
        self.assertIsInstance(breakdown.net_pnl, str)
        self.assertIsInstance(breakdown.gas_cost, str)


if __name__ == "__main__":
    unittest.main()