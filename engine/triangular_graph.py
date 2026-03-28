# PATH: engine/triangular_graph.py
"""
M7.A — Verified pool graph for triangular cycle discovery.

Builds a directed multi-graph from already-resolved, adapter-supported pools.
Nodes are tokens, edges are concrete on-chain pools with known adapter semantics.

CONTRACTS:
- Graph edges come ONLY from verified discovery stack (discovery/verify.py,
  discovery/index_factories.py, discovery/runtime.py).
- Symbolic token adjacency is NOT an edge. Every edge must have a resolved
  pool address, known adapter type, and fee tier.
- Graph is directional for quoting: edge A->B means "can swap A for B on
  this pool". V3/V2 pools support both directions, so always add both.
- No cross-chain edges (single-chain graph only).

SCOPE:
- First chain: arbitrum_one
- First universe: core/liquid tokens from core_tokens.yaml
- First adapters: only adapters already stable in current repo
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

logger = logging.getLogger("engine.triangular_graph")


@dataclass(frozen=True)
class PoolEdge:
    """A directed quoting edge backed by a concrete on-chain pool.

    Immutable so it can be used in sets and as dict keys.
    """
    token_in: str            # e.g. "WETH"
    token_out: str           # e.g. "USDC"
    pool_address: str        # checksummed or lowered — must be non-empty
    dex: str                 # e.g. "uniswap_v3"
    adapter_type: str        # e.g. "uniswap_v3", "algebra", "uniswap_v2"
    fee: Optional[int]       # fee tier (bps * 100 for V3), None for V2
    chain: str               # e.g. "arbitrum_one"
    decimals_in: int = 18
    decimals_out: int = 18

    @property
    def edge_key(self) -> str:
        """Deterministic identifier for dedup and logging."""
        fee_str = str(self.fee) if self.fee is not None else "v2"
        return f"{self.chain}:{self.dex}:{self.token_in}->{self.token_out}:{fee_str}:{self.pool_address[:10]}"

    def reverse(self) -> "PoolEdge":
        """Return the reverse-direction edge for the same pool."""
        return PoolEdge(
            token_in=self.token_out,
            token_out=self.token_in,
            pool_address=self.pool_address,
            dex=self.dex,
            adapter_type=self.adapter_type,
            fee=self.fee,
            chain=self.chain,
            decimals_in=self.decimals_out,
            decimals_out=self.decimals_in,
        )


@dataclass
class PoolGraph:
    """Directed multi-graph of verified pool edges for one chain.

    adjacency[token] -> list of PoolEdge where token == edge.token_in
    """
    chain: str
    adjacency: Dict[str, List[PoolEdge]] = field(default_factory=dict)
    _edge_keys: Set[str] = field(default_factory=set, repr=False)

    @property
    def node_count(self) -> int:
        return len(self.all_tokens())

    @property
    def edge_count(self) -> int:
        return len(self._edge_keys)

    def all_tokens(self) -> Set[str]:
        """Return the set of all tokens that appear as nodes."""
        tokens: Set[str] = set()
        for token, edges in self.adjacency.items():
            tokens.add(token)
            for e in edges:
                tokens.add(e.token_out)
        return tokens

    def add_edge(self, edge: PoolEdge) -> bool:
        """Add a directed edge. Returns False if duplicate (already present)."""
        if edge.edge_key in self._edge_keys:
            return False
        self._edge_keys.add(edge.edge_key)
        self.adjacency.setdefault(edge.token_in, []).append(edge)
        return True

    def add_pool(self, edge: PoolEdge) -> int:
        """Add both directions of a pool. Returns number of new edges added."""
        added = 0
        if self.add_edge(edge):
            added += 1
        if self.add_edge(edge.reverse()):
            added += 1
        return added

    def neighbors(self, token: str) -> List[PoolEdge]:
        """Get all outgoing edges from a token."""
        return self.adjacency.get(token, [])

    def neighbor_tokens(self, token: str) -> Set[str]:
        """Get the set of tokens reachable in one hop from token."""
        return {e.token_out for e in self.neighbors(token)}

    def to_summary(self) -> Dict[str, Any]:
        """Serializable summary for artifacts/logging."""
        return {
            "chain": self.chain,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "tokens": sorted(self.all_tokens()),
            "edges_per_token": {
                t: len(edges) for t, edges in sorted(self.adjacency.items())
            },
        }


# ---------------------------------------------------------------------------
# Graph builders — from verified discovery sources
# ---------------------------------------------------------------------------

def build_graph_from_runtime_pairs(
    chain: str,
    runtime_pairs: list,
) -> PoolGraph:
    """Build a PoolGraph from discovery.runtime.RuntimePair objects.

    This is the canonical path for discovery_runtime mode.
    Only pools that were already resolved through the discovery stack
    (factory.getPool / RPC verification) are included.

    Args:
        chain: Chain key (e.g. "arbitrum_one")
        runtime_pairs: List of RuntimePair (from discovery.runtime)

    Returns:
        PoolGraph with bidirectional edges for every resolved pool.
    """
    from discovery.index_factories import get_dex_adapter_type

    graph = PoolGraph(chain=chain)
    for rp in runtime_pairs:
        if rp.chain != chain:
            continue
        adapter_type = get_dex_adapter_type(chain, rp.dex) or rp.dex
        edge = PoolEdge(
            token_in=rp.token_a,
            token_out=rp.token_b,
            pool_address=rp.pool_address,
            dex=rp.dex,
            adapter_type=adapter_type,
            fee=rp.fee,
            chain=chain,
            decimals_in=rp.decimals_a,
            decimals_out=rp.decimals_b,
        )
        graph.add_pool(edge)

    logger.info(
        "Built graph from runtime_pairs: chain=%s nodes=%d edges=%d",
        chain, graph.node_count, graph.edge_count,
    )
    return graph


def build_graph_from_discovered_pools(
    chain: str,
    pools: list,
) -> PoolGraph:
    """Build a PoolGraph from discovery.index_factories.DiscoveredPool objects.

    This is the canonical path for factory-indexed discovery.

    Args:
        chain: Chain key
        pools: List of DiscoveredPool (from index_factories.PoolIndex)

    Returns:
        PoolGraph with bidirectional edges.
    """
    from discovery.index_factories import get_dex_adapter_type
    from discovery.verify import get_token_registry

    registry = get_token_registry()
    graph = PoolGraph(chain=chain)

    for pool in pools:
        if pool.chain != chain:
            continue
        # Use symbols from pool (already resolved)
        token_in = pool.token0_symbol
        token_out = pool.token1_symbol
        if not token_in or not token_out:
            continue

        # Get decimals from registry
        t0_info = registry.get_token(chain, token_in)
        t1_info = registry.get_token(chain, token_out)
        dec_in = t0_info.decimals if t0_info else 18
        dec_out = t1_info.decimals if t1_info else 18

        adapter_type = get_dex_adapter_type(chain, pool.dex) or pool.dex
        edge = PoolEdge(
            token_in=token_in,
            token_out=token_out,
            pool_address=pool.address,
            dex=pool.dex,
            adapter_type=adapter_type,
            fee=pool.fee_tier,
            chain=chain,
            decimals_in=dec_in,
            decimals_out=dec_out,
        )
        graph.add_pool(edge)

    logger.info(
        "Built graph from discovered_pools: chain=%s nodes=%d edges=%d",
        chain, graph.node_count, graph.edge_count,
    )
    return graph


def build_graph_from_pool_dicts(
    chain: str,
    pool_dicts: List[Dict[str, Any]],
) -> PoolGraph:
    """Build a PoolGraph from raw pool dictionaries.

    Useful for building from cached hot_pairs data or test fixtures.
    Each dict must have at minimum: token_in, token_out, dex, pool_address.

    Args:
        chain: Chain key
        pool_dicts: List of dicts with pool metadata.

    Returns:
        PoolGraph with bidirectional edges.
    """
    graph = PoolGraph(chain=chain)

    for d in pool_dicts:
        token_in = d.get("token_in") or d.get("token0_symbol", "")
        token_out = d.get("token_out") or d.get("token1_symbol", "")
        pool_address = d.get("pool_address") or d.get("address", "")
        dex = d.get("dex", "")
        if not token_in or not token_out or not pool_address:
            continue
        edge = PoolEdge(
            token_in=token_in,
            token_out=token_out,
            pool_address=pool_address,
            dex=dex,
            adapter_type=d.get("adapter_type", dex),
            fee=d.get("fee") or d.get("fee_tier"),
            chain=chain,
            decimals_in=d.get("decimals_in", 18),
            decimals_out=d.get("decimals_out", 18),
        )
        graph.add_pool(edge)

    logger.info(
        "Built graph from pool_dicts: chain=%s nodes=%d edges=%d",
        chain, graph.node_count, graph.edge_count,
    )
    return graph
