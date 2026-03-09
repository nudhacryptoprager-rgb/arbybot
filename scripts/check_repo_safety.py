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

__version__ = "1.10.0"

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
    "docs/DOCS_POLICY.md",                  # Policy doc describing the rules (meta-description)
    "docs/m4/ROLLING_CONTRACT.md",          # Schema version definitions (API contract)
    "docs/m4/M4_POLICY.md",                 # Policy thresholds (API contract)
]

# Path prefixes where versions are allowed (golden fixtures, artifacts)
DOCS_VERSION_EXEMPT_PREFIXES = [
    "docs/artifacts/",                      # Golden fixtures may have schema versions
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
    - Version strings (vX.Y.Z, vX.Y.x, vX.Y) are forbidden except in exempt files
    - Status_*.md files may have timestamps but NOT version strings
    - ISO timestamps forbidden in most docs except Status_*.md and exempt files
    """
    issues = []
    
    # Pattern for semantic versions: v1.2.3, v2.4.x, v2.4-fix, etc.
    # Catches: vX.Y.Z, vX.Y.x, vX.Y (with optional suffix)
    version_pattern = re.compile(r'\bv\d+\.\d+(?:\.[0-9xX]+)?(?:-\w+)?\b')
    # Pattern for namespaced schema identifiers: m4:signals:v1.1, namespace:component:vX.Y
    # These are ALLOWED in all docs as they describe JSON schema versions
    namespaced_version_pattern = re.compile(r'\w+:\w+:v\d+\.\d+(?:\.[0-9xX]+)?')
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
                # Exempt files and paths can have versions
                # Namespaced schema identifiers (m4:signals:v1.1) are ALWAYS allowed
                is_exempt = doc_path in DOCS_VERSION_EXEMPT or any(
                    doc_path.startswith(prefix) for prefix in DOCS_VERSION_EXEMPT_PREFIXES
                )
                if not is_exempt:
                    matches = version_pattern.findall(content)
                    if matches:
                        # Filter out versions that are part of namespaced schema identifiers
                        namespaced_matches = set(namespaced_version_pattern.findall(content))
                        standalone_versions = set()
                        for v in matches:
                            # Check if this version is part of any namespaced schema
                            is_namespaced = any(v in ns for ns in namespaced_matches)
                            if not is_namespaced:
                                standalone_versions.add(v)
                        
                        if standalone_versions:
                            issues.append(
                                f"DOCS_LINT: {doc_path} contains version string(s): {', '.join(sorted(standalone_versions))} "
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


def check_dev_report_alignment() -> List[str]:
    """Check that DEV_REPORT_LATEST.md aligns with rolling artifacts (v1.6.1 / v3.2.19).
    
    Verifies that:
    1. run_context.run_timestamp in DEV_REPORT matches run_summary_latest.json
    2. inputs.run_dir_name in DEV_REPORT matches run_summary_latest.json
    3. KEY METRICS: runs_in_window, total_net_usdc, unique_pairs, data_run_rate match _latest.json
    4. v3.2.19: signals_count, agg_status validation
    
    This prevents evidence drift where DEV_REPORT references old/stale artifacts.
    """
    issues = []
    
    dev_report_path = PROJECT_ROOT / "docs" / "DEV_REPORT_LATEST.md"
    rolling_summary_path = PROJECT_ROOT / "data" / "runs" / "_rolling" / "run_summary_latest.json"
    rolling_latest_path = PROJECT_ROOT / "data" / "runs" / "_rolling" / "_latest.json"
    
    if not dev_report_path.exists():
        return []  # No DEV_REPORT = skip
    
    if not rolling_summary_path.exists():
        return []  # No rolling artifacts = skip (offline-only mode)
    
    try:
        with open(rolling_summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        
        rolling_timestamp = summary.get("run_context", {}).get("run_timestamp", "")
        rolling_run_dir = summary.get("inputs", {}).get("run_dir_name", "")
        
        if not rolling_timestamp or not rolling_run_dir:
            return []  # Incomplete rolling data = skip
        
        dev_report_content = dev_report_path.read_text(encoding="utf-8")
        
        # Check run_dir_name alignment
        if rolling_run_dir and rolling_run_dir not in dev_report_content:
            issues.append(
                f"WARN: DEV_REPORT_ALIGNMENT: run_dir_name mismatch. "
                f"Rolling: {rolling_run_dir}, DEV_REPORT: does not contain this run_dir"
            )
        
        # Check run_timestamp alignment (full timestamp, not just date)
        # Extract just the date+time portion for comparison (YYYY-MM-DDTHH:MM:SS)
        rolling_ts_short = rolling_timestamp[:19]  # "2026-02-21T10:36:46"
        if rolling_ts_short not in dev_report_content:
            issues.append(
                f"WARN: DEV_REPORT_ALIGNMENT: run_timestamp mismatch. "
                f"Rolling: {rolling_ts_short}, DEV_REPORT: does not contain this timestamp"
            )
        
        # ===== KEY METRICS CHECK (v1.6.1 / v3.2.19) =====
        # Load _latest.json for quick_stats
        if rolling_latest_path.exists():
            with open(rolling_latest_path, "r", encoding="utf-8") as f:
                latest = json.load(f)
            
            quick_stats = latest.get("quick_stats", {})
            rolling_runs = latest.get("runs_in_window", 0)
            rolling_total_net = quick_stats.get("total_net_usdc", 0)
            rolling_unique_pairs = quick_stats.get("unique_pairs", 0)
            rolling_data_run_rate = latest.get("data_run_rate", 0)
            rolling_agg_status = latest.get("agg_status", "UNKNOWN")
            
            # v3.2.19: signals_count from summary metrics
            rolling_signals_count = summary.get("metrics", {}).get("included_signals_count", 0)
            if rolling_signals_count == 0:
                rolling_signals_count = summary.get("metrics", {}).get("signals_count", 0)
            
            # Extract values from DEV_REPORT using regex
            # runs_in_window: 103
            runs_match = re.search(r'runs_in_window[:\s]+(\d+)', dev_report_content)
            if runs_match:
                dev_runs = int(runs_match.group(1))
                if dev_runs != rolling_runs:
                    issues.append(
                        f"WARN: DEV_REPORT_ALIGNMENT: runs_in_window mismatch. "
                        f"Rolling: {rolling_runs}, DEV_REPORT: {dev_runs}"
                    )
            
            # computed_total_net_usdc: 5347.64 (aggregate value, not single-run total_net_usdc)
            # Look for "computed_total_net_usdc" specifically to avoid matching single-run metrics
            net_match = re.search(r'computed_total_net_usdc[:\s]*\$?([\d,]+\.?\d*)', dev_report_content)
            if net_match:
                dev_net_str = net_match.group(1).replace(',', '')
                dev_net = float(dev_net_str)
                # Allow 1% tolerance for rounding
                tolerance = abs(rolling_total_net) * 0.01
                if abs(dev_net - rolling_total_net) > tolerance:
                    issues.append(
                        f"WARN: DEV_REPORT_ALIGNMENT: total_net_usdc mismatch. "
                        f"Rolling: {rolling_total_net:.2f}, DEV_REPORT: {dev_net:.2f}"
                    )
            
            # unique_pairs: 8
            pairs_match = re.search(r'unique_pairs[:\s]+(\d+)', dev_report_content)
            if pairs_match:
                dev_pairs = int(pairs_match.group(1))
                if dev_pairs != rolling_unique_pairs:
                    issues.append(
                        f"WARN: DEV_REPORT_ALIGNMENT: unique_pairs mismatch. "
                        f"Rolling: {rolling_unique_pairs}, DEV_REPORT: {dev_pairs}"
                    )
            
            # v3.2.19: data_run_rate check (tolerance 0.02)
            rate_match = re.search(r'data_run_rate[:\s]*(0\.\d+)', dev_report_content)
            if rate_match:
                dev_rate = float(rate_match.group(1))
                if abs(dev_rate - rolling_data_run_rate) > 0.02:
                    issues.append(
                        f"WARN: DEV_REPORT_ALIGNMENT: data_run_rate mismatch. "
                        f"Rolling: {rolling_data_run_rate:.4f}, DEV_REPORT: {dev_rate:.4f}"
                    )
            
            # v3.2.19: agg_status check
            if rolling_agg_status != "UNKNOWN":
                # Regex requires colon to avoid matching "agg_status checks" in prose
                agg_match = re.search(r'agg_status:\s*(\w+)', dev_report_content)
                if agg_match:
                    dev_agg = agg_match.group(1)
                    if dev_agg != rolling_agg_status:
                        issues.append(
                            f"WARN: DEV_REPORT_ALIGNMENT: agg_status mismatch. "
                            f"Rolling: {rolling_agg_status}, DEV_REPORT: {dev_agg}"
                        )
            
    except Exception as e:
        issues.append(f"ERROR: Could not check DEV_REPORT alignment: {e}")
    
    return issues


def check_rolling_consistency() -> List[str]:
    """Check internal consistency between all 3 rolling artifacts (v1.7.0).
    
    Rolling artifacts must be internally consistent:
    1. _latest.json.run_context.run_timestamp == run_summary_latest.json.run_context.run_timestamp
    2. _latest.json.run_context.run_dir_name == run_summary_latest.json.inputs.run_dir_name
    3. _latest.json.runs_in_window approx == m4_stability_agg.json.runs_since_timestamp.runs_count
    4. _latest.json.data_run_rate approx == m4_stability_agg.json.quick_stats.data_run_rate
    
    This prevents drift where rolling artifacts reference different runs.
    """
    issues = []
    
    rolling_dir = PROJECT_ROOT / "data" / "runs" / "_rolling"
    latest_path = rolling_dir / "_latest.json"
    summary_path = rolling_dir / "run_summary_latest.json"
    agg_path = rolling_dir / "m4_stability_agg.json"
    
    # All 3 files must exist for consistency check
    if not latest_path.exists():
        return []  # No rolling artifacts = skip
    if not summary_path.exists():
        return []
    if not agg_path.exists():
        return []
    
    try:
        with open(latest_path, "r", encoding="utf-8") as f:
            latest = json.load(f)
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        with open(agg_path, "r", encoding="utf-8") as f:
            agg = json.load(f)
        
        # 1. Check run_timestamp match
        latest_ts = latest.get("run_context", {}).get("run_timestamp", "")
        summary_ts = summary.get("run_context", {}).get("run_timestamp", "")
        
        if latest_ts and summary_ts:
            # Compare first 19 chars (YYYY-MM-DDTHH:MM:SS)
            latest_ts_short = latest_ts[:19]
            summary_ts_short = summary_ts[:19]
            if latest_ts_short != summary_ts_short:
                issues.append(
                    f"ROLLING_DRIFT: run_timestamp mismatch. "
                    f"_latest: {latest_ts_short}, run_summary_latest: {summary_ts_short}"
                )
        
        # 2. Check run_dir_name match
        latest_run_dir = latest.get("run_context", {}).get("run_dir_name", "")
        summary_run_dir = summary.get("inputs", {}).get("run_dir_name", "")
        
        if latest_run_dir and summary_run_dir:
            if latest_run_dir != summary_run_dir:
                issues.append(
                    f"ROLLING_DRIFT: run_dir_name mismatch. "
                    f"_latest: {latest_run_dir}, run_summary_latest: {summary_run_dir}"
                )
        
        # 3. Check runs_in_window consistency
        latest_runs = latest.get("runs_in_window", 0)
        # m4_stability_agg structure: runs_since_timestamp.runs_count or direct runs_in_window
        agg_runs = agg.get("runs_since_timestamp", {}).get("runs_count")
        if agg_runs is None:
            agg_runs = agg.get("runs_in_window", 0)
        
        if latest_runs and agg_runs:
            # Allow difference of 1 (due to timing of when counts are taken)
            if abs(latest_runs - agg_runs) > 1:
                issues.append(
                    f"ROLLING_DRIFT: runs_in_window mismatch. "
                    f"_latest: {latest_runs}, m4_stability_agg: {agg_runs}"
                )
        
        # 4. Check data_run_rate consistency
        latest_drr = latest.get("data_run_rate", 0.0)
        agg_drr = agg.get("quick_stats", {}).get("data_run_rate", 0.0)
        
        if latest_drr and agg_drr:
            # Allow 5% tolerance
            if abs(latest_drr - agg_drr) > 0.05:
                issues.append(
                    f"ROLLING_DRIFT: data_run_rate mismatch. "
                    f"_latest: {latest_drr:.4f}, m4_stability_agg: {agg_drr:.4f}"
                )
        
    except Exception as e:
        issues.append(f"ERROR: Could not check rolling consistency: {e}")
    
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


def check_intent_protection(allow_edit: bool = False) -> List[str]:
    """Check that config/intent.txt is not modified without explicit permission (v1.8.0).
    
    intent.txt defines the stable pair discovery intent for M4+.
    Accidental modifications can break discovery contracts.
    
    Args:
        allow_edit: If True, skip this check (explicit permission granted)
    
    Returns:
        List of error messages if intent.txt is modified without permission
    """
    if allow_edit:
        return []  # Explicit permission granted
    
    issues = []
    intent_path = PROJECT_ROOT / "config" / "intent.txt"
    
    if not intent_path.exists():
        return []  # No intent.txt = skip
    
    try:
        # Check if intent.txt has uncommitted changes (modified in working tree)
        result = subprocess.run(
            ["git", "diff", "--name-only", "config/intent.txt"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        if "intent.txt" in result.stdout:
            issues.append(
                "INTENT_PROTECTION: config/intent.txt has uncommitted changes. "
                "Use --allow-intent-edit flag if this is intentional."
            )
        
        # Also check staged changes
        result_staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "config/intent.txt"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        if "intent.txt" in result_staged.stdout:
            issues.append(
                "INTENT_PROTECTION: config/intent.txt has staged changes. "
                "Use --allow-intent-edit flag if this is intentional."
            )
            
    except Exception as e:
        issues.append(f"ERROR: Could not check intent protection: {e}")
    
    return issues


def check_session_completion_gate() -> List[str]:
    """Check that DEV_REPORT_LATEST.md doesn't claim completion without goal_status=REACHED (v1.9.0).
    
    Session completion requires explicit goal_status field when completion language is detected.
    Per DOCS_POLICY.md section 9: Session Completion Gate.
    
    Returns:
        List of error messages if completion violations detected
    """
    issues = []
    dev_report = PROJECT_ROOT / "docs" / "DEV_REPORT_LATEST.md"
    
    if not dev_report.exists():
        return []  # No report = skip
    
    try:
        content = dev_report.read_text(encoding='utf-8')
        
        # Detect completion language (case-insensitive)
        completion_patterns = [
            r"all\s+\d+\s+steps?\s+completed?",
            r"session\s+(is\s+)?complete[d]?",
            r"all\s+tasks?\s+(are\s+)?done",
            r"goal\s+(is\s+)?reached",
            r"fully\s+implemented",
        ]
        
        import re
        has_completion_language = False
        for pattern in completion_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                has_completion_language = True
                break
        
        if has_completion_language:
            # Check for goal_status field (YAML format or Markdown table format)
            # YAML: "goal_status: REACHED"
            # Markdown table: "| goal_status | **REACHED** |" or "| goal_status | REACHED |"
            has_goal_status = "goal_status:" in content or re.search(r"\|\s*goal_status\s*\|", content)
            has_reached = (
                "goal_status: REACHED" in content 
                or "goal_status:REACHED" in content
                or re.search(r"\|\s*goal_status\s*\|.*\*?\*?REACHED\*?\*?\s*\|", content, re.IGNORECASE)
            )
            
            if not has_goal_status:
                issues.append(
                    "SESSION_COMPLETION: DEV_REPORT contains completion language but no 'goal_status' field. "
                    "Per DOCS_POLICY.md section 9, add 'goal_status: REACHED' to confirm completion."
                )
            elif not has_reached:
                # Has goal_status but not REACHED
                if re.search(r"goal_status[:\s|]+\s*(IN_PROGRESS|BLOCKED)", content, re.IGNORECASE):
                    issues.append(
                        "SESSION_COMPLETION: DEV_REPORT contains completion language but goal_status is not REACHED. "
                        "Remove completion language or set goal_status: REACHED with valid evidence."
                    )
        
        # v1.8.0: Check Primary Blocker Contract
        # If close_allowed=true, blocker_status_after must be RESOLVED or BLOCKED
        has_close_allowed_true = (
            "close_allowed: true" in content.lower()
            or "close_allowed:true" in content.lower()
            or re.search(r"\|\s*close_allowed\s*\|.*\*?\*?true\*?\*?\s*\|", content, re.IGNORECASE)
        )
        
        if has_close_allowed_true:
            # Check blocker_status_after
            has_blocker_resolved = (
                "blocker_status_after: RESOLVED" in content
                or re.search(r"\|\s*blocker_status_after\s*\|.*\*?\*?RESOLVED\*?\*?\s*\|", content, re.IGNORECASE)
            )
            has_blocker_blocked = (
                "blocker_status_after: BLOCKED" in content
                or re.search(r"\|\s*blocker_status_after\s*\|.*\*?\*?BLOCKED\*?\*?\s*\|", content, re.IGNORECASE)
            )
            has_blocker_in_progress = (
                "blocker_status_after: IN_PROGRESS" in content
                or re.search(r"\|\s*blocker_status_after\s*\|.*\*?\*?IN_PROGRESS\*?\*?\s*\|", content, re.IGNORECASE)
            )
            
            if has_blocker_in_progress:
                issues.append(
                    "PRIMARY_BLOCKER: close_allowed=true but blocker_status_after=IN_PROGRESS. "
                    "Per WORKFLOW.md Primary Blocker Contract, session cannot close with blocker in progress."
                )
            elif not has_blocker_resolved and not has_blocker_blocked:
                # Missing blocker_status_after field entirely
                has_blocker_field = (
                    "blocker_status_after" in content
                    or re.search(r"\|\s*blocker_status_after\s*\|", content, re.IGNORECASE)
                )
                if not has_blocker_field:
                    issues.append(
                        "PRIMARY_BLOCKER: close_allowed=true but missing blocker_status_after field. "
                        "Per WORKFLOW.md Primary Blocker Contract, add blocker_status_after: RESOLVED or BLOCKED."
                    )
    except Exception as e:
        issues.append(f"ERROR: Could not check session completion gate: {e}")
    
    return issues


def check_dev_report_claim_consistency() -> List[str]:
    """v3.2.64: Check DEV_REPORT claims are internally consistent.
    
    Validates:
    1. If DEV_REPORT says "PASS (0 warnings)" but goal_status=IN_PROGRESS, that's a conflict
    2. If DEV_REPORT says "Session complete" but goal_status=IN_PROGRESS, it's a contradiction
    3. If DEV_REPORT claims specific warning count that doesn't match reality
    
    Returns:
        List of warning/error messages
    """
    issues = []
    dev_report = PROJECT_ROOT / "docs" / "DEV_REPORT_LATEST.md"
    
    if not dev_report.exists():
        return []
    
    try:
        import re
        content = dev_report.read_text(encoding='utf-8')
        
        # Extract goal_status
        goal_status_match = re.search(
            r'\|\s*goal_status\s*\|\s*\*?\*?(REACHED|IN_PROGRESS|BLOCKED)\*?\*?\s*\|',
            content, re.IGNORECASE
        )
        goal_status = goal_status_match.group(1).upper() if goal_status_match else None
        
        # Check 1: "Session complete" text conflict with IN_PROGRESS goal_status
        session_complete_patterns = [
            r"session\s+(is\s+)?complete[d]?",
            r"session\s+closure?\s+justification",
        ]
        has_session_complete_text = any(
            re.search(p, content, re.IGNORECASE) for p in session_complete_patterns
        )
        
        if has_session_complete_text and goal_status == "IN_PROGRESS":
            issues.append(
                "DEV_REPORT_CONFLICT: Document contains 'Session complete' text but "
                "goal_status=IN_PROGRESS. Remove completion language or change goal_status."
            )
        
        # Check 2: close_allowed=false with completion language
        close_allowed_match = re.search(
            r'\|\s*close_allowed\s*\|\s*(true|false)\s*\|',
            content, re.IGNORECASE
        )
        close_allowed = close_allowed_match.group(1).lower() if close_allowed_match else None
        
        if close_allowed == "false" and has_session_complete_text:
            issues.append(
                "DEV_REPORT_CONFLICT: close_allowed=false but document contains 'Session complete' text. "
                "These are contradictory - update one or the other."
            )
        
        # Check 3: blocker_status_after=FIXED with IN_PROGRESS goal (partial fix claimed as complete)
        blocker_fixed_patterns = [
            r'\|\s*blocker_status_after\s*\|\s*\*?\*?FIXED\*?\*?\s*\|',
            r'blocker_status_after:\s*FIXED',
        ]
        has_blocker_fixed = any(
            re.search(p, content, re.IGNORECASE) for p in blocker_fixed_patterns
        )
        
        if has_blocker_fixed and goal_status == "IN_PROGRESS":
            # This is OK - partial fix, not session complete. Just informational.
            pass  # No issue - consistent state
        
    except Exception as e:
        issues.append(f"ERROR: Could not check DEV_REPORT claim consistency: {e}")
    
    return issues


def check_dev_report_runtime_claims() -> List[str]:
    """v3.2.65: Check DEV_REPORT claims match runtime artifacts.
    
    Parses the Session Progress table to extract runDir -> claimed values,
    then validates against actual run_summary.json in those runDirs.
    
    Validates:
    1. signals count: DEV_REPORT 'signals' column vs run_summary.metrics.signals_count
    2. net_usdc: DEV_REPORT 'net_usdc' column vs run_summary.metrics.total_net_usdc
    
    Returns:
        List of warning/error messages
    """
    issues = []
    dev_report = PROJECT_ROOT / "docs" / "DEV_REPORT_LATEST.md"
    runs_dir = PROJECT_ROOT / "data" / "runs"
    
    if not dev_report.exists():
        return []
    
    if not runs_dir.exists():
        return []  # No runtime artifacts to validate against
    
    try:
        import re
        content = dev_report.read_text(encoding='utf-8')
        
        # Parse Session Progress table for claims
        # Format: | Chain | RunDir | M5 Gate | signals | net_usdc | Status |
        # Example: | **Arbitrum** | 200317 | PASS | **6** | **$3.66** | ✅ SIGNAL_PRODUCING |
        # Note: Handles **$3.66** format where stars surround the dollar sign
        
        table_pattern = re.compile(
            r'\|\s*\*?\*?(\w+)\*?\*?\s*\|\s*(\d{6})\s*\|\s*(PASS|FAIL)\s*\|\s*\*?\*?(\d+)(?:\s*gated)?\*?\*?\s*\|\s*\*?\*?\$?([\d.]+)\*?\*?\s*\|',
            re.IGNORECASE
        )
        
        claims = list(table_pattern.finditer(content))
        
        for match in claims:
            chain = match.group(1)
            run_dir_suffix = match.group(2)
            claimed_signals = int(match.group(4))
            claimed_net_usdc = float(match.group(5))
            
            # Find the actual run directory (e.g., ci_m5_gate_20260309_200317)
            run_dirs = list(runs_dir.glob(f"*_{run_dir_suffix}"))
            
            if not run_dirs:
                # RunDir not found - skip (may be old/deleted)
                continue
            
            run_dir = run_dirs[0]
            reports_dir = run_dir / "reports"
            
            # Find run_summary file
            run_summaries = list(reports_dir.glob("run_summary_*.json"))
            
            if not run_summaries:
                continue
            
            run_summary_path = run_summaries[0]
            
            try:
                run_summary = json.loads(run_summary_path.read_text(encoding='utf-8'))
                metrics = run_summary.get("metrics", {})
                
                actual_signals = metrics.get("signals_count", 0)
                actual_net_usdc = round(metrics.get("total_net_usdc", 0), 2)
                
                # Check signals count mismatch
                if claimed_signals != actual_signals:
                    issues.append(
                        f"DEV_REPORT_RUNTIME_MISMATCH: {chain} ({run_dir_suffix}) claims "
                        f"signals={claimed_signals} but run_summary has signals_count={actual_signals}. "
                        f"(included_signals_count={metrics.get('included_signals_count', 0)})"
                    )
                
                # Check net_usdc mismatch (within $0.01 tolerance for rounding)
                if abs(claimed_net_usdc - actual_net_usdc) > 0.01:
                    issues.append(
                        f"DEV_REPORT_RUNTIME_MISMATCH: {chain} ({run_dir_suffix}) claims "
                        f"net_usdc=${claimed_net_usdc} but run_summary has total_net_usdc=${actual_net_usdc}"
                    )
                    
            except json.JSONDecodeError:
                continue  # Skip malformed files
                
    except Exception as e:
        issues.append(f"ERROR: Could not check DEV_REPORT runtime claims: {e}")
    
    return issues


def main():
    parser = argparse.ArgumentParser(description="Repo Safety Gate")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings too")
    parser.add_argument("--allow-roadmap-edit", action="store_true", 
                        help="Allow Roadmap.md modifications (explicit permission)")
    parser.add_argument("--allow-intent-edit", action="store_true",
                        help="Allow config/intent.txt modifications (explicit permission)")
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
    
    print("\n[10] Checking rolling artifact consistency...")
    issues = check_rolling_consistency()
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: Rolling artifacts internally consistent")
    
    print("\n[11] Checking DEV_REPORT alignment...")
    issues = check_dev_report_alignment()
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: DEV_REPORT_LATEST.md aligned with rolling artifacts")
    
    print("\n[12] Checking intent.txt protection...")
    issues = check_intent_protection(args.allow_intent_edit)
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: config/intent.txt not modified without explicit permission")
    
    print("\n[13] Checking session completion gate...")
    issues = check_session_completion_gate()
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: Session completion gate compliant")
    
    print("\n[14] Checking DEV_REPORT claim consistency...")
    issues = check_dev_report_claim_consistency()
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: DEV_REPORT claims internally consistent")
    
    print("\n[15] Checking DEV_REPORT runtime claims...")
    issues = check_dev_report_runtime_claims()
    all_issues.extend(issues)
    for issue in issues:
        print(f"  {issue}")
    if not issues:
        print("  OK: DEV_REPORT claims match runtime artifacts")
    
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
