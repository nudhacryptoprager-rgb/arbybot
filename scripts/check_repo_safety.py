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

__version__ = "1.5.0"

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
# NOTE: v1.4.0 - versions removed from Status headers per DOCS_POLICY.md
STATUS_VERSION_MAPPINGS = {
    # Disabled: versions now tracked only in DEV_REPORT_LATEST.md
    # "docs/status/Status_M5_0.md": ("scripts/ci_m5_0_gate.py", r"ci_m5_0_gate\.py.*v(\d+\.\d+\.\d+)"),
    # "docs/status/Status_M4.md": ("scripts/ci_m4_execution_gate.py", r"ci_m4_execution_gate\.py.*v(\d+\.\d+\.\d+)"),
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


# Files where versions are ALLOWED (exempt from docs-lint)
DOCS_VERSION_EXEMPT = [
    "docs/DEV_REPORT_LATEST.md",           # Canonical version tracking file
    "docs/m4/ROLLING_CONTRACT.md",          # Schema version definitions (API contract)
    "docs/m4/M4_POLICY.md",                 # Policy thresholds (API contract)
]

# Files where ISO timestamps are allowed
DOCS_TIMESTAMP_EXEMPT = [
    "docs/DEV_REPORT_LATEST.md",           # Contains rolling provenance
    "docs/m4/ROLLING_CONTRACT.md",          # JSON examples with timestamps
    "docs/m4/M4_POLICY.md",                 # JSON examples with timestamps
]


def check_docs_lint() -> List[str]:
    """Check docs for forbidden version and timestamp patterns.
    
    Per DOCS_POLICY.md:
    - Version strings (vX.Y.Z) are forbidden except in exempt files
    - Status_*.md files may have timestamps but NOT version strings
    - ISO timestamps forbidden in most docs except Status_*.md and exempt files
    """
    issues = []
    
    # Pattern for semantic versions: v1.2.3, v2.3.4-fix, etc.
    version_pattern = re.compile(r'\bv\d+\.\d+\.\d+\b')
    # Pattern for ISO timestamps: 2026-02-19T10:00:00
    timestamp_pattern = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')
    
    docs_dir = PROJECT_ROOT / "docs"
    if not docs_dir.exists():
        return issues
    
    try:
        # Get all tracked markdown files in docs/
        result = subprocess.run(
            ["git", "ls-files", "docs/**/*.md", "docs/*.md"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        
        tracked_docs = [f for f in result.stdout.strip().split("\n") if f and f.endswith(".md")]
        
        for doc_path in tracked_docs:
            full_path = PROJECT_ROOT / doc_path
            if not full_path.exists():
                continue
            
            try:
                content = full_path.read_text(encoding="utf-8")
                is_status_file = "Status_" in doc_path
                
                # Check VERSION strings
                # Status files must NOT have versions (they have timestamps instead)
                # Exempt files can have versions
                if doc_path not in DOCS_VERSION_EXEMPT:
                    matches = version_pattern.findall(content)
                    if matches:
                        unique_versions = set(matches)
                        issues.append(
                            f"DOCS_LINT: {doc_path} contains version string(s): {', '.join(sorted(unique_versions))} "
                            f"(versions only allowed in DEV_REPORT_LATEST.md)"
                        )
                
                # Check TIMESTAMP patterns
                # Status files can have timestamps, exempt files can have timestamps
                # Other docs should not have real ISO timestamps
                if not is_status_file and doc_path not in DOCS_TIMESTAMP_EXEMPT:
                    ts_matches = timestamp_pattern.findall(content)
                    if ts_matches:
                        # Only flag if more than 1 unique timestamp (could be a placeholder example)
                        unique_ts = set(ts_matches)
                        if len(unique_ts) > 1:
                            issues.append(
                                f"DOCS_LINT: {doc_path} contains ISO timestamp(s): {', '.join(sorted(list(unique_ts)[:3]))}... "
                                f"(timestamps only allowed in Status_*.md and DEV_REPORT_LATEST.md)"
                            )
                    
            except Exception:
                pass  # Skip unreadable files
                
    except Exception as e:
        issues.append(f"ERROR: Could not run docs-lint: {e}")
    
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


def check_roadmap_governance(allow_edit: bool = False) -> List[str]:
    """Check that Roadmap.md is not modified without explicit permission (v1.5.0).
    
    This prevents accidental Roadmap drift. Agent must have --allow-roadmap-edit flag
    to modify Roadmap.md.
    
    Args:
        allow_edit: If True, skip this check (explicit permission granted)
    
    Returns:
        List of error messages if Roadmap.md is modified without permission
    """
    if allow_edit:
        return []  # Explicit permission granted
    
    issues = []
    roadmap_path = PROJECT_ROOT / "Roadmap.md"
    
    if not roadmap_path.exists():
        return []  # No Roadmap.md = skip
    
    try:
        # Check if Roadmap.md has uncommitted changes (modified in working tree)
        result = subprocess.run(
            ["git", "diff", "--name-only", "Roadmap.md"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        if "Roadmap.md" in result.stdout:
            issues.append(
                "ROADMAP_GOVERNANCE: Roadmap.md has uncommitted changes. "
                "Use --allow-roadmap-edit flag if this is intentional."
            )
        
        # Also check staged changes
        result_staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "Roadmap.md"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        if "Roadmap.md" in result_staged.stdout:
            issues.append(
                "ROADMAP_GOVERNANCE: Roadmap.md has staged changes. "
                "Use --allow-roadmap-edit flag if this is intentional."
            )
            
    except Exception as e:
        issues.append(f"ERROR: Could not check Roadmap governance: {e}")
    
    return issues


def main():
    parser = argparse.ArgumentParser(description="Repo Safety Gate")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings too")
    parser.add_argument("--allow-roadmap-edit", action="store_true", 
                        help="Allow Roadmap.md modifications (explicit permission)")
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
    
    print("\n[8] Checking docs lint (version policy)...")
    issues = check_docs_lint()
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: Docs comply with DOCS_POLICY.md")
    
    print("\n[9] Checking Roadmap governance...")
    issues = check_roadmap_governance(args.allow_roadmap_edit)
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: Roadmap.md not modified without explicit permission")
    
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
