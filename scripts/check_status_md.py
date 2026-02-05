#!/usr/bin/env python3
"""CI check for Status*.md files.

Validates that all Status*.md files in docs/status/ contain the required sections
defined in docs/REPORT_TEMPLATE.md.

Required sections:
1. Metadata header (Оновлено, SHA, Статус)
2. DoD-commands (канонічні команди)
3. Risks/Ризики
4. Next steps/Наступні кроки

Usage:
    python scripts/check_status_md.py [--fix]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Required patterns for Status*.md files
REQUIRED_PATTERNS = [
    # Metadata header
    (r">\s*\*\*Оновлено\*\*:", "Metadata: Оновлено timestamp"),
    (r">\s*\*\*SHA\*\*:", "Metadata: SHA commit"),
    (r">\s*\*\*Статус\*\*:", "Metadata: Статус indicator"),
    # DoD-commands section
    (r"#{1,3}\s*DoD-commands|#{1,3}\s*канонічн[іа] команд", "Section: DoD-commands"),
    # Risks section (can be in English or Ukrainian)
    (r"#{1,3}\s*(Risks|Ризики)", "Section: Risks"),
    # Next steps section
    (r"#{1,3}\s*(Next steps|Наступні кроки)", "Section: Next steps"),
]


def check_status_file(filepath: Path) -> list[tuple[str, bool]]:
    """Check a Status*.md file for required sections.

    Returns list of (pattern_name, found) tuples.
    """
    content = filepath.read_text(encoding="utf-8")
    results = []
    for pattern, name in REQUIRED_PATTERNS:
        found = bool(re.search(pattern, content, re.IGNORECASE | re.MULTILINE))
        results.append((name, found))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Status*.md files for required sections")
    parser.add_argument("--fix", action="store_true", help="Add missing sections (not implemented)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--file", help="Check only specific Status file (e.g., Status_M5.md)")
    args = parser.parse_args()

    status_dir = Path(__file__).parent.parent / "docs" / "status"
    if not status_dir.exists():
        print(f"WARN: Status directory not found: {status_dir}")
        return 0

    if args.file:
        # Check only specific file
        filepath = status_dir / args.file
        if not filepath.exists():
            print(f"ERROR: File not found: {filepath}")
            return 1
        status_files = [filepath]
    else:
        status_files = list(status_dir.glob("Status*.md"))

    if not status_files:
        print("WARN: No Status*.md files found")
        return 0

    all_passed = True
    for filepath in status_files:
        results = check_status_file(filepath)
        missing = [name for name, found in results if not found]

        if missing:
            all_passed = False
            print(f"FAIL: {filepath.name}")
            for m in missing:
                print(f"  [X] Missing: {m}")
        else:
            if args.verbose:
                print(f"PASS: {filepath.name}")
            else:
                print(f"[OK] {filepath.name}")

    if all_passed:
        print("\n[OK] All Status*.md files pass validation")
        return 0
    else:
        print("\n[FAIL] Some Status*.md files are missing required sections")
        print("   See docs/REPORT_TEMPLATE.md for required format")
        return 1


if __name__ == "__main__":
    sys.exit(main())
