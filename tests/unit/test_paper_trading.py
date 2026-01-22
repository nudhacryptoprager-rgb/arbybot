# PATH: tests/unit/test_paper_trading.py
"""
Unit tests for paper trading module.

Tests PaperTrade and PaperSession functionality.
"""

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from strategy.paper_trading import (
    PaperTrade,
    PaperSession,
    calculate_usdc_value,
    calculate_pnl_usdc,
)
from core.format_money import format_money, format_money_short


class TestPaperTrade(unittest.TestCase):
    """Tests for PaperTrade dataclass."""
    
    def test_create_paper_trade(self):
        """Can create a PaperTrade with required fields."""
        trade = PaperTrade(
            spread_id="test_001",
            outcome="WOULD_EXECUTE",
        )
        
        self.assertEqual(trade.spread_id, "test_001")
        self.assertEqual(trade.outcome, "WOULD_EXECUTE")
        self.assertEqual(trade.numeraire, "USDC")
    
    def test_paper_trade_money_fields_are_strings(self):
        """Money fields are stored as strings."""
        trade = PaperTrade(
            spread_id="test_001",
            outcome="WOULD_EXECUTE",
            amount_in_numeraire="100.000000",
            expected_pnl_numeraire="1.500000",
            expected_pnl_bps="150.00",
            gas_price_gwei="0.01",
        )
        
        self.assertIsInstance(trade.amount_in_numeraire, str)
        self.assertIsInstance(trade.expected_pnl_numeraire, str)
        self.assertIsInstance(trade.expected_pnl_bps, str)
        self.assertIsInstance(trade.gas_price_gwei, str)
    
    def test_paper_trade_to_dict(self):
        """to_dict() returns dict with string money fields."""
        trade = PaperTrade(
            spread_id="test_001",
            outcome="WOULD_EXECUTE",
            amount_in_numeraire="100.000000",
            expected_pnl_numeraire="1.500000",
        )
        
        d = trade.to_dict()
        
        self.assertIsInstance(d, dict)
        self.assertEqual(d["spread_id"], "test_001")
        self.assertEqual(d["outcome"], "WOULD_EXECUTE")
        self.assertIsInstance(d["amount_in_numeraire"], str)
        self.assertIsInstance(d["expected_pnl_numeraire"], str)
    
    def test_paper_trade_to_json(self):
        """to_json() returns valid JSON string."""
        trade = PaperTrade(
            spread_id="test_001",
            outcome="WOULD_EXECUTE",
        )
        
        json_str = trade.to_json()
        parsed = json.loads(json_str)
        
        self.assertEqual(parsed["spread_id"], "test_001")
    
    def test_paper_trade_accepts_numeric_money_converts_to_string(self):
        """PaperTrade converts numeric money inputs to strings."""
        trade = PaperTrade(
            spread_id="test_001",
            outcome="WOULD_EXECUTE",
            amount_in_numeraire=100,  # int
            expected_pnl_numeraire=1.5,  # float (legacy)
        )
        
        self.assertIsInstance(trade.amount_in_numeraire, str)
        self.assertIsInstance(trade.expected_pnl_numeraire, str)


