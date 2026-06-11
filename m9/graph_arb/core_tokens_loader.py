"""Load token address/decimals/price maps from config (not inline hardcode)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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


def resolve_truncated_address(prefix: str, chain: str = "base") -> Optional[str]:
    """Map ``0x833589``-style prefix to a unique full address from core_tokens."""
    p = (prefix or "").strip().lower()
    if not p.startswith("0x") or len(p) >= 42:
        return None
    hits = [addr for addr in address_decimals_map(chain) if addr.startswith(p)]
    if len(hits) == 1:
        return hits[0]
    return None
