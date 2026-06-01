"""Pool depth / quality filter for M9 productive graph (Steps 2+5).

Loads evidence-based quarantine entries and provides helpers to check if a
route's pool should be excluded from the productive lane.

Design principle (per GPT review):
- NOT a global pair blacklist: other pools for the same pair may remain active.
- Filters specific pool_address / fee-tier routes confirmed as TOXIC or too shallow.
- Discovery lane still sees all pools for RCA purposes.
- Productive lane excludes quarantined + depth-insufficient pools.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import FrozenSet, Optional

logger = logging.getLogger(__name__)

_DEFAULT_QUARANTINE_PATH = "data/quarantine/m9_pool_depth_quarantine.json"

# Placeholder addresses used in the quarantine file before depth probe fills them
_PLACEHOLDER_PREFIXES = {"0x000000000000000000000000000000000000000"}

# Tiered quarantine: productive lane hard-drops only fatal reasons by default.
# Soft reasons remain visible in discovery lane and as metadata tags.
_HARD_QUARANTINE_REASONS = frozenset({
    "HONEYPOT",
    "FACTORY_NO_POOL",
    "ZERO_LIQUIDITY",
    "POOL_ZERO_LIQUIDITY",
    "UNSUPPORTED_DEX_TYPE",
    "UNKNOWN_V4_HOOK",
    "BLACKLISTED",
    "STRUCTURAL_SINGLE_VENUE_TOPOLOGY",
})

_SOFT_QUARANTINE_REASONS = frozenset({
    "TOXIC_PRICE_IMPACT",
    "LOW_EFFECTIVE_DEPTH",
})


def _entry_quarantine_reason(entry: dict) -> str:
    return str(
        entry.get("reject_reason")
        or entry.get("quarantine_reason")
        or ""
    ).strip()


def load_quarantined_pool_addresses(
    quarantine_path: str = _DEFAULT_QUARANTINE_PATH,
    *,
    hard_only: bool = True,
) -> FrozenSet[str]:
    """Load pool addresses from the depth quarantine file.

    Returns frozenset of lowercase pool addresses that must be excluded
    from the M9 productive graph lane.

    When ``hard_only=True`` (default), soft reasons such as
    ``TOXIC_PRICE_IMPACT`` and ``LOW_EFFECTIVE_DEPTH`` are retained as
    metadata but do not hard-drop pools from the productive graph.

    Placeholder addresses (0x0000...0001, 0x0000...0002) are silently skipped —
    they are filled in by pool_depth_probe after an on-chain run.
    """
    path = Path(quarantine_path)
    if not path.exists():
        logger.debug(
            "Pool depth quarantine file not found: %s (skipping — no pools excluded)",
            quarantine_path,
        )
        return frozenset()

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.warning(
            "Failed to load pool depth quarantine %s: %s",
            quarantine_path,
            exc,
            extra={"context": {"event": "pool_depth_quarantine_load_error", "error": str(exc)}},
        )
        return frozenset()

    addresses: set[str] = set()
    now_utc = __import__("datetime").datetime.utcnow()
    for entry in data.get("quarantined_pools", []):
        addr = entry.get("pool_address", "")
        if not addr or not addr.startswith("0x"):
            continue
        # Skip placeholder entries (not yet filled by pool_depth_probe)
        addr_lower = addr.lower()
        is_placeholder = any(addr_lower.startswith(p.lower()) for p in _PLACEHOLDER_PREFIXES)
        if is_placeholder:
            logger.debug(
                "Skipping placeholder quarantine entry: pair=%s fee=%s",
                entry.get("pair_id"),
                entry.get("fee"),
            )
            continue
        reason = _entry_quarantine_reason(entry)
        if hard_only and reason in _SOFT_QUARANTINE_REASONS:
            logger.debug(
                "Soft quarantine (not hard-dropped in productive lane): pair=%s reason=%s pool=%s",
                entry.get("pair_id"),
                reason,
                addr_lower[:14],
            )
            continue
        # Respect TTL: if retry_after_utc is set and has passed, skip (transient quarantine)
        retry_after = entry.get("retry_after_utc")
        if retry_after:
            try:
                import datetime as _dt
                retry_dt = _dt.datetime.strptime(retry_after, "%Y-%m-%dT%H:%M:%SZ")
                if now_utc >= retry_dt:
                    logger.info(
                        "Quarantine entry expired (retry_after=%s): pair=%s pool=%s — "
                        "excluded from filter; re-probe to confirm or remove",
                        retry_after,
                        entry.get("pair_id"),
                        addr_lower[:14],
                    )
                    continue
            except Exception:
                pass  # unparseable retry_after: treat as permanent
        addresses.add(addr_lower)

    if addresses:
        logger.info(
            "Pool depth quarantine loaded: %d addresses excluded from productive lane",
            len(addresses),
            extra={
                "context": {
                    "event": "pool_depth_quarantine_loaded",
                    "count": len(addresses),
                    "path": quarantine_path,
                }
            },
        )
    return frozenset(addresses)


def load_soft_quarantined_pool_addresses(
    quarantine_path: str = _DEFAULT_QUARANTINE_PATH,
) -> FrozenSet[str]:
    """Return pool addresses tagged with soft quarantine reasons (metadata only)."""
    path = Path(quarantine_path)
    if not path.exists():
        return frozenset()
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return frozenset()

    addresses: set[str] = set()
    for entry in data.get("quarantined_pools", []):
        addr = entry.get("pool_address", "")
        if not addr or not addr.startswith("0x"):
            continue
        addr_lower = addr.lower()
        if any(addr_lower.startswith(p.lower()) for p in _PLACEHOLDER_PREFIXES):
            continue
        if _entry_quarantine_reason(entry) in _SOFT_QUARANTINE_REASONS:
            addresses.add(addr_lower)
    return frozenset(addresses)


def load_quarantine_metadata(
    quarantine_path: str = _DEFAULT_QUARANTINE_PATH,
) -> list:
    """Return full list of quarantine entries for dashboard/artifact display."""
    path = Path(quarantine_path)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("quarantined_pools", [])
    except Exception:
        return []


def is_depth_sufficient(entry: dict, min_effective_depth_usd: float) -> bool:
    """Return True if an inventory route entry has sufficient on-chain depth.

    Uses the ``effective_depth_usd`` field produced by pool_depth_probe.
    If the field is absent (probe not yet run), returns True — conservative:
    unknown depth does not trigger exclusion.

    Args:
        entry: One dict from inventory active_routes.
        min_effective_depth_usd: Minimum acceptable depth in USD.
            0.0 means no filter (always True).
    """
    if min_effective_depth_usd <= 0:
        return True
    depth = entry.get("effective_depth_usd")
    if depth is None:
        return True  # depth unknown → don't exclude (conservative)
    return float(depth) >= min_effective_depth_usd
