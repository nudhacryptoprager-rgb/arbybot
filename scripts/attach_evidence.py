#!/usr/bin/env python3
"""
Attach evidence SHA to rolling artifacts.

Usage:
    python scripts/attach_evidence.py --sha <COMMIT_SHA>
    python scripts/attach_evidence.py  # Uses current HEAD

This script:
1. Reads current _latest.json and run_summary_latest.json
2. Sets run_context.evidence_sha to the provided (or current) SHA
3. Updates Status_M4.md with evidence link (optional)
4. Does NOT re-run or regenerate artifacts

The purpose is to document which commit "officially" corresponds to
these rolling artifacts, after the code has been committed.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROLLING_DIR = REPO_ROOT / "data" / "runs" / "_rolling"
STATUS_MD = REPO_ROOT / "docs" / "status" / "Status_M4.md"


def get_git_head_sha() -> str:
    """Get current git HEAD SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=REPO_ROOT
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def attach_evidence(sha: str, update_status_md: bool = True) -> int:
    """
    Attach evidence SHA to rolling artifacts.
    
    Args:
        sha: The commit SHA to attach as evidence
        update_status_md: Whether to update Status_M4.md
        
    Returns:
        0 on success, 1 on error
    """
    print(f"[ATTACH] Evidence SHA: {sha}")
    warnings = []
    
    # Update _latest.json
    latest_path = ROLLING_DIR / "_latest.json"
    if latest_path.exists():
        with open(latest_path) as f:
            latest_data = json.load(f)
        
        # Initialize run_context if not present
        if "run_context" not in latest_data:
            latest_data["run_context"] = {
                "code_sha": latest_data.get("git_sha", "unknown"),
                "code_dirty": False,
                "code_desc": latest_data.get("git_sha", "unknown"),
                "evidence_sha": None,  # null, not ""
            }
        
        # Check if run was dirty - add warning
        if latest_data["run_context"].get("code_dirty") is True:
            warnings.append("DIRTY_WORKTREE_PRECOMMIT: Run was made with uncommitted changes")
        
        latest_data["run_context"]["evidence_sha"] = sha
        # Also set top-level for easy access
        latest_data["latest_evidence_sha"] = sha
        latest_data["evidence_attached_at"] = datetime.now(timezone.utc).isoformat()
        
        with open(latest_path, "w") as f:
            json.dump(latest_data, f, indent=2)
        print(f"[ATTACH] Updated: {latest_path.name}")
    else:
        print(f"[ATTACH] SKIP: {latest_path.name} not found")
    
    # Update run_summary_latest.json
    summary_path = ROLLING_DIR / "run_summary_latest.json"
    if summary_path.exists():
        with open(summary_path) as f:
            summary_data = json.load(f)
        
        # Initialize run_context if not present
        if "run_context" not in summary_data:
            summary_data["run_context"] = {
                "code_sha": summary_data.get("source_sha", "unknown"),
                "code_dirty": False,
                "code_desc": summary_data.get("source_sha", "unknown"),
                "evidence_sha": None,  # null, not ""
            }
        
        # Check if run was dirty - add issue to evidence
        if summary_data["run_context"].get("code_dirty") is True:
            if "evidence" in summary_data:
                issues = summary_data["evidence"].get("issues", [])
                if "DIRTY_WORKTREE_PRECOMMIT" not in issues:
                    issues.append("DIRTY_WORKTREE_PRECOMMIT")
                    summary_data["evidence"]["issues"] = issues
                    summary_data["evidence"]["ok"] = False
        
        summary_data["run_context"]["evidence_sha"] = sha
        
        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=2)
        print(f"[ATTACH] Updated: {summary_path.name}")
    else:
        print(f"[ATTACH] SKIP: {summary_path.name} not found")
    
    # Update Status_M4.md
    if update_status_md and STATUS_MD.exists():
        content = STATUS_MD.read_text()
        
        # Find and update Evidence SHA line
        old_pattern = "**Evidence SHA**:"
        if old_pattern in content:
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if old_pattern in line:
                    lines[i] = f"**Evidence SHA**: `{sha}`  "
                    break
            content = "\n".join(lines)
            STATUS_MD.write_text(content)
            print(f"[ATTACH] Updated: Status_M4.md")
        else:
            print(f"[ATTACH] SKIP: Status_M4.md - no Evidence SHA line found")
    
    # Print warnings
    if warnings:
        print(f"[ATTACH] WARNINGS:")
        for w in warnings:
            print(f"  - {w}")
    
    print(f"[ATTACH] Done. Evidence SHA {sha} attached to rolling artifacts.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Attach evidence SHA to rolling artifacts"
    )
    parser.add_argument(
        "--sha",
        default=None,
        help="Commit SHA to attach (default: current HEAD)"
    )
    parser.add_argument(
        "--no-status-md",
        action="store_true",
        help="Skip updating Status_M4.md"
    )
    args = parser.parse_args()
    
    sha = args.sha or get_git_head_sha()
    if sha == "unknown":
        print("[ERROR] Could not determine SHA. Use --sha to specify.")
        return 1
    
    return attach_evidence(sha, update_status_md=not args.no_status_md)


if __name__ == "__main__":
    sys.exit(main())
