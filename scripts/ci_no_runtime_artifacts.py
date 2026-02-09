#!/usr/bin/env python3
"""
CI guard: Fail if runtime artifacts are staged for commit.

This script enforces the Artifacts Policy (docs/WORKFLOW.md#artifacts-policy):
- Runtime artifacts from data/runs/ are NEVER committed
- Only golden fixtures under docs/artifacts/golden/ are allowed

Usage:
  python scripts/ci_no_runtime_artifacts.py

Exit codes:
  0 - No runtime artifacts staged (OK)
  1 - Runtime artifacts found in staged changes (FAIL)

Can be used as:
  - Pre-commit hook
  - CI check
  - Manual verification
"""

import subprocess
import sys
from pathlib import Path

# Patterns that indicate runtime artifacts (should NOT be committed)
FORBIDDEN_PATTERNS = [
    "data/runs/",
    "run_summary_",
    "stability_summary_",
    "execution_report_",
    "signals_",
    "m4_stability_agg",
    "_latest.json",
    "online_runs_report_",
]

# Exceptions (allowed even if matching patterns)
ALLOWED_PATHS = [
    "docs/artifacts/golden/",
]


def get_staged_files() -> list[str]:
    """Get list of files staged for commit."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [f.strip() for f in result.stdout.splitlines() if f.strip()]


def is_allowed(filepath: str) -> bool:
    """Check if file is in allowed paths."""
    for allowed in ALLOWED_PATHS:
        if filepath.startswith(allowed):
            return True
    return False


def is_forbidden(filepath: str) -> bool:
    """Check if file matches forbidden patterns."""
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in filepath:
            return True
    return False


def main() -> int:
    """Main entry point."""
    staged = get_staged_files()
    
    violations = []
    for filepath in staged:
        if is_forbidden(filepath) and not is_allowed(filepath):
            violations.append(filepath)
    
    if violations:
        print("=" * 60)
        print("ERROR: Runtime artifacts detected in staged changes!")
        print("=" * 60)
        print()
        print("The following files violate the Artifacts Policy:")
        print("(See docs/WORKFLOW.md#artifacts-policy)")
        print()
        for v in violations:
            print(f"  ❌ {v}")
        print()
        print("Runtime artifacts should stay local or in CI artifacts.")
        print("Only golden fixtures under docs/artifacts/golden/ are allowed.")
        print()
        print("To fix:")
        print("  git reset HEAD <file>  # unstage the file")
        print("  # or add to .gitignore")
        print()
        return 1
    
    print("✅ No runtime artifacts in staged changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
