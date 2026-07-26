"""Canonical M9 bridge inventory paths (graph-handoff lane)."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

CANONICAL_BRIDGE_PATH = Path("data/tmp/m9_bridge_inventory_graph_handoff_latest.json")
CANONICAL_POINTER_PATH = Path("data/tmp/m9_bridge_canonical_pointer.json")
LEGACY_SHADOW_BRIDGE_PATH = Path("data/tmp/m9_bridge_inventory_shadow_latest.json")
# Production bridge written by the pipeline (start.py add_m9()).
PRODUCTION_BRIDGE_PATH = "data/tmp/m9_bridge_inventory_production_latest.json"


def sync_bridge_canonical(source: Path, *, metrics: Optional[Dict[str, Any]] = None) -> None:
    """Record canonical bridge path and mirror to legacy shadow_latest alias."""
    source = Path(source)
    if not source.is_file():
        return
    pointer = {
        "schema_version": "m9_bridge_canonical_pointer.1",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "canonical_bridge_path": str(CANONICAL_BRIDGE_PATH).replace("\\", "/"),
        "source_path": str(source).replace("\\", "/"),
        "legacy_alias_path": str(LEGACY_SHADOW_BRIDGE_PATH).replace("\\", "/"),
        "bridge_source_metrics": metrics or {},
    }
    CANONICAL_POINTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    CANONICAL_POINTER_PATH.write_text(
        json.dumps(pointer, indent=2), encoding="utf-8"
    )
    if source.resolve() != CANONICAL_BRIDGE_PATH.resolve():
        CANONICAL_BRIDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, CANONICAL_BRIDGE_PATH)
    shutil.copy2(CANONICAL_BRIDGE_PATH, LEGACY_SHADOW_BRIDGE_PATH)
