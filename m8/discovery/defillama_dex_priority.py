"""DeFiLlama DEX volume feed — scan-order weights only, not pool admission."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

_log = logging.getLogger(__name__)

_DEFILLAMA_DEX_OVERVIEW = "https://api.llama.fi/overview/dexs/{chain}"
_DEFAULT_TIMEOUT_S = 12.0

# Internal dex_id hints from DeFiLlama protocol slugs (priority weights only).
_SLUG_TO_DEX_ID: Dict[str, str] = {
    "uniswap": "uniswap_v3",
    "uniswap-v3": "uniswap_v3",
    "uniswap-v2": "uniswap_v2",
    "uniswap-v4": "uniswap_v4",
    "aerodrome": "aerodrome",
    "curve": "curve_stable",
    "balancer": "balancer_vault",
    "maverick": "maverick_v2",
    "sushiswap": "sushiswap_v2",
    "pancakeswap": "pancakeswap_v3",
}


def fetch_dex_priority_weights(
    chain: str = "base",
    *,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Dict[str, Any]:
    """Return normalized DEX weights for scan order; never used for pool admission."""
    url = _DEFILLAMA_DEX_OVERVIEW.format(chain=chain)
    try:
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "arby-m8-radar/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
        _log.debug("defillama dex priority fetch failed: %s", exc)
        return {
            "source": "defillama",
            "chain": chain,
            "status": "FETCH_FAILED",
            "dex_scan_weights": {},
            "note": "weights_for_scan_order_only_not_pool_admission",
        }

    protocols = data.get("protocols") or data.get("data") or []
    weights: Dict[str, float] = {}
    total_vol = 0.0
    rows: list[tuple[str, float]] = []
    for row in protocols:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or row.get("name") or "").lower()
        vol = float(row.get("total24h") or row.get("volume24h") or 0)
        dex_id = _SLUG_TO_DEX_ID.get(slug) or slug.replace("-", "_")
        if vol > 0:
            rows.append((dex_id, vol))
            total_vol += vol
    if total_vol > 0:
        for dex_id, vol in rows:
            weights[dex_id] = round(vol / total_vol, 6)
    return {
        "source": "defillama",
        "chain": chain,
        "status": "OK" if weights else "EMPTY",
        "dex_scan_weights": weights,
        "protocols_seen": len(protocols),
        "note": "weights_for_scan_order_only_not_pool_admission",
    }
