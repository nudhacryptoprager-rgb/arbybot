"""Address-first token decimals resolver (quote-size truth gate).

Resolution order:
  1. Route/inventory override (``token0_decimals`` / ``token1_decimals``)
  2. Static known-address map (Base anchors)
  3. Config tokens matched by lowercase address
  4. Config tokens matched by canonical symbol (not truncated hex)
  5. Runtime cache (``data/tmp/m9_token_decimals_cache.json``)
  6. On-chain ``decimals()`` when *w3* is provided

Never silently default to 18 for address-like or truncated-hex labels.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from m8_1.stable_anchor.config_loader import M8_1Config

log = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = "data/tmp/m9_token_decimals_cache.json"
_ERC20_DECIMALS_SELECTOR = "0x313ce567"

# Base mainnet — lowercase address → decimals
_KNOWN_ADDRESS_DECIMALS: Dict[str, int] = {
    "0x4200000000000000000000000000000000000006": 18,  # WETH
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": 6,   # USDC
    "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": 6,   # USDbC
    "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42": 6,   # EURC
    "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf": 8,   # cbBTC
    "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22": 18,  # cbETH
    "0xc1cba3fcea344f92d9239c08c0568f6f2f0ee452": 18,  # wstETH
    "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": 18,  # DAI
    "0x940181a94a35a4569e4529a3cdfb74e38fd98631": 18,  # AERO
    "0x417ac0e078398c154edfadd9ef675d30be60af93": 18,  # crvUSD
}


def is_truncated_hex_token(sym: str) -> bool:
    s = (sym or "").strip().lower()
    return s.startswith("0x") and 2 < len(s) < 42


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


def build_config_address_decimals(cfg: M8_1Config) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for tc in cfg.tokens.values():
        addr = (tc.address or "").strip().lower()
        if is_valid_eth_address(addr):
            out[addr] = int(tc.decimals)
    return out


def load_decimals_cache(path: str = DEFAULT_CACHE_PATH) -> Dict[str, int]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with p.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return {}
        return {
            str(k).lower(): int(v)
            for k, v in raw.items()
            if is_valid_eth_address(str(k))
        }
    except Exception as exc:
        log.debug("decimals cache load failed: %s", exc)
        return {}


def save_decimals_cache(cache: Dict[str, int], path: str = DEFAULT_CACHE_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + f".tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({k: int(v) for k, v in sorted(cache.items())}, fh, separators=(",", ":"))
    try:
        os.replace(tmp, str(p))
    except OSError:
        import time as _time

        _time.sleep(0.3)
        os.replace(tmp, str(p))


def fetch_on_chain_decimals(w3: Any, address: str) -> Optional[int]:
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


def resolve_decimals_for_address(
    address: str,
    *,
    cfg: Optional[M8_1Config] = None,
    override: object = None,
    symbol: str = "",
    cache: Optional[Dict[str, int]] = None,
    w3: Any = None,
    persist_cache: bool = True,
) -> Optional[int]:
    """Return decimals for *address*, or None when unknown."""
    if not is_valid_eth_address(address):
        return None

    addr_l = address.lower()

    # Address truth wins over polluted inventory overrides (quote-size gate).
    if addr_l in _KNOWN_ADDRESS_DECIMALS:
        return _KNOWN_ADDRESS_DECIMALS[addr_l]

    if cfg is not None:
        for tc in cfg.tokens.values():
            if (tc.address or "").lower() == addr_l:
                return int(tc.decimals)
        sym = (symbol or "").strip()
        if sym and not is_truncated_hex_token(sym):
            tc = cfg.tokens.get(sym)
            if tc is not None and (tc.address or "").lower() == addr_l:
                return int(tc.decimals)

    if override is not None:
        try:
            return int(override)
        except (TypeError, ValueError):
            pass

    if cache is not None and addr_l in cache:
        return int(cache[addr_l])

    # On-chain last — may populate cache
    if w3 is not None:
        dec = fetch_on_chain_decimals(w3, addr_l)
        if dec is not None:
            if cache is not None:
                cache[addr_l] = dec
                if persist_cache:
                    try:
                        disk = load_decimals_cache()
                        disk[addr_l] = dec
                        save_decimals_cache(disk)
                    except Exception:
                        pass
            return dec

    return None


def enrich_route_decimals(
    route: Dict[str, Any],
    cfg: Optional[M8_1Config] = None,
    cache: Optional[Dict[str, int]] = None,
    w3: Any = None,
) -> Dict[str, Any]:
    """Set ``token0_decimals`` / ``token1_decimals`` on a bridge route dict."""
    for sym_key, addr_key, dec_key in (
        ("token0", "token0_addr", "token0_decimals"),
        ("token1", "token1_addr", "token1_decimals"),
    ):
        addr = route.get(addr_key) or ""
        if not is_valid_eth_address(addr):
            field_sym = route.get(sym_key) or ""
            if is_valid_eth_address(field_sym):
                addr = field_sym
        sym = str(route.get(sym_key) or "")
        dec = resolve_decimals_for_address(
            addr,
            cfg=cfg,
            override=route.get(dec_key),
            symbol=sym,
            cache=cache,
            w3=w3,
            persist_cache=False,
        )
        if dec is not None:
            route[dec_key] = dec
    return route
