"""Chain-level token identity: address/decimals/symbol maps and ERC20 decimals probe.

Lowest-layer token truth shared by discovery (M8/M8.2), metadata (M8.3),
inventory (M8.1) and graph (M9). Token identity is a contract property, so it
must not live inside a milestone package that other milestones then import
upward.

Sources are config only (`config/core_tokens.yaml`, `config/m9_token_baselines.yaml`)
plus an optional on-chain `decimals()` call. No milestone imports.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import CONFIG_DIR, load_core_tokens, load_yaml

log = logging.getLogger(__name__)

_CHAIN_ALIASES = {"base": "base", "arbitrum": "arbitrum_one", "arbitrum_one": "arbitrum_one"}

_ERC20_DECIMALS_SELECTOR = "0x313ce567"

_ANCHOR_SYMBOLS = frozenset(
    {"WETH", "USDC", "USDT", "DAI", "USDbC", "EURC", "cbETH", "cbBTC"}
)


@lru_cache(maxsize=4)
def _core_tokens_raw() -> Dict[str, Any]:
    return load_core_tokens()


@lru_cache(maxsize=4)
def _baselines_raw() -> Dict[str, Any]:
    path = CONFIG_DIR / "m9_token_baselines.yaml"
    if not path.exists():
        return {}
    return load_yaml("m9_token_baselines.yaml")


def normalize_chain_key(chain: str) -> str:
    return _CHAIN_ALIASES.get((chain or "base").strip().lower(), chain)


def is_valid_eth_address(addr: object) -> bool:
    if not isinstance(addr, str):
        return False
    a = addr.strip().lower()
    if not a.startswith("0x") or len(a) != 42 or a == "0x" + "0" * 40:
        return False
    try:
        int(a[2:], 16)
    except ValueError:
        return False
    return True


def is_truncated_hex_token(sym: str) -> bool:
    s = (sym or "").strip().lower()
    return s.startswith("0x") and 2 < len(s) < 42


def _extra_tokens(chain_key: str) -> Dict[str, Any]:
    return ((_baselines_raw().get("extra_tokens") or {}).get(chain_key) or {})


def address_decimals_map(chain: str = "base") -> Dict[str, int]:
    """Lowercase address -> decimals from config/core_tokens.yaml (+ baselines)."""
    ck = normalize_chain_key(chain)
    out: Dict[str, int] = {}
    for meta_source in ((_core_tokens_raw().get(ck) or {}), _extra_tokens(ck)):
        for _sym, meta in meta_source.items():
            if not isinstance(meta, dict):
                continue
            addr = str(meta.get("address") or "").strip().lower()
            dec = meta.get("decimals")
            if addr.startswith("0x") and len(addr) == 42 and dec is not None:
                out[addr] = int(dec)
    return out


def address_symbol_map(chain: str = "base") -> Dict[str, str]:
    """Lowercase address -> canonical symbol."""
    ck = normalize_chain_key(chain)
    out: Dict[str, str] = {}
    for meta_source in ((_core_tokens_raw().get(ck) or {}), _extra_tokens(ck)):
        for sym, meta in meta_source.items():
            if not isinstance(meta, dict):
                continue
            addr = str(meta.get("address") or "").strip().lower()
            if addr.startswith("0x") and len(addr) == 42:
                out[addr] = str(sym)
    return out


def symbol_baseline_prices(chain: str = "base") -> Dict[str, float]:
    """Symbol -> USD baseline from config/m9_token_baselines.yaml."""
    ck = normalize_chain_key(chain)
    raw = (_baselines_raw().get("chains") or {}).get(ck) or {}
    sym_map = raw.get("symbol_prices_usd") or {}
    return {str(k): float(v) for k, v in sym_map.items() if v is not None}


def anchor_token_addresses(chain: str = "base") -> frozenset:
    """Canonical anchor token addresses for honeypot/entry policy."""
    sym_map = address_symbol_map(chain)
    dec_map = address_decimals_map(chain)
    return frozenset(
        addr for addr, sym in sym_map.items() if sym in _ANCHOR_SYMBOLS and addr in dec_map
    )


def resolve_truncated_address(
    prefix: str,
    chain: str = "base",
    *,
    route_index: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Map ``0x833589``-style prefix to a unique full address.

    Resolution order:
      1. Optional ``route_index`` (inventory / bridge routes)
      2. Unique prefix match in core_tokens + baselines
    """
    p = (prefix or "").strip().lower()
    if not p.startswith("0x") or len(p) >= 42:
        return None
    if route_index and p in route_index:
        return route_index[p]
    hits = [addr for addr in address_decimals_map(chain) if addr.startswith(p)]
    if len(hits) == 1:
        return hits[0]
    return None


def build_route_address_prefix_index(
    routes: List[Dict[str, Any]],
    chain: str = "base",
) -> Dict[str, str]:
    """Build prefix/symbol -> full address map from bridge inventory routes."""
    index: Dict[str, str] = {}
    for route in routes or []:
        if not isinstance(route, dict):
            continue
        for sym_key, addr_key in (("token0", "token0_addr"), ("token1", "token1_addr")):
            sym = str(route.get(sym_key) or "").strip()
            addr = str(route.get(addr_key) or "").strip().lower()
            if not is_valid_eth_address(addr):
                continue
            if sym:
                index[sym] = addr
                index[sym.lower()] = addr
                if sym.lower().startswith("0x") and len(sym) < 42:
                    index[sym.lower()] = addr
            for plen in (8, 10, 12):
                if len(addr) >= plen:
                    index[addr[:plen]] = addr
        pair_id = str(route.get("pair_id") or "")
        if "_" in pair_id:
            sym0, sym1 = pair_id.split("_", 1)
            for sym, addr_key in ((sym0, "token0_addr"), (sym1, "token1_addr")):
                addr = str(route.get(addr_key) or "").strip().lower()
                if is_valid_eth_address(addr) and sym:
                    index[sym] = addr
                    index[sym.lower()] = addr
                    if sym.lower().startswith("0x") and len(sym) < 42:
                        index[sym.lower()] = addr
    return index


def fetch_on_chain_decimals(w3: Any, address: str) -> Optional[int]:
    """Read ERC20 ``decimals()`` via eth_call; None when unavailable."""
    if w3 is None or not is_valid_eth_address(address):
        return None
    try:
        raw = w3.eth.call({"to": address, "data": _ERC20_DECIMALS_SELECTOR})
        if not raw or raw == b"" or raw == "0x":
            return None
        if isinstance(raw, str):
            return int(raw, 16)
        return int.from_bytes(raw[-32:], "big")
    except Exception as exc:
        log.debug("on-chain decimals() failed for %s: %s", address[:12], exc)
        return None


# Retained for callers that predate the public name.
_is_full_eth_address = is_valid_eth_address

__all__ = [
    "address_decimals_map",
    "address_symbol_map",
    "anchor_token_addresses",
    "build_route_address_prefix_index",
    "fetch_on_chain_decimals",
    "is_truncated_hex_token",
    "is_valid_eth_address",
    "normalize_chain_key",
    "resolve_truncated_address",
    "symbol_baseline_prices",
]
