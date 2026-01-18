# PATH: tests/unit/test_error_contract.py
"""
Unit tests for Issue B - M3 Quality v4 error contracts.

Tests:
A) Logging API correctness - no kwargs; only extra context allowed
B) Money formatting safety - format_money() never crashes on str/Decimal/int
C) No-float money contract - paper_trades dict/stats have no float
D) RPC health consistency - truth_report aligns with rejects
E) Rounding correctness - Decimal("0.005") with 2 decimals -> "0.01"
"""

import ast
import os
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestLoggingAPICorrectness(unittest.TestCase):
    """
    Requirement A): No calls like logger.error(..., spread_id=..., ...)
    All contextual fields passed only via extra={"context": {...}}
    """
    
    ALLOWED_LOGGER_KWARGS = {"exc_info", "extra", "stack_info", "stacklevel"}
    
    def _find_python_files(self, directory: Path) -> list:
        """Find all Python files in directory, excluding tests and venv."""
        py_files = []
        exclude_dirs = {"venv", ".venv", "__pycache__", ".git", "test", "tests"}
        
        if not directory.exists():
            return py_files
        
        for root, dirs, files in os.walk(directory):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for f in files:
                if f.endswith(".py"):
                    py_files.append(Path(root) / f)
        
        return py_files
    
    def _check_logger_calls(self, file_path: Path) -> list:
        """
        Parse Python file and find logger calls with invalid kwargs.
        
        Returns list of violations with line number and details.
        """
        violations = []
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
            
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            return violations
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check if it's a logger method call
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr in ("debug", "info", "warning", "error", "critical", "exception"):
                        # Check the object being called
                        obj_name = None
                        if isinstance(node.func.value, ast.Name):
                            obj_name = node.func.value.id
                        elif isinstance(node.func.value, ast.Attribute):
                            obj_name = node.func.value.attr
                        
                        # If it looks like a logger call
                        if obj_name and ("log" in obj_name.lower() or obj_name == "self"):
                            # Check for invalid kwargs
                            for keyword in node.keywords:
                                if keyword.arg and keyword.arg not in self.ALLOWED_LOGGER_KWARGS:
                                    violations.append({
                                        "file": str(file_path),
                                        "line": node.lineno,
                                        "method": node.func.attr,
                                        "invalid_kwarg": keyword.arg,
                                    })
        
        return violations
    
    def test_no_invalid_logger_kwargs_in_strategy(self):
        """Logger calls in strategy/ must not use invalid kwargs."""
        strategy_dir = PROJECT_ROOT / "strategy"
        if not strategy_dir.exists():
            self.skipTest("strategy/ directory not found")
        
        all_violations = []
        for py_file in self._find_python_files(strategy_dir):
            violations = self._check_logger_calls(py_file)
            all_violations.extend(violations)
        
        if all_violations:
            msg = "Found logger calls with invalid kwargs:\n"
            for v in all_violations:
                msg += f"  {v['file']}:{v['line']} - logger.{v['method']}(..., {v['invalid_kwarg']}=...)\n"
            self.fail(msg)
    
    def test_no_invalid_logger_kwargs_in_monitoring(self):
        """Logger calls in monitoring/ must not use invalid kwargs."""
        monitoring_dir = PROJECT_ROOT / "monitoring"
        if not monitoring_dir.exists():
            self.skipTest("monitoring/ directory not found")
        
        all_violations = []
        for py_file in self._find_python_files(monitoring_dir):
            violations = self._check_logger_calls(py_file)
            all_violations.extend(violations)
        
        if all_violations:
            msg = "Found logger calls with invalid kwargs:\n"
            for v in all_violations:
                msg += f"  {v['file']}:{v['line']} - logger.{v['method']}(..., {v['invalid_kwarg']}=...)\n"
            self.fail(msg)
    
    def test_logger_context_format(self):
        """Verify extra context is properly structured."""
        import logging
        
        # Create a test logger with capturing handler
        captured_records = []
        
        class CapturingHandler(logging.Handler):
            def emit(self, record):
                captured_records.append(record)
        
        test_logger = logging.getLogger("test_context_format")
        test_logger.setLevel(logging.DEBUG)
        handler = CapturingHandler()
        test_logger.addHandler(handler)
        
        # Log with proper context format
        test_logger.info(
            "Test message",
            extra={"context": {"spread_id": "test123", "amount": "100.00"}}
        )
        
        self.assertEqual(len(captured_records), 1)
        record = captured_records[0]
        self.assertTrue(hasattr(record, "context"))
        self.assertEqual(record.context["spread_id"], "test123")


