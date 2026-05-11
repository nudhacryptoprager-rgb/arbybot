"""E1.76 — GeckoTerminal scout.

Lightweight scouting layer that ranks Base pools by 24h volume.
GeckoTerminal exposes a public "top pools by network" endpoint
(``/networks/{network}/pools``) returning ``volume_usd.h24``,
``reserve_in_usd``, ``base_token``, ``quote_token`` per pool.

Pure parsing (``parse_geckoterminal_pools``) is unit-tested.  Network
fetch is opt-in (``ARBY_GECKO_SCOUT_ENABLE=1``) and fail-soft — on any
HTTP / parse failure we return an empty list.

Output rows are intentionally compatible with
``m7.scouts.tvl_scout.PoolTVLEntry`` (``chain``, ``project``,
``pool_address``, ``symbol``, ``tvl_usd``, ``volume_24h_usd``) so the
two scouts can be merged trivially upstream.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "GeckoPoolEntry",
    "parse_geckoterminal_pools",
    "rank_pools_by_volume",
    "fetch_top_pools",
]


@dataclass(frozen=True)
class GeckoPoolEntry:
    chain: str
    project: str
    pool_address: str
    symbol: str
    tvl_usd: float
    volume_24h_usd: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):
        return default
    return f


def parse_geckoterminal_pools(
    payload: Any,
    chain: str = "base",
) -> List[GeckoPoolEntry]:
    """Parse a GeckoTerminal v2 ``/networks/{net}/pools`` JSON payload.

    Expected shape::

      {
        "data": [
          {
            "id": "base_0xabc...",
            "type": "pool",
            "attributes": {
              "name": "WETH / USDC",
              "address": "0xabc...",
              "reserve_in_usd": "12345.6",
              "volume_usd": {"h24": "987.6"},
              "pool_created_at": "...",
            },
            "relationships": {
              "dex": {"data": {"id": "uniswap_v3_base"}},
              "base_token": {"data": {"id": "base_0x...weth"}},
              "quote_token": {"data": {"id": "base_0x...usdc"}}
            }
          },
          ...
        ]
      }

    Fail-soft: missing/malformed entries are skipped.  Never raises.
    """
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    out: List[GeckoPoolEntry] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        attrs = r.get("attributes") if isinstance(r.get("attributes"), dict) else {}
        rel = r.get("relationships") if isinstance(r.get("relationships"), dict) else {}
        addr = attrs.get("address") or ""
        if not isinstance(addr, str) or not addr:
            continue
        name = str(attrs.get("name") or "")
        # GeckoTerminal uses " / " — normalise to "-".
        # Strip trailing fee-tier suffix (e.g. " 0.05%", " 0.3%", " 1%") from
        # pool name before building the symbol so the fee tier does not leak
        # into token symbols like "WETH0.05%".
        _name_clean = re.sub(r"\s+\d+(?:\.\d+)?%\s*$", "", name)
        symbol = _name_clean.replace(" / ", "-").replace(" ", "")
        tvl = _safe_float(attrs.get("reserve_in_usd"))
        vol_block = attrs.get("volume_usd") or {}
        if isinstance(vol_block, dict):
            vol = _safe_float(vol_block.get("h24"))
        else:
            vol = 0.0
        dex_id = ""
        try:
            dex_id = (
                rel.get("dex", {}).get("data", {}).get("id", "")
                if isinstance(rel.get("dex"), dict)
                else ""
            )
        except Exception:
            dex_id = ""
        project = str(dex_id or "unknown").lower()
        out.append(
            GeckoPoolEntry(
                chain=chain,
                project=project,
                pool_address=str(addr).lower(),
                symbol=symbol,
                tvl_usd=tvl,
                volume_24h_usd=vol,
            )
        )
    return out


def rank_pools_by_volume(
    pools: Iterable[GeckoPoolEntry],
    *,
    min_volume_usd: float = 0.0,
    top_n: int = 50,
) -> List[GeckoPoolEntry]:
    """Sort pools by 24h volume desc, optionally clamp to ``top_n``."""
    rows = [p for p in (pools or []) if p.volume_24h_usd >= min_volume_usd]
    rows.sort(key=lambda p: p.volume_24h_usd, reverse=True)
    if top_n and top_n > 0:
        return rows[:top_n]
    return rows


def fetch_top_pools(
    *,
    network: str = "base",
    timeout_s: float = 5.0,
    page: int = 1,
) -> List[GeckoPoolEntry]:
    """Opt-in HTTP fetch.  Returns ``[]`` on any error.

    Disabled unless ``ARBY_GECKO_SCOUT_ENABLE=1`` is set so that unit
    tests / offline soaks never touch the network.  Uses ``urllib`` to
    avoid a hard dependency on aiohttp/httpx; the scout is a periodic
    background task so latency is acceptable.
    """
    if os.environ.get("ARBY_GECKO_SCOUT_ENABLE", "0") != "1":
        return []
    try:
        import json
        import urllib.request

        url = (
            f"https://api.geckoterminal.com/api/v2/networks/{network}/pools"
            f"?page={int(max(1, page))}"
        )
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": "arby-scout/1"}
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (URL is constant)
            body = resp.read().decode("utf-8")
        return parse_geckoterminal_pools(json.loads(body), chain=network)
    except Exception:
        return []
