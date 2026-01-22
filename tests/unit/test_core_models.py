# PATH: tests/unit/test_core_models.py
"""
Unit tests for core data models.

Includes SPREAD_ID CONTRACT v1.0 tests.
"""

import unittest
from decimal import Decimal

from core.models import (
    Quote, Opportunity, Trade, PnLBreakdown,
    generate_spread_id, generate_opportunity_id, parse_spread_id,
    validate_spread_id, format_spread_timestamp, SPREAD_ID_PATTERN,
)
from core.constants import RejectReason, TradeOutcome


class TestSpreadIdContract(unittest.TestCase):
    """
    SPREAD_ID CONTRACT v1.0 tests.
    
    CONTRACT:
    - Format: "spread_{cycle}_{YYYYMMDD}_{HHMMSS}_{index}"
    - When split by "_", produces 5 parts
    - timestamp = "YYYYMMDD_HHMMSS" (contains underscore)
    
    CRITICAL: generate_spread_id() and parse_spread_id() must be 
    mutually inverse (roundtrip stable).
    """

    def test_generate_spread_id_format(self):
        """spread_id follows contract format."""
        spread_id = generate_spread_id(1, "20260122_171426", 0)
        self.assertEqual(spread_id, "spread_1_20260122_171426_0")

    def test_generate_spread_id_deterministic(self):
        """Same inputs produce same spread_id."""
        id1 = generate_spread_id(5, "20260122_120000", 3)
        id2 = generate_spread_id(5, "20260122_120000", 3)
        self.assertEqual(id1, id2)

    def test_generate_spread_id_different_cycles(self):
        """Different cycles produce different spread_ids."""
        id1 = generate_spread_id(1, "20260122_120000", 0)
        id2 = generate_spread_id(2, "20260122_120000", 0)
        self.assertNotEqual(id1, id2)

    def test_generate_opportunity_id_format(self):
        """opportunity_id follows contract format."""
        spread_id = "spread_1_20260122_171426_0"
        opp_id = generate_opportunity_id(spread_id)
        self.assertEqual(opp_id, "opp_spread_1_20260122_171426_0")

    def test_parse_spread_id_valid(self):
        """parse_spread_id extracts components correctly."""
        result = parse_spread_id("spread_1_20260122_171426_0")
        
        self.assertTrue(result["valid"])
        self.assertEqual(result["cycle"], 1)
        self.assertEqual(result["date"], "20260122")
        self.assertEqual(result["time"], "171426")
        self.assertEqual(result["timestamp"], "20260122_171426")
        self.assertEqual(result["index"], 0)

    def test_parse_spread_id_large_values(self):
        """parse_spread_id handles large cycle and index."""
        result = parse_spread_id("spread_999_20260122_235959_42")
        
        self.assertTrue(result["valid"])
        self.assertEqual(result["cycle"], 999)
        self.assertEqual(result["index"], 42)

    def test_parse_spread_id_invalid_format(self):
        """parse_spread_id returns invalid for wrong format."""
        result = parse_spread_id("invalid_spread_id")
        self.assertFalse(result["valid"])
        self.assertIn("error", result)

    def test_parse_spread_id_wrong_prefix(self):
        """parse_spread_id returns invalid for wrong prefix."""
        result = parse_spread_id("opportunity_1_20260122_171426_0")
        self.assertFalse(result["valid"])

    def test_parse_spread_id_missing_index(self):
        """parse_spread_id returns invalid when index is missing."""
        # Old format without index should be invalid
        result = parse_spread_id("spread_1_20260122_171426")
        self.assertFalse(result["valid"])

    def test_roundtrip_generate_parse(self):
        """CRITICAL: generate -> parse roundtrip is stable."""
        original_cycle = 7
        original_ts = "20260115_143022"
        original_idx = 12
        
        # Generate
        spread_id = generate_spread_id(original_cycle, original_ts, original_idx)
        
        # Parse
        parsed = parse_spread_id(spread_id)
        
        # Verify roundtrip
        self.assertTrue(parsed["valid"], f"Failed to parse generated spread_id: {spread_id}")
        self.assertEqual(parsed["cycle"], original_cycle)
        self.assertEqual(parsed["timestamp"], original_ts)
        self.assertEqual(parsed["index"], original_idx)

    def test_roundtrip_generate_parse_regenerate(self):
        """CRITICAL: generate -> parse -> regenerate produces same ID."""
        original_id = generate_spread_id(3, "20260122_093438", 5)
        
        parsed = parse_spread_id(original_id)
        self.assertTrue(parsed["valid"])
        
        regenerated_id = generate_spread_id(
            parsed["cycle"], 
            parsed["timestamp"], 
            parsed["index"]
        )
        
        self.assertEqual(original_id, regenerated_id)

    def test_real_artifact_example(self):
        """
        COMPAT TEST: Real spread_id from artifacts must parse.
        
        Example from scan_20260122_171426.json artifact.
        """
        real_spread_id = "spread_1_20260122_171426_0"
        
        result = parse_spread_id(real_spread_id)
        
        self.assertTrue(result["valid"], 
            f"Real artifact spread_id should be valid: {real_spread_id}")
        self.assertEqual(result["cycle"], 1)
        self.assertEqual(result["date"], "20260122")
        self.assertEqual(result["time"], "171426")
        self.assertEqual(result["index"], 0)

    def test_validate_spread_id_quick(self):
        """validate_spread_id() returns bool quickly."""
        self.assertTrue(validate_spread_id("spread_1_20260122_171426_0"))
        self.assertFalse(validate_spread_id("invalid"))
        self.assertFalse(validate_spread_id("spread_1_20260122_171426"))  # missing index

    def test_format_spread_timestamp(self):
        """format_spread_timestamp produces correct format."""
        from datetime import datetime, timezone
        
        dt = datetime(2026, 1, 22, 17, 14, 26, tzinfo=timezone.utc)
        ts = format_spread_timestamp(dt)
        
        self.assertEqual(ts, "20260122_171426")


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

    def test_opportunity_id_syncs_with_spread_id(self):
        """id field syncs with spread_id."""
        opp = Opportunity(spread_id="spread_123")
        self.assertEqual(opp.id, "spread_123")


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
