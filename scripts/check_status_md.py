#!/usr/bin/env python3
"""CI check for Status*.md files (v2.x SHA-free).

Validates that all Status*.md files in docs/status/ contain the required sections
for v2.x provenance model (timestamp-based, no SHA).

Required sections:
1. Metadata header (Updated, Status, Policy Version OR Gate Version)
2. DoD-commands (canonical commands) OR Canonical Commands
3. Risks/Blockers OR Evidence Links
4. Next steps/focus OR Stage Clarification

Evidence Completeness (v2.x - for M4):
- Updated timestamp
- RunDir or run_id
- run_mode (REGISTRY_REAL/FIXTURE_OFFLINE)
- Policy/Gate version

Legacy/Archive files (containing 'ARCHIVE' or '_legacy' in name/header) are skipped.

Usage:
    python scripts/check_status_md.py [--verbose] [--evidence]
    python scripts/check_status_md.py --file Status_M4.md --verbose
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Required patterns for Status*.md files (v2.x - no SHA)
REQUIRED_PATTERNS = [
    # Metadata header - v2.x format (no SHA required)
    (r"\*\*(Оновлено|Updated)\*\*:", "Metadata: Updated timestamp"),
    (r"\*\*(Статус|Status)\*\*:", "Metadata: Status indicator"),
    (r"\*\*(Policy Version|Gate Version)\*\*:", "Metadata: Policy/Gate Version"),
    # DoD-commands section - either format
    (r"#{1,3}\s*(DoD-commands|канонічн[іа] команд|Canonical Commands)", "Section: Canonical Commands"),
    # Risks/Blockers/Evidence section - either format
    (r"#{1,3}\s*(Risks|Ризики|Blockers|Known Blockers|Evidence Links)", "Section: Evidence/Risks/Blockers"),
    # Next steps section - either format (including "Next focus", "Definition of Done")
    (r"#{1,3}\s*(Next steps|Next focus|Наступні кроки|Stage Clarification|Definition of Done)", "Section: Next steps/Stage"),
]

# Evidence completeness patterns (v2.x - timestamp-based, no SHA)
EVIDENCE_PATTERNS = [
    (r"\*\*Updated\*\*:\s*\d{4}-\d{2}-\d{2}", "Evidence: Updated date"),
    (r"(RunDir|run_dir|run_id).*data/runs/", "Evidence: RunDir/run_id path"),
    (r"run_mode.*(REGISTRY_REAL|FIXTURE_OFFLINE|ONLINE)", "Evidence: run_mode declaration"),
    (r"#{1,3}\s*(Canonical Commands|Proof Commands)", "Evidence: Commands section"),
    (r"\d+\s+passed", "Evidence: test results (N passed)"),
    (r"ci_full_pipeline|ci_m4_execution_gate|ci_m5_0_gate", "Evidence: gate command"),
]

# DONE status must have specific evidence (v2.x - no SHA)
DONE_EVIDENCE_PATTERNS = [
    (r"total_net_usdc", "DONE Evidence: total_net_usdc metric"),
    (r"signals_count|simulations_passed", "DONE Evidence: signals metric"),
    (r"(RESULT|status):\s*PASS", "DONE Evidence: PASS result"),
]


def is_legacy_or_archive(filepath: Path, content: str) -> bool:
    """Check if file is legacy/archive and should be skipped."""
    if "_legacy" in filepath.name.lower():
        return True
    if "ARCHIVE" in content[:500]:  # Check header
        return True
    if "НЕ АКТУАЛЬНО" in content[:500]:
        return True
    return False


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
    """Check Status file for evidence completeness (v2.x - no SHA).
    
    Evidence completeness means:
    - Updated timestamp is present
    - RunDir/run_id is present
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
    has_done = bool(re.search(r"\*\*DONE\*\*|\*\*PROVEN\*\*", content, re.IGNORECASE))
    if has_done:
        for pattern, name in DONE_EVIDENCE_PATTERNS:
            found = bool(re.search(pattern, content, re.IGNORECASE | re.MULTILINE))
            results.append((name, found))
    
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Status*.md files for required sections (v2.x)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--evidence", action="store_true", help="Check evidence completeness (for DONE claims)")
    parser.add_argument("--file", help="Check only specific Status file (e.g., Status_M4.md)")
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
        content = filepath.read_text(encoding="utf-8")
        
        # Skip legacy/archive files
        if is_legacy_or_archive(filepath, content):
            if args.verbose:
                print(f"SKIP: {filepath.name} (legacy/archive)")
            continue
        
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
        print("\n[OK] All Status*.md files pass validation (v2.x)")
        return 0
    else:
        print("\n[FAIL] Some Status*.md files are missing required sections")
        print("   See docs/DEV_REPORT_CANONICAL_UA.md for required format")
        if args.evidence:
            print("   Status DONE claims require complete evidence (timestamp, RunDir, run_mode, metrics)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
