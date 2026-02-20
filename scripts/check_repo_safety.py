#!/usr/bin/env python3
# PATH: scripts/check_repo_safety.py
"""
Repo Safety Gate - checks for dangerous tracked files.

This gate ensures the repo does not contain:
1. .vscode/settings.json if it has auto-approve keys (security risk)
2. Any secrets or credentials in tracked files
3. Runtime artifacts in git-tracked locations

Usage:
  python scripts/check_repo_safety.py           # Run check
  python scripts/check_repo_safety.py --strict  # Fail on warnings too

Exit codes:
  0 = PASS (no security issues found)
  1 = FAIL (dangerous files or patterns found)
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

PROJECT_ROOT = Path(__file__).parent.parent

__version__ = "1.3.0"

# Files that should never be tracked in git
FORBIDDEN_TRACKED_FILES = [
    # VS Code settings with potential auto-approve keys
    ".vscode/settings.json",
]

# DEV_REPORT files allowed in repo (v1.2.0)
# Only these exact files are allowed, no versioned DEV_REPORT files
ALLOWED_DEV_REPORTS = [
    "docs/DEV_REPORT_LATEST.md",
    "docs/DEV_REPORT_CANONICAL_UA.md",
]

# Script version mappings for Status file validation (v1.3.0)
# Map: Status file -> (script file, version regex pattern in Status)
STATUS_VERSION_MAPPINGS = {
    "docs/status/Status_M5_0.md": ("scripts/ci_m5_0_gate.py", r"ci_m5_0_gate\.py.*v(\d+\.\d+\.\d+)"),
    "docs/status/Status_M4.md": ("scripts/ci_m4_execution_gate.py", r"ci_m4_execution_gate\.py.*v(\d+\.\d+\.\d+)"),
}

# Keys that should never appear in TRACKED files
# v1.1.0: Only check tracked files, untracked files are INFO-level
FORBIDDEN_KEYS_IN_TRACKED = [
    "chat.tools.terminal.autoApprove",
    "chat.tools.codeGeneration.autoApprove",
    "chat.acceptAllTerminalRisks",
    "chat.agent.autoApprove",
]

# Patterns that indicate secrets or credentials
SECRET_PATTERNS = [
    "ALCHEMY_API_KEY=",
    "TENDERLY_ACCESS_KEY=",
    "PRIVATE_KEY=",
    "INFURA_API_KEY=",
    "ETHERSCAN_API_KEY=",
]


def is_git_tracked(filepath: Path) -> bool:
    """Check if a file is tracked by git."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(filepath)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def check_forbidden_files() -> List[str]:
    """Check for forbidden tracked files."""
    issues = []
    
    for forbidden in FORBIDDEN_TRACKED_FILES:
        filepath = PROJECT_ROOT / forbidden
        if filepath.exists() and is_git_tracked(filepath):
            issues.append(f"FORBIDDEN: {forbidden} is tracked in git (should be untracked)")
    
    return issues


def check_forbidden_keys() -> Tuple[List[str], List[str]]:
    """Check for forbidden keys in tracked files.
    
    Returns:
        Tuple of (errors, info_messages)
        - errors: Issues in tracked files that cause FAIL
        - info_messages: INFO-level messages for untracked files
    """
    errors = []
    info_messages = []
    
    # Check .vscode/settings.json specifically
    vscode_settings = PROJECT_ROOT / ".vscode" / "settings.json"
    if vscode_settings.exists():
        try:
            content = vscode_settings.read_text()
            tracked = is_git_tracked(vscode_settings)
            for key in FORBIDDEN_KEYS_IN_TRACKED:
                if key in content:
                    if tracked:
                        errors.append(f"DANGER: {key} found in tracked .vscode/settings.json")
                    else:
                        # v1.1.0: INFO-only for untracked files, never counted as warning
                        info_messages.append(f"INFO: {key} found in .vscode/settings.json (untracked, OK)")
        except Exception as e:
            errors.append(f"ERROR: Could not read .vscode/settings.json: {e}")
    
    return errors, info_messages


