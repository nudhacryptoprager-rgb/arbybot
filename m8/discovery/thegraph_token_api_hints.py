"""The Graph Token API (Pinax) pool hints for watchlist tokens."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from m8.discovery.pool_hints import PoolHint, normalize_dex_id

PINAX_API_BASE = "https://api.pinax.network"
_DEFAULT_TIMEOUT_S = 15.0
_DEFAULT_PROTOCOLS = (
    "uniswap_v2",
    "uniswap_v3",
    "uniswap_v4",
    "curvefi",
    "balancer",
    "aerodrome",
)


def _api_key() -> str:
    return (
        os.environ.get("GRAPH_API_KEY", "").strip()
        or os.environ.get("THEGRAPH_API_KEY", "").strip()
    )


def _get_json(url: str, *, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "arby-m8-hints/1.0",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(req, timeout=_DEFAULT_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _network_id(chain: str) -> str:
    return {"base": "base", "ethereum": "mainnet"}.get(chain, chain)


def _pool_row_to_hint(row: Dict[str, Any], *, chain: str, focus_token: str) -> Optional[PoolHint]:
    protocol = str(row.get("protocol") or row.get("dex") or "").lower()
    dex_id = normalize_dex_id("thegraph_token_api", protocol) or protocol
    if not dex_id:
        return None
    pool_addr = str(
        row.get("pool")
        or row.get("pool_address")
        or row.get("id")
        or ""
    ).lower()
    t0 = str(row.get("input_token") or row.get("token0") or row.get("token0_address") or "").lower()
    t1 = str(row.get("output_token") or row.get("token1") or row.get("token1_address") or "").lower()
    if not pool_addr or not t0 or not t1:
        return None
    liq = row.get("reserve_usd") or row.get("tvl_usd") or row.get("liquidity_usd")
    try:
        liq_f = float(liq) if liq is not None else None
    except (TypeError, ValueError):
        liq_f = None
    return PoolHint(
        source="thegraph_token_api",
        chain=chain,
        dex_id=dex_id,
        pool_address=pool_addr,
        token0_addr=t0,
        token1_addr=t1,
        created_at=row.get("created_at") or row.get("pool_created_at"),
        liquidity_usd=liq_f,
        volume_24h=None,
        confidence=0.65,
        raw={"protocol": protocol, "row": row},
        focus_token=focus_token.lower(),
    )


def fetch_token_hints(
    token_address: str,
    *,
    chain: str = "base",
    max_pools: int = 25,
    protocols: Optional[List[str]] = None,
) -> List[PoolHint]:
    """Query Pinax Token API pools for a token (hint-only)."""
    addr = (token_address or "").lower().strip()
    if not addr.startswith("0x"):
        return []
    api_key = _api_key()
    if not api_key:
        return []

    network = _network_id(chain)
    query_protocols = protocols or list(_DEFAULT_PROTOCOLS)
    hints: List[PoolHint] = []
    headers = {"Authorization": f"Bearer {api_key}"}

    for proto in query_protocols:
        url = (
            f"{PINAX_API_BASE}/v1/evm/pools?network={network}"
            f"&input_token={addr}&protocol={proto}&limit={max_pools}"
        )
        try:
            data = _get_json(url, headers=headers)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
            continue
        rows = data.get("data") or []
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            if not isinstance(row, dict):
                continue
            hint = _pool_row_to_hint(row, chain=chain, focus_token=addr)
            if hint:
                hints.append(hint)
    return hints
