"""Address-first token decimals resolver (quote-size truth gate).

Resolution order:
  1. Route/inventory override (``token0_decimals`` / ``token1_decimals``)
  2. Static known-address map (Base anchors)
  3. Config tokens matched by lowercase address
  4. Config tokens matched by canonical symbol (not truncated hex)
  5. Hint metadata (external hints — not economics-grade alone)
  6. Runtime cache (``data/tmp/m9_token_decimals_cache.json``)
  7. On-chain ``decimals()`` when *w3* is provided

Never silently default to 18 for address-like or truncated-hex labels in production.
``topology_probe`` may use ``topology_probe_fallback`` (18) for graph structure only.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.token_identity import (
    fetch_on_chain_decimals,
    is_truncated_hex_token,
    is_valid_eth_address,
)
from m8_1.stable_anchor.config_loader import M8_1Config

log = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = "data/tmp/m9_token_decimals_cache.json"

DECIMALS_SOURCE_ERC20 = "erc20_call"
DECIMALS_SOURCE_CORE_CONFIG = "core_config"
DECIMALS_SOURCE_HINT = "hint_metadata"
DECIMALS_SOURCE_ROUTE_OVERRIDE = "route_override"
DECIMALS_SOURCE_KNOWN_ADDRESS = "known_address"
DECIMALS_SOURCE_CACHE = "cache"
DECIMALS_SOURCE_FALLBACK_UNKNOWN = "fallback_unknown"
DECIMALS_SOURCE_TOPOLOGY_PROBE = "topology_probe_fallback"

M8_3_DECIMALS_SOURCE_PREFIX = "m8_3_"

DECIMALS_STATUS_UNKNOWN_DIAGNOSTIC = "UNKNOWN_DIAGNOSTIC"
TOPOLOGY_PROBE_DECIMALS_FALLBACK = 18

def _known_address_decimals(chain: str = "base") -> Dict[str, int]:
    from core.token_identity import address_decimals_map

    return address_decimals_map(chain)


def is_strict_token_address(addr: object) -> bool:
    """Reject truncated hex stored as token address (e.g. ``0x420000``)."""
    return is_valid_eth_address(addr)


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


def _hint_decimals_for_route(route: Dict[str, Any], dec_key: str) -> Optional[int]:
    hint_key = dec_key.replace("_decimals", "_decimals_hint")
    raw = route.get(hint_key)
    if raw is None:
        meta = route.get("hint_metadata") or {}
        if isinstance(meta, dict):
            raw = meta.get(dec_key) or meta.get(hint_key)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def resolve_decimals_with_source(
    address: str,
    *,
    cfg: Optional[M8_1Config] = None,
    override: object = None,
    symbol: str = "",
    cache: Optional[Dict[str, int]] = None,
    w3: Any = None,
    persist_cache: bool = True,
    route: Optional[Dict[str, Any]] = None,
    dec_key: str = "token0_decimals",
    topology_probe: bool = False,
) -> Tuple[Optional[int], str]:
    """Return (decimals, source_tag). Source is ``fallback_unknown`` when unresolved."""
    if not is_valid_eth_address(address):
        from core.token_identity import (
            build_route_address_prefix_index,
            resolve_truncated_address,
        )

        route_index = None
        if route is not None:
            route_index = build_route_address_prefix_index(
                [route], chain=str(route.get("chain") or "base")
            )
        resolved = resolve_truncated_address(
            str(address or symbol), route_index=route_index
        )
        if resolved:
            address = resolved
        elif topology_probe:
            return TOPOLOGY_PROBE_DECIMALS_FALLBACK, DECIMALS_SOURCE_TOPOLOGY_PROBE
        else:
            return None, DECIMALS_SOURCE_FALLBACK_UNKNOWN

    addr_l = address.lower()

    known = _known_address_decimals()
    if addr_l in known:
        return known[addr_l], DECIMALS_SOURCE_KNOWN_ADDRESS

    if cfg is not None:
        for tc in cfg.tokens.values():
            if (tc.address or "").lower() == addr_l:
                return int(tc.decimals), DECIMALS_SOURCE_CORE_CONFIG
        sym = (symbol or "").strip()
        if sym and not is_truncated_hex_token(sym):
            tc = cfg.tokens.get(sym)
            if tc is not None and (tc.address or "").lower() == addr_l:
                return int(tc.decimals), DECIMALS_SOURCE_CORE_CONFIG

    if override is not None:
        try:
            return int(override), DECIMALS_SOURCE_ROUTE_OVERRIDE
        except (TypeError, ValueError):
            pass

    if route is not None:
        hint = _hint_decimals_for_route(route, dec_key)
        if hint is not None:
            return hint, DECIMALS_SOURCE_HINT

    if cache is not None and addr_l in cache:
        return int(cache[addr_l]), DECIMALS_SOURCE_CACHE

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
            return dec, DECIMALS_SOURCE_ERC20

    if topology_probe:
        return TOPOLOGY_PROBE_DECIMALS_FALLBACK, DECIMALS_SOURCE_TOPOLOGY_PROBE

    return None, DECIMALS_SOURCE_FALLBACK_UNKNOWN


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
    dec, _src = resolve_decimals_with_source(
        address,
        cfg=cfg,
        override=override,
        symbol=symbol,
        cache=cache,
        w3=w3,
        persist_cache=persist_cache,
    )
    return dec


def decimals_skip_extra(entry: Dict[str, Any], w3: Any = None) -> Dict[str, Any]:
    """Telemetry payload for decimals-related edge-build skips."""
    extra = {
        "token0_addr": entry.get("token0_addr") or entry.get("token0"),
        "token1_addr": entry.get("token1_addr") or entry.get("token1"),
        "token0_decimals": entry.get("token0_decimals"),
        "token1_decimals": entry.get("token1_decimals"),
        "token0_decimals_source": entry.get("token0_decimals_source"),
        "token1_decimals_source": entry.get("token1_decimals_source"),
        "decimals_status": entry.get("decimals_status"),
    }
    if w3 is not None:
        from m9.graph_arb.token_metadata import probe_erc20_metadata

        for leg, key in (("token0", "token0_addr"), ("token1", "token1_addr")):
            addr = extra.get(key)
            if addr:
                extra[f"{leg}_erc20_probe"] = probe_erc20_metadata(w3, str(addr))
    return extra


def is_m8_3_decimals_source(source: Optional[str]) -> bool:
    return str(source or "").startswith(M8_3_DECIMALS_SOURCE_PREFIX)


def enrich_route_decimals(
    route: Dict[str, Any],
    cfg: Optional[M8_1Config] = None,
    cache: Optional[Dict[str, int]] = None,
    w3: Any = None,
    *,
    topology_probe: bool = False,
    persist_cache: bool = False,
    missing_only: bool = False,
    preserve_m8_3: bool = True,
) -> Dict[str, Any]:
    """Set decimals + ``token*_decimals_source`` on a bridge route dict."""
    sources: List[str] = []
    for sym_key, addr_key, dec_key in (
        ("token0", "token0_addr", "token0_decimals"),
        ("token1", "token1_addr", "token1_decimals"),
    ):
        src_key = dec_key.replace("_decimals", "_decimals_source")
        if preserve_m8_3 and is_m8_3_decimals_source(route.get(src_key)):
            if route.get(dec_key) is not None:
                sources.append(str(route.get(src_key)))
            continue
        if missing_only and route.get(dec_key) is not None:
            if route.get(src_key):
                sources.append(str(route.get(src_key)))
            continue
        addr = route.get(addr_key) or ""
        if not is_valid_eth_address(addr):
            field_sym = route.get(sym_key) or ""
            if is_valid_eth_address(field_sym):
                addr = field_sym
        sym = str(route.get(sym_key) or "")
        dec, src = resolve_decimals_with_source(
            addr,
            cfg=cfg,
            override=route.get(dec_key),
            symbol=sym,
            cache=cache,
            w3=w3,
            persist_cache=persist_cache,
            route=route,
            dec_key=dec_key,
            topology_probe=topology_probe,
        )
        src_key = dec_key.replace("_decimals", "_decimals_source")
        route[src_key] = src
        if dec is not None:
            route[dec_key] = dec
            sources.append(src)
    if any(s in (DECIMALS_SOURCE_TOPOLOGY_PROBE, DECIMALS_SOURCE_FALLBACK_UNKNOWN) for s in sources):
        route["decimals_status"] = DECIMALS_STATUS_UNKNOWN_DIAGNOSTIC
    elif route.get("token0_decimals") is not None and route.get("token1_decimals") is not None:
        route["decimals_status"] = "resolved"
    return route


def enrich_routes_decimals(
    routes: List[Dict[str, Any]],
    *,
    cfg: Optional[M8_1Config] = None,
    cache: Optional[Dict[str, int]] = None,
    w3: Any = None,
    topology_probe: bool = False,
    persist_cache: bool = True,
    missing_only: bool = False,
    preserve_m8_3: bool = True,
) -> Dict[str, int]:
    """Enrich all routes; return histogram of decimals sources used."""
    hist: Dict[str, int] = {}
    if cache is None:
        cache = load_decimals_cache()
    for route in routes:
        enrich_route_decimals(
            route,
            cfg=cfg,
            cache=cache,
            w3=w3,
            topology_probe=topology_probe,
            persist_cache=persist_cache,
            missing_only=missing_only,
            preserve_m8_3=preserve_m8_3,
        )
        for key in ("token0_decimals_source", "token1_decimals_source"):
            src = route.get(key)
            if src:
                hist[str(src)] = hist.get(str(src), 0) + 1
    if persist_cache and cache:
        try:
            disk = load_decimals_cache()
            disk.update(cache)
            save_decimals_cache(disk)
        except Exception:
            pass
    return hist


def is_economics_grade_decimals_source(source: Optional[str]) -> bool:
    """Economics-grade decimals: core/on-chain or M8.3-verified provenance."""
    if is_m8_3_decimals_source(source):
        inner = str(source)[len(M8_3_DECIMALS_SOURCE_PREFIX) :]
        return inner in (
            DECIMALS_SOURCE_ERC20,
            DECIMALS_SOURCE_CORE_CONFIG,
            DECIMALS_SOURCE_KNOWN_ADDRESS,
            DECIMALS_SOURCE_ROUTE_OVERRIDE,
            "m8_sniper_erc20",
            "registry_cache",
            "core_config",
            "known_address",
            "erc20_call",
        )
    return source in (
        DECIMALS_SOURCE_ERC20,
        DECIMALS_SOURCE_CORE_CONFIG,
        DECIMALS_SOURCE_KNOWN_ADDRESS,
        DECIMALS_SOURCE_ROUTE_OVERRIDE,
    )
