"""CoinGecko Onchain API — token pools / new pools (hint-only)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from m8.discovery.pool_hints import PoolHint, normalize_dex_id, normalize_pool_identity
from m8.discovery.radar_layer import stamp_radar_reason

_DEFAULT_TIMEOUT_S = 15.0
_ONCHAIN_BASE = "https://pro-api.coingecko.com/api/v3/onchain"

_NETWORK_MAP = {"base": "base"}


def _api_key() -> Optional[str]:
    key = os.environ.get("CG_DEMO_API_KEY", "").strip()
    if key:
        return key
    try:
        from m9.graph_arb.token_price_fetcher import _get_coingecko_api_key

        return _get_coingecko_api_key()
    except Exception:
        return None


def _get_json(path: str, *, timeout_s: float = _DEFAULT_TIMEOUT_S) -> Dict[str, Any]:
    key = _api_key()
    if not key:
        return {}
    url = f"{_ONCHAIN_BASE}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "arby-m8-radar/1.0",
            "x-cg-pro-api-key": key,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _pool_row_to_hint(
    row: Dict[str, Any],
    *,
    chain: str,
    network: str,
    focus_token: str,
    discovery: str,
) -> Optional[PoolHint]:
    attrs = row.get("attributes") or row
    addr = str(attrs.get("address") or row.get("address") or "").lower()
    if not addr:
        return None
    rel = row.get("relationships") or {}
    dex_raw = (
        rel.get("dex", {}).get("data", {}).get("id")
        or attrs.get("dex_id")
        or attrs.get("dex")
        or ""
    )
    dex_id = normalize_dex_id("coingecko_onchain", str(dex_raw))
    if not dex_id:
        dex_id = str(dex_raw or "unknown").replace("-", "_")
    t0 = str(attrs.get("base_token_address") or "").lower()
    t1 = str(attrs.get("quote_token_address") or "").lower()
    if not t0 or not t1:
        tokens = attrs.get("tokens") or []
        if len(tokens) >= 2:
            t0 = str(tokens[0].get("address") or "").lower()
            t1 = str(tokens[1].get("address") or "").lower()
    if not t0 or not t1:
        return None
    liq = _safe_float(attrs.get("reserve_in_usd") or attrs.get("liquidity_usd"))
    vol = _safe_float(attrs.get("volume_usd") or attrs.get("volume_24h"))
    hint = PoolHint(
        source="coingecko_onchain",
        chain=chain,
        dex_id=dex_id,
        pool_address=addr,
        token0_addr=t0,
        token1_addr=t1,
        created_at=attrs.get("pool_created_at"),
        liquidity_usd=liq,
        volume_24h=vol,
        confidence=0.52,
        raw={"discovery": discovery, "network": network, "row": row},
        focus_token=focus_token,
    )
    return stamp_radar_reason(normalize_pool_identity(hint))


def fetch_token_pool_hints(
    token_address: str,
    *,
    network: str = "base",
    chain: str = "base",
    page: int = 1,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> List[PoolHint]:
    """``/networks/{network}/tokens/{address}/pools``."""
    addr = (token_address or "").lower().strip()
    if not addr.startswith("0x") or not _api_key():
        return []
    net = _NETWORK_MAP.get(network, network)
    path = f"/networks/{net}/tokens/{addr}/pools?page={page}"
    try:
        data = _get_json(path, timeout_s=timeout_s)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return []
    hints: List[PoolHint] = []
    for row in data.get("data") or data.get("pools") or []:
        h = _pool_row_to_hint(
            row,
            chain=chain,
            network=net,
            focus_token=addr,
            discovery="token_pools",
        )
        if h:
            hints.append(h)
    return hints


def fetch_new_pools_hints(
    *,
    network: str = "base",
    chain: str = "base",
    page: int = 1,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> List[PoolHint]:
    """``/networks/{network}/new_pools``."""
    if not _api_key():
        return []
    net = _NETWORK_MAP.get(network, network)
    path = f"/networks/{net}/new_pools?page={page}"
    try:
        data = _get_json(path, timeout_s=timeout_s)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return []
    hints: List[PoolHint] = []
    for row in data.get("data") or data.get("pools") or []:
        h = _pool_row_to_hint(
            row,
            chain=chain,
            network=net,
            focus_token="",
            discovery="new_pools",
        )
        if h:
            hints.append(h)
    return hints


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
