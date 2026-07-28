"""Build anchor×exotic probe pairs for M8.1 fresh_delta mode (non-config tokens)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from m8_1.stable_anchor.pairs import TokenInfo

_ANCHOR_SYMS = frozenset({"USDC", "EURC", "USDT", "DAI", "WETH", "cbBTC"})
_DEFAULT_WATCHLIST = Path("data/tmp/m8_token_watchlist_latest.json")
_DEFAULT_REGISTRY = Path("data/runs/_rolling/m8_3_token_metadata_registry_latest.json")


def _short_symbol(addr: str) -> str:
    low = addr.lower()
    return f"0x{low[2:8]}" if low.startswith("0x") and len(low) >= 8 else low


def _resolve_decimals(
    addr: str,
    *,
    w3: Any,
    registry_row: Optional[Dict[str, Any]],
    cfg: Any,
    watchlist_entry: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    if watchlist_entry and watchlist_entry.get("decimals") is not None:
        try:
            return int(watchlist_entry["decimals"])
        except (TypeError, ValueError):
            pass
    if registry_row and registry_row.get("decimals") is not None:
        try:
            return int(registry_row["decimals"])
        except (TypeError, ValueError):
            pass
    from core.token_identity import address_decimals_map

    known = address_decimals_map("base").get(addr.lower())
    if known is not None:
        return int(known)
    if cfg is not None:
        for tc in cfg.tokens.values():
            if (tc.address or "").lower() == addr.lower():
                return int(tc.decimals)
    if w3 is not None:
        from core.token_identity import fetch_on_chain_decimals

        dec = fetch_on_chain_decimals(w3, addr)
        if dec is not None:
            return int(dec)
    return None


def build_exotic_token_info(
    addr: str,
    *,
    w3: Any,
    cfg: Any,
    watchlist_entry: Optional[Dict[str, Any]] = None,
    registry_row: Optional[Dict[str, Any]] = None,
) -> Optional[TokenInfo]:
    low = str(addr).lower()
    if not low.startswith("0x") or len(low) != 42:
        return None
    sym = str((watchlist_entry or {}).get("symbol") or (registry_row or {}).get("symbol") or "")
    if not sym or sym.lower().startswith("0x"):
        sym = _short_symbol(low)
    dec = _resolve_decimals(
        low,
        w3=w3,
        registry_row=registry_row,
        cfg=cfg,
        watchlist_entry=watchlist_entry,
    )
    if dec is None:
        return None
    return TokenInfo(symbol=sym, address=low, decimals=dec)


def anchor_tokens_from_config(cfg: Any) -> Dict[str, TokenInfo]:
    out: Dict[str, TokenInfo] = {}
    for sym, tc in cfg.tokens.items():
        if sym not in _ANCHOR_SYMS:
            continue
        out[sym] = TokenInfo(symbol=sym, address=tc.address.lower(), decimals=int(tc.decimals))
    return out


def enumerate_fresh_delta_pairs(
    cfg: Any,
    subset_addrs: Set[str],
    *,
    w3: Any = None,
    watchlist_path: Path = _DEFAULT_WATCHLIST,
    registry_path: Path = _DEFAULT_REGISTRY,
) -> List[Tuple[TokenInfo, TokenInfo]]:
    """Return anchor-connected pairs for watchlist/registry tokens outside config."""
    anchors = anchor_tokens_from_config(cfg)
    if not anchors or not subset_addrs:
        return []

    watchlist: Dict[str, Any] = {}
    if watchlist_path.is_file():
        wl_doc = json.loads(watchlist_path.read_text(encoding="utf-8"))
        watchlist = {
            str(k).lower(): v
            for k, v in (wl_doc.get("tokens") or {}).items()
            if isinstance(v, dict)
        }

    registry: Dict[str, Any] = {}
    if registry_path.is_file():
        doc = json.loads(registry_path.read_text(encoding="utf-8"))
        reg_raw = doc.get("token_registry") or doc.get("tokens") or {}
        registry = {
            str(k).lower(): v
            for k, v in reg_raw.items()
            if isinstance(v, dict)
        }

    subset_meta: Dict[str, Dict[str, Any]] = {}
    expand_subset_path = Path("data/tmp/m8_time_to_mirror_expand_subset.json")
    if expand_subset_path.is_file():
        for item in json.loads(expand_subset_path.read_text(encoding="utf-8")).get(
            "tokens"
        ) or []:
            if isinstance(item, dict):
                addr = str(item.get("token") or item.get("address") or "").lower()
                if addr.startswith("0x"):
                    subset_meta[addr] = item

    config_addrs = {(tc.address or "").lower() for tc in cfg.tokens.values()}
    pairs: List[Tuple[TokenInfo, TokenInfo]] = []
    seen: set[frozenset[str]] = set()

    for addr in sorted(subset_addrs):
        low = addr.lower()
        if low in config_addrs:
            continue
        exotic = build_exotic_token_info(
            low,
            w3=w3,
            cfg=cfg,
            watchlist_entry=watchlist.get(low) or subset_meta.get(low),
            registry_row=registry.get(low),
        )
        if exotic is None:
            continue
        for anchor in anchors.values():
            if exotic.address == anchor.address:
                continue
            key = frozenset({exotic.address, anchor.address})
            if key in seen:
                continue
            seen.add(key)
            if exotic.address < anchor.address:
                pairs.append((exotic, anchor))
            else:
                pairs.append((anchor, exotic))
    return pairs
