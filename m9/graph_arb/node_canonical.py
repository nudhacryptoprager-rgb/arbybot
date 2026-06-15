"""Canonical graph node symbols (address-first, core-token aliases)."""
from __future__ import annotations

from typing import Any, Dict, Optional

_PLACEHOLDER_SYMBOLS = frozenset({"T", "?", ""})


def canonical_graph_node(
    symbol: str,
    address: str = "",
    *,
    chain: str = "base",
) -> str:
    """Map truncated hex / address aliases to canonical symbols for graph keys."""
    from m9.graph_arb.core_tokens_loader import address_symbol_map, resolve_truncated_address

    sym = str(symbol or "").strip()
    addr = str(address or "").strip().lower()
    sym_map = address_symbol_map(chain)

    if addr in sym_map:
        return sym_map[addr]

    if sym.startswith("0x"):
        full = resolve_truncated_address(sym, chain)
        if full and full in sym_map:
            return sym_map[full]
        if len(sym) == 42 and sym.lower() in sym_map:
            return sym_map[sym.lower()]

    if sym in sym_map.values():
        return sym

    return sym


def normalize_expansion_route_tokens(
    route: Dict[str, Any],
    *,
    chain: str = "base",
) -> Dict[str, Any]:
    """Replace placeholder symbols (e.g. token1='T') from pair_id / addresses."""
    from m9.graph_arb.core_tokens_loader import address_symbol_map, resolve_truncated_address

    out = dict(route)
    sym_map = address_symbol_map(chain)
    pair_id = str(out.get("pair_id") or "")
    pair_parts = pair_id.split("_", 1) if pair_id and "_" in pair_id else []

    if len(pair_parts) == 2:
        if not out.get("token0"):
            out["token0"] = pair_parts[0]
        if not out.get("token1"):
            out["token1"] = pair_parts[1]

    def _addr_for(key: str, sym: str) -> str:
        raw = str(out.get(key) or "").strip().lower()
        if raw.startswith("0x") and len(raw) == 42:
            return raw
        if sym.startswith("0x"):
            full = resolve_truncated_address(sym, chain)
            if full:
                out[key] = full
                return full
        return raw

    def _fix_side(sym_key: str, addr_key: str, pair_idx: int) -> None:
        sym = str(out.get(sym_key) or "")
        if not sym and len(pair_parts) == 2:
            sym = pair_parts[pair_idx]
            out[sym_key] = sym
        addr = _addr_for(addr_key, sym)
        if sym in _PLACEHOLDER_SYMBOLS or (len(sym) <= 2 and sym not in sym_map.values()):
            if addr in sym_map:
                out[sym_key] = sym_map[addr]
                return
            if len(pair_parts) == 2:
                psym = pair_parts[pair_idx]
                if psym.startswith("0x"):
                    out[sym_key] = canonical_graph_node(psym, "", chain=chain)
                    return
            focus_sym = str(out.get("focus_token_symbol") or "")
            focus_addr = str(
                out.get("focus_token_address") or out.get("exotic_address") or ""
            ).lower()
            if focus_sym and focus_sym not in _PLACEHOLDER_SYMBOLS:
                if addr == focus_addr or sym == focus_sym:
                    out[sym_key] = focus_sym
                    return
        out[sym_key] = canonical_graph_node(sym, addr, chain=chain)

    _fix_side("token0", "token0_addr", 0)
    _fix_side("token1", "token1_addr", 1)

    t0 = str(out.get("token0") or "")
    t1 = str(out.get("token1") or "")
    if t0 and t1:
        out["pair_id"] = "_".join(sorted([t0, t1]))
    return out