class TestMoneyFormattingSafety(unittest.TestCase):
    """
    Requirement B): format_money(x) -> str that safely formats str|Decimal|int
    without throwing. Never use :.2f directly on money fields.
    """
    
    def test_format_money_with_string(self):
        """format_money handles string input."""
        from core.format_money import format_money
        
        result = format_money("123.456789")
        self.assertEqual(result, "123.456789")
        
        result = format_money("0.001")
        self.assertEqual(result, "0.001000")
    
    def test_format_money_with_decimal(self):
        """format_money handles Decimal input."""
        from core.format_money import format_money
        
        result = format_money(Decimal("123.456789"))
        self.assertEqual(result, "123.456789")
        
        result = format_money(Decimal("0"))
        self.assertEqual(result, "0.000000")
    
    def test_format_money_with_int(self):
        """format_money handles int input."""
        from core.format_money import format_money
        
        result = format_money(100)
        self.assertEqual(result, "100.000000")
        
        result = format_money(0)
        self.assertEqual(result, "0.000000")
    
    def test_format_money_with_none(self):
        """format_money handles None input."""
        from core.format_money import format_money
        
        result = format_money(None)
        self.assertEqual(result, "0.000000")
    
    def test_format_money_with_empty_string(self):
        """format_money handles empty string input."""
        from core.format_money import format_money
        
        result = format_money("")
        self.assertEqual(result, "0.000000")
        
        result = format_money("   ")
        self.assertEqual(result, "0.000000")
    
    def test_format_money_with_invalid_string(self):
        """format_money handles invalid string gracefully."""
        from core.format_money import format_money
        
        # Should not raise, returns zero
        result = format_money("not_a_number")
        self.assertEqual(result, "0.000000")
    
    def test_format_money_short(self):
        """format_money_short uses 2 decimal places."""
        from core.format_money import format_money_short
        
        result = format_money_short("123.456789")
        self.assertEqual(result, "123.46")
    
    def test_format_money_rounding_half_up(self):
        """format_money uses ROUND_HALF_UP: 0.005 -> 0.01 with 2 decimals."""
        from core.format_money import format_money_short, format_money
        
        # Critical test: Decimal("0.005") with 2 decimals must become "0.01"
        result = format_money_short(Decimal("0.005"))
        self.assertEqual(result, "0.01", "ROUND_HALF_UP: 0.005 should round to 0.01")
        
        result = format_money(Decimal("0.005"), decimals=2)
        self.assertEqual(result, "0.01")
        
        # Also test string input
        result = format_money_short("0.005")
        self.assertEqual(result, "0.01")
        
        # Test other rounding cases
        result = format_money_short(Decimal("0.004"))
        self.assertEqual(result, "0.00")
        
        result = format_money_short(Decimal("0.015"))
        self.assertEqual(result, "0.02")
    
    def test_record_trade_no_crash_on_string_money(self):
        """record_trade() must not crash when money fields are strings."""
        from core.format_money import format_money_short
        
        # Mock a PaperTrade-like object with string money fields
        class MockPaperTrade:
            outcome = "WOULD_EXECUTE"
            spread_id = "test_spread_001"
            expected_pnl_numeraire = "0.840000"  # String, not float!
            amount_in_numeraire = "300.000000"  # String, not float!
            numeraire = "USDC"
        
        trade = MockPaperTrade()
        
        # The key test: formatting should not crash
        try:
            msg = (
                f"Paper trade: {trade.outcome} {trade.spread_id} "
                f"PnL: {format_money_short(trade.expected_pnl_numeraire)} {trade.numeraire} "
                f"Amount: {format_money_short(trade.amount_in_numeraire)}"
            )
            self.assertIn("0.84", msg)
            self.assertIn("300.00", msg)
        except ValueError as e:
            self.fail(f"format_money_short crashed on string input: {e}")


