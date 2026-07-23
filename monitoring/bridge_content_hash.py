"""Canonical content hash for bridge inventory depth-gate verification."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict


def bridge_inventory_content_hash(inventory: Dict[str, Any]) -> str:
    """Hash bridge JSON excluding mutable ``depth_enrichment`` metadata."""
    clone = copy.deepcopy(inventory)
    clone.pop("depth_enrichment", None)
    blob = json.dumps(clone, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]
