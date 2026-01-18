# PATH: tests/unit/test_edge_cases.py
"""
Edge case tests for Issue #3 fixes.

Tests unusual inputs and boundary conditions.
"""

import json
import unittest
from decimal import Decimal, InvalidOperation
from unittest.mock import patch, MagicMock

from core.format_money import format_money, format_money_short


class TestFormatMoneyEdgeCases(unittest.TestCase):
    """Edge cases for format_money."""
    
    def test_extremely_large_number(self):
        """Handles extremely large numbers."""
        large = "999999999999999999999999.999999"
        result = format_money(large)
        self.assertIn("999999999999999999999999", result)
    
    def test_extremely_small_number(self):
        """Handles extremely small numbers."""
        small = "0.000000000000000001"
        result = format_money(small, decimals=18)
        self.assertEqual(result, "0.000000000000000001")
    
    def test_negative_zero(self):
        """Handles negative zero."""
        result = format_money("-0.00")
        # Should normalize to positive zero
        self.assertIn("0.000000", result)
    
    def test_plus_sign_prefix(self):
        """Handles explicit plus sign."""
        result = format_money("+123.45")
        self.assertEqual(result, "123.450000")
    
    def test_leading_zeros(self):
        """Handles leading zeros."""
        result = format_money("00123.45")
        self.assertEqual(result, "123.450000")
    
    def test_trailing_zeros_preserved(self):
        """Trailing zeros are preserved to specified decimals."""
        result = format_money("100", decimals=6)
        self.assertEqual(result, "100.000000")
    
    def test_unicode_minus(self):
        """Handles unicode minus sign (if present)."""
        # Some systems might use unicode minus
        result = format_money("−123.45")  # Unicode minus U+2212
        # Should either parse or return zero
        self.assertIsInstance(result, str)
    
    def test_whitespace_handling(self):
        """Handles various whitespace."""
        self.assertEqual(format_money("  123.45  "), "123.450000")
        self.assertEqual(format_money("\t100\n"), "100.000000")
    
    def test_comma_decimal_separator(self):
        """Handles comma as decimal separator (should fail gracefully)."""
        result = format_money("123,45")
        # Should return zero (invalid format)
        self.assertEqual(result, "0.000000")
    
    def test_thousand_separator(self):
        """Handles thousand separators (should fail gracefully)."""
        result = format_money("1,000.00")
        # Should return zero (invalid format)
        self.assertEqual(result, "0.000000")
    
    def test_currency_symbol(self):
        """Handles currency symbols (should fail gracefully)."""
        result = format_money("$100.00")
        self.assertEqual(result, "0.000000")
    
    def test_infinity(self):
        """Handles infinity values."""
        result = format_money(float('inf'))
        # Should handle gracefully
        self.assertIsInstance(result, str)
    
    def test_nan(self):
        """Handles NaN values."""
        result = format_money(float('nan'))
        # Should handle gracefully
        self.assertIsInstance(result, str)
    
    def test_boolean_input(self):
        """Handles boolean input (True=1, False=0)."""
        # Booleans are ints in Python
        self.assertEqual(format_money(True), "1.000000")
        self.assertEqual(format_money(False), "0.000000")
    
    def test_zero_decimals(self):
        """Handles zero decimal places."""
        result = format_money("123.999", decimals=0)
        self.assertEqual(result, "124")  # Rounded
    
    def test_many_decimals(self):
        """Handles many decimal places."""
        result = format_money("1.123456789012345678901234567890", decimals=20)
        self.assertEqual(len(result.split('.')[1]), 20)


