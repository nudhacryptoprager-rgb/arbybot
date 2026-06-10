"""Token address/symbol normalization for M8 discovery resolvers."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

TOKEN_ADDRESS_UNRESOLVED = "TOKEN_ADDRESS_UNRESOLVED"


def is_valid_eth_address(addr: str) -> bool:
    a = (addr or "").strip().lower()
    return a.startswith("0x") and len(a) == 42


def normalize_token_addr_or_symbol(
    value: str,
    *,
    config: Optional[Dict[str, Any]] = None,
    addr_to_sym: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return ``(addr_lower, symbol, reject_reason)``.

    Partial hex strings (e.g. ``0x420000``) are rejected with
    ``TOKEN_ADDRESS_UNRESOLVED``. Known symbols resolve via config maps.
    """
    raw = (value or "").strip()
    if not raw:
        return None, None, TOKEN_ADDRESS_UNRESOLVED

    if raw.startswith("0x"):
        low = raw.lower()
        if is_valid_eth_address(low):
            sym = (addr_to_sym or {}).get(low) or ""
            return low, sym or None, None
        return None, None, TOKEN_ADDRESS_UNRESOLVED

    sym = raw.upper()
    maps = addr_to_sym
    if maps is None and config is not None:
        from m8.discovery.anchor_registry import build_anchor_maps

        maps, _ = build_anchor_maps(config)
    if maps:
        for addr, s in maps.items():
            if str(s).upper() == sym:
                return addr, str(s), None
    return None, sym, None


def normalize_pair_addresses(
    *,
    exotic_symbol: str,
    anchor_symbol: str,
    exotic_address: str = "",
    anchor_address: str = "",
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, str, str, Optional[str]]:
    """Normalize both legs; return reject_reason when any leg is invalid."""
    from m8.discovery.anchor_registry import build_anchor_maps

    addr_to_sym, _ = (
        build_anchor_maps(config) if config else ({}, frozenset())
    )
    ex_addr, ex_sym, ex_rej = normalize_token_addr_or_symbol(
        exotic_address or exotic_symbol,
        config=config,
        addr_to_sym=addr_to_sym,
    )
    an_addr, an_sym, an_rej = normalize_token_addr_or_symbol(
        anchor_address or anchor_symbol,
        config=config,
        addr_to_sym=addr_to_sym,
    )
    if ex_rej:
        return "", "", "", "", ex_rej
    if an_rej:
        return "", "", "", "", an_rej
    return (
        ex_addr or "",
        an_addr or "",
        ex_sym or exotic_symbol,
        an_sym or anchor_symbol,
        None,
    )
