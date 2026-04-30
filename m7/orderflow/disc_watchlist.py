"""E1.42 Iter 2 — DISC→PROD watchlist with TTL.

When the discovery (DISC) lane records a profitable round-trip case,
that pair becomes a candidate for promotion to the production (PROD)
lane's hot universe. To prevent stale promotions from accumulating, each
entry carries an explicit ``ttl_seconds`` and an ``expires_at_epoch``;
``prune_expired`` removes entries past their TTL, and
``is_pair_active`` answers PROD-lane membership queries.

Artifact: ``data/runs/_rolling/m7_disc_watchlist.json`` (shared across
lanes — DISC writes, PROD reads). Schema:

    {
      "schema_version": "1.0",
      "updated_at_epoch": <int>,
      "entries": [
        {
          "pair_address": "0x...",
          "token_a": "0x...",
          "token_b": "0x...",
          "buy_venue": "pancakeswap_v3",
          "buy_fee": 500,
          "sell_venue": "uniswap_v3",
          "sell_fee": 10000,
          "profit_bps": 91.0771,
          "scoring_path": "registry_fast",
          "session_id": "5749662e",
          "promoted_at_epoch": 1714348497,
          "ttl_seconds": 14400,
          "expires_at_epoch": 1714362897
        }
      ]
    }

This module is intentionally side-effect free at import time. Wiring
into the runtime is done by ``hot_runtime_artifacts._update_rollup_*``
(producer) and the PROD intent loader (consumer) in a follow-up step.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.logging import get_logger

logger = get_logger("m7.orderflow.disc_watchlist")

SCHEMA_VERSION = "1.0"
DEFAULT_TTL_SEC = 14400  # 4 hours
DEFAULT_PATH = os.path.join("data", "runs", "_rolling", "m7_disc_watchlist.json")


def _now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _resolve_path(path: Optional[str] = None) -> str:
    if path:
        return path
    return os.environ.get("ARBY_DISC_WATCHLIST_PATH", DEFAULT_PATH)


def _atomic_write(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=os.path.dirname(path), suffix=".tmp", prefix=".arby_disc_wl_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_watchlist(path: Optional[str] = None) -> Dict[str, Any]:
    """Read the watchlist artifact. Returns canonical empty payload on miss/error."""
    p = _resolve_path(path)
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("entries"), list):
                return {
                    "schema_version": data.get("schema_version", SCHEMA_VERSION),
                    "updated_at_epoch": int(data.get("updated_at_epoch") or 0),
                    "entries": list(data["entries"]),
                }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug("read_watchlist failed: %s", str(exc)[:120])
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at_epoch": 0,
        "entries": [],
    }


def prune_expired(
    payload: Dict[str, Any],
    *,
    now_epoch: Optional[int] = None,
) -> Dict[str, Any]:
    """Return a copy of *payload* with expired entries dropped."""
    now = now_epoch if now_epoch is not None else _now_epoch()
    keep: List[Dict[str, Any]] = []
    for e in payload.get("entries", []):
        try:
            exp = int(e.get("expires_at_epoch") or 0)
        except (TypeError, ValueError):
            exp = 0
        if exp > now:
            keep.append(e)
    out = dict(payload)
    out["entries"] = keep
    return out


def record_profitable_pair(
    *,
    pair_address: str,
    token_a: Optional[str] = None,
    token_b: Optional[str] = None,
    buy_venue: Optional[str] = None,
    buy_fee: Optional[int] = None,
    sell_venue: Optional[str] = None,
    sell_fee: Optional[int] = None,
    profit_bps: float,
    scoring_path: Optional[str] = None,
    session_id: Optional[str] = None,
    ttl_seconds: int = DEFAULT_TTL_SEC,
    path: Optional[str] = None,
    now_epoch: Optional[int] = None,
) -> Dict[str, Any]:
    """Append/replace a profitable-pair entry. Pair_address is the dedup key.

    Returns the updated payload (post-prune, post-merge).
    """
    if not pair_address:
        raise ValueError("pair_address is required")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be > 0")
    pair_norm = pair_address.lower()
    now = now_epoch if now_epoch is not None else _now_epoch()
    p = _resolve_path(path)

    payload = prune_expired(read_watchlist(p), now_epoch=now)
    entries = [e for e in payload["entries"] if str(e.get("pair_address", "")).lower() != pair_norm]
    entries.append(
        {
            "pair_address": pair_norm,
            "token_a": (token_a or "").lower() or None,
            "token_b": (token_b or "").lower() or None,
            "buy_venue": buy_venue,
            "buy_fee": buy_fee,
            "sell_venue": sell_venue,
            "sell_fee": sell_fee,
            "profit_bps": round(float(profit_bps), 4),
            "scoring_path": scoring_path,
            "session_id": session_id,
            "promoted_at_epoch": now,
            "ttl_seconds": int(ttl_seconds),
            "expires_at_epoch": now + int(ttl_seconds),
        }
    )
    payload["entries"] = entries
    payload["updated_at_epoch"] = now
    payload["schema_version"] = SCHEMA_VERSION
    _atomic_write(p, payload)
    return payload


def is_pair_active(
    pair_address: str,
    *,
    path: Optional[str] = None,
    now_epoch: Optional[int] = None,
) -> bool:
    """Return True iff *pair_address* has an unexpired watchlist entry."""
    if not pair_address:
        return False
    target = pair_address.lower()
    payload = prune_expired(read_watchlist(path), now_epoch=now_epoch)
    return any(
        str(e.get("pair_address", "")).lower() == target for e in payload["entries"]
    )


def active_pair_addresses(
    *,
    path: Optional[str] = None,
    now_epoch: Optional[int] = None,
) -> List[str]:
    """Return lowercase pair_addresses currently active in the watchlist."""
    payload = prune_expired(read_watchlist(path), now_epoch=now_epoch)
    return [str(e.get("pair_address", "")).lower() for e in payload["entries"] if e.get("pair_address")]
