#!/usr/bin/env python3
"""CI check for Status*.md files.

Validates that all Status*.md files in docs/status/ contain the required sections
defined in docs/REPORT_TEMPLATE.md.

Required sections:
1. Metadata header (Оновлено, SHA, Статус) OR new format (Updated, Evidence SHA, Status)
2. DoD-commands (канонічні команди) OR Canonical Commands
3. Risks/Ризики OR Evidence Links
4. Next steps/Наступні кроки OR Stage Clarification

Evidence Completeness (for M4):
- Evidence SHA
- RunDir
- run_mode
- Proof Commands section

Usage:
    python scripts/check_status_md.py [--fix] [--evidence]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Required patterns for Status*.md files (either format)
REQUIRED_PATTERNS = [
    # Metadata header - either old format or new format
    (r"\*\*(Оновлено|Updated)\*\*:", "Metadata: Updated timestamp"),
    (r"\*\*(SHA|Evidence SHA)\*\*:", "Metadata: SHA commit"),
    (r"\*\*(Статус|Status)\*\*:", "Metadata: Status indicator"),
    # DoD-commands section - either format
    (r"#{1,3}\s*(DoD-commands|канонічн[іа] команд|Canonical Commands)", "Section: Canonical Commands"),
    # Risks/Evidence section - either format
    (r"#{1,3}\s*(Risks|Ризики|Evidence Links)", "Section: Evidence/Risks"),
    # Next steps section - either format
    (r"#{1,3}\s*(Next steps|Наступні кроки|Stage Clarification)", "Section: Next steps/Stage"),
]

# Evidence completeness patterns (for --evidence mode)
EVIDENCE_PATTERNS = [
    (r"\*\*Evidence SHA\*\*:\s*`[0-9a-f]{7,}`", "Evidence: SHA reference"),
    (r"\*\*RunDir\*\*.*data/runs/", "Evidence: RunDir path"),
    (r"\*\*run_mode\*\*.*FIXTURE_OFFLINE|ONLINE|REALTIME", "Evidence: run_mode declaration"),
    (r"#{1,3}\s*Proof Commands", "Evidence: Proof Commands section"),
    (r"\d+\s+passed", "Evidence: test results (N passed)"),
    (r"ci_full_pipeline|ci_m4_execution_gate", "Evidence: gate command"),
]

# DONE status must have specific evidence
DONE_EVIDENCE_PATTERNS = [
    (r"total_net_usdc", "DONE Evidence: total_net_usdc metric"),
    (r"simulations_passed", "DONE Evidence: simulations_passed metric"),
    (r"RESULT:\s*PASS", "DONE Evidence: PASS result"),
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


def check_evidence_completeness(filepath: Path) -> list[tuple[str, bool]]:
    """Check Status file for evidence completeness.
    
    Evidence completeness means:
    - SHA is present and specific
    - RunDir is present
    - run_mode is declared
    - Proof commands are shown
    - If DONE status, metrics are present
    """
    content = filepath.read_text(encoding="utf-8")
    results = []
    
    # Check evidence patterns
    for pattern, name in EVIDENCE_PATTERNS:
        found = bool(re.search(pattern, content, re.IGNORECASE | re.MULTILINE))
        results.append((name, found))
    
    # If file claims DONE, check for DONE-specific evidence
    has_done = bool(re.search(r"\*\*DONE\*\*", content, re.IGNORECASE))
    if has_done:
        for pattern, name in DONE_EVIDENCE_PATTERNS:
            found = bool(re.search(pattern, content, re.IGNORECASE | re.MULTILINE))
            results.append((name, found))
    
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Status*.md files for required sections")
    parser.add_argument("--fix", action="store_true", help="Add missing sections (not implemented)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--evidence", action="store_true", help="Check evidence completeness (for DONE claims)")
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
        
        # Evidence completeness check (--evidence flag)
        if args.evidence:
            ev_results = check_evidence_completeness(filepath)
            ev_missing = [name for name, found in ev_results if not found]
            if ev_missing:
                all_passed = False
                print(f"  EVIDENCE INCOMPLETE: {filepath.name}")
                for m in ev_missing:
                    print(f"    [X] Missing: {m}")
            else:
                print(f"  [OK] Evidence complete: {filepath.name}")

    if all_passed:
        print("\n[OK] All Status*.md files pass validation")
        return 0
    else:
        print("\n[FAIL] Some Status*.md files are missing required sections")
        print("   See docs/REPORT_TEMPLATE.md for required format")
        if args.evidence:
            print("   Status DONE claims require complete evidence (SHA, RunDir, run_mode, metrics)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
