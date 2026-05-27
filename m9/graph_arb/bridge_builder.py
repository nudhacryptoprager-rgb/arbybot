"""M8 → M9 bridge inventory builder.

Merges and filters three source streams:
  1. M8 new-pool sniper events  (new_pool_sniper_latest.json)
  2. M8.1 stable-anchor data    (m8_1_stable_anchor_latest.json)
  3. Base depth-enriched inventory (m9_depth_enriched_inventory.json)

Bridge funnel (tracked in bridge_source_metrics):
  m8_new_pools_input
    → token_verified        (symbol present, not junk/too-long)
    → anchor_connected      (paired with USDC/EURC/WETH/cbBTC/DAI/USDT)
    → cross_dex_seen        (token appears in ≥2 sniper events)
    → factory_verified      (pool present in base factory-verified inventory)
    → depth_ok              (pool has depth_probe_ok in base inventory)
    → graph_ready_from_m8   (M8-sourced pools added to bridge output)

Output: data/runs/_rolling/m9_bridge_inventory_latest.json
Schema: m9_bridge_inventory.1
"""
from __future__ import annotations

import json
from collections import Counter as _Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dex.adapters.uniswap_v4 import is_safe_v4_hook as _is_safe_v4_hook

_ANCHOR_TOKENS = frozenset({
    "USDC", "EURC", "WETH", "cbBTC", "WETH_BASE", "DAI", "USDT",
})
# Symbols longer than this are almost always junk tokens at creation time
_MAX_SYMBOL_LEN = 15
# How old an artifact may be before it is considered stale (seconds).
# 30 min: aligns with recommended M8→bridge→M9 cadence for timely long-tail discovery.
_M8_STALE_SECONDS = 1800        # 30 min (was 4 * 3600)
_M8_1_STALE_SECONDS = 4 * 3600
# Fresh-window threshold: admit single-quoteable-venue pools when the sniper
# artifact is this young.  New pools take 60–90 min to appear on a second DEX,
# so we relax the multi-venue gate for the first hour to avoid missing MEV-naive
# fresh liquidity.  Admitted routes are tagged freshness_window=True.
_FRESH_WINDOW_SECONDS: int = 3600   # 1 hour

# Maps M8 sniper dex_id → M9 adapter_type.
# Adapter_type should always be the canonical type string, never "unsupported".
# Routes that have no quote adapter yet go into m8_pending_routes with explicit reason.
_DEX_ID_TO_ADAPTER_TYPE: Dict[str, str] = {
    "uniswap_v2": "uniswap_v2",
    "uniswap_v3": "uniswap_v3",
    "uniswap_v4": "uniswap_v4",         # P3: quote adapter pending — explicit quarantine
    "pancakeswap_v3": "uniswap_v3",
    "sushiswap_v3": "uniswap_v3",
    "sushiswap_v2": "uniswap_v2",
    "baseswap_v2": "uniswap_v2",
    "aerodrome": "ve33",
    "aerodrome_slipstream": "aerodrome_slipstream",
    "aerodrome_v2_stable": "aerodrome_v2_stable",
    # Curve: recognised DEX type → curve_stable adapter (get_dy)
    # Coin indices are loaded from config/adapter_metadata.yaml per pool
    "curve": "curve_stable",
    # Balancer: recognised DEX types; quote adapter wired via BalancerVaultAdapter
    # pool_id and vault_address loaded from config/adapter_metadata.yaml
    "balancer_stable": "balancer_stable",
    "balancer_weighted": "balancer_weighted",
}
_UNSUPPORTED_ADAPTER = "unsupported"

# Adapter types that are correctly identified but do NOT yet have a working M9 quote
# adapter.  Events from these dexes are quarantined with an explicit reason code rather
# than silently entering active_routes (which would cause QUOTE_DECODE errors at runtime).
# NOTE: balancer_stable and balancer_weighted are now wired via BalancerVaultAdapter.
_PENDING_ADAPTER_TYPES: frozenset = frozenset()

