"""
M4 Evidence Module

Git context detection and evidence attachment for artifact provenance.

Key concepts:
- code_sha: SHA of code that ran the scan (captured at run time)
- code_dirty: True if uncommitted changes existed at run time
- evidence_sha: SHA of commit that documents this run (attached post-commit)

Usage:
    from m4.evidence import get_git_context, get_git_head_sha
    
    context = get_git_context()
    # {'code_sha': 'abc1234', 'code_dirty': True, 'code_desc': 'abc1234-dirty'}
"""

import subprocess
from pathlib import Path
from typing import Optional

# Repository root - assumes this file is at m4/evidence.py
REPO_ROOT = Path(__file__).resolve().parent.parent


def get_git_head_sha() -> str:
    """
    Get current git HEAD SHA (short form).
    
    Returns:
        7-char SHA string, or 'unknown' if git not available.
    """
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


def get_git_context() -> dict:
    """
    Get full git context for run_context field.
    
    Returns:
        Dict with:
            code_sha: str - current HEAD SHA (short)
            code_dirty: bool|None - True if uncommitted changes, None if unavailable
            code_desc: str - "{sha}-dirty" or "{sha}-clean" or "unknown"
    """
    context = {
        "code_sha": "unknown",
        "code_dirty": None,
        "code_desc": "unknown",
    }
    try:
        # Get SHA
        sha_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=REPO_ROOT
        )
        if sha_result.returncode == 0:
            sha = sha_result.stdout.strip()
            context["code_sha"] = sha
            
            # Check dirty status
            dirty_result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5, cwd=REPO_ROOT
            )
            if dirty_result.returncode == 0:
                is_dirty = len(dirty_result.stdout.strip()) > 0
                context["code_dirty"] = is_dirty
                context["code_desc"] = f"{sha}-dirty" if is_dirty else f"{sha}-clean"
            else:
                context["code_desc"] = sha
    except Exception:
        pass
    
    return context


def get_git_sha() -> str:
    """
    Get short git SHA for artifact provenance.
    Alias for get_git_head_sha() for backward compatibility.
    """
    return get_git_head_sha()


def get_source_sha() -> str:
    """
    DEPRECATED: Use get_git_context()['code_sha'] instead.
    
    Get source SHA for artifact provenance.
    Returns 'unknown' if git unavailable.
    """
    return get_git_head_sha()


def is_evidence_ok(issues: list) -> bool:
    """
    Determine if evidence is OK based on issues list.
    
    Evidence is NOT OK if:
    - DIRTY_WORKTREE_PRECOMMIT is present
    - Any other critical issue is present
    
    Args:
        issues: List of issue strings
        
    Returns:
        True if evidence is acceptable for PROVEN status
    """
    critical_issues = {"DIRTY_WORKTREE_PRECOMMIT"}
    return not any(issue in critical_issues for issue in issues)


def validate_evidence(git_ctx: dict) -> tuple:
    """
    Validate evidence and return (ok, issues) tuple.
    
    Args:
        git_ctx: Dict from get_git_context()
        
    Returns:
        (ok: bool, issues: list[str])
    """
    issues = []
    
    # Check dirty worktree - weaker evidence
    if git_ctx.get("code_dirty") is True:
        issues.append("DIRTY_WORKTREE_PRECOMMIT")
    
    ok = is_evidence_ok(issues)
    return ok, issues