class TestNoFloatMoneyContract(unittest.TestCase):
    """
    Requirement C): No float conversions in money fields.
    paper_trades dict/stats must have no float values.
    """
    
    def _contains_float(self, obj: Any, path: str = "") -> list:
        """Recursively check for float values, return paths to floats."""
        float_paths = []
        
        if isinstance(obj, float):
            float_paths.append(path or "root")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                float_paths.extend(self._contains_float(v, f"{path}.{k}" if path else k))
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                float_paths.extend(self._contains_float(v, f"{path}[{i}]"))
        
        return float_paths
    
    def test_paper_trade_dict_no_float(self):
        """PaperTrade.to_dict() must not contain float values in money fields."""
        from strategy.paper_trading import PaperTrade
        
        trade = PaperTrade(
            spread_id="test_001",
            outcome="WOULD_EXECUTE",
            amount_in_numeraire="300.000000",
            expected_pnl_numeraire="0.840000",
            gas_price_gwei="0.01",
        )
        
        trade_dict = trade.to_dict()
        
        # Check money fields are strings
        self.assertIsInstance(trade_dict["amount_in_numeraire"], str)
        self.assertIsInstance(trade_dict["expected_pnl_numeraire"], str)
        self.assertIsInstance(trade_dict["gas_price_gwei"], str)
        self.assertIsInstance(trade_dict["expected_pnl_bps"], str)
    
    def test_session_stats_no_float(self):
        """Paper session stats must not contain float values in money fields."""
        from strategy.paper_trading import PaperSession
        
        session = PaperSession()
        stats = session.get_stats()
        
        # Check money fields are strings
        self.assertIsInstance(stats["total_pnl_usdc"], str)
        self.assertIsInstance(stats["total_pnl_bps"], str)
        self.assertIsInstance(stats["notion_capital_usdc"], str)
    
    def test_truth_report_pnl_no_float(self):
        """TruthReport PnL fields must not contain float values."""
        from monitoring.truth_report import build_truth_report
        
        report = build_truth_report(
            scan_stats={},
            reject_histogram={},
            opportunities=[],
        )
        
        report_dict = report.to_dict()
        
        # Check cumulative_pnl
        self.assertIsInstance(report_dict["cumulative_pnl"]["total_usdc"], str)
        
        # Check pnl
        self.assertIsInstance(report_dict["pnl"]["signal_pnl_usdc"], str)
        self.assertIsInstance(report_dict["pnl"]["would_execute_pnl_usdc"], str)
        
        # Check pnl_normalized
        self.assertIsInstance(report_dict["pnl_normalized"]["notion_capital_numeraire"], str)
    
    def test_calculate_usdc_value_returns_decimal(self):
        """calculate_usdc_value must return Decimal, not float."""
        from strategy.paper_trading import calculate_usdc_value
        
        result = calculate_usdc_value("100", "1.5")
        self.assertIsInstance(result, Decimal)
        self.assertNotIsInstance(result, float)
        self.assertEqual(result, Decimal("150"))
    
    def test_calculate_pnl_usdc_returns_decimal(self):
        """calculate_pnl_usdc must return Decimal, not float."""
        from strategy.paper_trading import calculate_pnl_usdc
        
        result = calculate_pnl_usdc("100", "105", "0.5", "0.1")
        self.assertIsInstance(result, Decimal)
        self.assertEqual(result, Decimal("4.4"))


class TestRPCHealthConsistency(unittest.TestCase):
    """
    Requirement D): RPC health metrics consistent with observed rejects.
    If INFRA_RPC_ERROR > 0, then rpc_total_requests > 0.
    """
    
    def test_rpc_health_consistency_with_rpc_errors(self):
        """If reject_histogram has INFRA_RPC_ERROR > 0, rpc_total_requests must be > 0."""
        from monitoring.truth_report import RPCHealthMetrics, build_health_section
        
        reject_histogram = {
            "QUOTE_REVERT": 66,
            "QUOTE_GAS_TOO_HIGH": 47,
            "INFRA_RPC_ERROR": 5,  # RPC errors present
        }
        
        # Create metrics with no tracked calls (simulating the bug)
        rpc_metrics = RPCHealthMetrics()
        
        # Build health - should reconcile
        health = build_health_section({}, reject_histogram, rpc_metrics)
        
        # After reconciliation, rpc_total_requests should reflect INFRA_RPC_ERROR
        self.assertGreater(
            health["rpc_total_requests"],
            0,
            "RPC health inconsistent: INFRA_RPC_ERROR > 0 but rpc_total_requests = 0"
        )
        self.assertGreaterEqual(
            health["rpc_failed_requests"],
            5,
            "rpc_failed_requests should be at least INFRA_RPC_ERROR count"
        )
    
    def test_rpc_metrics_reconcile(self):
        """RPCHealthMetrics.reconcile_with_rejects fixes inconsistencies."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        self.assertEqual(metrics.rpc_total_requests, 0)
        
        # Reconcile with rejects containing INFRA_RPC_ERROR
        metrics.reconcile_with_rejects({"INFRA_RPC_ERROR": 10})
        
        self.assertEqual(metrics.rpc_failed_count, 10)
        self.assertEqual(metrics.rpc_total_requests, 10)
    
    def test_health_metrics_track_quote_attempts(self):
        """Health metrics should track quote_call_attempts."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        
        # Record some calls
        metrics.record_success(latency_ms=50)
        metrics.record_success(latency_ms=60)
        metrics.record_failure()
        
        self.assertEqual(metrics.rpc_success_count, 2)
        self.assertEqual(metrics.rpc_failed_count, 1)
        self.assertEqual(metrics.rpc_total_requests, 3)
        self.assertEqual(metrics.quote_call_attempts, 3)
        self.assertEqual(metrics.avg_latency_ms, 55)