# Per-adapter quarantine reason for pending adapters
_PENDING_ADAPTER_REASONS: Dict[str, str] = {}

_DEFAULT_SNIPER = "data/runs/_rolling/new_pool_sniper_latest.json"
_DEFAULT_ANCHOR = "data/runs/_rolling/m8_1_stable_anchor_latest.json"
_DEFAULT_BASE_INV = "data/tmp/m9_depth_enriched_inventory.json"
_BRIDGE_OUTPUT = "data/runs/_rolling/m9_bridge_inventory_latest.json"

_SCHEMA_VERSION = "m9_bridge_inventory.1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: str) -> Optional[Dict]:
    p = Path(path)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _artifact_age_seconds(artifact: Dict, now_ts: float) -> Optional[float]:
    """Return age of artifact in seconds, or None if timestamp is missing/unparseable."""
    ts_str = artifact.get("generated_at_utc") or artifact.get("run_timestamp")
    if not ts_str:
        return None
    try:
        ts_clean = str(ts_str).rstrip("Z")
        dt = datetime.fromisoformat(ts_clean).replace(tzinfo=timezone.utc)
        return now_ts - dt.timestamp()
    except Exception:
        return None


def _is_symbol_valid(sym: str) -> bool:
    """Return True if symbol looks like a real token name (not junk)."""
    if not sym or not isinstance(sym, str):
        return False
    if len(sym) > _MAX_SYMBOL_LEN:
        return False
    if sym.isdigit():
        return False
    return True


def _is_anchor_connected(token0_sym: str, token1_sym: str) -> bool:
    return token0_sym in _ANCHOR_TOKENS or token1_sym in _ANCHOR_TOKENS


# ---------------------------------------------------------------------------
# Core bridge logic
# ---------------------------------------------------------------------------

