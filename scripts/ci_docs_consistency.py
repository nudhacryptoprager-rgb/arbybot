#!/usr/bin/env python3
"""CI gate for docs consistency (v2.x SHA-free).

Checks that documentation follows v2.x provenance model:
- No SHA-based evidence requirements in core docs
- No filecite artifacts
- No references to non-existent files
- DEV_REPORT template matches actual artifact paths

Usage:
    python scripts/ci_docs_consistency.py [--verbose]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Files to check
CORE_DOCS = [
    "Roadmap.md",
    "AGENTS.md",
    "docs/WORKFLOW.md",
    "docs/status/INDEX.md",
    "docs/DEV_REPORT_CANONICAL_UA.md",
    "docs/m4/ROLLING_CONTRACT.md",
]

# Files excluded from v2.x check (legacy/archive - may contain SHA refs)
ARCHIVE_DOCS = [
    "docs/REPORT_TEMPLATE.md",
    "docs/README.md",
    "docs/status/STATUS.md",
]

# Forbidden patterns (v2.x SHA-free)
FORBIDDEN_PATTERNS = [
    (r"filecite", "filecite artifact (garbage from AI)"),
    (r"Evidence SHA.*`[0-9a-f]{7,}`", "SHA-based evidence (deprecated in v2.x)"),
    (r"git diff.*previous_sha", "SHA-based compare workflow (deprecated)"),
    (r"strategy/scanner\.py", "reference to non-existent strategy/scanner.py (use strategy/jobs/run_scan*.py)"),
]

# Non-existent files - these are allowed if marked as TODO
# The script checks these files exist or are marked as TODO
TODO_FILES = [
    "discovery/intent_loader.py",
    "discovery/verify.py", 
    "discovery/index_factories.py",
    "discovery/dexscreener.py",
]

# Required patterns in DEV_REPORT_CANONICAL_UA.md
DEV_REPORT_REQUIRED = [
    (r"run_summary_latest\.metrics\.signals_count", "metrics.signals_count path"),
    (r"m4_stability_agg.*quick_stats", "quick_stats path for aggregator metrics"),
    (r"run_summary_latest\.inputs\.run_mode", "inputs.run_mode path"),
]


def check_file(filepath: Path, verbose: bool = False) -> list[str]:
    """Check a single file for forbidden patterns.
    
    Returns list of issues found.
    """
    if not filepath.exists():
        return [f"File not found: {filepath}"]
    
    content = filepath.read_text(encoding="utf-8")
    issues = []
    
    for pattern, description in FORBIDDEN_PATTERNS:
        matches = list(re.finditer(pattern, content, re.IGNORECASE))
        if matches:
            for match in matches:
                line_num = content[:match.start()].count('\n') + 1
                issues.append(f"{filepath.name}:{line_num} - {description}")
                if verbose:
                    print(f"  FOUND: {match.group()} at line {line_num}")
    
    return issues


def check_dev_report(filepath: Path, verbose: bool = False) -> list[str]:
    """Check DEV_REPORT_CANONICAL_UA.md for required patterns."""
    if not filepath.exists():
        return [f"File not found: {filepath}"]
    
    content = filepath.read_text(encoding="utf-8")
    issues = []
    
    for pattern, description in DEV_REPORT_REQUIRED:
        if not re.search(pattern, content, re.IGNORECASE):
            issues.append(f"{filepath.name} missing: {description}")
    
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Check docs consistency (v2.x)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    all_issues = []
    
    print("Docs Consistency Gate (v2.x SHA-free)")
    print("=" * 50)
    
    # Check core docs for forbidden patterns
    for doc_path in CORE_DOCS:
        filepath = root / doc_path
        if args.verbose:
            print(f"Checking: {doc_path}")
        issues = check_file(filepath, args.verbose)
        all_issues.extend(issues)
        if not issues and args.verbose:
            print(f"  [OK] {doc_path}")
    
    # Check DEV_REPORT for required patterns
    dev_report = root / "docs/DEV_REPORT_CANONICAL_UA.md"
    issues = check_dev_report(dev_report, args.verbose)
    all_issues.extend(issues)

    # Check TODO_FILES references
    # Files in TODO_FILES that are referenced in docs must either:
    # 1. Exist, OR
    # 2. Be marked with TODO/PLACEHOLDER in the referencing doc
    if args.verbose:
        print("Checking TODO_FILES references...")
    for doc_path in CORE_DOCS:
        filepath = root / doc_path
        if not filepath.exists():
            continue
        content = filepath.read_text(encoding="utf-8")
        for todo_file in TODO_FILES:
            file_exists = (root / todo_file).exists()
            is_referenced = todo_file in content
            if is_referenced and not file_exists:
                # Check if marked with TODO/PLACEHOLDER near reference
                pattern = rf"(TODO|PLACEHOLDER|not.*implemented|future).{{0,100}}{re.escape(todo_file)}"
                pattern2 = rf"{re.escape(todo_file)}.{{0,100}}(TODO|PLACEHOLDER|not.*implemented|future)"
                has_marker = re.search(pattern, content, re.IGNORECASE) or re.search(pattern2, content, re.IGNORECASE)
                if not has_marker:
                    all_issues.append(f"{doc_path}: references {todo_file} which doesn't exist (add TODO marker)")
                elif args.verbose:
                    print(f"  [OK] {doc_path} references {todo_file} with TODO marker")

    # Report results
    print()
    if all_issues:
        print(f"[FAIL] {len(all_issues)} issues found:")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1
    else:
        print("[OK] All docs pass consistency check")
        return 0


if __name__ == "__main__":
    sys.exit(main())