class TestPaperSession(unittest.TestCase):
    """Tests for PaperSession class."""
    
    def test_create_paper_session(self):
        """Can create a PaperSession."""
        session = PaperSession()
        
        self.assertEqual(len(session.trades), 0)
        self.assertEqual(session.stats["total_trades"], 0)
    
    def test_record_trade(self):
        """Can record a trade to session."""
        session = PaperSession()
        trade = PaperTrade(
            spread_id="test_001",
            outcome="WOULD_EXECUTE",
            expected_pnl_numeraire="1.500000",
        )
        
        result = session.record_trade(trade)
        
        self.assertTrue(result)
        self.assertEqual(len(session.trades), 1)
        self.assertEqual(session.stats["total_trades"], 1)
        self.assertEqual(session.stats["would_execute_count"], 1)
    
    def test_record_trade_updates_pnl(self):
        """Recording WOULD_EXECUTE trades updates PnL."""
        session = PaperSession()
        
        trade1 = PaperTrade(
            spread_id="test_001",
            outcome="WOULD_EXECUTE",
            expected_pnl_numeraire="1.500000",
        )
        trade2 = PaperTrade(
            spread_id="test_002",
            outcome="WOULD_EXECUTE",
            expected_pnl_numeraire="2.500000",
        )
        
        session.record_trade(trade1)
        session.record_trade(trade2)
        
        # PnL should be sum: 1.5 + 2.5 = 4.0
        total_pnl = Decimal(session.stats["total_pnl_usdc"])
        self.assertEqual(total_pnl, Decimal("4.000000"))
    
    def test_record_trade_cooldown_dedup(self):
        """Duplicate spread_id within cooldown is rejected."""
        session = PaperSession(cooldown_seconds=60)
        
        trade1 = PaperTrade(spread_id="test_001", outcome="WOULD_EXECUTE")
        trade2 = PaperTrade(spread_id="test_001", outcome="WOULD_EXECUTE")  # Same spread_id
        
        result1 = session.record_trade(trade1)
        result2 = session.record_trade(trade2)
        
        self.assertTrue(result1)
        self.assertFalse(result2)  # Rejected as duplicate
        self.assertEqual(len(session.trades), 1)
    
    def test_get_stats(self):
        """get_stats() returns stats dict with string money values."""
        session = PaperSession()
        stats = session.get_stats()
        
        self.assertIn("total_trades", stats)
        self.assertIn("total_pnl_usdc", stats)
        self.assertIn("notion_capital_usdc", stats)
        self.assertIsInstance(stats["total_pnl_usdc"], str)
        self.assertIsInstance(stats["notion_capital_usdc"], str)
    
    def test_get_pnl_summary(self):
        """get_pnl_summary() returns PnL summary with string values."""
        session = PaperSession()
        trade = PaperTrade(
            spread_id="test_001",
            outcome="WOULD_EXECUTE",
            expected_pnl_numeraire="100.000000",
        )
        session.record_trade(trade)
        
        summary = session.get_pnl_summary()
        
        self.assertIn("total_pnl_usdc", summary)
        self.assertIn("normalized_return_pct", summary)
        self.assertIsInstance(summary["total_pnl_usdc"], str)
    
    def test_session_writes_paper_trades_file(self):
        """Session writes trades to paper_trades.jsonl when output_dir set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            session = PaperSession(output_dir=output_dir)
            
            trade = PaperTrade(
                spread_id="test_001",
                outcome="WOULD_EXECUTE",
                expected_pnl_numeraire="1.000000",
            )
            session.record_trade(trade)
            
            # Check file exists
            trades_file = output_dir / "paper_trades.jsonl"
            self.assertTrue(trades_file.exists())
            
            # Check content
            with open(trades_file, "r") as f:
                lines = f.readlines()
            
            self.assertEqual(len(lines), 1)
            parsed = json.loads(lines[0])
            self.assertEqual(parsed["spread_id"], "test_001")


class TestCalculateFunctions(unittest.TestCase):
    """Tests for calculation functions."""
    
    def test_calculate_usdc_value(self):
        """calculate_usdc_value returns Decimal."""
        result = calculate_usdc_value("100", "1.5")
        
        self.assertIsInstance(result, Decimal)
        self.assertEqual(result, Decimal("150"))
    
    def test_calculate_pnl_usdc(self):
        """calculate_pnl_usdc returns Decimal."""
        result = calculate_pnl_usdc(
            buy_value="100",
            sell_value="105",
            fees="0.5",
            gas_cost="0.1",
        )
        
        self.assertIsInstance(result, Decimal)
        self.assertEqual(result, Decimal("4.4"))
    
    def test_calculate_pnl_usdc_negative(self):
        """calculate_pnl_usdc can return negative PnL."""
        result = calculate_pnl_usdc(
            buy_value="100",
            sell_value="95",
            fees="0.5",
            gas_cost="0.1",
        )
        
        self.assertEqual(result, Decimal("-5.6"))


class TestFormatMoneyIntegration(unittest.TestCase):
    """Integration tests for format_money with paper trading."""
    
    def test_format_money_in_trade_logging(self):
        """format_money works correctly in trade logging context."""
        trade = PaperTrade(
            spread_id="test_001",
            outcome="WOULD_EXECUTE",
            expected_pnl_numeraire="0.840000",
            amount_in_numeraire="300.000000",
        )
        
        # This simulates what record_trade does
        pnl_formatted = format_money_short(trade.expected_pnl_numeraire)
        amount_formatted = format_money_short(trade.amount_in_numeraire)
        
        msg = (
            f"Paper trade: {trade.outcome} {trade.spread_id} "
            f"PnL: {pnl_formatted} {trade.numeraire} "
            f"Amount: {amount_formatted}"
        )
        
        self.assertIn("0.84", msg)
        self.assertIn("300.00", msg)
    
    def test_format_money_rounding(self):
        """format_money rounds 0.005 to 0.01 with 2 decimals."""
        result = format_money_short(Decimal("0.005"))
        self.assertEqual(result, "0.01")
        
        result = format_money_short("0.005")
        self.assertEqual(result, "0.01")


if __name__ == "__main__":
    unittest.main()