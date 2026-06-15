"""Load token address/decimals/price maps from config (not inline hardcode)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import CONFIG_DIR, load_core_tokens, load_yaml

_CHAIN_ALIASES = {"base": "base", "arbitrum": "arbitrum_one", "arbitrum_one": "arbitrum_one"}


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


def address_decimals_map(chain: str = "base") -> Dict[str, int]:
    """Lowercase address → decimals from config/core_tokens.yaml."""
    ck = normalize_chain_key(chain)
    out: Dict[str, int] = {}
    for _sym, meta in (_core_tokens_raw().get(ck) or {}).items():
        if not isinstance(meta, dict):
            continue
        addr = str(meta.get("address") or "").strip().lower()
        dec = meta.get("decimals")
        if addr.startswith("0x") and len(addr) == 42 and dec is not None:
            out[addr] = int(dec)
    extras = ((_baselines_raw().get("extra_tokens") or {}).get(ck) or {})
    for _sym, meta in extras.items():
        if not isinstance(meta, dict):
            continue
        addr = str(meta.get("address") or "").strip().lower()
        dec = meta.get("decimals")
        if addr.startswith("0x") and len(addr) == 42 and dec is not None:
            out[addr] = int(dec)
    return out


def address_symbol_map(chain: str = "base") -> Dict[str, str]:
    """Lowercase address → canonical symbol."""
    ck = normalize_chain_key(chain)
    out: Dict[str, str] = {}
    for sym, meta in (_core_tokens_raw().get(ck) or {}).items():
        if not isinstance(meta, dict):
            continue
        addr = str(meta.get("address") or "").strip().lower()
        if addr.startswith("0x") and len(addr) == 42:
            out[addr] = str(sym)
    extras = ((_baselines_raw().get("extra_tokens") or {}).get(ck) or {})
    for sym, meta in extras.items():
        if not isinstance(meta, dict):
            continue
        addr = str(meta.get("address") or "").strip().lower()
        if addr.startswith("0x") and len(addr) == 42:
            out[addr] = str(sym)
    return out


def symbol_baseline_prices(chain: str = "base") -> Dict[str, float]:
    """Symbol → USD baseline from config/m9_token_baselines.yaml."""
    ck = normalize_chain_key(chain)
    raw = (_baselines_raw().get("chains") or {}).get(ck) or {}
    sym_map = raw.get("symbol_prices_usd") or {}
    return {str(k): float(v) for k, v in sym_map.items() if v is not None}


_ANCHOR_SYMBOLS = frozenset(
    {"WETH", "USDC", "USDT", "DAI", "USDbC", "EURC", "cbETH", "cbBTC"}
)


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


def _is_full_eth_address(addr: str) -> bool:
    a = (addr or "").strip().lower()
    if not a.startswith("0x") or len(a) != 42 or a == "0x" + "0" * 40:
        return False
    try:
        int(a[2:], 16)
    except ValueError:
        return False
    return True


def build_route_address_prefix_index(
    routes: List[Dict[str, Any]],
    chain: str = "base",
) -> Dict[str, str]:
    """Build prefix/symbol → full address map from bridge inventory routes."""
    index: Dict[str, str] = {}
    for route in routes or []:
        if not isinstance(route, dict):
            continue
        for sym_key, addr_key in (("token0", "token0_addr"), ("token1", "token1_addr")):
            sym = str(route.get(sym_key) or "").strip()
            addr = str(route.get(addr_key) or "").strip().lower()
            if not _is_full_eth_address(addr):
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
                if _is_full_eth_address(addr) and sym:
                    index[sym] = addr
                    index[sym.lower()] = addr
                    if sym.lower().startswith("0x") and len(sym) < 42:
                        index[sym.lower()] = addr
    return index
