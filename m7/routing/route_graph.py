"""E1.69 Wave C — Route graph optimizer.

Pure path-enumeration over pool adjacency.  No I/O, no web3.
Consumers (cold lane / scout / orderflow) supply a *PoolEdge* list and
the graph enumerates 2-hop / 3-hop paths between a desired
``(token_in, token_out)`` pair.

Each path is scored by the **bottleneck** TVL along the path so that
production-size routes (every hop has $50+ depth) rank above thin
single-hop dust.  Splitting / multi-hop sizing logic stays in the hot
lane scorer; this module only proposes *which paths to ask about*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class PoolEdge:
    """A single AMM pool, treated as an undirected edge between two tokens.

    ``tvl_usd`` is best-effort: 0 / None means "unknown" and disqualifies
    the edge from the production-size frontier (path scorer drops paths
    containing unknown-TVL edges from the production tier).
    """

    address: str
    token0: str
    token1: str
    dex: str
    fee_bps: Optional[int] = None
    tvl_usd: Optional[float] = None

    def other(self, token: str) -> Optional[str]:
        if token == self.token0:
            return self.token1
        if token == self.token1:
            return self.token0
        return None


@dataclass(frozen=True)
class RoutePath:
    tokens: Tuple[str, ...]
    pools: Tuple[PoolEdge, ...]

    @property
    def hops(self) -> int:
        return len(self.pools)

    @property
    def bottleneck_tvl_usd(self) -> float:
        """Min TVL across the path; 0.0 when any edge has unknown TVL."""
        if not self.pools:
            return 0.0
        vals = [p.tvl_usd or 0.0 for p in self.pools]
        return min(vals)

    @property
    def display_key(self) -> str:
        return " -> ".join(self.tokens)


def _normalize(token: str) -> str:
    return token.upper()


def build_adjacency(pools: Iterable[PoolEdge]) -> Dict[str, List[PoolEdge]]:
    """Token symbol -> pool edges incident to that token."""
    adj: Dict[str, List[PoolEdge]] = {}
    for pool in pools:
        for tok in (pool.token0, pool.token1):
            adj.setdefault(_normalize(tok), []).append(pool)
    return adj


def enumerate_paths(
    pools: Sequence[PoolEdge],
    token_in: str,
    token_out: str,
    max_hops: int = 3,
    bridge_whitelist: Optional[Sequence[str]] = None,
) -> List[RoutePath]:
    """Enumerate simple paths token_in -> token_out up to ``max_hops``.

    * Direct (1 hop), bridged (2 hops), and triangular (3 hops) routes.
    * ``bridge_whitelist`` constrains *intermediate* tokens (defaults to
      common production bridges WETH / USDC / AERO / cbBTC).
    * Rejects revisiting any token within a path (no cycles).
    * Rejects revisiting the same pool address (no degenerate splits).
    """
    if max_hops < 1 or max_hops > 4:
        raise ValueError("max_hops must be in [1, 4]")

    src = _normalize(token_in)
    dst = _normalize(token_out)
    if src == dst:
        return []

    bridges = {
        _normalize(t)
        for t in (bridge_whitelist or ("WETH", "USDC", "AERO", "CBBTC", "USDT"))
    }
    adj = build_adjacency(pools)

    out: List[RoutePath] = []

    def _walk(node: str, visited_tokens: Tuple[str, ...], used_pools: Tuple[str, ...],
              edges: Tuple[PoolEdge, ...]) -> None:
        if len(edges) >= max_hops:
            return
        for edge in adj.get(node, ()):
            if edge.address in used_pools:
                continue
            nxt = edge.other(node)
            if nxt is None:
                continue
            nxt_n = _normalize(nxt)
            new_edges = edges + (edge,)
            new_tokens = visited_tokens + (nxt_n,)
            if nxt_n == dst:
                out.append(RoutePath(tokens=new_tokens, pools=new_edges))
                continue
            if nxt_n in visited_tokens:
                continue  # cycle
            # Intermediate hops must be in the bridge whitelist.
            if nxt_n not in bridges:
                continue
            _walk(nxt_n, new_tokens, used_pools + (edge.address,), new_edges)

    _walk(src, (src,), (), ())
    return out


def rank_paths(
    paths: Iterable[RoutePath],
    min_production_tvl_usd: float = 50_000.0,
) -> List[RoutePath]:
    """Sort by (production_tier desc, bottleneck_tvl desc, fewer_hops asc).

    A path is *production tier* when every hop has ``tvl_usd`` >=
    ``min_production_tvl_usd``.  Within a tier paths sort by bottleneck
    TVL descending; ties broken by lower hop count.
    """
    def _key(p: RoutePath):
        prod = all((e.tvl_usd or 0.0) >= min_production_tvl_usd for e in p.pools)
        return (
            0 if prod else 1,            # tier  (lower number = better)
            -p.bottleneck_tvl_usd,        # higher bottleneck first
            p.hops,                       # fewer hops first
        )

    return sorted(paths, key=_key)


def select_production_paths(
    pools: Sequence[PoolEdge],
    token_in: str,
    token_out: str,
    max_hops: int = 3,
    min_production_tvl_usd: float = 50_000.0,
    top_n: int = 5,
) -> List[RoutePath]:
    """High-level entry point used by cold lane / scout: enumerate + rank
    and return the top ``top_n`` production-tier paths."""
    paths = enumerate_paths(pools, token_in, token_out, max_hops=max_hops)
    ranked = rank_paths(paths, min_production_tvl_usd=min_production_tvl_usd)
    return ranked[:top_n]
