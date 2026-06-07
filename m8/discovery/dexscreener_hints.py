"""DexScreener token → pool hints (hint-only, no on-chain truth)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from m8.discovery.pool_hints import PoolHint, normalize_dex_id

DEXSCREENER_BASE = "https://api.dexscreener.com/latest/dex/tokens"
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


def fetch_token_hints(
    token_address: str,
    *,
    chain: str = "base",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> List[PoolHint]:
    """Fetch pairs for *token_address* from DexScreener API."""
    addr = (token_address or "").lower().strip()
    if not addr.startswith("0x"):
        return []
    url = f"{DEXSCREENER_BASE}/{addr}"
    try:
        data = _get_json(url, timeout_s=timeout_s)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return []

    pairs = data.get("pairs") or []
    hints: List[PoolHint] = []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        hint = _pair_to_hint(pair, chain=chain, focus_token=addr)
        if hint:
            hints.append(hint)
    return hints


def _pair_to_hint(
    pair: Dict[str, Any],
    *,
    chain: str,
    focus_token: str,
) -> Optional[PoolHint]:
    chain_id = str(pair.get("chainId") or "").lower()
    if chain_id not in ("base", "8453"):
        return None
    raw_dex = str(pair.get("dexId") or "")
    dex_id = normalize_dex_id("dexscreener", raw_dex)
    if not dex_id:
        return None
    pool_addr = str(pair.get("pairAddress") or "").lower()
    if not pool_addr:
        return None
    base = pair.get("baseToken") or {}
    quote = pair.get("quoteToken") or {}
    t0 = str(base.get("address") or "").lower()
    t1 = str(quote.get("address") or "").lower()
    if not t0 or not t1:
        return None
    liq = pair.get("liquidity") or {}
    vol = pair.get("volume") or {}
    created_ms = pair.get("pairCreatedAt")
    created_at: Optional[str] = None
    if created_ms:
        try:
            from datetime import datetime, timezone

            created_at = datetime.fromtimestamp(
                int(created_ms) / 1000.0, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError, OSError):
            created_at = None
    liq_usd = _safe_float(liq.get("usd"))
    vol_h24 = _safe_float(vol.get("h24"))
    txns = pair.get("txns") or {}
    txns_h24 = txns.get("h24") if isinstance(txns, dict) else {}
    txn_count = 0
    if isinstance(txns_h24, dict):
        txn_count = int(txns_h24.get("buys") or 0) + int(txns_h24.get("sells") or 0)
    confidence = 0.55
    if liq_usd and liq_usd > 1000:
        confidence += 0.1
    if vol_h24 and vol_h24 > 100:
        confidence += 0.05
    if txn_count >= 10:
        confidence += 0.05
    return PoolHint(
        source="dexscreener",
        chain=chain,
        dex_id=dex_id,
        pool_address=pool_addr,
        token0_addr=t0,
        token1_addr=t1,
        created_at=created_at,
        liquidity_usd=liq_usd,
        volume_24h=vol_h24,
        confidence=min(1.0, confidence),
        raw={"dexId": raw_dex, "pair": pair, "txns_h24": txn_count},
        focus_token=focus_token,
    )


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
