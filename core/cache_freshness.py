"""Cache freshness guards for runtime JSON under data/cache/."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple


def _parse_iso_ts(value: Any) -> Optional[float]:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def cache_freshness(
    path: Path,
    *,
    schema_id: Optional[str] = None,
    chain: Optional[str] = None,
    max_age_seconds: Optional[float] = None,
    now_ts: Optional[float] = None,
) -> Tuple[bool, str]:
    """Return (is_fresh, reason). Missing file is fresh (nothing to load)."""
    if not path.exists():
        return True, "missing_ok"

    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"unreadable:{exc}"

    if not isinstance(data, dict):
        return False, "not_object"

    if schema_id:
        found = data.get("schema_version") or data.get("schema_id") or data.get("schema")
        if found and schema_id not in str(found):
            return False, f"schema_mismatch:{found}"

    if chain:
        file_chain = data.get("chain") or data.get("chain_key")
        if file_chain and str(file_chain).lower() != str(chain).lower():
            return False, f"chain_mismatch:{file_chain}"

    if max_age_seconds is not None:
        now = now_ts if now_ts is not None else datetime.now(tz=timezone.utc).timestamp()
        ts = _parse_iso_ts(data.get("generated_at_utc"))
        if ts is None:
            ts = _parse_iso_ts(data.get("updated_at_utc"))
        if ts is None:
            ts = float(data.get("last_updated") or data.get("updated_ts") or 0) or None
        if ts is None:
            return False, "no_timestamp"
        age = now - ts
        if age > max_age_seconds:
            return False, f"stale_age_s:{int(age)}"

    return True, "ok"
