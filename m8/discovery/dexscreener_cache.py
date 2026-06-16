"""Local TTL cache for DexScreener token-pairs radar (hot/cold tiers)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_CACHE_PATH = "data/tmp/m8_dexscreener_radar_cache.json"
HOT_TTL_S = 1800.0
COLD_TTL_S = 21600.0


def _now() -> float:
    return time.time()


def load_cache(path: str = DEFAULT_CACHE_PATH) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"entries": {}, "schema_version": "m8_dexscreener_cache.1"}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"entries": {}, "schema_version": "m8_dexscreener_cache.1"}


def save_cache(doc: Dict[str, Any], path: str = DEFAULT_CACHE_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def get_cached_pairs(
    token: str,
    *,
    cache: Optional[Dict[str, Any]] = None,
    path: str = DEFAULT_CACHE_PATH,
    hot: bool = True,
) -> Optional[List[Dict[str, Any]]]:
    doc = cache if cache is not None else load_cache(path)
    entry = (doc.get("entries") or {}).get(token.lower())
    if not entry:
        return None
    ttl = HOT_TTL_S if hot else COLD_TTL_S
    if _now() - float(entry.get("fetched_at") or 0) > ttl:
        return None
    pairs = entry.get("pairs")
    return list(pairs) if isinstance(pairs, list) else None


def set_cached_pairs(
    token: str,
    pairs: List[Dict[str, Any]],
    *,
    cache: Optional[Dict[str, Any]] = None,
    path: str = DEFAULT_CACHE_PATH,
    persist: bool = True,
) -> Dict[str, Any]:
    doc = cache if cache is not None else load_cache(path)
    entries = doc.setdefault("entries", {})
    entries[token.lower()] = {
        "fetched_at": _now(),
        "pairs": pairs,
        "pair_count": len(pairs),
    }
    if persist:
        save_cache(doc, path)
    return doc