def build_bridge_inventory(
    sniper_path: str = _DEFAULT_SNIPER,
    anchor_path: str = _DEFAULT_ANCHOR,
    base_inv_path: str = _DEFAULT_BASE_INV,
    output_path: str = _BRIDGE_OUTPUT,
) -> Dict[str, Any]:
    """Build the M9 bridge inventory from M8/M8.1 sources + base depth inventory.

    Returns bridge_source_metrics dict.  Writes the output artifact to output_path.
    """
    now_ts = datetime.now(tz=timezone.utc).timestamp()

    sniper = _load_json(sniper_path)
    anchor = _load_json(anchor_path)
    base_inv = _load_json(base_inv_path)

    # ------------------------------------------------------------------
    # Staleness detection
    # ------------------------------------------------------------------
    m8_stale: bool
    m8_1_stale: bool

    if sniper is None:
        m8_stale = True
    else:
        age = _artifact_age_seconds(sniper, now_ts)
        m8_stale = (age is None) or (age > _M8_STALE_SECONDS)

    if anchor is None:
        m8_1_stale = True
    else:
        age = _artifact_age_seconds(anchor, now_ts)
        m8_1_stale = (age is None) or (age > _M8_1_STALE_SECONDS)

    # ------------------------------------------------------------------
    # Stage 1: M8 sniper events
    # ------------------------------------------------------------------
    # Merge global recent_events with per-dex windows so minority DEXes
    # (V2, V3, ve33) are not pushed out by high-volume V4 events.
    _raw_events: List[Dict] = (sniper.get("recent_events", []) if sniper else [])
    _by_dex: Dict[str, List[Dict]] = (sniper.get("recent_events_by_dex", {}) if sniper else {})
    if _by_dex:
        _seen_ids: set = {e.get("event_id") for e in _raw_events if e.get("event_id")}
        for _dex_events in _by_dex.values():
            for _ev in _dex_events:
                if _ev.get("event_id") not in _seen_ids:
                    _raw_events.append(_ev)
                    _seen_ids.add(_ev.get("event_id"))
    m8_events: List[Dict] = _raw_events
    m8_new_pools_input = len(m8_events)

    # Stage 2: token_verified — symbol present and non-junk
    token_verified_events: List[Dict] = [
        e for e in m8_events
        if _is_symbol_valid(e.get("token0_symbol", ""))
        and _is_symbol_valid(e.get("token1_symbol", ""))
    ]

    # Stage 3: anchor_connected — one leg is a known stable/bluechip
    anchor_connected_events: List[Dict] = [
        e for e in token_verified_events
        if _is_anchor_connected(
            e.get("token0_symbol", ""),
            e.get("token1_symbol", ""),
        )
    ]

    # Stage 4: cross_dex_seen — token symbol seen in ≥2 events
    # (proxy for the same underlying token existing on multiple DEXes)
    all_syms: List[str] = []
    for e in anchor_connected_events:
        all_syms.append(e.get("token0_symbol", ""))
        all_syms.append(e.get("token1_symbol", ""))
    sym_freq = _Counter(all_syms)
    cross_dex_seen_events: List[Dict] = [
        e for e in anchor_connected_events
        if sym_freq[e.get("token0_symbol", "")] >= 2
        or sym_freq[e.get("token1_symbol", "")] >= 2
    ]
    cross_dex_seen_count = len(cross_dex_seen_events)

    # ------------------------------------------------------------------
    # Stage 4b: multi_venue_confirmed — token seen on ≥2 DISTINCT dex_ids.
    # Gate uses only QUOTEABLE DEX IDs (not pending, not unsupported adapters).
    # Separate diagnostic counters for seen (all dex_ids) vs quoteable (arb-ready).
    # Tokens failing this check are quarantined with STRUCTURAL_SINGLE_VENUE_TOPOLOGY.
    # ------------------------------------------------------------------
    from collections import defaultdict as _defaultdict
    _sym_dex_ids_all: Dict[str, set] = _defaultdict(set)   # all DEX IDs (diagnostic)
    _sym_dex_ids_qte: Dict[str, set] = _defaultdict(set)   # quoteable DEX IDs only (gate)
    for _e4b in anchor_connected_events:
        _dex4b = _e4b.get("dex", "unknown")
        _adp4b = _DEX_ID_TO_ADAPTER_TYPE.get(_dex4b, "uniswap_v3")
        _is_quoteable4b = (_adp4b != _UNSUPPORTED_ADAPTER and _adp4b not in _PENDING_ADAPTER_TYPES)
        for _s4b in [_e4b.get("token0_symbol", ""), _e4b.get("token1_symbol", "")]:
            if _s4b:
                _sym_dex_ids_all[_s4b].add(_dex4b)
                if _is_quoteable4b:
                    _sym_dex_ids_qte[_s4b].add(_dex4b)
    # Gate: must be present on ≥2 QUOTEABLE dex_ids (no pending/unsupported as second venue)
    _multi_venue_syms: "frozenset[str]" = frozenset(
        sym for sym, dexes in _sym_dex_ids_qte.items() if len(dexes) >= 2
    )
    # Diagnostic: seen on ≥2 any dex_ids (may include pending adapters)
    _multi_venue_seen_count: int = sum(
        1 for dexes in _sym_dex_ids_all.values() if len(dexes) >= 2
    )
    _m8_multi_venue_quoteable_count: int = len(_multi_venue_syms)
    # backward compat alias — "verified" now means quoteable, not just seen
    _m8_multi_venue_verified_count: int = _m8_multi_venue_quoteable_count
    multi_venue_events: List[Dict] = [
        e for e in cross_dex_seen_events
        if e.get("token0_symbol", "") in _multi_venue_syms
        or e.get("token1_symbol", "") in _multi_venue_syms
    ]
    _single_venue_events: List[Dict] = [
        e for e in cross_dex_seen_events
        if e not in multi_venue_events
    ]
    _structural_single_venue_blocked = len(_single_venue_events)
    _m8_multi_venue_verified_count = len(_multi_venue_syms)

    # ------------------------------------------------------------------
    # Stage 4c: fresh_window admission — relax multi-venue gate for pools
    # from a sniper artifact that is itself younger than _FRESH_WINDOW_SECONDS.
    #
    # Rationale: brand-new pools take 60–90 min to propagate to a second DEX.
    # During this window they always fail the multi-venue gate, which causes
    # the bridge to miss the highest-alpha opportunity (MEV-naive fresh pools).
    #
    # Policy: admit events from _single_venue_events when ALL of:
    #   1. Sniper artifact age < _FRESH_WINDOW_SECONDS (fresh run)
    #   2. Adapter type is supported (not pending, not unsupported)
    #   3. Token is anchor-connected (already guaranteed by ancestry)
    #
    # Fresh-window routes are tagged freshness_window=True in active_routes
    # and counted in bridge_source_metrics.fresh_window_admitted_count.
    # ------------------------------------------------------------------
    _sniper_age: Optional[float] = None
    if sniper is not None:
        _sniper_age = _artifact_age_seconds(sniper, now_ts)
    _sniper_in_fresh_window: bool = (
        _sniper_age is not None and _sniper_age < _FRESH_WINDOW_SECONDS
    )
    _fresh_window_events: List[Dict] = []
    if _sniper_in_fresh_window:
        for _fw_e in _single_venue_events:
            _fw_dex = _fw_e.get("dex", "")
            _fw_adp = _DEX_ID_TO_ADAPTER_TYPE.get(_fw_dex, "uniswap_v3")
            if _fw_adp != _UNSUPPORTED_ADAPTER and _fw_adp not in _PENDING_ADAPTER_TYPES:
                _fresh_window_events.append(_fw_e)
    _fresh_window_admitted_count: int = len(_fresh_window_events)

    # ------------------------------------------------------------------
    # Stage 5: Base inventory metrics (already factory_verified + depth_ok)
    # ------------------------------------------------------------------
    base_active: List[Dict] = base_inv.get("active_routes", []) if base_inv else []
    factory_verified_count = sum(1 for r in base_active if r.get("factory_verified"))
    depth_ok_count = sum(1 for r in base_active if r.get("depth_probe_ok"))

    anchor_in_base = [
        r for r in base_active
        if r.get("token0") in _ANCHOR_TOKENS or r.get("token1") in _ANCHOR_TOKENS
    ]
    anchor_connected_from_base = len(anchor_in_base)

    # ------------------------------------------------------------------
    # Stage 6: M8 pools that are anchor-connected + cross-dex-seen
    # These pools are "graph-ready": they have an anchor token and their
    # pair token appears in ≥2 sniper events (cross-dex signal).
    # Pools already in base inventory are depth-verified; new M8 pools
    # (not yet in base) are added to active_routes for M9 runtime quoting.
    # ------------------------------------------------------------------
    base_pool_addrs = frozenset(
        r.get("pool_address", "").lower()
        for r in base_active
        if r.get("pool_address")
    )
    # Partition multi_venue_events by adapter support.
    # (Stage 4b filtered to tokens with >=2 distinct dex_ids; single-venue events
    #  are quarantined with STRUCTURAL_SINGLE_VENUE_TOPOLOGY reason.)
    supported_events: List[Dict] = []
    pending_events: List[Dict] = []   # recognised adapter, no M9 quote adapter yet
    unsupported_events: List[Dict] = []
    for e in multi_venue_events:
        dex_id = e.get("dex", "")
        adapter_type = _DEX_ID_TO_ADAPTER_TYPE.get(dex_id, "uniswap_v3")
        if adapter_type == _UNSUPPORTED_ADAPTER:
            unsupported_events.append(e)
        elif adapter_type in _PENDING_ADAPTER_TYPES:
            pending_events.append(e)
        else:
            supported_events.append(e)

    # New M8 pools not yet in base inventory — supported dexes only.
    # adapter_type is propagated so builder.py does not default to uniswap_v3.
    # V4 pools: admitted when hook is safe (zero-address OR in _KNOWN_SAFE_HOOKS).
    # Unknown V4 hooks are quarantined (see uniswap_v4.py whitelist policy).

    def _v4_hook_ok(e: Dict) -> bool:
        """Return True when the event's V4 hooks are safe (or the pool is not V4)."""
        if _DEX_ID_TO_ADAPTER_TYPE.get(e.get("dex", ""), "") != "uniswap_v4":
            return True
        return _is_safe_v4_hook(e.get("hooks"))

    def _build_m8_route(e: Dict, freshness_window: bool = False) -> Dict:
        return {
            "route_id": f"m8_{e.get('event_id', '').replace(':', '_')}",
            "pair_id": "_".join(sorted([e.get("token0_symbol", ""), e.get("token1_symbol", "")])),
            "dex_id": e.get("dex", ""),
            "adapter_type": _DEX_ID_TO_ADAPTER_TYPE.get(e.get("dex", ""), "uniswap_v3"),
            "token0": e.get("token0_symbol", ""),
            "token1": e.get("token1_symbol", ""),
            "token0_addr": e.get("token0", ""),
            "token1_addr": e.get("token1", ""),
            "factory_address": e.get("factory", ""),
            "pool_address": e.get("pool", ""),
            "factory_verified": True,  # pool emitted by known factory
            "source": "m8_sniper",
            "block_number": e.get("block_number"),
            "fee": e.get("fee"),
            "tick_spacing": e.get("tick_spacing"),
            "hooks": e.get("hooks"),
            "depth_probe_ok": None,   # not yet depth-probed
            "effective_depth_usd": None,
            "freshness_window": freshness_window,
        }

    m8_new_routes: List[Dict] = [
        _build_m8_route(e, freshness_window=False)
        for e in supported_events
        if e.get("pool", "").lower() not in base_pool_addrs
        and _v4_hook_ok(e)
    ]

    # V4 pools with unknown hooks → quarantine with UNKNOWN_V4_HOOK reason
    _v4_unknown_hook_events = [
        e for e in supported_events
        if _DEX_ID_TO_ADAPTER_TYPE.get(e.get("dex", ""), "") == "uniswap_v4"
        and not _is_safe_v4_hook(e.get("hooks"))
    ]
    m8_quarantined_routes_v4_hooks: List[Dict] = [
        {
            "route_id": f"m8_{_hke.get('event_id', '').replace(':', '_')}",
            "pair_id": "_".join(sorted([_hke.get("token0_symbol", ""), _hke.get("token1_symbol", "")])),
            "dex_id": _hke.get("dex", ""),
            "adapter_type": "uniswap_v4",
            "token0": _hke.get("token0_symbol", ""),
            "token1": _hke.get("token1_symbol", ""),
            "pool_address": _hke.get("pool", ""),
            "hooks": _hke.get("hooks"),
            "source": "m8_sniper",
            "quarantine_reason": "UNKNOWN_V4_HOOK",
            "quarantine_note": (
                f"V4 pool hooks={_hke.get('hooks')!r} is not in the safe-hooks whitelist. "
                "Add to dex/adapters/uniswap_v4.py after on-chain audit."
            ),
        }
        for _hke in _v4_unknown_hook_events
    ]

    # Fresh-window routes: single-venue but fresh sniper → admitted with flag.
    # Pool addresses already in base or already in m8_new_routes are skipped.
    _m8_new_pool_addrs = frozenset(r["pool_address"].lower() for r in m8_new_routes)
    m8_fresh_window_routes: List[Dict] = [
        _build_m8_route(e, freshness_window=True)
        for e in _fresh_window_events
        if e.get("pool", "").lower() not in base_pool_addrs
        and e.get("pool", "").lower() not in _m8_new_pool_addrs
        and _v4_hook_ok(e)
    ]
    # Extend m8_new_routes with fresh-window admissions
    m8_new_routes = m8_new_routes + m8_fresh_window_routes

    # Unsupported M8 routes (truly unknown adapters) are quarantined.
    m8_quarantined_routes: List[Dict] = [
        {
            "route_id": f"m8_{e.get('event_id', '').replace(':', '_')}",
            "pair_id": "_".join(sorted([e.get("token0_symbol", ""), e.get("token1_symbol", "")])),
            "dex_id": e.get("dex", ""),
            "adapter_type": _UNSUPPORTED_ADAPTER,
            "token0": e.get("token0_symbol", ""),
            "token1": e.get("token1_symbol", ""),
            "pool_address": e.get("pool", ""),
            "source": "m8_sniper",
            "quarantine_reason": "UNSUPPORTED_DEX_TYPE",
            "quarantine_note": f"No M9 adapter for dex_id={e.get('dex', '')!r}; add adapter before enabling.",
        }
        for e in unsupported_events
    ]

    # Pending M8 routes: known adapter_type but no M9 quote adapter yet.
    # Tracked explicitly so CI can count them and plan P3 work.
    m8_pending_routes: List[Dict] = [
        {
            "route_id": f"m8_{e.get('event_id', '').replace(':', '_')}",
            "pair_id": "_".join(sorted([e.get("token0_symbol", ""), e.get("token1_symbol", "")])),
            "dex_id": e.get("dex", ""),
            "adapter_type": _DEX_ID_TO_ADAPTER_TYPE.get(e.get("dex", ""), "uniswap_v3"),
            "token0": e.get("token0_symbol", ""),
            "token1": e.get("token1_symbol", ""),
            "pool_address": e.get("pool", ""),
            "source": "m8_sniper",
            "quarantine_reason": _PENDING_ADAPTER_REASONS.get(
                _DEX_ID_TO_ADAPTER_TYPE.get(e.get("dex", ""), ""), "NO_QUOTE_ADAPTER"
            ),
            "quarantine_note": (
                f"M9 quote adapter for adapter_type={_DEX_ID_TO_ADAPTER_TYPE.get(e.get('dex',''), '')!r} "
                f"is pending; tracked for P3 delivery."
            ),
        }
        for e in pending_events
    ]

    # graph_ready_from_m8 = supported anchor-connected multi-venue-confirmed M8 pools
    # + fresh-window admissions (single-venue but fresh sniper artifact)
    graph_ready_from_m8 = len(supported_events) + len(m8_fresh_window_routes)

    # Single-venue blocked routes: cross_dex_seen but only 1 distinct DEX.
    # These are quarantined because they cannot form an arb cycle (no second venue to
    # capture price divergence). Reason: STRUCTURAL_SINGLE_VENUE_TOPOLOGY.
    m8_single_venue_routes: List[Dict] = [
        {
            "route_id": f"m8_{e.get('event_id', '').replace(':', '_')}",
            "pair_id": "_".join(sorted([e.get("token0_symbol", ""), e.get("token1_symbol", "")])),
            "dex_id": e.get("dex", ""),
            "adapter_type": _DEX_ID_TO_ADAPTER_TYPE.get(e.get("dex", ""), "uniswap_v3"),
            "token0": e.get("token0_symbol", ""),
            "token1": e.get("token1_symbol", ""),
            "pool_address": e.get("pool", ""),
            "source": "m8_sniper",
            "quarantine_reason": "STRUCTURAL_SINGLE_VENUE_TOPOLOGY",
            "quarantine_note": (
                f"Token only observed on single DEX {e.get('dex','')!r}; "
                "needs >=2 distinct venues for arb cycle formation."
            ),
        }
        for e in _single_venue_events
    ]

    _unsupported_dex_count = len(unsupported_events)
    _pending_adapter_count = len(pending_events)
    if _unsupported_dex_count:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "bridge_builder: %d M8 event(s) have UNSUPPORTED adapter_type "
            "(dexes: %s). Add M9 adapter to unlock.",
            _unsupported_dex_count,
            list({e.get('dex', '?') for e in unsupported_events}),
        )
    if _pending_adapter_count:
        import logging as _logging
        _logging.getLogger(__name__).info(
            "bridge_builder: %d M8 event(s) quarantined as pending adapter "
            "(dexes: %s). Unlock by delivering M9 quote adapter.",
            _pending_adapter_count,
            list({e.get('dex', '?') for e in pending_events}),
        )

    # DEX coverage matrix: per-dex breakdown of event counts and adapter support
    from collections import Counter as _C
    _dex_counts = _C(e.get("dex", "unknown") for e in cross_dex_seen_events)
    # Compute graph_ready_count per dex_id from supported_events
    _dex_graph_ready = _C(e.get("dex", "unknown") for e in supported_events)
    # Compute pending_count per dex_id from pending_events
    _dex_pending = _C(e.get("dex", "unknown") for e in pending_events)
    dex_coverage_matrix: Dict[str, Any] = {
        dex_id: {
            "event_count": count,
            "adapter_type": _DEX_ID_TO_ADAPTER_TYPE.get(dex_id, "unknown"),
            "adapter_supported": (
                _DEX_ID_TO_ADAPTER_TYPE.get(dex_id, "unknown") != _UNSUPPORTED_ADAPTER
                and _DEX_ID_TO_ADAPTER_TYPE.get(dex_id, "unknown") not in _PENDING_ADAPTER_TYPES
            ),
            "adapter_pending": _DEX_ID_TO_ADAPTER_TYPE.get(dex_id, "unknown") in _PENDING_ADAPTER_TYPES,
            "graph_ready_count": _dex_graph_ready.get(dex_id, 0),
            "pending_count": _dex_pending.get(dex_id, 0),
            "quarantine_reason": _PENDING_ADAPTER_REASONS.get(
                _DEX_ID_TO_ADAPTER_TYPE.get(dex_id, ""), None
            ),
        }
        for dex_id, count in sorted(_dex_counts.items())
    }

    # ------------------------------------------------------------------
    # M8.1 anchor routes contributed to base (routes already in base from M8.1)
    # ------------------------------------------------------------------
    m8_1_anchor_routes_input = 0
    if anchor:
        # Check both near_miss_routes (legacy) and active_routes (current schema)
        m8_1_anchor_routes_input = len(
            anchor.get("near_miss_routes", []) or anchor.get("active_routes", [])
        )

    # ------------------------------------------------------------------
    # M8 context: existing base pools for non-anchor tokens seen in M8 events.
    # If M8 sniped a pool for a token that is already in the base universe
    # (multi-pool token, non-anchor), the existing base routes for that token
    # become "M8-context" routes — M8 confirmed the token is currently active.
    # This enables cycles_with_m8_pool > 0 when M8 tracks known base tokens
    # even when the new M8 pool itself cannot form a cycle (exotic pair token).
    # ------------------------------------------------------------------
    _base_tokens: "set[str]" = {
        tok
        for r in base_active
        for tok in [r.get("token0", ""), r.get("token1", "")]
        if tok
    }
    _m8_context_tokens: "set[str]" = set()
    for _e in token_verified_events:  # token_verified: symbols OK, pre-anchor filter
        _pool_addr = (_e.get("pool", "") or "").lower()
        if _pool_addr in base_pool_addrs:
            continue  # pool already in base, skip
        for _tok in [_e.get("token0_symbol", ""), _e.get("token1_symbol", "")]:
            if _tok and _tok not in _ANCHOR_TOKENS and _tok in _base_tokens:
                _m8_context_tokens.add(_tok)
    _m8_context_pool_addrs: "list[str]" = list({
        r.get("pool_address", "").lower()
        for r in base_active
        if (r.get("token0") in _m8_context_tokens or r.get("token1") in _m8_context_tokens)
        and r.get("pool_address")
    })

    # Per-token pool breakdown: how many base routes exist for each M8-context token.
    # Helps diagnose why positive_cycles_with_m8_pool=0: a token with many pools
    # (liquidity is present) but still no positive cycle indicates market/economics issue.
    _m8_context_token_pool_breakdown: Dict[str, int] = {
        tok: sum(
            1 for r in base_active
            if (r.get("token0") == tok or r.get("token1") == tok) and r.get("pool_address")
        )
        for tok in sorted(_m8_context_tokens)
    }

    # ------------------------------------------------------------------
    # Assemble bridge_source_metrics
    # ------------------------------------------------------------------
    bridge_source_metrics: Dict[str, Any] = {
        "m8_new_pools_input": m8_new_pools_input,
        "m8_1_anchor_routes_input": m8_1_anchor_routes_input,
        "token_verified_count": len(token_verified_events),
        "anchor_connected_count": len(anchor_connected_events),
        "cross_dex_seen_count": cross_dex_seen_count,
        "factory_verified_count": factory_verified_count,
        "depth_ok_count": depth_ok_count,
        "anchor_connected_from_base": anchor_connected_from_base,
        "graph_ready_from_m8": graph_ready_from_m8,
        "graph_ready_total": len(base_active) + len(m8_new_routes),
        "graph_ready_from_m8_new": len(m8_new_routes),
        "unsupported_dex_count": _unsupported_dex_count,
        "pending_adapter_count": _pending_adapter_count,
        "dex_coverage_matrix": dex_coverage_matrix,
        "m8_stale": m8_stale,
        "m8_1_stale": m8_1_stale,
        "sniper_path": sniper_path,
        "anchor_path": anchor_path,
        "base_inv_path": base_inv_path,
        "m8_context_token_count": len(_m8_context_tokens),
        "m8_context_tokens": sorted(_m8_context_tokens),
        "m8_context_pool_count": len(_m8_context_pool_addrs),
        "m8_context_pool_addresses": _m8_context_pool_addrs,
        "m8_context_token_pool_breakdown": _m8_context_token_pool_breakdown,
        # Stage 4b multi-venue diagnostics
        "m8_multi_venue_seen_count": _multi_venue_seen_count,         # diagnostic: >=2 any DEX IDs
        "m8_multi_venue_quoteable_count": _m8_multi_venue_quoteable_count,  # gate: >=2 quoteable DEX IDs
        "m8_multi_venue_verified_count": _m8_multi_venue_verified_count,    # backward compat alias
        "structural_single_venue_blocked_count": _structural_single_venue_blocked,
        # Stage 4c fresh-window diagnostics
        "sniper_in_fresh_window": _sniper_in_fresh_window,
        "sniper_age_seconds": round(_sniper_age, 1) if _sniper_age is not None else None,
        "fresh_window_admitted_count": _fresh_window_admitted_count,
    }

    # ------------------------------------------------------------------
    # Write output artifact
    # ------------------------------------------------------------------
    output_artifact: Dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "generated_at_utc": _iso_now(),
        "bridge_source_metrics": bridge_source_metrics,
        "source_inventory": base_inv_path if base_inv else None,
        "total_candidates": len(base_active) + len(m8_new_routes),
        "active_routes": base_active + m8_new_routes,
        "quarantined_routes": (
            (base_inv.get("quarantined_routes", []) if base_inv else [])
            + m8_quarantined_routes
            + m8_single_venue_routes
            + m8_quarantined_routes_v4_hooks
        ),
        "pending_routes": m8_pending_routes,
        "summary": {
            "active_count": len(base_active) + len(m8_new_routes),
            "quarantined_count": (
                len(base_inv.get("quarantined_routes", [])) if base_inv else 0
            ),
            "bridge_funnel": bridge_source_metrics,
        },
    }

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_artifact, f, ensure_ascii=False, indent=2)

    return bridge_source_metrics
