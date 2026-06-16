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
import os
from collections import Counter as _Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
    "uniswap_v4": "uniswap_v4",         # quoted via raw_http_probe; safe-hook pools admitted, unknown hooks quarantined
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
    # Maverick V2: directional liquidity bins; quotes via PoolInformation.calculateSwap
    "maverick_v2": "maverick_v2",
    # Algebra (dynamic-fee concentrated liquidity): Camelot V3, QuickSwap V3, etc.
    # Quotes via quoteExactInputSingle(tokenIn,tokenOut,amountIn,limitSqrtPrice) — no fee
    # tier input (fee is dynamic). Wired in raw_http_probe / quote_probe as adapter_type
    # "algebra". Primarily an Arbitrum/Polygon path; kept here so cross-curve long-tail
    # tokens on Algebra DEXes enter the M9 graph instead of silent quarantine.
    "algebra": "algebra",
    "camelot_v3": "algebra",
    "quickswap_v3": "algebra",
}
_UNSUPPORTED_ADAPTER = "unsupported"

# Adapter types that are correctly identified but do NOT yet have a working M9 quote
# adapter.  Events from these dexes are quarantined with an explicit reason code rather
# than silently entering active_routes (which would cause QUOTE_DECODE errors at runtime).
# NOTE: balancer_stable, balancer_weighted, and maverick_v2 are now wired via their
# respective quote adapters. _PENDING_ADAPTER_TYPES is empty — all adapter types
# recognised above have working M9 quote adapters.
_PENDING_ADAPTER_TYPES: frozenset = frozenset()

# Per-adapter quarantine reason for pending adapters
_PENDING_ADAPTER_REASONS: Dict[str, str] = {}

_DEFAULT_SNIPER = "data/runs/_rolling/new_pool_sniper_latest.json"
_DEFAULT_ANCHOR = "data/runs/_rolling/m8_1_stable_anchor_latest.json"
_DEFAULT_BASE_INV = "data/tmp/m9_depth_enriched_inventory.json"
_BRIDGE_OUTPUT = "data/runs/_rolling/m9_bridge_inventory_latest.json"
_DEFAULT_CURVE_DISCOVERY = "data/runs/_rolling/m9_curve_discovery_latest.json"
_DEFAULT_CROSS_DEX_EXPANSION = "data/runs/_rolling/m8_cross_dex_expansion_latest.json"


