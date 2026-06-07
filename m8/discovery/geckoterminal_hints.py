"""GeckoTerminal token→pools and new_pools hint fetchers.

``ClankerDiscoverySource`` (clanker_source.py) remains the Clanker/V4 new-pool
specialist; this module is the universal GeckoTerminal hint resolver.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from m8.discovery.clanker_source import GECKOTERMINAL_BASE_URL
from m8.discovery.pool_hints import PoolHint, normalize_dex_id, normalize_pool_identity

_DEFAULT_TIMEOUT_S = 12.0


def _get_json(url: str, *, timeout_s: float = _DEFAULT_TIMEOUT_S) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "arby-m8-hints/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _tok_addr_from_gecko_id(tok_id: str) -> str:
    parts = (tok_id or "").split("_")
    return parts[-1].lower() if parts else ""


def fetch_token_pool_hints(
    token_address: str,
    *,
    network: str = "base",
    chain: str = "base",
    page: int = 1,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> List[PoolHint]:
    """Token → pools via GeckoTerminal ``/tokens/{addr}/pools``."""
    addr = (token_address or "").lower().strip()
    if not addr.startswith("0x"):
        return []
    url = (
        f"{GECKOTERMINAL_BASE_URL}/networks/{network}/tokens/{addr}/pools"
        f"?page={page}"
    )
    try:
        data = _get_json(url, timeout_s=timeout_s)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return []

    hints: List[PoolHint] = []
    for item in data.get("data") or []:
        hint = _pool_item_to_hint(item, chain=chain, focus_token=addr, network=network)
        if hint:
            hints.append(hint)
    return hints


def fetch_new_pool_hints(
    *,
    network: str = "base",
    chain: str = "base",
    page: int = 1,
    dex_filter: Optional[str] = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> List[PoolHint]:
    """Network new_pools mode (all DEXes unless dex_filter set)."""
    url = f"{GECKOTERMINAL_BASE_URL}/networks/{network}/new_pools?page={page}"
    try:
        data = _get_json(url, timeout_s=timeout_s)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return []

    hints: List[PoolHint] = []
    for item in data.get("data") or []:
        hint = _pool_item_to_hint(item, chain=chain, focus_token="", network=network)
        if not hint:
            continue
        if dex_filter and hint.dex_id != dex_filter:
            raw_dex = (hint.raw or {}).get("gecko_dex_id", "")
            if raw_dex != dex_filter:
                continue
        hints.append(hint)
    return hints


def _pool_item_to_hint(
    item: Dict[str, Any],
    *,
    chain: str,
    focus_token: str,
    network: str,
) -> Optional[PoolHint]:
    attrs = item.get("attributes") or {}
    rels = item.get("relationships") or {}
    raw_dex = rels.get("dex", {}).get("data", {}).get("id", "")
    dex_id = normalize_dex_id("geckoterminal", raw_dex)
    if not dex_id:
        return None
    pool_addr = str(attrs.get("address") or "").lower()
    if not pool_addr:
        return None
    base_tok = rels.get("base_token", {}).get("data", {}) or {}
    quote_tok = rels.get("quote_token", {}).get("data", {}) or {}
    t0 = _tok_addr_from_gecko_id(base_tok.get("id", ""))
    t1 = _tok_addr_from_gecko_id(quote_tok.get("id", ""))
    if not t0 or not t1:
        return None
    vol = attrs.get("volume_usd") or {}
    vol_h24 = _safe_float(vol.get("h24") if isinstance(vol, dict) else vol)
    liq = _safe_float(attrs.get("reserve_in_usd"))
    hint = PoolHint(
        source="geckoterminal",
        chain=chain,
        dex_id=dex_id,
        pool_address=pool_addr,
        token0_addr=t0,
        token1_addr=t1,
        created_at=attrs.get("pool_created_at"),
        liquidity_usd=liq,
        volume_24h=vol_h24,
        confidence=0.5,
        raw={"gecko_dex_id": raw_dex, "network": network, "item": item},
        focus_token=focus_token,
        fee=_safe_int(attrs.get("fee_tier")),
        tick_spacing=_safe_int(attrs.get("tick_spacing")),
    )
    return normalize_pool_identity(hint)


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
