"""Artifact projection helpers — pure scan_scope / provenance transforms."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = ["project_capacity_overlap_scope"]


def project_capacity_overlap_scope(
    *,
    capacity_valid_cycle_ids: List[str],
    shadow_selected_cycle_ids: Optional[List[str]] = None,
    shadow_quoted_cycle_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    cap = set(capacity_valid_cycle_ids or [])
    selected = set(shadow_selected_cycle_ids or [])
    quoted = set(shadow_quoted_cycle_ids or [])
    return {
        "capacity_valid_cycle_ids": sorted(cap),
        "shadow_selected_cycle_ids": sorted(selected),
        "shadow_quoted_cycle_ids": sorted(quoted),
        "capacity_shadow_overlap_count": len(cap & quoted),
        "capacity_shadow_selected_overlap_count": len(cap & selected),
    }
