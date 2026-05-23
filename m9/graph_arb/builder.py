"""Build directed token-exchange graph from inventory."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from m8_1.stable_anchor.config_loader import load_config, M8_1Config
from m8_1.stable_anchor.pairs import TokenInfo
from m9.graph_arb.models import GraphEdge

logger = logging.getLogger(__name__)

_DEFAULT_INVENTORY = "data/tmp/m8_1_exotic_inventory_latest.json"
# Merged shadow inventory (M8 + M8.1 + gap edges) takes priority when present
_SHADOW_INVENTORY = "data/tmp/m9_shadow_inventory_with_gap_edges.json"
_DEFAULT_CONFIG = "config/exotic_base_anchor.yaml"


def _fee_bps_from_edge(adapter_type: str, fee: int, tick_spacing: Optional[int]) -> float:
    """Compute LP fee in bps for scoring purposes.

    For V3-family adapters: fee_bps = fee / 100 (fee is in hundredths of a bip).
    """
    if adapter_type in ("aerodrome_slipstream",):
        # tick_spacing-based, fee field is nominal
        return fee / 100.0 if fee else 30.0
    elif adapter_type in ("aerodrome_v2_stable",):
        return 1.0  # 0.01% stable swap default
    elif adapter_type in ("curve_stable",):
        return 1.0  # ~0.01% curve default
    elif adapter_type in ("uniswap_v2",):
        return 30.0  # 0.30% uniswap v2
    else:
        return fee / 100.0 if fee else 30.0


def _parse_pair_symbols(pair_id: str) -> "tuple[str, str]":
    """Split canonical pair_id (alphabetical) into (sym0, sym1)."""
    parts = pair_id.split("_")
    if len(parts) != 2:
        raise ValueError(f"Cannot parse pair_id: {pair_id!r}")
    return parts[0], parts[1]


def build_graph_from_inventory(
    inventory_path: str = _DEFAULT_INVENTORY,
    config_path: str = _DEFAULT_CONFIG,
    exclude_factory_classes: Optional["frozenset[str]"] = None,
    min_qsr_edge: float = 0.0,
    exclude_route_ids: Optional["frozenset[str]"] = None,
    exclude_edge_keys: Optional["frozenset[str]"] = None,
    require_factory_verified: bool = False,
) -> "Dict[str, Dict[str, List[GraphEdge]]]":
    """Build a directed adjacency dict from inventory active_routes.

    Args:
        require_factory_verified: When True, skip any route whose
            ``factory_verified`` field is not exactly ``True``.  Routes
            lacking the field are treated as unverified and filtered out.
            Use this after running pool_verifier to ensure only on-chain
            confirmed pools enter the graph.

    Returns:
        adjacency[token_in_sym][token_out_sym] = List[GraphEdge]
    """
    inv_path = Path(inventory_path)
    if not inv_path.exists():
        logger.warning(
            "Graph inventory not found, returning empty graph",
            extra={"context": {"path": str(inv_path), "event": "graph_build_no_inventory"}},
        )
        return {}

    try:
        cfg: M8_1Config = load_config(config_path)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"CONFIG_MISSING: M9 graph builder requires config at {config_path!r}. "
            f"Create the file or pass --config explicitly. Original error: {exc}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"CONFIG_INVALID: Failed to load M9 config from {config_path!r}: {exc}"
        ) from exc

    try:
        with inv_path.open("r", encoding="utf-8") as fh:
            inventory = json.load(fh)
    except Exception as exc:
        logger.error("Failed to load inventory %s: %s", inv_path, exc)
        return {}

    active_routes = inventory.get("active_routes", [])
    if not active_routes:
        logger.warning(
            "Inventory has no active_routes",
            extra={"context": {"path": str(inv_path), "event": "graph_build_empty_inventory"}},
        )
        return {}

    # Build token lookup: symbol → TokenInfo
    token_map: Dict[str, TokenInfo] = {}
    for sym, tc in cfg.tokens.items():
        token_map[sym] = TokenInfo(symbol=sym, address=tc.address, decimals=tc.decimals)

    adjacency: Dict[str, Dict[str, List[GraphEdge]]] = defaultdict(lambda: defaultdict(list))
    built_count = 0
    unverified_skipped = 0

    for entry in active_routes:
        pair_id = entry.get("pair_id", "")
        dex_id = entry.get("dex_id", "")
        fee = int(entry.get("fee", 0))
        factory_class = entry.get("factory_class", "UNKNOWN")
        pool_address = entry.get("pool_address", "0x0000000000000000000000000000000000000000")
        route_id = entry.get("route_id", "_")

        if exclude_factory_classes and factory_class in exclude_factory_classes:
            continue
        if exclude_route_ids and route_id in exclude_route_ids:
            continue
        if require_factory_verified and entry.get("factory_verified") is not True:
            unverified_skipped += 1
            logger.debug(
                "Skipping unverified route (require_factory_verified=True)",
                extra={"context": {"route_id": route_id, "event": "graph_build_skip_unverified"}},
            )
            continue

        try:
            sym0, sym1 = _parse_pair_symbols(pair_id)
        except ValueError:
            continue

        # Determine adapter_type and tick_spacing from config
        adapter_type = "uniswap_v3"
        tick_spacing: Optional[int] = None
        quoter_addr = "0x0000000000000000000000000000000000000000"

        dex_cfg = cfg.dexes.get(dex_id)
        if dex_cfg is None:
            logger.debug(
                "Unknown dex in inventory",
                extra={"context": {"dex_id": dex_id, "event": "graph_build_unknown_dex"}},
            )
        else:
            adapter_type = dex_cfg.adapter_type
            quoter_addr = dex_cfg.quoter
            if adapter_type == "aerodrome_slipstream" and dex_cfg.tick_spacings:
                # Use first tick spacing (or match by fee/tick_spacing field)
                tick_spacing = dex_cfg.tick_spacings[0]
                tick_key = entry.get("tick_spacing")
                if tick_key is not None:
                    tick_spacing = int(tick_key)
                elif fee > 0:
                    # Aerodrome Slipstream inventory stores tick_spacing in 'fee' field
                    tick_spacing = fee

        fee_bps = _fee_bps_from_edge(adapter_type, fee, tick_spacing)

        # Resolve token info
        t0 = token_map.get(sym0)
        t1 = token_map.get(sym1)
        if t0 is None or t1 is None:
            logger.debug(
                "Unknown token symbol in inventory edge",
                extra={
                    "context": {
                        "pair_id": pair_id,
                        "event": "graph_build_unknown_token",
                        "sym0": sym0,
                        "sym1": sym1,
                    }
                },
            )
            # Fall back to placeholder
            if t0 is None:
                t0 = TokenInfo(
                    symbol=sym0,
                    address="0x" + "0" * 40,
                    decimals=18,
                )
            if t1 is None:
                t1 = TokenInfo(
                    symbol=sym1,
                    address="0x" + "0" * 40,
                    decimals=18,
                )

        edge_key_fwd = f"{route_id}>{sym0}@{sym1}"
        edge_key_rev = f"{route_id}>{sym1}@{sym0}"

        if exclude_edge_keys:
            if edge_key_fwd in exclude_edge_keys and edge_key_rev in exclude_edge_keys:
                continue

        # Forward: sym0 → sym1
        if not (exclude_edge_keys and edge_key_fwd in exclude_edge_keys):
            fwd_edge = GraphEdge(
                token_in_sym=sym0,
                token_out_sym=sym1,
                token_in_addr=t0.address,
                token_out_addr=t1.address,
                token_in_decimals=t0.decimals,
                token_out_decimals=t1.decimals,
                route_id=route_id,
                dex_id=dex_id,
                adapter_type=adapter_type,
                fee=fee,
                tick_spacing=tick_spacing,
                quoter_addr=quoter_addr,
                pool_address=pool_address,
                fee_bps=fee_bps,
                factory_class=factory_class,
                pair_id=pair_id,
            )
            adjacency[sym0][sym1].append(fwd_edge)
            built_count += 1

        # Reverse: sym1 → sym0
        if not (exclude_edge_keys and edge_key_rev in exclude_edge_keys):
            rev_edge = GraphEdge(
                token_in_sym=sym1,
                token_out_sym=sym0,
                token_in_addr=t1.address,
                token_out_addr=t0.address,
                token_in_decimals=t1.decimals,
                token_out_decimals=t0.decimals,
                route_id=route_id,
                dex_id=dex_id,
                adapter_type=adapter_type,
                fee=fee,
                tick_spacing=tick_spacing,
                quoter_addr=quoter_addr,
                pool_address=pool_address,
                fee_bps=fee_bps,
                factory_class=factory_class,
                pair_id=pair_id,
            )
            adjacency[sym1][sym0].append(rev_edge)
            built_count += 1

    logger.info(
        "Graph built",
        extra={
            "context": {
                "event": "graph_built",
                "token_count": len(adjacency),
                "edge_count": built_count,
                "inventory_path": str(inv_path),
                "unverified_skipped": unverified_skipped,
            }
        },
    )
    return dict(adjacency)


def graph_token_count(adjacency: "Dict[str, Dict[str, List[GraphEdge]]]") -> int:
    """Count unique tokens in the graph (as origins)."""
    return len(adjacency)


def graph_edge_count(adjacency: "Dict[str, Dict[str, List[GraphEdge]]]") -> int:
    """Count total directed edges (counting multiple routes per token pair)."""
    return sum(len(edges) for adj in adjacency.values() for edges in adj.values())


def graph_route_count(adjacency: "Dict[str, Dict[str, List[GraphEdge]]]") -> int:
    """Count unique route_ids across all directed edges."""
    seen: set = set()
    for adj in adjacency.values():
        for edges in adj.values():
            for e in edges:
                seen.add(e.route_id)
    return len(seen)


# ---------------------------------------------------------------------------
# Funnel A counters + Inventory reject taxonomy
# ---------------------------------------------------------------------------

def extract_inventory_stats(inventory_path: str) -> "Dict[str, object]":
    """Extract Funnel A counters and inventory reject taxonomy from inventory JSON.

    Returns a dict with two top-level keys:
      ``funnel_a``   — pipeline stage counts (raw→graph_ready)
      ``reject_histogram`` — categorised inventory reject counts

    Safe to call independently of build_graph_from_inventory; returns empty
    dicts if the file cannot be opened.
    """
    inv_path = Path(inventory_path)
    if not inv_path.exists():
        return {"funnel_a": {}, "reject_histogram": {}}

    try:
        with inv_path.open("r", encoding="utf-8") as fh:
            inventory = json.load(fh)
    except Exception:
        return {"funnel_a": {}, "reject_histogram": {}}

    pools: list = inventory.get("pools", [])
    active_routes: list = inventory.get("active_routes", [])
    pairs_probed: list = inventory.get("pairs_probed", [])
    dexes_probed: list = inventory.get("dexes_probed", [])

    # --- Funnel A counts ---
    raw_hints = len(pools)  # every pool candidate considered
    verified_pools = sum(
        1 for p in pools if p.get("pool_exists") and p.get("active") and not p.get("error")
    )
    verified_tokens = len({
        sym
        for pair_id in pairs_probed
        for sym in pair_id.split("_")
        if "_" in pair_id
    })
    ar_count = len(active_routes)
    # Count routes without factory_verified=True (purity metric for M9_INVENTORY_PURITY goal)
    unverified_active_routes = sum(
        1 for r in active_routes if r.get("factory_verified") is not True
    )
    # graph_ready_edges is computed separately (we can't fully know without running builder)
    # Use active_routes * 2 as a reasonable proxy (forward + reverse for each route)
    graph_ready_edges_proxy = ar_count * 2

    funnel_a = {
        "raw_hints": raw_hints,
        "pairs_probed": len(pairs_probed),
        "dexes_probed": len(dexes_probed),
        "verified_tokens": verified_tokens,
        "verified_pools": verified_pools,
        "active_routes": ar_count,
        "unverified_active_routes": unverified_active_routes,
        "graph_ready_edges_proxy": graph_ready_edges_proxy,
    }

    # --- Inventory reject taxonomy ---
    reject: "Dict[str, int]" = {}

    def _inc(key: str) -> None:
        reject[key] = reject.get(key, 0) + 1

    zero_addr = "0x" + "0" * 40
    for p in pools:
        if not p.get("pool_exists"):
            _inc("missing_pool")
            continue
        qr = p.get("quarantine_reason")
        if qr:
            if qr == "LOW_LIQUIDITY":
                _inc("bad_liquidity")
            elif qr == "STALE_QUOTE":
                _inc("stale_quote")
            else:
                _inc("quarantine_other")
        if p.get("error"):
            _inc("rpc_error")

    # Count active routes where token symbols can't be parsed
    for entry in active_routes:
        pair_id = entry.get("pair_id", "")
        if "_" not in pair_id:
            _inc("unknown_token")
            continue
        addr = entry.get("pool_address", "")
        if not addr or addr == zero_addr:
            _inc("missing_pool_address")

    return {"funnel_a": funnel_a, "reject_histogram": reject}


def best_inventory_path(
    preferred: Optional[str] = None,
    fallback: Optional[str] = None,
) -> str:
    """Return the best available inventory path.

    Checks ``preferred`` first (defaults to shadow inventory), then
    ``fallback`` (defaults to m8_1 exotic inventory).
    """
    p = preferred or _SHADOW_INVENTORY
    f = fallback or _DEFAULT_INVENTORY
    return p if Path(p).exists() else f
