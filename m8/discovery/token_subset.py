"""Load token address subsets for hot-path expansion and probes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Set


def load_token_subset_file(path: str | Path) -> Optional[Set[str]]:
    p = Path(path)
    if not p.is_file():
        return None
    doc = json.loads(p.read_text(encoding="utf-8"))
    raw = doc.get("tokens") or []
    out: Set[str] = set()
    for item in raw:
        if isinstance(item, str) and item.lower().startswith("0x"):
            out.add(item.lower())
        elif isinstance(item, dict):
            addr = item.get("token") or item.get("address")
            if addr and str(addr).lower().startswith("0x"):
                out.add(str(addr).lower())
    return out if out else None


def write_token_subset_file(
    tokens: List[str] | List[Dict[str, Any]],
    path: str | Path,
    *,
    source: str,
    lane_meta: Optional[dict] = None,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    normalized: List[Dict[str, Any]] = []
    for item in tokens:
        if isinstance(item, dict):
            addr = str(item.get("token") or item.get("address") or "").lower()
            if not addr.startswith("0x"):
                continue
            row = {"token": addr}
            for key in ("source", "priority_score", "first_seen_block", "transitions_1_to_2"):
                if item.get(key) is not None:
                    row[key] = item[key]
            normalized.append(row)
        elif isinstance(item, str) and item.lower().startswith("0x"):
            normalized.append({"token": item.lower()})
    payload = {
        "schema_version": "m8_token_subset_v2",
        "source": source,
        "tokens": normalized,
        "token_count": len(normalized),
    }
    if lane_meta:
        payload["lane_meta"] = lane_meta
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