def curve_temporarily_disabled() -> bool:
    """When set, exclude all curve_stable routes from bridge output and M9 graph."""
    return os.environ.get("ARBY_M9_DISABLE_CURVE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _without_curve_routes(routes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not curve_temporarily_disabled():
        return routes
    return [
        r
        for r in routes
        if r.get("dex_id") != "curve_stable"
        and r.get("adapter_type") != "curve_stable"
    ]


def _filter_curve_routes_productive_admission(
    routes: List[Dict[str, Any]],
    *,
    curve_pool_indices_path: Optional[str] = None,
    chain: str = "base",
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Keep only curve_stable routes whose pool passed rolling get_dy probe (QUOTE_OK_*)."""
    from m9.graph_arb.adapter_metadata import load_adapter_metadata

    if curve_temporarily_disabled():
        return routes, {
            "curve_productive_admission_before": 0,
            "curve_productive_admission_after": 0,
            "curve_productive_admission_filtered": 0,
        }

    meta = load_adapter_metadata(curve_pool_indices_path=curve_pool_indices_path)
    kept: List[Dict[str, Any]] = []
    curve_before = 0
    curve_filtered = 0
    for route in routes:
        is_curve = (
            route.get("dex_id") == "curve_stable"
            or route.get("adapter_type") == "curve_stable"
        )
        if not is_curve:
            kept.append(route)
            continue
        curve_before += 1
        pool = str(route.get("pool_address") or "").lower()
        if pool and meta.curve_pool_quotable(pool, chain=chain):
            kept.append(route)
        else:
            curve_filtered += 1
    return kept, {
        "curve_productive_admission_before": curve_before,
        "curve_productive_admission_after": curve_before - curve_filtered,
        "curve_productive_admission_filtered": curve_filtered,
    }

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


_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
# Base anchor token addresses → symbols (address-only sniper events).
_BASE_ANCHOR_ADDR_TO_SYMBOL: Dict[str, str] = {
    "0x4200000000000000000000000000000000000006": "WETH",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
    "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42": "EURC",
    "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf": "cbBTC",
    "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": "DAI",
    "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2": "USDT",
}


def _is_symbol_valid(sym: str) -> bool:
    """Return True if symbol looks like a real token name (not junk)."""
    if not sym or not isinstance(sym, str):
        return False
    if len(sym) > _MAX_SYMBOL_LEN:
        return False
    if sym.isdigit():
        return False
    return True


def _symbol_from_token_addr(addr: Optional[str]) -> str:
    """Resolve a display symbol from a token address when ERC20 symbol() is missing."""
    if not addr or not isinstance(addr, str):
        return ""
    normalized = addr.lower()
    if normalized == _ZERO_ADDRESS:
        return "WETH"
    anchor_sym = _BASE_ANCHOR_ADDR_TO_SYMBOL.get(normalized)
    if anchor_sym:
        return anchor_sym
    if normalized.startswith("0x") and len(normalized) >= 10:
        return normalized[2:8].upper()
    return ""


def _enrich_sniper_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Fill missing token symbols from addresses so token_verified can proceed."""
    enriched = dict(event)
    for side in ("0", "1"):
        sym_key = f"token{side}_symbol"
        addr_key = f"token{side}"
        if not _is_symbol_valid(enriched.get(sym_key, "")):
            resolved = _symbol_from_token_addr(enriched.get(addr_key))
            if resolved:
                enriched[sym_key] = resolved
    return enriched


def _build_m8_funnel_reject_histogram(
    m8_events: List[Dict],
    token_verified_events: List[Dict],
    anchor_connected_events: List[Dict],
    cross_dex_seen_events: List[Dict],
    multi_venue_events: List[Dict],
    supported_events: List[Dict],
    fresh_window_events: List[Dict],
    single_venue_events: List[Dict],
    unsupported_events: List[Dict],
    pending_events: List[Dict],
) -> Dict[str, int]:
    """Per-event reject reason for M8-origin pools that did not reach graph_ready."""
    verified_ids = {e.get("event_id") for e in token_verified_events}
    anchor_ids = {e.get("event_id") for e in anchor_connected_events}
    cross_ids = {e.get("event_id") for e in cross_dex_seen_events}
    multi_ids = {e.get("event_id") for e in multi_venue_events}
    ready_ids = {
        e.get("event_id")
        for e in supported_events + fresh_window_events
        if e.get("event_id")
    }
    hist: Dict[str, int] = {}
    for e in m8_events:
        eid = e.get("event_id")
        if eid in ready_ids:
            continue
        t0_sym = e.get("token0_symbol")
        t1_sym = e.get("token1_symbol")
        if eid not in verified_ids:
            if t0_sym is None or t1_sym is None:
                reason = "TOKEN_SYMBOL_MISSING"
            else:
                reason = "TOKEN_SYMBOL_INVALID"
        elif eid not in anchor_ids:
            reason = "NOT_ANCHOR_CONNECTED"
        elif eid not in cross_ids:
            reason = "CROSS_DEX_NOT_SEEN"
        elif eid in {x.get("event_id") for x in unsupported_events}:
            reason = "UNSUPPORTED_DEX_TYPE"
        elif eid in {x.get("event_id") for x in pending_events}:
            reason = "PENDING_ADAPTER"
        elif eid in {x.get("event_id") for x in single_venue_events}:
            reason = "STRUCTURAL_SINGLE_VENUE_TOPOLOGY"
        elif eid not in multi_ids:
            reason = "MULTI_VENUE_GATE_FAILED"
        else:
            reason = "OTHER_REJECT"
        hist[reason] = hist.get(reason, 0) + 1
    return hist


def _is_anchor_connected(token0_sym: str, token1_sym: str) -> bool:
    return token0_sym in _ANCHOR_TOKENS or token1_sym in _ANCHOR_TOKENS


# ---------------------------------------------------------------------------
# Static pre-configured route injection
# ---------------------------------------------------------------------------

def _load_curve_discovery_routes(
    chain: str = "base",
    discovery_path: str = _DEFAULT_CURVE_DISCOVERY,
    max_age_seconds: float = 4 * 3600,
) -> List[Dict[str, Any]]:
    """Load discovered Curve pools from m9_curve_discovery_latest.json.

    These routes are production-quality: they came from factory.pool_list()
    enumeration with on-chain coins() verification (scripts/m9_curve_discovery.py).
    factory_verified=True because they were found via factory contract enumeration.

    Returns empty list when:
    - artifact does not exist (not yet generated)
    - artifact is stale (older than max_age_seconds)
    - chain does not match
    - file is malformed
    """
    import json as _json
    from datetime import timezone as _tz
    from pathlib import Path as _Path

    p = _Path(discovery_path)
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as fh:
            data = _json.load(fh)
    except Exception:
        return []

    if data.get("chain") != chain:
        return []

    # Check freshness
    ts_str = data.get("generated_at_utc", "")
    if ts_str:
        try:
            from datetime import datetime as _dt
            ts = _dt.fromisoformat(ts_str.rstrip("Z")).replace(tzinfo=_tz.utc)
            age = (_dt.now(tz=_tz.utc) - ts).total_seconds()
            if age > max_age_seconds:
                return []
        except Exception:
            pass  # malformed timestamp — admit anyway

    factory_addr = str(data.get("factory_address", ""))
    routes: List[Dict[str, Any]] = []
    for pool in (data.get("discovered_pools") or []):
        pool_addr = str(pool.get("pool_address", "")).lower()
        coin_indices = pool.get("coin_indices") or {}
        if not pool_addr or len(coin_indices) < 2:
            continue
        syms = sorted(coin_indices.keys())
        sym0, sym1 = syms[0], syms[1]
        pair_id = f"{sym0}_{sym1}"
        routes.append({
            "route_id": f"curve_disc_{pool_addr}",
            "pair_id": pair_id,
            "dex_id": "curve_stable",
            "adapter_type": "curve_stable",
            "token0": sym0,
            "token1": sym1,
            "fee": 0,
            "tick_spacing": None,
            "factory_address": factory_addr,
            "pool_address": pool_addr,
            "factory_verified": True,    # enumerated from factory.pool_list()
            "metadata_seeded": False,
            "source": "curve_factory_discovery",
            "pool_kind": str(pool.get("pool_kind", "stable")),
        })
    return routes


def _load_cross_dex_expansion_routes(
    expansion_path: str = _DEFAULT_CROSS_DEX_EXPANSION,
    chain: str = "base",
    max_age_seconds: float = 48 * 3600,
    graph_handoff_only: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Load M8.2 cross-DEX expansion routes_admitted from rolling artifact."""
    from datetime import timezone as _tz

    p = Path(expansion_path)
    empty: Tuple[List[Dict[str, Any]], Dict[str, Any]] = ([], {})
    if not p.exists():
        return empty
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return empty
    if data.get("chain") and data.get("chain") != chain:
        return empty
    ts_str = data.get("generated_at_utc", "")
    if ts_str:
        try:
            from datetime import datetime as _dt

            ts = _dt.fromisoformat(ts_str.rstrip("Z")).replace(tzinfo=_tz.utc)
            age = (_dt.now(tz=_tz.utc) - ts).total_seconds()
            if age > max_age_seconds:
                return empty
        except Exception:
            pass
    from m8.discovery.pool_hints import route_bridge_eligible
    from m8.discovery.graph_handoff import (
        apply_bridge_handoff_metadata,
        refresh_graph_handoff_in_expansion_doc,
        select_graph_handoff_universe_routes,
        _route_pool_key,
    )

    refresh_graph_handoff_in_expansion_doc(data)
    summary = data.get("summary") or {}
    debug = list(summary.get("graph_topology_ready_debug") or [])
    handoff_funnel = dict(summary.get("handoff_funnel") or {})

    routes_raw = data.get("routes_admitted") or []
    universe_keys: Set[Tuple[str, str, str]] = set()
    if graph_handoff_only:
        _universe, _funnel = select_graph_handoff_universe_routes(routes_raw, debug)
        handoff_funnel = _funnel
        universe_route_ids = {
            str(r.get("route_id") or "") for r in _universe if r.get("route_id")
        }
    else:
        universe_route_ids = set()

    routes: List[Dict[str, Any]] = []
    _graph_handoff_reject_hist: Dict[str, int] = {}
    for raw in routes_raw:
        if not route_bridge_eligible(raw):
            _graph_handoff_reject_hist["HINT_ONLY_NOT_BRIDGE_ELIGIBLE"] = (
                _graph_handoff_reject_hist.get("HINT_ONLY_NOT_BRIDGE_ELIGIBLE", 0) + 1
            )
            continue
        if graph_handoff_only:
            if not universe_route_ids:
                _graph_handoff_reject_hist["NO_GRAPH_HANDOFF_UNIVERSE"] = (
                    _graph_handoff_reject_hist.get("NO_GRAPH_HANDOFF_UNIVERSE", 0) + 1
                )
                continue
            rid = str(raw.get("route_id") or "")
            if rid not in universe_route_ids:
                _graph_handoff_reject_hist["NOT_IN_GRAPH_HANDOFF_UNIVERSE"] = (
                    _graph_handoff_reject_hist.get("NOT_IN_GRAPH_HANDOFF_UNIVERSE", 0) + 1
                )
                continue
        from m9.graph_arb.node_canonical import normalize_expansion_route_tokens

        tagged = apply_bridge_handoff_metadata(normalize_expansion_route_tokens(dict(raw)))
        routes.append(tagged)
    _hint_only_dropped = len(routes_raw) - len(routes)
    summary = data.get("summary") or {}
    return routes, {
        "reject_reason_histogram": data.get("reject_reason_histogram") or {},
        "multi_venue_tokens": summary.get("multi_venue_tokens", 0),
        "subgraph_ready_tokens": summary.get("subgraph_ready_tokens", 0),
        "graph_topology_ready_tokens": summary.get("graph_topology_ready_tokens", 0),
        "cross_anchor_ready_tokens": summary.get("cross_anchor_ready_tokens", 0),
        "connector_graph_ready_tokens": summary.get("connector_graph_ready_tokens", 0),
        "graph_handoff_ready_tokens": summary.get("graph_handoff_ready_tokens", 0),
        "handoff_ready": summary.get("handoff_ready", False),
        "handoff_lane": summary.get("handoff_lane") or data.get("handoff_lane"),
        "graph_handoff_cycle_potential_routes": handoff_funnel.get(
            "graph_handoff_cycle_potential_routes",
            summary.get("graph_handoff_cycle_potential_routes", 0),
        ),
        "graph_handoff_universe_routes": handoff_funnel.get(
            "graph_handoff_universe_routes", len(routes) if graph_handoff_only else 0
        ),
        "handoff_funnel": handoff_funnel,
        "graph_handoff_bridge_reject_histogram": _graph_handoff_reject_hist,
        "connector_routes_count": summary.get("connector_routes_count", 0),
        "verified_second_pool_count": summary.get("verified_second_pool_count", 0),
        "routes_admitted_count": summary.get("routes_admitted_count", 0),
        "tokens_in": summary.get("tokens_in", 0),
        "dex_ids_checked": summary.get("dex_ids_checked") or [],
        "pools_found_by_dex": summary.get("pools_found_by_dex") or {},
        "quoteable_by_dex": summary.get("quoteable_by_dex") or {},
        "admitted_by_dex": summary.get("admitted_by_dex") or {},
        "routes_admitted_raw": summary.get(
            "routes_admitted_raw", summary.get("routes_admitted_count", len(routes))
        ),
        "expansion_hint_only_dropped": _hint_only_dropped,
    }


def _build_static_curve_routes(chain: str = "base") -> List[Dict[str, Any]]:
    """Return route entries for pre-configured Curve pools from adapter_metadata.yaml.

    SEED-ONLY: use only with include_config_seed=True (smoke / bootstrap mode).
    Production discovery should go through Curve factory events + on-chain coin() verify.
    Routes produced here are tagged source='adapter_metadata' and counted in
    bridge_source_metrics['metadata_seeded_count'] — NOT in factory_verified_count.
    """
    try:
        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        meta = load_adapter_metadata()
        curve_chain_pools = meta.curve_pools.get(chain, {})
    except Exception:
        return []

    routes: List[Dict[str, Any]] = []
    for pool_addr, curve_pool in curve_chain_pools.items():
        coin_indices = curve_pool.coin_indices  # {sym: index}
        syms = sorted(coin_indices.keys())      # alphabetical for pair_id
        if len(syms) < 2:
            continue
        sym0, sym1 = syms[0], syms[1]
        pair_id = f"{sym0}_{sym1}"
        routes.append({
            "route_id": f"curve_meta_{pool_addr.lower()}",
            "pair_id": pair_id,
            "dex_id": "curve_stable",
            "adapter_type": "curve_stable",
            "token0": sym0,
            "token1": sym1,
            "fee": 0,
            "tick_spacing": None,
            "factory_address": "",
            "pool_address": pool_addr,
            "factory_verified": False,   # no factory event evidence; manually curated
            "metadata_seeded": True,     # came from adapter_metadata.yaml config
            "source": "adapter_metadata",
            "pool_kind": curve_pool.pool_kind,
        })
    return routes


def _build_static_balancer_routes(chain: str = "base") -> List[Dict[str, Any]]:
    """Return route entries for pre-configured Balancer pools from adapter_metadata.yaml.

    SEED-ONLY: use only with include_config_seed=True (smoke / bootstrap mode).
    Routes produced here are tagged source='adapter_metadata' and counted in
    bridge_source_metrics['metadata_seeded_count'].
    """
    try:
        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        meta = load_adapter_metadata()
        chain_pools = meta.balancer_pools.get(chain, {})
    except Exception:
        return []

    # We need a symbol↔address reverse map to assign token0/token1 names.
    # Build it from known token addresses (same map as in token_price_fetcher).
    _ADDR_TO_SYM: Dict[str, str] = {
        "0x4200000000000000000000000000000000000006": "WETH",
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
        "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42": "EURC",
        "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf": "cbBTC",
        "0x940181a94a35a4569e4529a3cdfb74e38fd98631": "AERO",
        "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b": "VIRTUAL",
        "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": "DAI",
        "0x417ac0e078398c154edfadd9ef675d30be60af93": "crvUSD",
        "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": "USDbC",
        "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22": "cbETH",
        "0xc1cba3fcea344f92d9239c08c0568f6f2f0ee452": "wstETH",
        # Balancer-specific tokens
        "0x54330d28ca3357f294334bdc454a032e7f353416": "OLAS",
        "0x5a7a2bf9ffae199f088b25837dcd7e115cf8e1bb": "IMO",
        "0x4ea71a20e655794051d1ee8b6e4a3269b13ccacc": "AaveUSDC",
        "0xca5d8f8a8d49439357d3cf46ca2e720702f132b8": "GYD",
    }

    routes: List[Dict[str, Any]] = []
    for pool_id, pool in chain_pools.items():
        assets = list(pool.assets)
        if len(assets) < 2:
            continue
        sym0 = _ADDR_TO_SYM.get(assets[0].lower(), assets[0][:8])
        sym1 = _ADDR_TO_SYM.get(assets[1].lower(), assets[1][:8])
        pair_id = "_".join(sorted([sym0, sym1]))
        routes.append({
            "route_id": f"balancer_meta_{pool.pool_address.lower()}",
            "pair_id": pair_id,
            "dex_id": f"balancer_{pool.pool_kind}",
            "adapter_type": f"balancer_{pool.pool_kind}" if pool.pool_kind in ("stable", "weighted") else "balancer_stable",
            "token0": sym0,
            "token1": sym1,
            "token0_addr": assets[0].lower(),
            "token1_addr": assets[1].lower(),
            "fee": 0,
            "tick_spacing": None,
            "factory_address": "0xba12222222228d8ba445958a75a0704d566bf2c8",
            "pool_address": pool.pool_address.lower(),
            "pool_id": pool_id.lower(),
            "vault_address": "0xba12222222228d8ba445958a75a0704d566bf2c8",
            "factory_verified": False,
            "metadata_seeded": True,
            "source": "adapter_metadata",
            "pool_kind": pool.pool_kind,
            "liquidity_ok": True,
            "depth_probe_ok": True,
            "status": "active",
            "quoter_addr": "0xba12222222228d8ba445958a75a0704d566bf2c8",
            "effective_depth_usd": 50.0,
        })
    return routes


def _build_static_simple_routes(chain: str = "base") -> List[Dict[str, Any]]:
    """Load pre-configured V2/ve33/aerodrome_v2_stable routes from adapter_metadata.yaml.

    Reads the ``simple_routes.<chain>`` list from adapter_metadata.yaml.
    Each entry requires: pool_address, dex_id, adapter_type, token0, token1.

    SEED-ONLY: use only with include_config_seed=True (smoke / bootstrap mode).
    Routes are tagged source='adapter_metadata' and counted in metadata_seeded_count.
    """
    import yaml as _yaml
    from pathlib import Path as _Path

    p = _Path("config/adapter_metadata.yaml")
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as fh:
            raw = _yaml.safe_load(fh) or {}
    except Exception:
        return []

    chain_routes = (raw.get("simple_routes") or {}).get(chain, [])
    if not isinstance(chain_routes, list):
        return []

    routes: List[Dict[str, Any]] = []
    for r in chain_routes:
        if not isinstance(r, dict):
            continue
        pool_addr = str(r.get("pool_address", "")).lower()
        if not pool_addr or len(pool_addr) != 42:
            continue
        sym0 = str(r.get("token0", ""))
        sym1 = str(r.get("token1", ""))
        if not sym0 or not sym1:
            continue
        dex_id = str(r.get("dex_id", ""))
        adapter_type = str(r.get("adapter_type", "uniswap_v2"))
        factory = str(r.get("factory_address", ""))
        pair_id = "_".join(sorted([sym0, sym1]))
        routes.append({
            "route_id": f"meta_{adapter_type}_{pool_addr[2:10]}",
            "pair_id": pair_id,
            "dex_id": dex_id,
            "adapter_type": adapter_type,
            "token0": sym0,
            "token1": sym1,
            "fee": int(r.get("fee", 0)),
            "tick_spacing": None,
            "factory_address": factory,
            "pool_address": pool_addr,
            "factory_verified": False,
            "metadata_seeded": True,
            "source": "adapter_metadata",
            "effective_depth_usd": 50.0,
            "liquidity_ok": True,
            "depth_probe_ok": True,
            "status": "active",
        })
    return routes


_DEPTH_STASH_KEYS = (
    "effective_depth_usd",
    "depth_probe_ok",
    "depth_probe_error",
    "depth_probe_source",
    "depth_method",
    "price_impact_at_100usd",
    "depth_status",
    "depth_reject_reason",
)


def _depth_stash_from_routes(routes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    stash: Dict[str, Dict[str, Any]] = {}
    for route in routes:
        pool = str(route.get("pool_address") or "").lower()
        if not pool or route.get("effective_depth_usd") is None:
            continue
        stash[pool] = {k: route.get(k) for k in _DEPTH_STASH_KEYS if route.get(k) is not None}
    return stash


def _apply_depth_stash(routes: List[Dict[str, Any]], stash: Dict[str, Dict[str, Any]]) -> int:
    applied = 0
    for route in routes:
        pool = str(route.get("pool_address") or "").lower()
        if not pool or pool not in stash:
            continue
        if route.get("effective_depth_usd") is not None:
            continue
        route.update(stash[pool])
        applied += 1
    return applied


def build_bridge_inventory(
    sniper_path: str = _DEFAULT_SNIPER,
    anchor_path: str = _DEFAULT_ANCHOR,
    base_inv_path: str = _DEFAULT_BASE_INV,
    output_path: str = _BRIDGE_OUTPUT,
    include_config_seed: bool = False,
    curve_discovery_path: str = _DEFAULT_CURVE_DISCOVERY,
    expansion_path: Optional[str] = _DEFAULT_CROSS_DEX_EXPANSION,
    registry_path: Optional[str] = None,
    registry_ttl_seconds: Optional[float] = None,
    include_expansion_duplicates_for_shadow: bool = False,
    graph_handoff_only: bool = False,
    enforce_m8_provenance: bool = False,
    watchlist_path: Optional[str] = "data/tmp/m8_token_watchlist_latest.json",
) -> Dict[str, Any]:
    """Build the M9 bridge inventory from M8/M8.1 sources + base depth inventory.

    Args:
        include_config_seed: When True, inject pre-configured Curve pools from
            adapter_metadata.yaml into active_routes (smoke/bootstrap mode only).
            These routes are tagged source='adapter_metadata' and counted separately
            in metadata_seeded_count — NOT as factory_verified.
            Default False: production mode relies on dynamic discovery only.
        registry_path: When provided, enable the M8.2 pending-pair registry —
            a persistent cross-run accumulator that promotes long-tail tokens to
            active_routes once they are observed on >=2 distinct quoteable venues
            (even across separate sniper windows).  Default None disables it
            (keeps unit tests side-effect free).
        registry_ttl_seconds: TTL for venue observations in the registry.
        expansion_path: M8.2 cross-DEX expansion artifact; None disables merge.
        include_expansion_duplicates_for_shadow: When True, re-admit expansion routes
            whose pool_address already exists in base/M8 (tagged shadow_dedupe_duplicate).
            Diagnostic/shadow only — do not use for productive canonical bridge.

    Returns bridge_source_metrics dict.  Writes the output artifact to output_path.
    """
    now_ts = datetime.now(tz=timezone.utc).timestamp()

    _depth_stash: Dict[str, Dict[str, Any]] = {}
    _prior_out = _load_json(output_path)
    if _prior_out:
        _depth_stash.update(_depth_stash_from_routes(_prior_out.get("active_routes") or []))

    sniper = _load_json(sniper_path)
    anchor = _load_json(anchor_path)
    base_inv = _load_json(base_inv_path)

    from monitoring.sniper_artifacts import assess_sniper_artifact_for_m9

    _m8_sniper_m9_assessment = assess_sniper_artifact_for_m9(sniper)

    # ------------------------------------------------------------------
    # Staleness detection
    # ------------------------------------------------------------------
    m8_stale: bool
    m8_1_stale: bool

    _sniper_age_seconds: Optional[float] = None
    if sniper is None:
        m8_stale = True
    else:
        _sniper_age_seconds = _artifact_age_seconds(sniper, now_ts)
        m8_stale = (_sniper_age_seconds is None) or (_sniper_age_seconds > _M8_STALE_SECONDS)

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
    m8_events: List[Dict] = [_enrich_sniper_event(e) for e in _raw_events]
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

    # ------------------------------------------------------------------
    # Stage 3b: M8.2 pending-pair registry update (cross-run accumulator)
    # Record every anchor-connected event as a (dex_id, pool) venue observation
    # keyed by the exotic token's address.  Promotion (single→multi venue) is
    # applied later, after m8_new_routes is built.  Enabled only when
    # registry_path is provided (keeps unit tests side-effect free).
    # ------------------------------------------------------------------
    _registry: Optional[Dict[str, Any]] = None
    _registry_stats: Dict[str, int] = {}

    def _is_quoteable_dex(dex_id: str) -> bool:
        _adp = _DEX_ID_TO_ADAPTER_TYPE.get(dex_id, "uniswap_v3")
        return _adp != _UNSUPPORTED_ADAPTER and _adp not in _PENDING_ADAPTER_TYPES

    if registry_path is not None:
        from m8.discovery import pending_pair_registry as _ppr
        _ttl = (
            registry_ttl_seconds
            if registry_ttl_seconds is not None
            else _ppr.DEFAULT_TTL_SECONDS
        )
        _registry = _ppr.load_registry(registry_path)
        _registry_stats = _ppr.update_registry(
            _registry, anchor_connected_events, now_ts, ttl_seconds=_ttl
        )

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

    # ------------------------------------------------------------------
    # Stage 5a: Inject Curve factory discovery routes (PRODUCTION path)
    # Routes here came from factory.pool_list() enumeration via
    # scripts/m9_curve_discovery.py; no config-seed flag required.
    # Deduplicates by pool_address against existing base_active.
    # ------------------------------------------------------------------
    if curve_temporarily_disabled():
        _disc_routes = []
        _curve_discovery_artifact_loaded_count = 0
    else:
        _disc_routes = _load_curve_discovery_routes(
            chain="base", discovery_path=curve_discovery_path
        )
        _curve_discovery_artifact_loaded_count = len(_disc_routes)
    _base_active_addrs_disc = frozenset(
        r.get("pool_address", "").lower() for r in base_active if r.get("pool_address")
    )
    _curve_discovery_admitted: List[Dict] = []
    for _dr in _disc_routes:
        if _dr.get("pool_address", "").lower() not in _base_active_addrs_disc:
            base_active = list(base_active) + [_dr]
            _curve_discovery_admitted.append(_dr)
    _curve_discovery_count: int = len(_curve_discovery_admitted)

    # ------------------------------------------------------------------
    # Stage 5b: Config-seed injection (SMOKE / BOOTSTRAP MODE ONLY)
    # In production mode (default), Curve pools must enter via dynamic
    # factory discovery (scripts/m9_curve_discovery.py) + on-chain verify.
    # Set include_config_seed=True only for smoke runs or explicit seeding.
    # ------------------------------------------------------------------
    _metadata_seeded_routes: List[Dict] = []
    if include_config_seed and not curve_temporarily_disabled():
        _static_curve = _build_static_curve_routes(chain="base")
        _base_active_addrs = frozenset(
            r.get("pool_address", "").lower() for r in base_active if r.get("pool_address")
        )
        for _scr in _static_curve:
            if _scr.get("pool_address", "").lower() not in _base_active_addrs:
                base_active = list(base_active) + [_scr]
                _metadata_seeded_routes.append(_scr)
        # Balancer config-seed: inject pre-configured V2 Vault pools
        _static_balancer = _build_static_balancer_routes(chain="base")
        _base_active_addrs_b = frozenset(
            r.get("pool_address", "").lower() for r in base_active if r.get("pool_address")
        )
        for _sbr in _static_balancer:
            if _sbr.get("pool_address", "").lower() not in _base_active_addrs_b:
                base_active = list(base_active) + [_sbr]
                _metadata_seeded_routes.append(_sbr)
        # Simple routes config-seed: ve33, aerodrome_v2_stable, uniswap_v2 family
        _static_simple = _build_static_simple_routes(chain="base")
        _base_active_addrs_s = frozenset(
            r.get("pool_address", "").lower() for r in base_active if r.get("pool_address")
        )
        for _ssr in _static_simple:
            if _ssr.get("pool_address", "").lower() not in _base_active_addrs_s:
                base_active = list(base_active) + [_ssr]
                _metadata_seeded_routes.append(_ssr)
    _metadata_seeded_count: int = len(_metadata_seeded_routes)

    # factory_verified_count counts routes from base inventory (not metadata seeds)
    factory_verified_count = sum(
        1 for r in base_active
        if r.get("factory_verified") and r.get("source") != "adapter_metadata"
    )
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
            "origin_source": "m8_sniper",
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

    # ------------------------------------------------------------------
    # Stage 6b: M8.2 registry promotion (single→multi venue).
    # Tokens that have accumulated >=2 distinct quoteable venues across runs
    # (persisted in the registry) are promoted: a route is built for every
    # quoteable venue and injected into active_routes.  This unlocks arb cycles
    # for long-tail tokens whose second venue appeared only after the first had
    # expired from the sniper window — the structural single-venue barrier.
    # Deduplicated by pool address against base inventory and existing M8 routes.
    # ------------------------------------------------------------------
    _registry_promoted_routes: List[Dict] = []
    _registry_promoted_tokens: int = 0
    if _registry is not None:
        from m8.discovery import pending_pair_registry as _ppr
        _promo_events = _ppr.promotable_events(_registry, _is_quoteable_dex)
        _registry_promoted_tokens = len(
            _ppr.multi_venue_tokens(_registry, _is_quoteable_dex)
        )
        _existing_addrs = set(base_pool_addrs) | {
            r["pool_address"].lower() for r in m8_new_routes if r.get("pool_address")
        }
        for _pe in _promo_events:
            _pe_pool = (_pe.get("pool", "") or "").lower()
            if not _pe_pool or _pe_pool in _existing_addrs:
                continue
            if not _v4_hook_ok(_pe):
                continue
            _route = _build_m8_route(_pe, freshness_window=False)
            _route["promoted_from_registry"] = True
            _route["promotion_reason"] = _ppr.PROMOTION_REASON
            _registry_promoted_routes.append(_route)
            _existing_addrs.add(_pe_pool)
        m8_new_routes = m8_new_routes + _registry_promoted_routes

    # ------------------------------------------------------------------
    # Stage 6c: M8.2 cross-DEX expansion routes (multi-venue from factory resolve)
    # ------------------------------------------------------------------
    _expansion_routes: List[Dict] = []
    _expansion_meta: Dict[str, Any] = {}
    if expansion_path:
        _expansion_routes, _expansion_meta = _load_cross_dex_expansion_routes(
            expansion_path, chain="base", graph_handoff_only=graph_handoff_only
        )
        _expansion_existing = set(base_pool_addrs) | {
            r["pool_address"].lower()
            for r in m8_new_routes
            if r.get("pool_address")
        }
        _expansion_raw_input = len(_expansion_routes)
        _expansion_admitted: List[Dict] = []
        _expansion_deduped_pools: List[str] = []
        for _er in _expansion_routes:
            _ep = (_er.get("pool_address") or "").lower()
            if not _ep:
                continue
            if _ep in _expansion_existing:
                _expansion_deduped_pools.append(_ep)
                if include_expansion_duplicates_for_shadow:
                    _dup = dict(_er)
                    _dup["shadow_dedupe_duplicate"] = True
                    _dup["include_expansion_duplicates_for_shadow"] = True
                    _expansion_admitted.append(_dup)
                continue
            _expansion_admitted.append(_er)
            _expansion_existing.add(_ep)
        m8_new_routes = m8_new_routes + _expansion_admitted
        _expansion_routes = [
            r for r in _expansion_admitted if not r.get("shadow_dedupe_duplicate")
        ]
        _expansion_meta["expansion_routes_raw_input"] = _expansion_raw_input
        _expansion_meta["expansion_routes_after_dedupe"] = len(_expansion_routes)
        _expansion_meta["expansion_routes_shadow_duplicates_included"] = len(
            _expansion_admitted
        ) - len(_expansion_routes)
        _expansion_meta["expansion_deduped_existing_pool_count"] = len(
            _expansion_deduped_pools
        )
        _expansion_meta["expansion_deduped_pool_samples"] = _expansion_deduped_pools[:8]
        _raw_admitted = _expansion_meta.get("routes_admitted_raw")
        if _raw_admitted is None:
            _raw_admitted = _expansion_raw_input
        _expansion_meta["routes_admitted_raw"] = _raw_admitted
        _expansion_meta["routes_admitted_after_bridge_dedupe"] = len(_expansion_routes)

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
    # M8.1 anchor probe contribution.
    #
    # M8.1 (route_discovery_scope="quote_probe_only") is a single-leg quote
    # health probe over stable-anchor pairs.  It intentionally emits
    # active_routes=[] (see scripts/m8_1_stable_anchor_run.py): it confirms that
    # on-chain quotes SUCCEED for anchor candidates, it does NOT assemble arb
    # routes.  Its true contribution is the count of passing anchor quote probes
    # (metrics.stable_anchor_passes_total), NOT the capped sample of rejected
    # near_miss_routes.  Counting near_miss (rejects) here understated/misreported
    # M8.1's contribution as 0/50.  We report passes as the contribution and keep
    # the near-miss sample size separately for transparency.
    # ------------------------------------------------------------------
    m8_1_anchor_routes_input = 0
    m8_1_anchor_near_miss_count = 0
    if anchor:
        _anchor_metrics = anchor.get("metrics", {}) or {}
        m8_1_anchor_routes_input = int(
            _anchor_metrics.get("stable_anchor_passes_total", 0) or 0
        )
        m8_1_anchor_near_miss_count = len(
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
        "m8_1_anchor_near_miss_count": m8_1_anchor_near_miss_count,
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
        "m8_sniper_artifact_operational": _m8_sniper_m9_assessment.get(
            "operational", False
        ),
        "m8_sniper_artifact_blockers": _m8_sniper_m9_assessment.get("blockers") or [],
        "sniper_age_seconds": (
            round(_sniper_age_seconds, 1) if _sniper_age_seconds is not None else None
        ),
        "sniper_generated_at_utc": (
            sniper.get("generated_at_utc") if sniper else None
        ),
        "m8_stale_threshold_seconds": _M8_STALE_SECONDS,
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
        "m8_funnel_reject_histogram": _build_m8_funnel_reject_histogram(
            m8_events,
            token_verified_events,
            anchor_connected_events,
            cross_dex_seen_events,
            multi_venue_events,
            supported_events,
            _fresh_window_events,
            _single_venue_events,
            unsupported_events,
            pending_events,
        ),
        # Stage 4c fresh-window diagnostics
        "sniper_in_fresh_window": _sniper_in_fresh_window,
        "sniper_age_seconds": round(_sniper_age, 1) if _sniper_age is not None else None,
        "fresh_window_admitted_count": _fresh_window_admitted_count,
        # Config-seed diagnostics (SMOKE MODE only, not production)
        # metadata_seeded_count is separated from factory_verified_count intentionally:
        # seed routes come from manual config, not from factory event + on-chain verify.
        "metadata_seeded_count": _metadata_seeded_count,
        "include_config_seed": include_config_seed,
        # Curve factory discovery (production path, no seed flag required)
        "curve_discovery_artifact_loaded_count": _curve_discovery_artifact_loaded_count,
        "curve_discovery_admitted_count": _curve_discovery_count,
        "curve_discovery_count": _curve_discovery_count,
        "graph_ready_from_expansion": len(_expansion_routes),
        "m8_2_handoff_ready": _expansion_meta.get("handoff_ready"),
        "m8_2_handoff_lane": _expansion_meta.get("handoff_lane"),
        "graph_handoff_universe_routes": _expansion_meta.get(
            "graph_handoff_universe_routes"
        ),
        "graph_handoff_cycle_potential_routes": _expansion_meta.get(
            "graph_handoff_cycle_potential_routes"
        ),
        "expansion_handoff_funnel": _expansion_meta.get("handoff_funnel"),
        "graph_handoff_bridge_reject_histogram": _expansion_meta.get(
            "graph_handoff_bridge_reject_histogram"
        ),
        "expansion_routes_raw_input": _expansion_meta.get(
            "expansion_routes_raw_input", len(_expansion_routes)
        ),
        "expansion_routes_after_dedupe": _expansion_meta.get(
            "expansion_routes_after_dedupe", len(_expansion_routes)
        ),
        "expansion_routes_input": _expansion_meta.get(
            "expansion_routes_after_dedupe", len(_expansion_routes)
        ),
        "expansion_multi_venue_count": _expansion_meta.get("multi_venue_tokens", 0)
        or _expansion_meta.get("subgraph_ready_tokens", 0),
        "expansion_subgraph_ready_tokens": _expansion_meta.get(
            "subgraph_ready_tokens", 0
        ),
        "expansion_verified_second_pool_count": _expansion_meta.get(
            "verified_second_pool_count", 0
        ),
        "expansion_tokens_in": _expansion_meta.get("tokens_in", 0),
        "expansion_dex_ids_checked": _expansion_meta.get("dex_ids_checked", []),
        "expansion_pools_found_by_dex": _expansion_meta.get("pools_found_by_dex", {}),
        "expansion_quoteable_by_dex": _expansion_meta.get("quoteable_by_dex", {}),
        "expansion_admitted_by_dex": _expansion_meta.get("admitted_by_dex", {}),
        "expansion_reject_histogram": _expansion_meta.get("reject_reason_histogram", {}),
        "expansion_deduped_existing_pool_count": _expansion_meta.get(
            "expansion_deduped_existing_pool_count", 0
        ),
        "expansion_deduped_pool_samples": _expansion_meta.get(
            "expansion_deduped_pool_samples", []
        ),
        "expansion_routes_shadow_duplicates_included": _expansion_meta.get(
            "expansion_routes_shadow_duplicates_included", 0
        ),
        "routes_admitted_raw": _expansion_meta.get("routes_admitted_raw"),
        "routes_admitted_after_bridge_dedupe": _expansion_meta.get(
            "routes_admitted_after_bridge_dedupe"
        ),
        "include_expansion_duplicates_for_shadow": include_expansion_duplicates_for_shadow,
        "existence_blocker": "M8_2_FRESH_MULTI_VENUE_UNIVERSE_TOO_SMALL",
    }

    # Curve rolling indices artifact coverage (bridge inventory curve_stable routes)
    try:
        from m9.graph_arb.adapter_metadata import (
            check_curve_pools_configured,
            load_adapter_metadata,
        )

        _curve_meta = load_adapter_metadata()
        _curve_route_addrs = sorted(
            {
                str(r.get("pool_address", "")).lower()
                for r in base_active
                if r.get("adapter_type") == "curve_stable" and r.get("pool_address")
            }
        )
        _curve_missing = check_curve_pools_configured(_curve_meta, _curve_route_addrs)
        bridge_source_metrics["curve_stable_route_count"] = len(_curve_route_addrs)
        bridge_source_metrics["curve_indices_configured_count"] = (
            len(_curve_route_addrs) - len(_curve_missing)
        )
        bridge_source_metrics["curve_indices_missing_count"] = len(_curve_missing)
        if _curve_missing:
            bridge_source_metrics["curve_indices_missing_sample"] = _curve_missing[:5]
    except Exception:
        pass

    # ------------------------------------------------------------------
    # M8.2 pending-pair registry diagnostics + persistence
    # ------------------------------------------------------------------
    if _registry is not None and registry_path is not None:
        from m8.discovery import pending_pair_registry as _ppr
        bridge_source_metrics["registry_enabled"] = True
        bridge_source_metrics["registry_tokens_tracked"] = _registry_stats.get(
            "tokens_tracked", 0
        )
        bridge_source_metrics["registry_venues_tracked"] = _registry_stats.get(
            "venues_tracked", 0
        )
        bridge_source_metrics["registry_multi_venue_tokens"] = _registry_promoted_tokens
        bridge_source_metrics["registry_new_tokens"] = _registry_stats.get(
            "new_tokens", 0
        )
        bridge_source_metrics["registry_new_venues"] = _registry_stats.get(
            "new_venues", 0
        )
        bridge_source_metrics["registry_pruned_venues"] = _registry_stats.get(
            "pruned_venues", 0
        )
        bridge_source_metrics["registry_pruned_tokens"] = _registry_stats.get(
            "pruned_tokens", 0
        )
        bridge_source_metrics["registry_promoted_routes"] = len(
            _registry_promoted_routes
        )
        _ppr.save_registry(_registry, registry_path)
    else:
        bridge_source_metrics["registry_enabled"] = False
        bridge_source_metrics["registry_promoted_routes"] = 0

    # ------------------------------------------------------------------
    # Per-pool quality state (discovery → productive admission)
    # ------------------------------------------------------------------
    final_active = _without_curve_routes(base_active + m8_new_routes)
    if not os.environ.get("ARBY_M9_CURVE_ADMIT_ALL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        final_active, _curve_adm = _filter_curve_routes_productive_admission(
            final_active
        )
        bridge_source_metrics.update(_curve_adm)
    try:
        from m8.discovery.distinct_pricing_lane import (
            enrich_balancer_routes_from_index,
            evaluate_distinct_pricing_lane,
            quoteable_by_dex,
            stamp_maverick_quote_amounts_from_debug,
            stamp_productive_quote_status_from_artifacts,
        )

        bridge_source_metrics.update(enrich_balancer_routes_from_index(final_active))
        bridge_source_metrics.update(
            stamp_maverick_quote_amounts_from_debug(final_active)
        )
        bridge_source_metrics.update(
            stamp_productive_quote_status_from_artifacts(final_active)
        )
        from m9.graph_arb.leg_capacity import route_probe_direction_status

        for _pr in final_active:
            _pr["probe_direction_status"] = route_probe_direction_status(_pr)
        bridge_source_metrics["discovery_quoteable_by_dex"] = quoteable_by_dex(
            final_active, field="quote_smoke_status"
        )
        bridge_source_metrics["productive_quoteable_by_dex"] = quoteable_by_dex(
            final_active, field="productive_quote_status"
        )
        _distinct_lane = evaluate_distinct_pricing_lane(final_active)
        bridge_source_metrics.update(_distinct_lane)
        if not _distinct_lane.get("distinct_pricing_lane_ready"):
            bridge_source_metrics["distinct_pricing_blocker"] = (
                _distinct_lane.get("existence_blocker")
            )
    except Exception as _dpl_exc:
        bridge_source_metrics["distinct_pricing_lane_error"] = str(_dpl_exc)[:200]
    try:
        from m9.graph_arb.pool_quality import (
            annotate_routes_pool_quality,
            productive_admission_histogram,
        )

        bridge_source_metrics["pool_quality_histogram"] = annotate_routes_pool_quality(
            final_active
        )
        bridge_source_metrics["productive_admission_histogram"] = (
            productive_admission_histogram(final_active)
        )
    except Exception as _pq_exc:
        bridge_source_metrics["pool_quality_error"] = str(_pq_exc)[:200]

    # ------------------------------------------------------------------
    # M8 provenance gate (canonical bridge: M8 sniper / watchlist / specialized)
    # ------------------------------------------------------------------
    _exploration_routes: List[Dict[str, Any]] = []
    try:
        from m8.discovery.origin_source import (
            CANONICAL_ORIGINS,
            collect_m8_token_addrs,
            partition_canonical_routes,
        )

        _m8_token_addrs = collect_m8_token_addrs(
            sniper=sniper,
            registry=_registry,
            watchlist_path=watchlist_path,
        )
        bridge_source_metrics["m8_tokens_in"] = len(_m8_token_addrs)
        bridge_source_metrics["hint_tokens_matched"] = sum(
            1 for r in final_active if r.get("matched_m8_token")
        )
        bridge_source_metrics["specialized_index_tokens_matched"] = sum(
            1
            for r in final_active
            if r.get("origin_source") == "specialized_index_for_m8_token"
        )
        _enforce = enforce_m8_provenance or os.environ.get(
            "ARBY_BRIDGE_ENFORCE_M8_PROVENANCE", ""
        ).strip().lower() in ("1", "true", "yes")
        if _enforce:
            _canonical, _exploration_routes = partition_canonical_routes(
                final_active, _m8_token_addrs
            )
            if graph_handoff_only:
                _graph_promoted: List[Dict[str, Any]] = []
                _remain_exploration: List[Dict[str, Any]] = []
                for _r in _exploration_routes:
                    if str(_r.get("handoff_lane") or "") == "graph_topology" or (
                        _r.get("requires_quote_validation")
                        and str(_r.get("source") or "") == "m8_cross_dex_expansion"
                    ):
                        _r.setdefault("origin_source", "m8_watchlist_hint")
                        _graph_promoted.append(_r)
                    else:
                        _remain_exploration.append(_r)
                _exploration_routes = _remain_exploration
                _canonical = _canonical + _graph_promoted
                bridge_source_metrics["graph_handoff_provenance_promoted"] = len(
                    _graph_promoted
                )
                _curve_promoted: List[Dict[str, Any]] = []
                _remain_after_curve: List[Dict[str, Any]] = []
                for _r in _exploration_routes:
                    if str(_r.get("dex_id") or "") != "curve_stable":
                        _remain_after_curve.append(_r)
                        continue
                    _prod = str(
                        _r.get("productive_quote_status")
                        or _r.get("quote_smoke_status")
                        or ""
                    )
                    if _prod.startswith("QUOTE_OK"):
                        _r.setdefault("origin_source", "curve_factory_discovery")
                        _curve_promoted.append(_r)
                    else:
                        _remain_after_curve.append(_r)
                _exploration_routes = _remain_after_curve
                _canonical = _canonical + _curve_promoted
                bridge_source_metrics["curve_active_promoted_count"] = len(
                    _curve_promoted
                )
            bridge_source_metrics["routes_rejected_not_m8_derived"] = len(
                _exploration_routes
            )
            bridge_source_metrics["m8_provenance_enforced"] = True
            bridge_source_metrics["canonical_routes_count"] = len(_canonical)
            final_active = _canonical
        else:
            for _r in final_active:
                if not _r.get("origin_source"):
                    from m8.discovery.origin_source import stamp_route_origin_source

                    stamp_route_origin_source(_r, _m8_token_addrs)
            bridge_source_metrics["m8_provenance_enforced"] = False
            bridge_source_metrics["routes_rejected_not_m8_derived"] = sum(
                1
                for r in final_active
                if r.get("origin_source") not in CANONICAL_ORIGINS
            )
        _distinct = {"curve_stable", "balancer_vault", "maverick_v2"}
        bridge_source_metrics["active_dex_counts"] = dict(
            _Counter(str(r.get("dex_id") or "unknown") for r in final_active)
        )
        bridge_source_metrics["exploration_dex_counts"] = dict(
            _Counter(
                str(r.get("dex_id") or "unknown") for r in _exploration_routes
            )
        )
        bridge_source_metrics["active_distinct_pricing_routes"] = sum(
            1 for r in final_active if str(r.get("dex_id") or "") in _distinct
        )
        bridge_source_metrics["exploration_distinct_pricing_routes"] = sum(
            1
            for r in _exploration_routes
            if str(r.get("dex_id") or "") in _distinct
        )
        bridge_source_metrics["shadow_exploration_routes"] = len(_exploration_routes)
        bridge_source_metrics["shadow_exploration_route_samples"] = [
            {
                "pool_address": r.get("pool_address"),
                "dex_id": r.get("dex_id"),
                "origin_source": r.get("origin_source"),
            }
            for r in _exploration_routes[:12]
        ]
    except Exception as _prov_exc:
        bridge_source_metrics.setdefault("shadow_exploration_routes", 0)
        bridge_source_metrics["m8_provenance_error"] = str(_prov_exc)[:200]

    # ------------------------------------------------------------------
    # Hard quarantine: promote BAL#402 from pool-lane RCA, then drop paused pools
    # ------------------------------------------------------------------
    try:
        from m9.graph_arb.route_quarantine import (
            load_hard_quarantine_pool_addresses,
            merge_paused_from_balancer_pool_lane,
            merge_paused_pools_from_lane_rca,
        )

        _rca_merge = merge_paused_pools_from_lane_rca()
        if _rca_merge.get("added"):
            bridge_source_metrics["paused_pools_from_cycle_rca"] = _rca_merge["added"]
        _pool_lane_merge = merge_paused_from_balancer_pool_lane()
        if _pool_lane_merge.get("added"):
            bridge_source_metrics["paused_pools_from_pool_lane"] = _pool_lane_merge["added"]

        _hard_q = load_hard_quarantine_pool_addresses()
        if _hard_q:
            _before = len(final_active)
            final_active = [
                r
                for r in final_active
                if (r.get("pool_address") or "").lower() not in _hard_q
            ]
            bridge_source_metrics["hard_quarantine_pools_applied"] = len(_hard_q)
            bridge_source_metrics["routes_dropped_hard_quarantine"] = _before - len(
                final_active
            )
    except Exception as _hq_exc:
        bridge_source_metrics["hard_quarantine_error"] = str(_hq_exc)[:200]

    # ------------------------------------------------------------------
    # Quote-size truth: propagate token decimals on every active route
    # ------------------------------------------------------------------
    try:
        from m8_1.stable_anchor.config_loader import load_config as _load_m8_cfg
        from m9.graph_arb.token_decimals import load_decimals_cache
        from m9.graph_arb.token_metadata import enrich_route_token_metadata, validate_route_token_addresses

        _cfg_for_dec = None
        _cfg_candidate = base_inv_path or "config/exotic_base_anchor.yaml"
        if _cfg_candidate and Path(_cfg_candidate).exists():
            _cfg_for_dec = _load_m8_cfg(_cfg_candidate)
        _dec_cache = load_decimals_cache()
        _dec_w3 = None
        if os.environ.get("ARBY_BRIDGE_ENRICH_DECIMALS_ONCHAIN", "1").strip().lower() not in (
            "0",
            "false",
            "no",
        ):
            try:
                from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID
                from web3 import Web3

                _rpc, _, _ = resolve_rpc_http(
                    chain_id=_CHAIN_KEY_TO_ID.get("base", 8453),
                    network="base",
                )
                if _rpc:
                    _dec_w3 = Web3(Web3.HTTPProvider(_rpc, request_kwargs={"timeout": 8}))
            except Exception as _w3_exc:
                bridge_source_metrics["decimals_w3_error"] = str(_w3_exc)[:120]
        _malformed_dropped = 0
        _metadata_reject_hist: Dict[str, int] = {}
        _dec_src_hist: Dict[str, int] = {}
        _kept_active: List[Dict[str, Any]] = []
        for _dr in final_active:
            _rej = validate_route_token_addresses(_dr)
            if _rej:
                _malformed_dropped += 1
                _metadata_reject_hist[_rej] = _metadata_reject_hist.get(_rej, 0) + 1
                continue
            enrich_route_token_metadata(
                _dr,
                cfg=_cfg_for_dec,
                cache=_dec_cache,
                w3=_dec_w3,
                chain="base",
                topology_probe=False,
            )
            for _sk in ("token0_decimals_source", "token1_decimals_source"):
                _src = _dr.get(_sk)
                if _src:
                    _dec_src_hist[str(_src)] = _dec_src_hist.get(str(_src), 0) + 1
            _kept_active.append(_dr)
        if _malformed_dropped:
            final_active = _kept_active
            bridge_source_metrics["routes_dropped_malformed_token_address"] = _malformed_dropped
            bridge_source_metrics["metadata_reject_histogram"] = _metadata_reject_hist
        bridge_source_metrics["decimals_source_histogram"] = _dec_src_hist
        bridge_source_metrics["routes_with_decimals"] = sum(
            1
            for r in final_active
            if r.get("token0_decimals") is not None and r.get("token1_decimals") is not None
        )
        from m9.graph_arb.token_decimals import is_economics_grade_decimals_source

        bridge_source_metrics["routes_decimals_economics_grade"] = sum(
            1
            for r in final_active
            if r.get("token0_decimals") is not None
            and r.get("token1_decimals") is not None
            and is_economics_grade_decimals_source(r.get("token0_decimals_source"))
            and is_economics_grade_decimals_source(r.get("token1_decimals_source"))
        )
    except Exception as _dec_exc:
        bridge_source_metrics["decimals_enrich_error"] = str(_dec_exc)[:200]

    if _depth_stash:
        _depth_stash_applied = _apply_depth_stash(final_active, _depth_stash)
        bridge_source_metrics["depth_stash_applied"] = _depth_stash_applied
        try:
            from m9.graph_arb.depth_telemetry import depth_known_rate

            bridge_source_metrics["depth_known_rate"] = depth_known_rate(final_active)
        except Exception:
            pass

    if graph_handoff_only and _expansion_meta:
        from m8.discovery.graph_handoff import compute_expansion_to_bridge_funnel

        _expansion_handoff = int(
            _expansion_meta.get("graph_handoff_universe_routes")
            or (_expansion_meta.get("handoff_funnel") or {}).get(
                "graph_handoff_universe_routes"
            )
            or 0
        )
        _bridge_reject = dict(
            _expansion_meta.get("graph_handoff_bridge_reject_histogram") or {}
        )
        _dedupe_loss = max(
            0,
            int(_expansion_meta.get("expansion_routes_raw_input") or 0)
            - int(_expansion_meta.get("expansion_routes_after_dedupe") or 0),
        )
        if _dedupe_loss:
            _bridge_reject["BRIDGE_DEDUPE_EXISTING_POOL"] = (
                _bridge_reject.get("BRIDGE_DEDUPE_EXISTING_POOL", 0) + _dedupe_loss
            )
        bridge_source_metrics["expansion_to_bridge_funnel"] = (
            compute_expansion_to_bridge_funnel(
                expansion_funnel=_expansion_meta.get("handoff_funnel") or {},
                bridge_input_routes=int(
                    _expansion_meta.get("expansion_routes_raw_input") or 0
                ),
                bridge_active_routes=len(final_active),
                bridge_reject_histogram=_bridge_reject,
            )
        )
        bridge_source_metrics["expansion_handoff_routes"] = _expansion_handoff
        bridge_source_metrics["bridge_active_routes_from_handoff"] = len(final_active)

    _m8_direct_routes = [
        r for r in final_active if str(r.get("source") or "") == "m8_sniper"
    ]
    bridge_source_metrics["m8_direct_routes_in_bridge"] = len(_m8_direct_routes)
    bridge_source_metrics["m8_direct_pool_count"] = len(
        {
            (r.get("pool_address") or "").lower()
            for r in _m8_direct_routes
            if r.get("pool_address")
        }
    )
    bridge_source_metrics["routes_decimals_unknown"] = sum(
        1
        for r in final_active
        if r.get("token0_decimals") is None or r.get("token1_decimals") is None
    )

    try:
        from m9.graph_arb.depth_telemetry import pre_shadow_bridge_blockers

        _pre_shadow = pre_shadow_bridge_blockers(
            depth_known_rate_value=bridge_source_metrics.get("depth_known_rate"),
            routes_decimals_unknown=int(
                bridge_source_metrics.get("routes_decimals_unknown") or 0
            ),
            active_route_count=len(final_active),
        )
        if _pre_shadow:
            bridge_source_metrics["pre_shadow_blockers"] = _pre_shadow
    except Exception:
        pass

    # ------------------------------------------------------------------
    # Write output artifact
    # ------------------------------------------------------------------
    output_artifact: Dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "generated_at_utc": _iso_now(),
        "m8_2_handoff_ready": bridge_source_metrics.get("m8_2_handoff_ready"),
        "m8_2_handoff_lane": bridge_source_metrics.get("m8_2_handoff_lane"),
        "bridge_source_metrics": bridge_source_metrics,
        "source_inventory": base_inv_path if base_inv else None,
        "total_candidates": len(base_active) + len(m8_new_routes),
        "active_routes": final_active,
        "quarantined_routes": (
            (base_inv.get("quarantined_routes", []) if base_inv else [])
            + m8_quarantined_routes
            + m8_single_venue_routes
            + m8_quarantined_routes_v4_hooks
        ),
        "pending_routes": m8_pending_routes,
        "exploration_routes": _exploration_routes,
        "summary": {
            "active_count": len(final_active),
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

    if graph_handoff_only:
        try:
            from m9.graph_arb.topology_diagnostic import quick_cycle_count

            _after_builder = quick_cycle_count(
                str(out_path),
                cycle_lengths=(2, 3, 4),
                lane="discovery",
            )
            bridge_source_metrics["graph_handoff_cycle_potential_after_builder"] = (
                _after_builder
            )
            output_artifact["graph_handoff_cycle_potential_after_builder"] = (
                _after_builder
            )
            output_artifact["bridge_source_metrics"] = bridge_source_metrics
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(output_artifact, f, ensure_ascii=False, indent=2)
        except Exception as _topo_exc:
            bridge_source_metrics["graph_handoff_topology_error"] = str(_topo_exc)[:200]

    return bridge_source_metrics
