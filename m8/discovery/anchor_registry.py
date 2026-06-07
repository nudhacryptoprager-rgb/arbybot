"""Config-driven anchor token resolution (no hardcoded chain addresses).

Trust anchors come from strategy YAML (``tokens`` section) and optional
``config/core_tokens.yaml`` via :func:`config.get_all_token_addresses`.
Symbol-only fallbacks use :data:`pending_pair_registry._ANCHOR_TOKENS`.
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, Set, Tuple


def chain_key_from_config(config: Dict[str, Any], fallback: str = "base") -> str:
    """Resolve core_tokens.yaml chain key from strategy config."""
    chain = str(config.get("chain") or fallback).strip().lower()
    if chain in ("base", "base_mainnet"):
        return "base"
    return chain


def build_anchor_maps(
    config: Dict[str, Any],
    *,
    chain_key: str | None = None,
) -> Tuple[Dict[str, str], FrozenSet[str]]:
    """Return (addr_lower -> symbol, all_known_symbol_set) from config only."""
    from m8.discovery.pending_pair_registry import _ANCHOR_TOKENS

    ck = chain_key or chain_key_from_config(config)
    addr_to_sym: Dict[str, str] = {}
    sym_set: Set[str] = set(_ANCHOR_TOKENS)

    for sym, info in (config.get("tokens") or {}).items():
        if not isinstance(info, dict):
            continue
        sym_set.add(str(sym))
        addr = info.get("address") or info.get("addr")
        if addr:
            addr_to_sym[str(addr).lower()] = str(sym)

    try:
        from config import get_all_token_addresses

        for sym, addr in get_all_token_addresses(ck).items():
            sym_set.add(str(sym))
            low = str(addr).lower()
            addr_to_sym.setdefault(low, str(sym))
    except (ImportError, KeyError, FileNotFoundError):
        pass

    return addr_to_sym, frozenset(sym_set)


def quote_anchor_maps(
    config: Dict[str, Any],
) -> Tuple[Dict[str, str], FrozenSet[str]]:
    """Routing anchors only (USDC/WETH/…) — NOT every core_tokens.yaml entry."""
    from m8.discovery.pending_pair_registry import _ANCHOR_TOKENS

    full_addr, _ = build_anchor_maps(config)
    quote_syms: Set[str] = set(_ANCHOR_TOKENS)
    for sym in (config.get("tokens") or {}):
        if sym in _ANCHOR_TOKENS:
            quote_syms.add(str(sym))
    quote_addr = {
        addr: sym for addr, sym in full_addr.items() if sym in quote_syms
    }
    return quote_addr, frozenset(quote_syms)


def is_anchor_address(addr: str, addr_to_sym: Dict[str, str]) -> bool:
    return (addr or "").lower() in addr_to_sym


def is_anchor_symbol(sym: str, anchor_syms: FrozenSet[str]) -> bool:
    return sym in anchor_syms or sym in ("USDBC", "USDbC", "ETH")


def symbol_for_address(addr: str, addr_to_sym: Dict[str, str]) -> str:
    return addr_to_sym.get((addr or "").lower(), "")