def check_secret_patterns() -> List[str]:
    """Check for secret patterns in tracked files."""
    issues = []
    
    # Check common files that might contain secrets
    files_to_check = [
        ".env",
        ".env.local",
        "config/secrets.yaml",
        "secrets.yaml",
    ]
    
    for filename in files_to_check:
        filepath = PROJECT_ROOT / filename
        if filepath.exists() and is_git_tracked(filepath):
            try:
                content = filepath.read_text()
                for pattern in SECRET_PATTERNS:
                    if pattern in content:
                        issues.append(f"SECRET: {pattern.split('=')[0]} found in tracked {filename}")
            except Exception:
                pass
    
    return issues


def check_runtime_artifacts() -> List[str]:
    """Check that runtime artifacts are not tracked."""
    issues = []
    
    # data/runs/** should NOT be tracked
    runs_dir = PROJECT_ROOT / "data" / "runs"
    if runs_dir.exists():
        try:
            result = subprocess.run(
                ["git", "ls-files", "data/runs/"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True
            )
            tracked_files = [f for f in result.stdout.strip().split("\n") if f]
            
            # Exclude docs/artifacts which are allowed
            tracked_runtime = [f for f in tracked_files if not f.startswith("docs/")]
            
            if tracked_runtime:
                issues.append(f"RUNTIME: {len(tracked_runtime)} runtime files tracked in data/runs/")
                for f in tracked_runtime[:5]:  # Show first 5
                    issues.append(f"  - {f}")
                if len(tracked_runtime) > 5:
                    issues.append(f"  ... and {len(tracked_runtime) - 5} more")
        except Exception as e:
            issues.append(f"ERROR: Could not check data/runs/: {e}")
    
    return issues


def check_dev_report_bloat() -> List[str]:
    """Check for versioned DEV_REPORT files (v1.2.0).
    
    Only docs/DEV_REPORT_LATEST.md and docs/DEV_REPORT_CANONICAL_UA.md are allowed.
    Any versioned DEV_REPORT_YYYY-MM-DD_v*.md files cause FAIL.
    """
    issues = []
    
    try:
        result = subprocess.run(
            ["git", "ls-files", "docs/DEV_REPORT*.md"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        tracked_reports = [f for f in result.stdout.strip().split("\n") if f]
        
        # Check each tracked file against allowed list
        for report in tracked_reports:
            if report not in ALLOWED_DEV_REPORTS:
                issues.append(f"DEV_REPORT_BLOAT: {report} is tracked (only DEV_REPORT_LATEST.md allowed)")
        
        # Also check for multiple DEV_REPORT files (excluding canonical)
        non_canonical = [r for r in tracked_reports if r != "docs/DEV_REPORT_CANONICAL_UA.md"]
        if len(non_canonical) > 1:
            issues.append(f"DEV_REPORT_BLOAT: {len(non_canonical)} DEV_REPORT files tracked (should be exactly 1)")
            
    except Exception as e:
        issues.append(f"ERROR: Could not check DEV_REPORT files: {e}")
    
    return issues


def extract_script_version(script_path: Path) -> str:
    """Extract __version__ from a Python script."""
    try:
        content = script_path.read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)
    except Exception:
        pass
    return ""


def check_status_version_consistency() -> List[str]:
    """Check that Status files reference correct script versions (v1.3.0).
    
    Each Status file that references a script version must match the actual
    __version__ in that script.
    """
    issues = []
    
    for status_file, (script_file, pattern) in STATUS_VERSION_MAPPINGS.items():
        status_path = PROJECT_ROOT / status_file
        script_path = PROJECT_ROOT / script_file
        
        if not status_path.exists() or not script_path.exists():
            continue
        
        try:
            status_content = status_path.read_text(encoding="utf-8")
            match = re.search(pattern, status_content)
            if match:
                doc_version = match.group(1)
                script_version = extract_script_version(script_path)
                
                if script_version and doc_version != script_version:
                    issues.append(
                        f"STATUS_VERSION_MISMATCH: {status_file} says {script_file} v{doc_version}, "
                        f"but script has __version__={script_version}"
                    )
        except Exception as e:
            issues.append(f"ERROR: Could not check {status_file}: {e}")
    
    return issues


def check_dev_report_freshness() -> List[str]:
    """Check that DEV_REPORT_LATEST.md contains current rolling timestamp (v1.3.0).
    
    The DEV_REPORT should contain the run_timestamp from run_summary_latest.json
    to prevent stale reports.
    """
    issues = []
    
    dev_report_path = PROJECT_ROOT / "docs" / "DEV_REPORT_LATEST.md"
    rolling_summary_path = PROJECT_ROOT / "data" / "runs" / "_rolling" / "run_summary_latest.json"
    
    if not dev_report_path.exists():
        issues.append("DEV_REPORT_FRESHNESS: docs/DEV_REPORT_LATEST.md not found")
        return issues
    
    if not rolling_summary_path.exists():
        # No rolling artifacts = skip freshness check (offline-only mode)
        return []
    
    try:
        with open(rolling_summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        
        run_timestamp = summary.get("run_context", {}).get("run_timestamp", "")
        if not run_timestamp:
            return []  # No timestamp to check
        
        # Extract date portion (YYYY-MM-DD) for freshness check
        timestamp_date = run_timestamp[:10]  # "2026-02-19"
        
        dev_report_content = dev_report_path.read_text(encoding="utf-8")
        
        # Check if the DEV_REPORT contains the timestamp date
        if timestamp_date not in dev_report_content:
            issues.append(
                f"WARN: DEV_REPORT_FRESHNESS: docs/DEV_REPORT_LATEST.md may be stale "
                f"(rolling timestamp {timestamp_date} not found)"
            )
            
    except Exception as e:
        issues.append(f"ERROR: Could not check DEV_REPORT freshness: {e}")
    
    return issues


def main():
    parser = argparse.ArgumentParser(description="Repo Safety Gate")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings too")
    args = parser.parse_args()
    
    print(f"Repo Safety Gate v{__version__}")
    print("=" * 50)
    
    all_issues = []
    
    # Run all checks
    print("\n[1] Checking forbidden tracked files...")
    issues = check_forbidden_files()
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: No forbidden tracked files")
    
    print("\n[2] Checking for forbidden keys...")
    errors, info_msgs = check_forbidden_keys()
    for err in errors:
        print(f"  {err}")
        all_issues.append(err)
    for info in info_msgs:
        print(f"  {info}")  # Just print, don't add to issues
    if not errors and not info_msgs:
        print("  OK: No forbidden keys found")
    
    print("\n[3] Checking for secret patterns...")
    issues = check_secret_patterns()
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: No secrets in tracked files")
    
    print("\n[4] Checking runtime artifacts...")
    issues = check_runtime_artifacts()
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: Runtime artifacts not tracked")
    
    print("\n[5] Checking DEV_REPORT bloat...")
    issues = check_dev_report_bloat()
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: Only DEV_REPORT_LATEST.md tracked")
    
    print("\n[6] Checking Status version consistency...")
    issues = check_status_version_consistency()
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: Status files match script versions")
    
    print("\n[7] Checking DEV_REPORT freshness...")
    issues = check_dev_report_freshness()
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: DEV_REPORT_LATEST.md is fresh")
    
    # Summary
    print("\n" + "=" * 50)
    # v1.1.0: INFO messages don't count toward warnings
    errors = [i for i in all_issues if not i.startswith("WARN:") and not i.startswith("INFO:")]
    warnings = [i for i in all_issues if i.startswith("WARN:")]
    
    if errors:
        print(f"RESULT: FAIL ({len(errors)} errors, {len(warnings)} warnings)")
        sys.exit(1)
    elif warnings and args.strict:
        print(f"RESULT: FAIL (strict mode, {len(warnings)} warnings)")
        sys.exit(1)
    else:
        print(f"RESULT: PASS ({len(warnings)} warnings)")
        sys.exit(0)


if __name__ == "__main__":
    main()
