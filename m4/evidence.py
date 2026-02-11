"""
M4 Evidence Module (SHA-free v2.0)

Timestamp-based artifact provenance. SHA tracking removed.

Key concepts:
- run_timestamp: ISO timestamp when scan started (primary identifier)
- All SHA fields return None for backward compatibility

Usage:
    from m4.evidence import get_git_context, get_run_timestamp
    
    context = get_git_context()
    # {'code_sha': None, 'code_dirty': None, 'code_desc': None, 'run_timestamp': '2026-02-11T...'}
"""

from datetime import datetime, timezone
from typing import Optional


def get_run_timestamp() -> str:
    """
    Get current UTC timestamp for artifact provenance.
    
    Returns:
        ISO-8601 timestamp string with Z suffix.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_git_head_sha() -> Optional[str]:
    """
    DEPRECATED: SHA tracking removed.
    
    Returns:
        None (SHA tracking disabled)
    """
    return None


def get_git_context() -> dict:
    """
    Get run context for artifact provenance.
    
    SHA tracking removed - returns timestamp-based context.
    SHA fields kept as None for backward compatibility.
    
    Returns:
        Dict with:
            code_sha: None (deprecated)
            code_dirty: None (deprecated)
            code_desc: None (deprecated)
            run_timestamp: str - ISO timestamp of this call
    """
    return {
        "code_sha": None,
        "code_dirty": None,
        "code_desc": None,
        "run_timestamp": get_run_timestamp(),
    }


def get_git_sha() -> Optional[str]:
    """
    DEPRECATED: SHA tracking removed.
    Kept for backward compatibility.
    """
    return None


def get_source_sha() -> Optional[str]:
    """
    DEPRECATED: SHA tracking removed.
    Kept for backward compatibility.
    """
    return None


def is_evidence_ok(issues: list) -> bool:
    """
    Evidence is always OK now (no SHA validation needed).
    
    Kept for backward compatibility with gates.
    
    Args:
        issues: List of issue strings (ignored)
        
    Returns:
        Always True
    """
    return True


def validate_evidence(git_ctx: dict) -> tuple:
    """
    Validate evidence - always passes now (no SHA validation).
    
    Kept for backward compatibility.
    
    Args:
        git_ctx: Dict from get_git_context() (ignored)
        
    Returns:
        (True, [])
    """
    return True, []
