"""Build directed token-exchange graph from inventory."""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from m8_1.stable_anchor.config_loader import load_config, M8_1Config
from m8_1.stable_anchor.pairs import TokenInfo
from m9.graph_arb.models import GraphEdge
from m9.graph_arb.adapter_metadata import load_adapter_metadata, AdapterMetadata
from m9.graph_arb.bridge_builder import curve_temporarily_disabled

logger = logging.getLogger(__name__)

_ZERO_ETH_ADDRESS = "0x" + "0" * 40

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
    elif adapter_type in ("ve33",):
        return 20.0  # aerodrome volatile ~0.2%; per-pool in reality
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


def productive_dex_ids_from_config(config_path: str) -> "frozenset[str]":
    """DEX ids allowed in productive lane (``m9_dex_productivity.enabled_for_productive``)."""
    import yaml

    with open(config_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    productivity = raw.get("m9_dex_productivity") or {}
    dexes = raw.get("dexes") or {}
    allowed: set[str] = set()
    for dex_id, dex_cfg in dexes.items():
        if not dex_cfg.get("enabled", True):
            continue
        prod = productivity.get(dex_id) or {}
        if bool(prod.get("enabled_for_productive", False)):
            allowed.add(dex_id)
    return frozenset(allowed)


def _is_valid_eth_address(addr: object) -> bool:
    """True for non-zero 0x-prefixed 20-byte hex addresses."""
    if not isinstance(addr, str):
        return False
    a = addr.strip().lower()
    if not a.startswith("0x") or len(a) != 42 or a == _ZERO_ETH_ADDRESS:
        return False
    try:
        int(a[2:], 16)
    except ValueError:
        return False
    return True


def _decimals_for_symbol(sym: str, cfg: M8_1Config, override: object) -> int:
    if override is not None:
        try:
            return int(override)
        except (TypeError, ValueError):
            pass
    tc = cfg.tokens.get(sym)
    return int(tc.decimals) if tc is not None else 18


def _is_truncated_hex_token(sym: str) -> bool:
    """True for partial address tokens like ``0x833589`` used as pair_id symbols."""
    s = (sym or "").strip().lower()
    return s.startswith("0x") and 2 < len(s) < 42


def _entry_symbol_address_map(entry: dict) -> Dict[str, str]:
    """Map pair_id symbols (incl. truncated hex) to validated route addresses."""
    out: Dict[str, str] = {}
    for sym_key, addr_key in (("token0", "token0_addr"), ("token1", "token1_addr")):
        sym = str(entry.get(sym_key) or "")
        addr = entry.get(addr_key) or ""
        if not _is_valid_eth_address(addr) and _is_valid_eth_address(sym):
            addr = sym
        if not _is_valid_eth_address(addr):
            continue
        al = addr.lower()
        if sym:
            out[sym] = al
            out[sym.lower()] = al
        out[al] = al
        if len(al) >= 10:
            out[al[:8]] = al
    return out


def _resolve_route_token(
    sym: str,
    entry: dict,
    token_map: Dict[str, TokenInfo],
    cfg: M8_1Config,
    dec_key: str,
) -> Optional[TokenInfo]:
    """Resolve a route leg: inventory addr fields beat polluted token_map keys."""
    if not sym:
        return None
    sym_map = _entry_symbol_address_map(entry)
    addr = sym_map.get(sym) or sym_map.get(sym.lower())
    if _is_valid_eth_address(addr):
        return TokenInfo(
            symbol=sym,
            address=addr.lower(),
            decimals=_decimals_for_symbol(sym, cfg, entry.get(dec_key)),
        )
    existing = token_map.get(sym)
    if existing is not None and _is_valid_eth_address(existing.address):
        return existing
    return None


def _merge_inventory_token_addresses(
    token_map: Dict[str, TokenInfo],
    active_routes: list,
    cfg: M8_1Config,
) -> None:
    """Augment token_map with on-chain addresses from M8 bridge routes.

    Config tokens win on conflict. Inventory fills missing symbols and replaces
    placeholder zero addresses that would otherwise collapse QSR.
    """
    for entry in active_routes:
        pair_id = entry.get("pair_id", "")
        if "_" not in pair_id:
            continue
        try:
            sym0, sym1 = _parse_pair_symbols(pair_id)
        except ValueError:
            continue

        addr0 = entry.get("token0_addr") or ""
        addr1 = entry.get("token1_addr") or ""
        if not _is_valid_eth_address(addr0):
            t0_field = entry.get("token0", "")
            if _is_valid_eth_address(t0_field):
                addr0 = t0_field
        if not _is_valid_eth_address(addr1):
            t1_field = entry.get("token1", "")
            if _is_valid_eth_address(t1_field):
                addr1 = t1_field

        for sym, addr, dec_key in (
            (sym0, addr0, "token0_decimals"),
            (sym1, addr1, "token1_decimals"),
        ):
            if not sym or _is_truncated_hex_token(sym) or not _is_valid_eth_address(addr):
                continue
            addr_l = addr.lower()
            decimals = _decimals_for_symbol(sym, cfg, entry.get(dec_key))
            existing = token_map.get(sym)
            if existing is None:
                token_map[sym] = TokenInfo(symbol=sym, address=addr_l, decimals=decimals)
                continue
            if not _is_valid_eth_address(existing.address):
                token_map[sym] = TokenInfo(symbol=sym, address=addr_l, decimals=decimals)
                continue
            if existing.address.lower() != addr_l:
                logger.debug(
                    "Inventory token address differs from config; keeping config",
                    extra={
                        "context": {
                            "event": "graph_build_token_addr_conflict",
                            "symbol": sym,
                            "config_addr": existing.address,
                            "inventory_addr": addr_l,
                        }
                    },
                )


def build_graph_from_inventory(
    inventory_path: str = _DEFAULT_INVENTORY,
    config_path: str = _DEFAULT_CONFIG,
    exclude_factory_classes: Optional["frozenset[str]"] = None,
    min_qsr_edge: float = 0.0,
    exclude_route_ids: Optional["frozenset[str]"] = None,
    exclude_edge_keys: Optional["frozenset[str]"] = None,
    require_factory_verified: bool = False,
    # Pool-quality gate (Steps 2+3): productive lane filtering
    exclude_pool_addresses: Optional["frozenset[str]"] = None,
    min_effective_depth_usd: float = 0.0,
    lane: str = "discovery",
) -> "Dict[str, Dict[str, List[GraphEdge]]]":
    """Build a directed adjacency dict from inventory active_routes.

    Args:
        require_factory_verified: When True, skip any route whose
            ``factory_verified`` field is not exactly ``True``.  Routes
            lacking the field are treated as unverified and filtered out.
            Use this after running pool_verifier to ensure only on-chain
            confirmed pools enter the graph.
        exclude_pool_addresses: Frozenset of lowercase pool addresses to skip.
            Only applied when ``lane='productive'``. Load from
            ``pool_depth_filter.load_quarantined_pool_addresses()``.
        min_effective_depth_usd: Minimum effective depth in USD (from depth probe).
            Routes with ``effective_depth_usd < threshold`` are excluded.
            Only applied when ``lane='productive'`` and depth data is present.
        lane: 'discovery' (default) or 'productive'.
            Discovery lane sees all pools including thin/quarantined ones — useful
            for RCA and universe mapping.
            Productive lane applies ``exclude_pool_addresses`` and
            ``min_effective_depth_usd`` filters.

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

    # Build token lookup: symbol → TokenInfo (config), then M8 route addresses.
    token_map: Dict[str, TokenInfo] = {}
    for sym, tc in cfg.tokens.items():
        token_map[sym] = TokenInfo(symbol=sym, address=tc.address, decimals=tc.decimals)
    _merge_inventory_token_addresses(token_map, active_routes, cfg)

    adjacency: Dict[str, Dict[str, List[GraphEdge]]] = defaultdict(lambda: defaultdict(list))
    built_count = 0
    unverified_skipped = 0
    depth_skipped = 0
    curve_unindexed_skipped = 0
    curve_unquotable_skipped = 0
    curve_disabled_skipped = 0
    invalid_token_addr_skipped = 0
    unknown_token_skipped = 0
    productivity_skipped = 0
    admission_skipped = 0
    _productive_lane = (lane == "productive")
    _productive_dexes = (
        productive_dex_ids_from_config(config_path) if _productive_lane else frozenset()
    )

    # Load per-pool adapter metadata (Curve coin indices, Balancer pool_id/vault_address).
    # Graceful: returns empty registry when file missing or malformed.
    _adapter_meta: AdapterMetadata = load_adapter_metadata()
    # Infer chain from config name if possible; default "base".
    _meta_chain = "base"
    if config_path and "arbitrum" in config_path.lower():
        _meta_chain = "arbitrum"
    elif config_path and "mantle" in config_path.lower():
        _meta_chain = "mantle"

    for entry in active_routes:
        pair_id = entry.get("pair_id", "")
        dex_id = entry.get("dex_id", "")
        fee = int(entry.get("fee") or 0)
        factory_class = entry.get("factory_class", "UNKNOWN")
        factory_verified_flag: bool = entry.get("factory_verified") is True
        pool_address = entry.get("pool_address", "0x0000000000000000000000000000000000000000")
        route_id = entry.get("route_id", "_")

        if curve_temporarily_disabled() and (
            dex_id == "curve_stable" or entry.get("adapter_type") == "curve_stable"
        ):
            curve_disabled_skipped += 1
            continue

        if _productive_lane and _productive_dexes and dex_id not in _productive_dexes:
            productivity_skipped += 1
            continue

        if _productive_lane:
            from m9.graph_arb.pool_quality import productive_admission_ok

            _min_depth = min_effective_depth_usd if min_effective_depth_usd > 0 else 50.0
            if not productive_admission_ok(entry, min_depth_usd=_min_depth):
                admission_skipped += 1
                continue

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

        # Productive lane: pool-quality gate (Steps 2+3)
        if _productive_lane:
            if exclude_pool_addresses and pool_address.lower() in exclude_pool_addresses:
                depth_skipped += 1
                logger.debug(
                    "Productive lane: skipping quarantined pool",
                    extra={
                        "context": {
                            "event": "graph_build_skip_quarantine",
                            "pool_address": pool_address,
                            "pair_id": pair_id,
                            "route_id": route_id,
                        }
                    },
                )
                continue
            if min_effective_depth_usd > 0:
                depth_usd = entry.get("effective_depth_usd")
                if depth_usd is not None and float(depth_usd) < min_effective_depth_usd:
                    depth_skipped += 1
                    logger.debug(
                        "Productive lane: skipping low-depth pool",
                        extra={
                            "context": {
                                "event": "graph_build_skip_low_depth",
                                "pool_address": pool_address,
                                "pair_id": pair_id,
                                "effective_depth_usd": depth_usd,
                                "threshold": min_effective_depth_usd,
                            }
                        },
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
        hooks: Optional[str] = None  # V4 only

        dex_cfg = cfg.dexes.get(dex_id)
        if dex_cfg is None:
            logger.debug(
                "Unknown dex in inventory",
                extra={"context": {"dex_id": dex_id, "event": "graph_build_unknown_dex"}},
            )
            # Fallback: use adapter_type already stored in the inventory entry (set by bridge_builder)
            _entry_adapter = entry.get("adapter_type")
            if _entry_adapter and _entry_adapter not in ("unknown", "unsupported"):
                adapter_type = _entry_adapter
            if adapter_type in ("uniswap_v2", "ve33", "aerodrome_v2_stable", "curve_stable", "maverick_v2"):
                # V2/ve33/aerodrome_v2_stable/curve_stable/maverick_v2: quoter is the pool itself
                quoter_addr = pool_address
        else:
            adapter_type = dex_cfg.adapter_type
            quoter_addr = dex_cfg.quoter
            # V2, ve33, aerodrome_v2_stable, curve_stable, and maverick_v2 adapters quote on the pool itself.
            # Curve: get_dy is called on the pool contract; no separate quoter.
            # Maverick V2: PoolInformation.calculateSwap takes pool addr as first param.
            if adapter_type in ("uniswap_v2", "ve33", "aerodrome_v2_stable", "curve_stable", "maverick_v2"):
                quoter_addr = pool_address
            if adapter_type == "aerodrome_slipstream" and dex_cfg.tick_spacings:
                # Use first tick spacing (or match by fee/tick_spacing field)
                tick_spacing = dex_cfg.tick_spacings[0]
                tick_key = entry.get("tick_spacing")
                if tick_key is not None:
                    tick_spacing = int(tick_key)
                elif fee > 0:
                    # Aerodrome Slipstream inventory stores tick_spacing in 'fee' field
                    tick_spacing = fee
            elif adapter_type == "uniswap_v4":
                # V4 pools: tick_spacing is stored in the inventory entry (from M8 sniper)
                tick_key = entry.get("tick_spacing")
                if tick_key is not None:
                    tick_spacing = int(tick_key)
                hooks = entry.get("hooks")

        fee_bps = _fee_bps_from_edge(adapter_type, fee, tick_spacing)

        # Resolve per-pool adapter metadata (Curve/Balancer).
        # These fields flow into GraphEdge → DexRoute → quote_probe / raw_http_probe.
        _token_in_index: Optional[int] = None
        _token_out_index: Optional[int] = None
        _pool_id: Optional[str] = None
        _vault_address: Optional[str] = None
        _pool_kind: Optional[str] = None
        _balancer_assets: Optional[tuple] = None
        _maverick_token_a: Optional[str] = None

        if adapter_type == "curve_stable":
            # Variant ("stable"/"crypto") drives the get_dy ABI selector in the
            # quoter. Read it from the rolling indices artifact; default to
            # "stable" when the pool is not yet classified.
            _pool_kind = _adapter_meta.curve_pool_kind(pool_address, chain=_meta_chain) or "stable"
        elif adapter_type in ("balancer_stable", "balancer_weighted"):
            _pool_kind = "stable" if adapter_type == "balancer_stable" else "weighted"
            _b_pool = _adapter_meta.balancer_pool_meta(pool_address, chain=_meta_chain)
            if _b_pool is not None:
                _pool_id = _b_pool.pool_id
                _pool_kind = _b_pool.pool_kind
                _vault_address = _adapter_meta.balancer_vault_address(_meta_chain)
            # M8.2 expansion / bridge inventory may carry pool_id before YAML index merge.
            if not _pool_id:
                _entry_pool_id = entry.get("pool_id")
                if _entry_pool_id:
                    _pool_id = str(_entry_pool_id).lower()
            if not _vault_address:
                _entry_vault = entry.get("vault_address")
                if _entry_vault:
                    _vault_address = str(_entry_vault).lower()
            if not _vault_address:
                _vault_address = _adapter_meta.balancer_vault_address(_meta_chain)
            if _b_pool is not None and _b_pool.assets:
                _balancer_assets = _b_pool.assets
            else:
                _entry_assets = entry.get("balancer_assets")
                if _entry_assets:
                    _balancer_assets = tuple(str(a).lower() for a in _entry_assets)
                elif pool_address:
                    try:
                        from m8.discovery.mirror_index import MirrorIndex

                        for _bent in MirrorIndex.load(_meta_chain).balancer:
                            if _bent.pool_address.lower() == pool_address.lower():
                                _balancer_assets = _bent.assets
                                break
                    except Exception:
                        pass
        elif adapter_type == "maverick_v2":
            _ta = str(entry.get("token_a") or "").lower()
            if _ta.startswith("0x") and len(_ta) == 42:
                _maverick_token_a = _ta

        # Curve index lookup happens per-direction (fwd / rev), computed below.

        # Resolve token info (entry addresses win over truncated-hex token_map keys)
        t0 = _resolve_route_token(sym0, entry, token_map, cfg, "token0_decimals")
        t1 = _resolve_route_token(sym1, entry, token_map, cfg, "token1_decimals")
        if t0 is None or t1 is None:
            if _productive_lane:
                unknown_token_skipped += 1
                continue
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
            # Last resort: placeholder (quote will fail — should be rare after merge)
            if t0 is None:
                t0 = TokenInfo(
                    symbol=sym0,
                    address=_ZERO_ETH_ADDRESS,
                    decimals=_decimals_for_symbol(sym0, cfg, entry.get("token0_decimals")),
                )
            if t1 is None:
                t1 = TokenInfo(
                    symbol=sym1,
                    address=_ZERO_ETH_ADDRESS,
                    decimals=_decimals_for_symbol(sym1, cfg, entry.get("token1_decimals")),
                )

        if not _is_valid_eth_address(t0.address) or not _is_valid_eth_address(t1.address):
            invalid_token_addr_skipped += 1
            continue
        if t0.address.lower() == t1.address.lower():
            invalid_token_addr_skipped += 1
            continue

        edge_key_fwd = f"{route_id}>{sym0}@{sym1}"
        edge_key_rev = f"{route_id}>{sym1}@{sym0}"

        if exclude_edge_keys:
            if edge_key_fwd in exclude_edge_keys and edge_key_rev in exclude_edge_keys:
                continue

        # Freshness window: True when M8 sniped pool is within _FRESH_WINDOW_SECONDS
        _freshness_window = bool(entry.get("freshness_window", False))

        # Depth-aware sizing input: measured on-chain depth (pool_depth_probe / package #8).
        _raw_depth = entry.get("effective_depth_usd")
        _effective_depth_usd: Optional[float] = (
            float(_raw_depth) if _raw_depth is not None else None
        )

        # Forward: sym0 → sym1
        if not (exclude_edge_keys and edge_key_fwd in exclude_edge_keys):
            # Curve: per-direction index lookup
            _fwd_idx_in, _fwd_idx_out = (
                _adapter_meta.curve_indices(pool_address, sym0, sym1, chain=_meta_chain)
                if adapter_type == "curve_stable"
                else (None, None)
            )
            if adapter_type == "maverick_v2" and _maverick_token_a:
                _fwd_idx_in = 1 if t0.address.lower() == _maverick_token_a else 0
            # Curve quoting requires resolved coin indices: get_dy(i,j,dx) cannot
            # be called without them. A curve_stable edge with unresolved indices
            # is structurally unquoteable and would only emit QUOTE_REVERT, poisoning
            # QSR. Skip admission (reversible: the edge re-enters automatically once
            # discover_curve_indices classifies the pool). NOT a Curve disable —
            # classified Curve pools are still admitted and quoted.
            if adapter_type == "curve_stable" and (
                _fwd_idx_in is None or _fwd_idx_out is None
            ):
                curve_unindexed_skipped += 1
            elif adapter_type == "curve_stable" and not _adapter_meta.curve_pool_quotable(
                pool_address, chain=_meta_chain
            ):
                curve_unquotable_skipped += 1
            else:
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
                    factory_verified=factory_verified_flag,
                    hooks=hooks,
                    token_in_index=_fwd_idx_in,
                    token_out_index=_fwd_idx_out,
                    pool_id=_pool_id,
                    vault_address=_vault_address,
                    pool_kind=_pool_kind,
                    freshness_window=_freshness_window,
                    effective_depth_usd=_effective_depth_usd,
                    balancer_assets=_balancer_assets,
                    token_a_address=_maverick_token_a,
                )
                adjacency[sym0][sym1].append(fwd_edge)
                built_count += 1

        # Reverse: sym1 → sym0
        if not (exclude_edge_keys and edge_key_rev in exclude_edge_keys):
            # Curve: reversed direction — swap token order for index lookup
            _rev_idx_in, _rev_idx_out = (
                _adapter_meta.curve_indices(pool_address, sym1, sym0, chain=_meta_chain)
                if adapter_type == "curve_stable"
                else (None, None)
            )
            if adapter_type == "maverick_v2" and _maverick_token_a:
                _rev_idx_in = 1 if t1.address.lower() == _maverick_token_a else 0
            if adapter_type == "curve_stable" and (
                _rev_idx_in is None or _rev_idx_out is None
            ):
                curve_unindexed_skipped += 1
            elif adapter_type == "curve_stable" and not _adapter_meta.curve_pool_quotable(
                pool_address, chain=_meta_chain
            ):
                curve_unquotable_skipped += 1
            else:
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
                    factory_verified=factory_verified_flag,
                    hooks=hooks,
                    token_in_index=_rev_idx_in,
                    token_out_index=_rev_idx_out,
                    pool_id=_pool_id,
                    vault_address=_vault_address,
                    pool_kind=_pool_kind,
                    freshness_window=_freshness_window,
                    effective_depth_usd=_effective_depth_usd,
                    balancer_assets=_balancer_assets,
                    token_a_address=_maverick_token_a,
                )
                adjacency[sym1][sym0].append(rev_edge)
                built_count += 1

    logger.info(
        "Graph built",
        extra={
            "context": {
                "event": "graph_built",
                "lane": lane,
                "token_count": len(adjacency),
                "edge_count": built_count,
                "inventory_path": str(inv_path),
                "unverified_skipped": unverified_skipped,
                "depth_skipped": depth_skipped,
                "curve_unindexed_skipped": curve_unindexed_skipped,
                "curve_unquotable_skipped": curve_unquotable_skipped,
                "curve_disabled_skipped": curve_disabled_skipped,
                "invalid_token_addr_skipped": invalid_token_addr_skipped,
                "unknown_token_skipped": unknown_token_skipped,
                "productivity_skipped": productivity_skipped,
                "admission_skipped": admission_skipped,
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