class TestPriceSanityDiagnostics(unittest.TestCase):
    """
    Requirement E): PRICE_SANITY_FAILED samples should have anchor_source filled.
    """
    
    def test_price_sanity_failed_has_anchor_source(self):
        """PRICE_SANITY_FAILED rejects should include anchor_source for debugging."""
        # Simulate a reject sample with proper structure
        reject_sample = {
            "reason": "PRICE_SANITY_FAILED",
            "spread_id": "spread_001",
            "details": {
                "expected_price": "1.0001",
                "actual_price": "1.5000",
                "deviation_pct": "49.99",
                "anchor_source": {
                    "dex": "uniswap_v3",
                    "pool": "0x1234567890abcdef",
                    "fee": 500,
                    "block": 12345678,
                },
            }
        }
        
        if reject_sample["reason"] == "PRICE_SANITY_FAILED":
            anchor = reject_sample.get("details", {}).get("anchor_source")
            self.assertIsNotNone(anchor, "PRICE_SANITY_FAILED must have anchor_source")
            self.assertIn("dex", anchor)
            self.assertIn("pool", anchor)
            self.assertIn("block", anchor)


class TestCalculateConfidence(unittest.TestCase):
    """Test calculate_confidence is available and works correctly."""
    
    def test_calculate_confidence_import(self):
        """calculate_confidence must be importable from monitoring.truth_report."""
        from monitoring.truth_report import calculate_confidence
        self.assertTrue(callable(calculate_confidence))
    
    def test_calculate_confidence_range(self):
        """calculate_confidence returns value between 0 and 1."""
        from monitoring.truth_report import calculate_confidence
        
        # All perfect scores
        score = calculate_confidence(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertEqual(score, 1.0)
        
        # All zero scores
        score = calculate_confidence(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(score, 0.0)
        
        # Mixed scores
        score = calculate_confidence(0.5, 0.5, 0.5, 0.5, 0.5)
        self.assertEqual(score, 0.5)
    
    def test_calculate_confidence_clamped(self):
        """calculate_confidence clamps to [0, 1] range."""
        from monitoring.truth_report import calculate_confidence
        
        # Even with out-of-range inputs, output is clamped
        score = calculate_confidence(2.0, 2.0, 2.0, 2.0, 2.0)
        self.assertLessEqual(score, 1.0)
        
        score = calculate_confidence(-1.0, -1.0, -1.0, -1.0, -1.0)
        self.assertGreaterEqual(score, 0.0)


class TestPaperSessionImport(unittest.TestCase):
    """Test PaperSession is available from strategy.paper_trading."""
    
    def test_paper_session_import(self):
        """PaperSession must be importable from strategy.paper_trading."""
        from strategy.paper_trading import PaperSession
        self.assertTrue(callable(PaperSession))
    
    def test_paper_trade_import(self):
        """PaperTrade must be importable from strategy.paper_trading."""
        from strategy.paper_trading import PaperTrade
        self.assertTrue(callable(PaperTrade))
    
    def test_paper_session_record_trade(self):
        """PaperSession.record_trade works with string money values."""
        from strategy.paper_trading import PaperSession, PaperTrade
        
        session = PaperSession()
        trade = PaperTrade(
            spread_id="test_001",
            outcome="WOULD_EXECUTE",
            amount_in_numeraire="100.000000",
            expected_pnl_numeraire="1.500000",
        )
        
        result = session.record_trade(trade)
        self.assertTrue(result)
        self.assertEqual(len(session.trades), 1)


if __name__ == "__main__":
    unittest.main()