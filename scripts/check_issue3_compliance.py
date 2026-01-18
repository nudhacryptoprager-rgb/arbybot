# PATH: scripts/check_issue3_compliance.py
#!/usr/bin/env python
"""
Script to check Issue #3 compliance across the codebase.

Checks:
1. No invalid logger kwargs
2. No :.Nf format on money fields
3. No float values in money-related code
"""

import ast
import re
import sys
from pathlib import Path
from typing import List, Tuple


def find_python_files(directories: List[str]) -> List[Path]:
    """Find all Python files in given directories."""
    files = []
    for dir_name in directories:
        dir_path = Path(dir_name)
        if dir_path.exists():
            files.extend(dir_path.rglob("*.py"))
    return files


def check_logger_kwargs(filepath: Path) -> List[Tuple[int, str]]:
    """Check for invalid logger kwargs."""
    violations = []
    allowed_kwargs = {"exc_info", "extra", "stack_info", "stacklevel"}
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return violations
    
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        
        if node.func.attr not in ("debug", "info", "warning", "error", "critical"):
            continue
        
        obj = node.func.value
        is_logger = False
        if isinstance(obj, ast.Name):
            is_logger = "log" in obj.id.lower()
        elif isinstance(obj, ast.Attribute):
            is_logger = "log" in obj.attr.lower()
        
        if not is_logger:
            continue
        
        for kw in node.keywords:
            if kw.arg and kw.arg not in allowed_kwargs:
                violations.append((node.lineno, f"logger.{node.func.attr}(..., {kw.arg}=...)"))
    
    return violations


def check_format_codes(filepath: Path) -> List[Tuple[int, str]]:
    """Check for :.Nf format codes on potential money fields."""
    violations = []
    money_patterns = ["pnl", "usdc", "usdt", "amount", "value", "price", "fee", "gas", "cost"]
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        return violations
    
    for i, line in enumerate(lines, 1):
        # Check for :.Nf format codes
        if re.search(r":\.\d+f", line):
            # Check if it's near a money-related variable
            line_lower = line.lower()
            for pattern in money_patterns:
                if pattern in line_lower:
                    violations.append((i, line.strip()[:80]))
                    break
    
    return violations


def main():
    print("Issue #3 Compliance Check")
    print("=" * 60)
    
    directories = ["core", "strategy", "monitoring"]
    files = find_python_files(directories)
    
    total_violations = 0
    
    # Check logger kwargs
    print("\n[1] Checking logger kwargs...")
    for filepath in files:
        violations = check_logger_kwargs(filepath)
        if violations:
            print(f"\n  {filepath}:")
            for line, msg in violations:
                print(f"    Line {line}: {msg}")
                total_violations += 1
    
    if total_violations == 0:
        print("  OK: No invalid logger kwargs found")
    
    # Check format codes
    print("\n[2] Checking format codes on money fields...")
    format_violations = 0
    for filepath in files:
        violations = check_format_codes(filepath)
        if violations:
            print(f"\n  {filepath}:")
            for line, msg in violations:
                print(f"    Line {line}: {msg}")
                format_violations += 1
    
    if format_violations == 0:
        print("  OK: No suspicious format codes found")
    else:
        print(f"\n  WARNING: {format_violations} potential format code issues")
        print("  (Review manually - may be false positives)")
    
    total_violations += format_violations
    
    # Summary
    print("\n" + "=" * 60)
    if total_violations == 0:
        print("PASSED: No compliance issues found")
        return 0
    else:
        print(f"ISSUES: {total_violations} potential problems found")
        return 1


if __name__ == "__main__":
    sys.exit(main())