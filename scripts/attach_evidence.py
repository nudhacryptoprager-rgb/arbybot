#!/usr/bin/env python3
"""
Attach evidence SHA to rolling artifacts.

Usage:
    python scripts/attach_evidence.py --sha <COMMIT_SHA>
    python scripts/attach_evidence.py  # Uses current HEAD
    python scripts/attach_evidence.py --dry-run  # Preview changes

This script:
1. Reads current _latest.json and run_summary_latest.json
2. Sets run_context.evidence_sha to the provided (or current) SHA
3. Updates attached_evidence_sha in _latest.json
4. Updates Status_M4.md with evidence link (optional)
5. Does NOT re-run or regenerate artifacts

The purpose is to document which commit "officially" corresponds to
these rolling artifacts, after the code has been committed.

Exit codes:
    0 = Success (changes applied)
    1 = Error
    2 = Noop (nothing changed - SHA already attached)
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


def attach_evidence(sha: str, update_status_md: bool = True, dry_run: bool = False) -> int:
    """
    Attach evidence SHA to rolling artifacts.
    
    Args:
        sha: The commit SHA to attach as evidence
        update_status_md: Whether to update Status_M4.md
        dry_run: If True, only preview changes without writing
        
    Returns:
        0 on success, 1 on error, 2 on noop (nothing changed)
    """
    mode = "[DRY-RUN]" if dry_run else "[ATTACH]"
    print(f"{mode} Evidence SHA to attach: {sha}")
    print(f"{mode} Rolling dir: {ROLLING_DIR}")
    print()
    
    warnings = []
    changes_made = 0
    
    # =====================================================
    # Update _latest.json
    # =====================================================
    latest_path = ROLLING_DIR / "_latest.json"
    if latest_path.exists():
        with open(latest_path) as f:
            latest_data = json.load(f)
        
        # Get old values
        old_evidence = latest_data.get("run_context", {}).get("evidence_sha")
        old_attached = latest_data.get("attached_evidence_sha")
        
        print(f"{mode} File: {latest_path.name}")
        print(f"{mode}   run_context.evidence_sha: {old_evidence!r} → {sha!r}")
        print(f"{mode}   attached_evidence_sha: {old_attached!r} → {sha!r}")
        
        # Initialize run_context if not present
        if "run_context" not in latest_data:
            latest_data["run_context"] = {
                "code_sha": latest_data.get("latest_run_code_sha", "unknown"),
                "code_dirty": False,
                "code_desc": "unknown",
                "evidence_sha": None,
            }
        
        # Check if run was dirty - add warning
        if latest_data["run_context"].get("code_dirty") is True:
            warnings.append("DIRTY_WORKTREE_PRECOMMIT: Run was made with uncommitted changes")
        
        # Get current HEAD for informational purposes
        current_head = get_git_head_sha()
        
        # Update evidence fields
        latest_data["run_context"]["evidence_sha"] = sha
        latest_data["attached_evidence_sha"] = sha
        latest_data["repo_head_sha_at_attach"] = current_head  # Informational: actual HEAD when attach ran
        latest_data["evidence_attached_at"] = datetime.now(timezone.utc).isoformat()
        
        if old_evidence != sha or old_attached != sha:
            changes_made += 1
            if not dry_run:
                with open(latest_path, "w") as f:
                    json.dump(latest_data, f, indent=2)
                print(f"{mode}   WRITTEN ✓")
        else:
            print(f"{mode}   (no change)")
    else:
        print(f"{mode} SKIP: {latest_path.name} not found")
    
    print()
    
    # =====================================================
    # Update run_summary_latest.json
    # =====================================================
    summary_path = ROLLING_DIR / "run_summary_latest.json"
    if summary_path.exists():
        with open(summary_path) as f:
            summary_data = json.load(f)
        
        # Get old value
        old_evidence = summary_data.get("run_context", {}).get("evidence_sha")
        
        print(f"{mode} File: {summary_path.name}")
        print(f"{mode}   run_context.evidence_sha: {old_evidence!r} → {sha!r}")
        
        # Initialize run_context if not present
        if "run_context" not in summary_data:
            summary_data["run_context"] = {
                "code_sha": summary_data.get("source_sha", "unknown"),
                "code_dirty": False,
                "code_desc": summary_data.get("source_sha", "unknown"),
                "evidence_sha": None,
            }
        
        # Check if run was dirty - add issue to evidence
        if summary_data["run_context"].get("code_dirty") is True:
            if "evidence" in summary_data:
                issues = summary_data["evidence"].get("issues", [])
                if "DIRTY_WORKTREE_PRECOMMIT" not in issues:
                    issues.append("DIRTY_WORKTREE_PRECOMMIT")
                    summary_data["evidence"]["issues"] = issues
                    summary_data["evidence"]["ok"] = False
        
        # Update evidence SHA
        summary_data["run_context"]["evidence_sha"] = sha
        
        if old_evidence != sha:
            changes_made += 1
            if not dry_run:
                with open(summary_path, "w") as f:
                    json.dump(summary_data, f, indent=2)
                print(f"{mode}   WRITTEN ✓")
        else:
            print(f"{mode}   (no change)")
    else:
        print(f"{mode} SKIP: {summary_path.name} not found")
    
    print()
    
    # =====================================================
    # Update Status_M4.md
    # =====================================================
    if update_status_md and STATUS_MD.exists():
        content = STATUS_MD.read_text(encoding='utf-8')
        
        # Find and update Evidence SHA line
        old_pattern = "**Evidence SHA**:"
        if old_pattern in content:
            lines = content.split("\n")
            old_line = None
            new_line = f"**Evidence SHA**: `{sha}`  "
            for i, line in enumerate(lines):
                if old_pattern in line:
                    old_line = line
                    lines[i] = new_line
                    break
            
            print(f"{mode} File: Status_M4.md")
            print(f"{mode}   Evidence SHA line: {old_line.strip()!r} → {new_line.strip()!r}")
            
            # Compare stripped versions to avoid trailing whitespace differences
            if old_line.strip() != new_line.strip():
                changes_made += 1
                if not dry_run:
                    content = "\n".join(lines)
                    STATUS_MD.write_text(content, encoding='utf-8')
                    print(f"{mode}   WRITTEN ✓")
            else:
                print(f"{mode}   (no change)")
        else:
            print(f"{mode} SKIP: Status_M4.md - no '**Evidence SHA**:' line found")
    
    # =====================================================
    # Summary
    # =====================================================
    print()
    if warnings:
        print(f"{mode} WARNINGS:")
        for w in warnings:
            print(f"  ⚠️  {w}")
        print()
    
    if changes_made == 0:
        print(f"{mode} NOOP: No changes needed (evidence_sha already = {sha})")
        if not dry_run:
            print(f"{mode} Exit code: 2 (noop)")
            return 2
    elif dry_run:
        print(f"{mode} Would update {changes_made} file(s). Use without --dry-run to apply.")
    else:
        print(f"{mode} SUCCESS: Evidence SHA {sha} attached to {changes_made} file(s).")
    
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to files"
    )
    args = parser.parse_args()
    
    sha = args.sha or get_git_head_sha()
    if sha == "unknown":
        print("[ERROR] Could not determine SHA. Use --sha to specify.")
        return 1
    
    return attach_evidence(sha, update_status_md=not args.no_status_md, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
