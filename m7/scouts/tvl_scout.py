"""E1.69 Wave D — TVL scout.

Periodic background scanner that ranks Base AMM pools by TVL/volume to
surface *production-size* candidates the event-driven hot lane would
otherwise miss.  Network I/O is fail-soft: if DefiLlama is unreachable
the scout returns an empty list (caller falls back to existing
discovery).  Designed to be invoked once per hour by the runtime
supervisor.

The scout writes a rolling artifact ``m7_tvl_scout_latest.json`` whose
schema mirrors `discovery.runtime` rolling artifacts so consumers
(orderflow, bridge) can ingest it without bespoke loaders.

Pure logic (`rank_pools_by_tvl`, `select_production_pools`,
`parse_defillama_pools`) is unit-tested.  The actual HTTP fetch is
opt-in (``ARBY_TVL_SCOUT_ENABLE=1``) and fully isolated.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class PoolTVLEntry:
    """A pool surfaced by the TVL scout."""

    chain: str
    project: str           # "uniswap-v3", "aerodrome-v1", "aerodrome-slipstream"
    pool_address: str
    symbol: str            # e.g. "WETH-USDC"
    tvl_usd: float
    volume_24h_usd: float = 0.0

    @property
    def production_grade(self) -> bool:
        return self.tvl_usd >= 50_000.0

    def to_dict(self) -> dict:
        return asdict(self)


def parse_defillama_pools(payload: dict, chain: str = "Base") -> List[PoolTVLEntry]:
    """Parse the DefiLlama yields-v1 response into PoolTVLEntry rows.

    DefiLlama yields response shape:
        {"data": [{"chain": "Base", "project": "uniswap-v3",
                   "symbol": "WETH-USDC", "pool": "0x...",
                   "tvlUsd": 12345.0, "volumeUsd24h": 99.0, ...}, ...]}

    Fail-soft: missing keys yield empty list, never raises.
    """
    if not payload or not isinstance(payload, dict):
        return []
    rows = payload.get("data") or []
    if not isinstance(rows, list):
        return []
    out: List[PoolTVLEntry] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if (r.get("chain") or "").lower() != chain.lower():
            continue
        try:
            tvl = float(r.get("tvlUsd") or 0.0)
        except (TypeError, ValueError):
            continue
        if tvl <= 0:
            continue
        addr = (r.get("pool") or "").strip()
        if not addr:
            continue
        try:
            vol = float(r.get("volumeUsd24h") or 0.0)
        except (TypeError, ValueError):
            vol = 0.0
        out.append(PoolTVLEntry(
            chain=chain.lower(),
            project=(r.get("project") or "unknown").strip().lower(),
            pool_address=addr.lower(),
            symbol=(r.get("symbol") or "").upper(),
            tvl_usd=tvl,
            volume_24h_usd=vol,
        ))
    return out


def rank_pools_by_tvl(pools: Iterable[PoolTVLEntry]) -> List[PoolTVLEntry]:
    """Sort pools by ``tvl_usd`` descending, stable."""
    return sorted(pools, key=lambda p: p.tvl_usd, reverse=True)


def select_production_pools(
    pools: Iterable[PoolTVLEntry],
    *,
    top_n: int = 50,
    min_tvl_usd: float = 50_000.0,
    project_whitelist: Optional[Sequence[str]] = None,
) -> List[PoolTVLEntry]:
    """Production-grade subset: TVL >= min_tvl_usd, ranked, top_n cap.

    ``project_whitelist`` defaults to known Base AMM projects.  Use
    ``None`` (default) to keep the full whitelist; pass an explicit
    sequence to restrict further.
    """
    whitelist = {
        p.lower() for p in (project_whitelist or (
            "uniswap-v3", "uniswap-v4", "aerodrome-v1",
            "aerodrome-slipstream", "sushiswap", "pancakeswap-amm-v3",
        ))
    }
    filtered = [
        p for p in pools
        if p.tvl_usd >= min_tvl_usd and (p.project in whitelist if whitelist else True)
    ]
    return rank_pools_by_tvl(filtered)[:top_n]


# ---------------------------------------------------------------------------
# Optional fetcher (network I/O — opt-in via env)
# ---------------------------------------------------------------------------


def fetch_defillama_pools(timeout_s: float = 8.0) -> List[PoolTVLEntry]:
    """Fail-soft fetch from DefiLlama yields endpoint.

    Returns [] on any error so the caller can fall back to existing
    discovery.  Uses ``httpx`` (already a project dep) when available;
    otherwise returns [].
    """
    import os
    if os.environ.get("ARBY_TVL_SCOUT_ENABLE", "0") != "1":
        return []
    try:
        import httpx  # type: ignore
    except Exception:
        return []
    url = "https://yields.llama.fi/pools"
    try:
        resp = httpx.get(url, timeout=timeout_s)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    return parse_defillama_pools(data, chain="Base")
