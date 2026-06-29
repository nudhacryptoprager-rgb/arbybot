"""M8.2 — Pending-pair registry (single→multi venue promotion).

Problem solved
--------------
The M8 sniper window only holds the most recent N events per DEX.  A long-tail
token is typically born on a single venue (e.g. uniswap_v3) and a *second*
venue (e.g. aerodrome) only appears 60–90 min later — by which time the first
observation has already expired from the sniper window.  The bridge's
multi-venue gate (Stage 4b) therefore never sees both venues at once and the
token is quarantined as ``STRUCTURAL_SINGLE_VENUE_TOPOLOGY`` forever.

This module is a **persistent, cross-run accumulator** keyed by the exotic
token's on-chain address.  Every anchor-connected sniper event is recorded as a
``(dex_id, pool_address)`` venue observation.  When a token accumulates ≥2
distinct *quoteable* venues across runs, it becomes *promotable*: the bridge
injects routes for all its venues into ``active_routes``, unlocking the
multi-venue arbitrage cycle that the single-window gate could never see.

Design notes
------------
* **Pure / no RPC.**  Only file IO + dict manipulation, so it is safe to call
  from ``bridge_builder`` without breaking the "bridge is RPC-free" contract.
* **Address-keyed**, not symbol-keyed: symbols collide (many "DEGEN"s); only the
  on-chain address uniquely identifies the token.
* **TTL pruning**: stale venues (``last_seen_ts`` older than the TTL) are dropped
  so dead long-tail tokens do not accumulate forever.
* No import of ``bridge_builder`` (would create a cycle).  The quoteable-venue
  decision is injected as a predicate from the caller.

Artifact: ``data/runs/_rolling/m8_pending_pairs.json``
Schema:   ``m8_pending_pairs.1``
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SCHEMA_VERSION = "m8_pending_pairs.1"

# Default registry location (canonical rolling artifact).
DEFAULT_REGISTRY_PATH = "data/runs/_rolling/m8_pending_pairs.json"

# Default time-to-live for a venue observation (seconds).  Long-tail tokens that
# do not gain a second venue within this window are considered dead and pruned.
# 48h: a token's second venue usually appears within 1–2h, but we keep a generous
# buffer to survive scanner downtime / sparse runs.
DEFAULT_TTL_SECONDS: float = 48 * 3600

# Anchor tokens (kept local to avoid a circular import with bridge_builder).
from m8.discovery.mirror_anchors import ALL_MIRROR_ANCHOR_SYMS

_ANCHOR_TOKENS = ALL_MIRROR_ANCHOR_SYMS

# Fields copied from a sniper event into a venue record.  These are exactly the
# fields bridge_builder._build_m8_route() consumes, so a stored venue record can
# be replayed straight through the normal M8 route builder.
_EVENT_FIELDS = (
    "event_id", "chain", "dex", "factory", "pool",
    "token0", "token1", "token0_symbol", "token1_symbol",
    "fee", "tick_spacing", "stable", "hooks", "block_number",
)

PROMOTION_REASON = "MULTI_VENUE_REGISTRY_PROMOTION"


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------
def load_registry(path: str = DEFAULT_REGISTRY_PATH) -> Dict[str, Any]:
    """Load the registry, returning an empty skeleton when missing/corrupt."""
    p = Path(path)
    if not p.exists():
        return _empty_registry()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_registry()
    if not isinstance(data, dict) or "tokens" not in data:
        return _empty_registry()
    data.setdefault("schema_version", SCHEMA_VERSION)
    if not isinstance(data.get("tokens"), dict):
        data["tokens"] = {}
    return data


def save_registry(registry: Dict[str, Any], path: str = DEFAULT_REGISTRY_PATH) -> None:
    """Persist the registry artifact (atomic-ish overwrite)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    registry["schema_version"] = SCHEMA_VERSION
    registry["generated_at_utc"] = datetime.now(tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with open(p, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def _empty_registry() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": None,
        "updated_ts": None,
        "tokens": {},
    }


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------
def split_token_anchor(
    event: Dict[str, Any],
    anchor_tokens: "frozenset[str]" = _ANCHOR_TOKENS,
) -> Optional[Tuple[str, str, str]]:
    """Return (exotic_addr_lower, exotic_symbol, anchor_symbol) or None.

    None when the event is not anchor-connected, is an anchor↔anchor pair, or is
    missing the exotic token's address.
    """
    t0s = event.get("token0_symbol", "") or ""
    t1s = event.get("token1_symbol", "") or ""
    t0a = event.get("token0", "") or ""
    t1a = event.get("token1", "") or ""

    t0_anchor = t0s in anchor_tokens
    t1_anchor = t1s in anchor_tokens

    if t0_anchor and not t1_anchor:
        anchor_sym, exotic_sym, exotic_addr = t0s, t1s, t1a
    elif t1_anchor and not t0_anchor:
        anchor_sym, exotic_sym, exotic_addr = t1s, t0s, t0a
    else:
        # neither anchor (not anchor-connected) OR both anchor (no exotic leg)
        return None

    if not exotic_addr:
        return None
    return exotic_addr.lower(), exotic_sym, anchor_sym


def _provenance_from_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Pool-creation provenance from a sniper event (not token contract age)."""
    block = event.get("block_number")
    out: Dict[str, Any] = {
        "source_event_block": block,
        "pool_first_seen_block": block,
    }
    if event.get("token_first_seen_ts") is not None:
        out["token_first_seen_ts"] = event["token_first_seen_ts"]
    return out


def _trim_event(event: Dict[str, Any]) -> Dict[str, Any]:
    row = {k: event.get(k) for k in _EVENT_FIELDS}
    row.update(_provenance_from_event(event))
    return row


def update_registry(
    registry: Dict[str, Any],
    events: List[Dict[str, Any]],
    now_ts: float,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    anchor_tokens: "frozenset[str]" = _ANCHOR_TOKENS,
) -> Dict[str, int]:
    """Record anchor-connected events as venue observations and prune stale ones.

    Mutates ``registry`` in place.  Returns a stats dict.
    """
    tokens: Dict[str, Any] = registry.setdefault("tokens", {})
    new_tokens = 0
    new_venues = 0

    for event in events:
        split = split_token_anchor(event, anchor_tokens)
        if split is None:
            continue
        exotic_addr, exotic_sym, anchor_sym = split
        pool = (event.get("pool", "") or "").lower()
        dex = event.get("dex", "") or ""
        if not pool or not dex:
            continue

        tok = tokens.get(exotic_addr)
        if tok is None:
            tok = {
                "symbol": exotic_sym,
                "anchors": [],
                "first_seen_ts": now_ts,
                "last_seen_ts": now_ts,
                "venues": {},
            }
            tokens[exotic_addr] = tok
            new_tokens += 1
        tok["symbol"] = exotic_sym or tok.get("symbol")
        tok["last_seen_ts"] = now_ts
        if anchor_sym and anchor_sym not in tok["anchors"]:
            tok["anchors"].append(anchor_sym)

        venue_key = f"{dex}::{pool}"
        venue = tok["venues"].get(venue_key)
        if venue is None:
            venue = _trim_event(event)
            venue["first_seen_ts"] = now_ts
            venue["last_seen_ts"] = now_ts
            if venue.get("pool_first_seen_block") is None:
                venue["pool_first_seen_block"] = event.get("block_number")
            if venue.get("source_event_block") is None:
                venue["source_event_block"] = event.get("block_number")
            tok["venues"][venue_key] = venue
            new_venues += 1
        else:
            venue["last_seen_ts"] = now_ts
            if venue.get("source_event_block") is None:
                venue["source_event_block"] = event.get("block_number")

    pruned_venues, pruned_tokens = _prune(registry, now_ts, ttl_seconds)

    registry["updated_ts"] = now_ts
    multi = sum(
        1 for t in tokens.values()
        if len({v["dex"] for v in t["venues"].values()}) >= 2
    )
    return {
        "tokens_tracked": len(tokens),
        "venues_tracked": sum(len(t["venues"]) for t in tokens.values()),
        "multi_venue_tokens": multi,
        "new_tokens": new_tokens,
        "new_venues": new_venues,
        "pruned_venues": pruned_venues,
        "pruned_tokens": pruned_tokens,
    }


def _prune(
    registry: Dict[str, Any], now_ts: float, ttl_seconds: float
) -> Tuple[int, int]:
    tokens: Dict[str, Any] = registry.get("tokens", {})
    cutoff = now_ts - ttl_seconds
    pruned_venues = 0
    pruned_tokens = 0
    for addr in list(tokens.keys()):
        tok = tokens[addr]
        venues = tok.get("venues", {})
        for vkey in list(venues.keys()):
            if venues[vkey].get("last_seen_ts", 0) < cutoff:
                del venues[vkey]
                pruned_venues += 1
        if not venues:
            del tokens[addr]
            pruned_tokens += 1
    return pruned_venues, pruned_tokens


def _distinct_quoteable_dex_ids(
    token_entry: Dict[str, Any],
    quoteable: Callable[[str], bool],
) -> "set[str]":
    return {
        v["dex"]
        for v in token_entry.get("venues", {}).values()
        if quoteable(v.get("dex", ""))
    }


def multi_venue_tokens(
    registry: Dict[str, Any],
    quoteable: Callable[[str], bool],
) -> List[Tuple[str, Dict[str, Any]]]:
    """Tokens with ≥2 distinct *quoteable* venues. Returns (addr, entry) pairs."""
    out: List[Tuple[str, Dict[str, Any]]] = []
    for addr, entry in registry.get("tokens", {}).items():
        if len(_distinct_quoteable_dex_ids(entry, quoteable)) >= 2:
            out.append((addr, entry))
    return out


def promotable_events(
    registry: Dict[str, Any],
    quoteable: Callable[[str], bool],
) -> List[Dict[str, Any]]:
    """Replay-able sniper events for every quoteable venue of multi-venue tokens.

    Each returned event is tagged ``_registry_promoted=True`` so the bridge can
    mark the resulting route. Only quoteable venues are emitted (a pending /
    unsupported second venue does not unlock a real arb cycle).
    """
    events: List[Dict[str, Any]] = []
    for _addr, entry in multi_venue_tokens(registry, quoteable):
        for venue in entry.get("venues", {}).values():
            if not quoteable(venue.get("dex", "")):
                continue
            ev = {k: venue.get(k) for k in _EVENT_FIELDS}
            ev["_registry_promoted"] = True
            events.append(ev)
    return events
