"""Merge rolling external pool hint artifacts across radar phases."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from m8.discovery.pool_hints import PoolHint, dedupe_hints, build_artifact


def _hint_rows(artifact: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not artifact:
        return []
    return [row for row in (artifact.get("hints") or []) if isinstance(row, dict)]


def merge_hint_artifacts(
    *artifacts: Optional[Dict[str, Any]],
    chain: str = "base",
    sources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Dedupe-merge hint rows; later phases augment, not replace, prior verified pools."""
    merged: List[PoolHint] = []
    source_set: List[str] = list(sources or [])
    for artifact in artifacts:
        if not artifact:
            continue
        for src in artifact.get("sources") or []:
            if src and src not in source_set:
                source_set.append(str(src))
        for row in _hint_rows(artifact):
            merged.append(PoolHint.from_dict(row))
    deduped = dedupe_hints(merged)
    metrics = {}
    for artifact in artifacts:
        if not artifact:
            continue
        m = artifact.get("metrics") or {}
        if isinstance(m, dict):
            for k, v in m.items():
                if k not in metrics or metrics[k] in (None, 0, "", []):
                    metrics[k] = v
    return build_artifact(
        chain=chain,
        sources=source_set or ["merged"],
        hints=deduped,
        metrics=metrics,
    )


def load_hint_artifact(path: str | Path) -> Optional[Dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def merge_hint_artifact_files(
    base_path: str | Path,
    incoming_path: str | Path,
    output_path: str | Path,
    *,
    chain: str = "base",
) -> Dict[str, Any]:
    base = load_hint_artifact(base_path)
    incoming = load_hint_artifact(incoming_path)
    merged = merge_hint_artifacts(base, incoming, chain=chain)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged
