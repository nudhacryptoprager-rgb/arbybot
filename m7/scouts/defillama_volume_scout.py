"""E1.76 — DefiLlama volume scout.

The existing TVL scout (``m7.scouts.tvl_scout``) ranks Base pools by
DefiLlama yields TVL.  This module adds a *volume* layer using
DefiLlama's protocol/dex volume endpoint to identify chains and DEXes
with real activity, so the cold scanner can deprioritise dead venues.

Pure parsing functions (``parse_dex_volumes``,
``rank_dexes_by_24h_volume``) are unit-tested.  Network fetch is
opt-in (``ARBY_DEFILLAMA_VOLUME_SCOUT_ENABLE=1``) and fail-soft.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "DexVolumeEntry",
    "parse_dex_volumes",
    "rank_dexes_by_24h_volume",
    "fetch_dex_volumes",
]


@dataclass(frozen=True)
class DexVolumeEntry:
    chain: str
    project: str          # e.g. "uniswap-v3"
    volume_24h_usd: float
    volume_7d_usd: float = 0.0

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


def parse_dex_volumes(
    payload: Any,
    chain_filter: Optional[str] = "Base",
) -> List[DexVolumeEntry]:
    """Parse DefiLlama dex-volume payload.

    Tolerant to two common shapes:

      A) ``{"protocols": [{"name", "chains": ["Base"], "total24h",
            "total7d"}]}``
      B) ``{"dexes": [{"name", "chain", "volume24hUSD",
            "volume7dUSD"}]}``

    Fail-soft on schema drift.
    """
    if not isinstance(payload, dict):
        return []
    rows = payload.get("protocols")
    if not isinstance(rows, list):
        rows = payload.get("dexes")
    if not isinstance(rows, list):
        return []
    out: List[DexVolumeEntry] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or r.get("project") or "").lower().strip()
        if not name:
            continue
        chain = r.get("chain")
        if chain is None and isinstance(r.get("chains"), list):
            chains = [str(c) for c in r["chains"]]
            if chain_filter and chain_filter not in chains:
                continue
            chain = chain_filter or (chains[0] if chains else "")
        elif chain_filter and chain and str(chain) != chain_filter:
            continue
        v24 = _safe_float(r.get("total24h"))
        if v24 == 0.0:
            v24 = _safe_float(r.get("volume24hUSD") or r.get("volume_24h_usd"))
        v7 = _safe_float(r.get("total7d"))
        if v7 == 0.0:
            v7 = _safe_float(r.get("volume7dUSD") or r.get("volume_7d_usd"))
        out.append(
            DexVolumeEntry(
                chain=str(chain or chain_filter or ""),
                project=name,
                volume_24h_usd=v24,
                volume_7d_usd=v7,
            )
        )
    return out


def rank_dexes_by_24h_volume(
    rows: Iterable[DexVolumeEntry],
    *,
    min_volume_usd: float = 0.0,
    top_n: int = 20,
) -> List[DexVolumeEntry]:
    out = [r for r in (rows or []) if r.volume_24h_usd >= min_volume_usd]
    out.sort(key=lambda r: r.volume_24h_usd, reverse=True)
    if top_n and top_n > 0:
        return out[:top_n]
    return out


def fetch_dex_volumes(
    *,
    chain: str = "Base",
    timeout_s: float = 5.0,
) -> List[DexVolumeEntry]:
    """Opt-in HTTP fetch.  Returns ``[]`` on any error or when disabled."""
    if os.environ.get("ARBY_DEFILLAMA_VOLUME_SCOUT_ENABLE", "0") != "1":
        return []
    try:
        import json
        import urllib.request

        url = (
            "https://api.llama.fi/overview/dexs"
            f"/{chain}?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"
        )
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": "arby-scout/1"}
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            body = resp.read().decode("utf-8")
        return parse_dex_volumes(json.loads(body), chain_filter=chain)
    except Exception:
        return []
