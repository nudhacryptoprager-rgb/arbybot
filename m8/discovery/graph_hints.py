"""The Graph token-address pool hints for M8.2 watchlist tokens."""
from __future__ import annotations

from typing import List

from discovery.graph_client import GraphPool, query_pools_by_token
from m8.discovery.pool_hints import PoolHint, normalize_dex_id


def fetch_token_hints(
    token_address: str,
    *,
    chain: str = "base",
    max_pools: int = 20,
    protocols: List[str] | None = None,
) -> List[PoolHint]:
    """Convert Graph subgraph pools for a token into PoolHint rows."""
    addr = (token_address or "").lower().strip()
    if not addr.startswith("0x"):
        return []
    pools = query_pools_by_token(
        chain,
        addr,
        max_pools=max_pools,
        protocols=protocols,
    )
    hints: List[PoolHint] = []
    for p in pools:
        dex_id = normalize_dex_id("thegraph", p.protocol) or p.protocol
        confidence = 0.6
        if p.tvl_usd > 5000:
            confidence += 0.1
        hints.append(
            PoolHint(
                source="thegraph",
                chain=chain,
                dex_id=dex_id,
                pool_address=p.pool_address.lower(),
                token0_addr=p.token0_address.lower(),
                token1_addr=p.token1_address.lower(),
                created_at=None,
                liquidity_usd=p.tvl_usd,
                volume_24h=p.volume_usd_24h,
                confidence=min(1.0, confidence),
                raw={
                    "protocol": p.protocol,
                    "token0_symbol": p.token0_symbol,
                    "token1_symbol": p.token1_symbol,
                    "fee_tier": p.fee_tier,
                },
                focus_token=addr,
            )
        )
    return hints
