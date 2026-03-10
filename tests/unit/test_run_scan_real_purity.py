# PATH: tests/unit/test_run_scan_real_purity.py
"""
Test that run_scan_real.py has no fixture/offline branches.

This test enforces the architectural rule that run_scan_real.py
is ONLY for real RPC orchestration - no fixture generation logic.

Fixture generation lives in:
- ci_m5_0_gate.py --offline
- ci_m4_execution_gate.py --offline
"""

import ast
from pathlib import Path


def test_run_scan_real_has_no_fixture_imports():
    """run_scan_real.py must not import fixture modules."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    assert path.exists(), f"File not found: {path}"
    
    content = path.read_text(encoding="utf-8")
    
    # Forbidden import patterns
    forbidden = [
        "from tests.",
        "import tests.",
        "from strategy.fixtures",
        "import strategy.fixtures",
        "FIXTURE_OFFLINE",
        "generate_fixture",
    ]
    
    for pattern in forbidden:
        assert pattern not in content, \
            f"run_scan_real.py contains forbidden pattern: {pattern}"


def test_run_scan_real_has_no_offline_mode():
    """run_scan_real.py must not have --offline argument."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    assert path.exists(), f"File not found: {path}"
    
    content = path.read_text(encoding="utf-8")
    
    # Check for --offline argument
    assert "--offline" not in content, \
        "run_scan_real.py must not have --offline argument"
    
    assert "offline" not in content.lower() or "ARBY_OFFLINE" in content, \
        "run_scan_real.py should not reference 'offline' mode"


def test_run_scan_real_has_expected_functions():
    """run_scan_real.py must have expected structure."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    assert path.exists(), f"File not found: {path}"
    
    content = path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    
    function_names = {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    
    # Expected core functions
    required = {"run_scan", "run_scanner", "main"}
    missing = required - function_names
    assert not missing, f"Missing expected functions: {missing}"


def test_run_scan_real_line_count():
    """run_scan_real.py should not grow excessively."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    assert path.exists(), f"File not found: {path}"
    
    content = path.read_text(encoding="utf-8")
    line_count = len(content.splitlines())
    
    # Current: ~1313 lines (v3.3.0: +113 for dynamic size sweep)
    # For now, just warn if it grows significantly
    max_lines = 1350  # Alert if it grows past this
    
    assert line_count <= max_lines, \
        f"run_scan_real.py has {line_count} lines (max: {max_lines}). Consider refactoring."
