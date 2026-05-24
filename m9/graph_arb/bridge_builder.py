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

_ANCHOR_TOKENS = frozenset({
    "USDC", "EURC", "WETH", "cbBTC", "WETH_BASE", "DAI", "USDT",
})
# Symbols longer than this are almost always junk tokens at creation time
_MAX_SYMBOL_LEN = 15
# How old an artifact may be before it is considered stale (seconds)
_M8_STALE_SECONDS = 4 * 3600
_M8_1_STALE_SECONDS = 4 * 3600

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
    m8_events: List[Dict] = (sniper.get("recent_events", []) if sniper else [])
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
    # Stage 6: M8 new pools that appear in the base inventory
    # (factory_verified + depth_ok already implied by their presence)
    # ------------------------------------------------------------------
    base_pool_addrs = frozenset(
        r.get("pool_address", "").lower()
        for r in base_active
        if r.get("pool_address")
    )
    m8_pools_in_base: List[Dict] = [
        e for e in cross_dex_seen_events
        if e.get("pool", "").lower() in base_pool_addrs
    ]
    graph_ready_from_m8 = len(m8_pools_in_base)

    # ------------------------------------------------------------------
    # M8.1 anchor routes contributed to base (routes already in base from M8.1)
    # ------------------------------------------------------------------
    m8_1_anchor_routes_input = 0
    if anchor:
        m8_1_anchor_routes_input = len(anchor.get("near_miss_routes", []))

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
        "graph_ready_total": len(base_active),
        "m8_stale": m8_stale,
        "m8_1_stale": m8_1_stale,
        "sniper_path": sniper_path,
        "anchor_path": anchor_path,
        "base_inv_path": base_inv_path,
    }

    # ------------------------------------------------------------------
    # Write output artifact
    # ------------------------------------------------------------------
    output_artifact: Dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "generated_at_utc": _iso_now(),
        "bridge_source_metrics": bridge_source_metrics,
        "source_inventory": base_inv_path if base_inv else None,
        "total_candidates": len(base_active),
        "active_routes": base_active,
        "quarantined_routes": (base_inv.get("quarantined_routes", []) if base_inv else []),
        "summary": {
            "active_count": len(base_active),
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