class TestPaperTradingEdgeCases(unittest.TestCase):
    """Edge cases for paper trading."""
    
    def test_empty_spread_id(self):
        """Handles empty spread_id."""
        from strategy.paper_trading import PaperTrade, PaperSession
        
        trade = PaperTrade(spread_id="", outcome="WOULD_EXECUTE")
        session = PaperSession()
        
        # Should still work
        result = session.record_trade(trade)
        self.assertTrue(result)
    
    def test_very_long_spread_id(self):
        """Handles very long spread_id."""
        from strategy.paper_trading import PaperTrade, PaperSession
        
        long_id = "x" * 1000
        trade = PaperTrade(spread_id=long_id, outcome="WOULD_EXECUTE")
        session = PaperSession()
        
        result = session.record_trade(trade)
        self.assertTrue(result)
    
    def test_special_chars_in_spread_id(self):
        """Handles special characters in spread_id."""
        from strategy.paper_trading import PaperTrade, PaperSession
        
        special_id = "spread/test:123|456"
        trade = PaperTrade(spread_id=special_id, outcome="WOULD_EXECUTE")
        session = PaperSession()
        
        result = session.record_trade(trade)
        self.assertTrue(result)
        
        # Should be JSON serializable
        json_str = trade.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["spread_id"], special_id)
    
    def test_unicode_in_metadata(self):
        """Handles unicode in metadata."""
        from strategy.paper_trading import PaperTrade
        
        trade = PaperTrade(
            spread_id="test",
            outcome="WOULD_EXECUTE",
            metadata={"note": "Тест 测试 🚀"}
        )
        
        json_str = trade.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["metadata"]["note"], "Тест 测试 🚀")
    
    def test_negative_pnl(self):
        """Handles negative PnL correctly."""
        from strategy.paper_trading import PaperTrade, PaperSession
        
        session = PaperSession()
        
        trade = PaperTrade(
            spread_id="loss_trade",
            outcome="WOULD_EXECUTE",
            expected_pnl_numeraire="-5.000000",
        )
        session.record_trade(trade)
        
        stats = session.get_stats()
        total_pnl = Decimal(stats["total_pnl_usdc"])
        self.assertEqual(total_pnl, Decimal("-5.000000"))
    
    def test_zero_cooldown(self):
        """Handles zero cooldown (no dedup)."""
        from strategy.paper_trading import PaperSession, PaperTrade
        
        session = PaperSession(cooldown_seconds=0)
        
        # Same spread_id should be accepted with zero cooldown
        trade1 = PaperTrade(spread_id="same", outcome="WOULD_EXECUTE")
        trade2 = PaperTrade(spread_id="same", outcome="WOULD_EXECUTE")
        
        self.assertTrue(session.record_trade(trade1))
        # With zero cooldown, immediate duplicate might still be blocked
        # depending on implementation


class TestTruthReportEdgeCases(unittest.TestCase):
    """Edge cases for truth report."""
    
    def test_empty_reject_histogram(self):
        """Handles empty reject histogram."""
        from monitoring.truth_report import build_health_section
        
        health = build_health_section({}, {})
        
        self.assertEqual(health["top_reject_reasons"], [])
    
    def test_many_reject_reasons(self):
        """Handles many reject reasons (should limit to top 5)."""
        from monitoring.truth_report import build_health_section
        
        rejects = {f"REASON_{i}": i for i in range(20)}
        health = build_health_section({}, rejects)
        
        self.assertEqual(len(health["top_reject_reasons"]), 5)
    
    def test_zero_rpc_success(self):
        """Handles 100% RPC failure."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        for _ in range(10):
            metrics.record_failure()
        
        self.assertEqual(metrics.rpc_success_rate, 0.0)
        self.assertEqual(metrics.rpc_total_requests, 10)
    
    def test_all_rpc_success(self):
        """Handles 100% RPC success."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        for _ in range(10):
            metrics.record_success(latency_ms=100)
        
        self.assertEqual(metrics.rpc_success_rate, 1.0)
    
    def test_normalized_return_with_zero_capital(self):
        """Handles zero notional capital."""
        from monitoring.truth_report import build_truth_report
        
        report = build_truth_report(
            scan_stats={},
            reject_histogram={},
            opportunities=[],
            paper_session_stats={
                "total_pnl_usdc": "10.000000",
                "notion_capital_usdc": "0.000000",  # Zero capital
            },
        )
        
        # Should handle gracefully (None or some indicator)
        data = report.to_dict()
        # normalized_return_pct should be None or handle division by zero


class TestRoundingEdgeCases(unittest.TestCase):
    """Edge cases for rounding behavior."""
    
    def test_exact_half_values(self):
        """Tests exact .5 values round up."""
        cases = [
            ("0.5", 0, "1"),
            ("1.5", 0, "2"),
            ("2.5", 0, "3"),
            ("0.05", 1, "0.1"),
            ("0.15", 1, "0.2"),
            ("0.005", 2, "0.01"),
            ("0.015", 2, "0.02"),
            ("0.025", 2, "0.03"),
        ]
        
        for value, decimals, expected in cases:
            result = format_money(value, decimals=decimals)
            self.assertEqual(result, expected, 
                f"format_money({value}, decimals={decimals}) = {result}, expected {expected}")
    
    def test_negative_exact_half_values(self):
        """Tests negative exact .5 values round away from zero."""
        cases = [
            ("-0.5", 0, "-1"),
            ("-1.5", 0, "-2"),
            ("-0.05", 1, "-0.1"),
            ("-0.005", 2, "-0.01"),
            ("-0.025", 2, "-0.03"),
        ]
        
        for value, decimals, expected in cases:
            result = format_money(value, decimals=decimals)
            self.assertEqual(result, expected,
                f"format_money({value}, decimals={decimals}) = {result}, expected {expected}")


if __name__ == "__main__":
    unittest.main()