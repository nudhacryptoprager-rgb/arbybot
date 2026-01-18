# PATH: tests/unit/test_logging_contract.py
"""
Tests specifically for logging contract enforcement.

Per Issue #3 AC (A): No kwargs to logger; only extra={"context": {...}} allowed.
"""

import ast
import logging
import unittest
from io import StringIO
from pathlib import Path
from typing import List, Dict, Any


class TestLoggingContractEnforcement(unittest.TestCase):
    """AST-based tests for logging contract."""
    
    ALLOWED_KWARGS = {"exc_info", "extra", "stack_info", "stacklevel"}
    
    def _find_logger_violations(self, source_code: str) -> List[Dict[str, Any]]:
        """Find logger calls with invalid kwargs using AST."""
        violations = []
        
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return violations
        
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            
            if not isinstance(node.func, ast.Attribute):
                continue
            
            # Check if it's a logger method
            method_name = node.func.attr
            if method_name not in ("debug", "info", "warning", "error", "critical", "exception"):
                continue
            
            # Check the object (should be logger or similar)
            obj = node.func.value
            is_logger = False
            
            if isinstance(obj, ast.Name):
                is_logger = "log" in obj.id.lower() or obj.id == "logger"
            elif isinstance(obj, ast.Attribute):
                is_logger = "log" in obj.attr.lower() or obj.attr == "logger"
            
            if not is_logger:
                continue
            
            # Check kwargs
            for kw in node.keywords:
                if kw.arg and kw.arg not in self.ALLOWED_KWARGS:
                    violations.append({
                        "line": node.lineno,
                        "method": method_name,
                        "invalid_kwarg": kw.arg,
                    })
        
        return violations
    
    def test_paper_trading_no_invalid_kwargs(self):
        """strategy/paper_trading.py has no invalid logger kwargs."""
        filepath = Path("strategy/paper_trading.py")
        if not filepath.exists():
            self.skipTest(f"{filepath} not found")
        
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        
        violations = self._find_logger_violations(source)
        
        if violations:
            msg = f"Found {len(violations)} logging violations in {filepath}:\n"
            for v in violations:
                msg += f"  Line {v['line']}: logger.{v['method']}(..., {v['invalid_kwarg']}=...)\n"
            self.fail(msg)
    
    def test_run_scan_no_invalid_kwargs(self):
        """strategy/jobs/run_scan.py has no invalid logger kwargs."""
        filepath = Path("strategy/jobs/run_scan.py")
        if not filepath.exists():
            self.skipTest(f"{filepath} not found")
        
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        
        violations = self._find_logger_violations(source)
        
        if violations:
            msg = f"Found {len(violations)} logging violations in {filepath}:\n"
            for v in violations:
                msg += f"  Line {v['line']}: logger.{v['method']}(..., {v['invalid_kwarg']}=...)\n"
            self.fail(msg)
    
    def test_truth_report_no_invalid_kwargs(self):
        """monitoring/truth_report.py has no invalid logger kwargs."""
        filepath = Path("monitoring/truth_report.py")
        if not filepath.exists():
            self.skipTest(f"{filepath} not found")
        
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        
        violations = self._find_logger_violations(source)
        
        if violations:
            msg = f"Found {len(violations)} logging violations in {filepath}:\n"
            for v in violations:
                msg += f"  Line {v['line']}: logger.{v['method']}(..., {v['invalid_kwarg']}=...)\n"
            self.fail(msg)


class TestLoggingContextCapture(unittest.TestCase):
    """Tests that context is properly captured in log records."""
    
    def setUp(self):
        """Set up test logger with capturing handler."""
        self.captured_records = []
        
        class CapturingHandler(logging.Handler):
            def __init__(self, records_list):
                super().__init__()
                self.records = records_list
            
            def emit(self, record):
                self.records.append(record)
        
        self.logger = logging.getLogger(f"test_capture_{id(self)}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = []
        self.handler = CapturingHandler(self.captured_records)
        self.logger.addHandler(self.handler)
    
    def test_context_captured_in_record(self):
        """Log records capture context from extra."""
        self.logger.info(
            "Test message",
            extra={"context": {"key1": "value1", "key2": 123}}
        )
        
        self.assertEqual(len(self.captured_records), 1)
        record = self.captured_records[0]
        
        self.assertTrue(hasattr(record, "context"))
        self.assertEqual(record.context["key1"], "value1")
        self.assertEqual(record.context["key2"], 123)
    
    def test_context_with_spread_id(self):
        """spread_id in context is accessible."""
        self.logger.error(
            "Trade failed",
            extra={"context": {"spread_id": "test_123", "error": "timeout"}}
        )
        
        record = self.captured_records[0]
        self.assertEqual(record.context["spread_id"], "test_123")
    
    def test_exc_info_with_context(self):
        """exc_info works alongside context."""
        try:
            raise ValueError("Test error")
        except ValueError:
            self.logger.error(
                "Caught error",
                exc_info=True,
                extra={"context": {"operation": "test"}}
            )
        
        record = self.captured_records[0]
        self.assertIsNotNone(record.exc_info)
        self.assertEqual(record.context["operation"], "test")


if __name__ == "__main__":
    unittest.main()