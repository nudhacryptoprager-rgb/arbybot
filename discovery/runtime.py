# PATH: discovery/runtime.py
"""
Discovery Runtime Module - Dynamic universe expansion at runtime.

v2.4.0: Added for discovery_runtime mode.

PURPOSE:
    When discovery_runtime=true in config, this module expands the trading
    universe by resolving intent.txt pairs to pool addresses via factory.getPool().
    
CONTRACT:
    - Default: discovery_runtime=false (use hardcoded pairs from config/pairs)
    - When enabled:
        1. Reads pairs from config/intent.txt
        2. Filters to pairs with both tokens resolvable in core_tokens.yaml
        3. Uses discovery/pool_resolver.py to resolve pool addresses
        4. Respects discovery_runtime_max_pairs cap (default: 20)
        5. Returns deterministic ordering (sorted by canonical_key)
    - Observability: stats in stats["discovery_runtime"]
    
SAFETY:
    - ARBY_SKIP_RPC=1 causes immediate return with empty list (no RPC calls)
    - Cache prevents spamming RPC endpoints (persistent pool_resolver cache)
    - Negative cache means "no pool exists" is also cached

USAGE:
    from discovery.runtime import resolve_runtime_pairs, get_runtime_stats
    
    # In run_scan_real.py when discovery_runtime=true
    resolved_pairs = resolve_runtime_pairs(
        chain="arbitrum_one",
        dexes=["uniswap_v3", "sushiswap_v3"],
        max_pairs=20,
    )
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("discovery.runtime")


@dataclass
class RuntimePair:
    """A resolved pair from discovery runtime."""
    chain: str
    token_a: str
    token_b: str
    addr_a: str
    addr_b: str
    dex: str
    fee: Optional[int]
    pool_address: str
    
    @property
    def canonical_key(self) -> str:
        """Deterministic key for sorting."""
        t0, t1 = sorted([self.token_a, self.token_b])
        fee_str = str(self.fee) if self.fee else "v2"
        return f"{self.chain}:{self.dex}:{t0}/{t1}:{fee_str}"
    
    @property
    def display_name(self) -> str:
        """Human-readable name."""
        return f"{self.token_a}/{self.token_b}"


@dataclass
class RuntimeStats:
    """Statistics for discovery runtime operations."""
    enabled: bool = True
    pairs_evaluated: int = 0
    pairs_resolved: int = 0
    pairs_skipped_no_tokens: int = 0
    pairs_skipped_no_pool: int = 0
    pairs_skipped_max_cap: int = 0
    pools_from_cache: int = 0
    pools_from_rpc: int = 0
    rpc_calls: int = 0
    dexes_queried: List[str] = field(default_factory=list)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "enabled": self.enabled,
            "pairs_evaluated": self.pairs_evaluated,
            "pairs_resolved": self.pairs_resolved,
            "pairs_skipped_no_tokens": self.pairs_skipped_no_tokens,
            "pairs_skipped_no_pool": self.pairs_skipped_no_pool,
            "pairs_skipped_max_cap": self.pairs_skipped_max_cap,
            "pools_from_cache": self.pools_from_cache,
            "pools_from_rpc": self.pools_from_rpc,
            "rpc_calls": self.rpc_calls,
            "dexes_queried": self.dexes_queried,
            "error": self.error,
        }


# V3 fee tiers to query for each pair
V3_FEE_TIERS = [100, 500, 3000, 10000]

# Default max pairs to resolve per cycle
DEFAULT_MAX_PAIRS = 20


def resolve_runtime_pairs(
    chain: str,
    dexes: Optional[List[str]] = None,
    max_pairs: int = DEFAULT_MAX_PAIRS,
    fee_tiers: Optional[List[int]] = None,
    rpc_url: Optional[str] = None,
) -> tuple[List[RuntimePair], RuntimeStats]:
    """
    Resolve intent.txt pairs to pool addresses via factory.getPool().
    
    Args:
        chain: Chain key (e.g., "arbitrum_one")
        dexes: List of DEX keys to query (default: all V3 dexes for chain)
        max_pairs: Maximum pairs to resolve per call (deterministic cap)
        fee_tiers: V3 fee tiers to query (default: [100, 500, 3000, 10000])
        rpc_url: RPC URL (optional, will use default if not provided)
        
    Returns:
        Tuple of (resolved_pairs, stats)
    """
    stats = RuntimeStats()
    
    # Check ARBY_SKIP_RPC
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        logger.debug("ARBY_SKIP_RPC=1, skipping runtime discovery")
        stats.enabled = False
        stats.error = "ARBY_SKIP_RPC=1"
        return [], stats
    
    # Import dependencies
    try:
        from discovery.intent_loader import get_intent_universe
        from discovery.verify import get_token_registry
        from discovery.pool_resolver import get_pool_resolver
        from discovery.index_factories import FACTORY_ADDRESSES
    except ImportError as e:
        logger.warning("Discovery runtime dependencies not available: %s", e)
        stats.enabled = False
        stats.error = f"ImportError: {e}"
        return [], stats
    
    # Get intent universe
    universe = get_intent_universe()
    registry = get_token_registry()
    resolver = get_pool_resolver()
    
    # Get pairs for chain
    intent_pairs = universe.get_pairs_for_chain(chain)
    if not intent_pairs:
        logger.debug("No intent pairs for chain %s", chain)
        stats.error = f"no_intent_pairs_for_{chain}"
        return [], stats
    
    # Determine dexes to query
    chain_factories = FACTORY_ADDRESSES.get(chain, {})
    if dexes is None:
        # Default to V3 dexes only
        dexes = [d for d in chain_factories.keys() if "v3" in d.lower()]
    stats.dexes_queried = dexes
    
    # Determine fee tiers
    if fee_tiers is None:
        fee_tiers = V3_FEE_TIERS
    
    # Sort pairs deterministically for consistent ordering
    sorted_pairs = sorted(intent_pairs, key=lambda p: p.canonical_key)
    
    resolved: List[RuntimePair] = []
    seen_pairs: Set[str] = set()  # Dedupe by canonical pair key
    
    for pair in sorted_pairs:
        if len(resolved) >= max_pairs:
            stats.pairs_skipped_max_cap += len(sorted_pairs) - len(resolved)
            break
        
        stats.pairs_evaluated += 1
        
        # Resolve token addresses
        addr_a = registry.get_address(chain, pair.token_a)
        addr_b = registry.get_address(chain, pair.token_b)
        
        if not addr_a or not addr_b:
            stats.pairs_skipped_no_tokens += 1
            logger.debug(
                "Skipping pair %s/%s: missing token address (a=%s, b=%s)",
                pair.token_a, pair.token_b, bool(addr_a), bool(addr_b)
            )
            continue
        
        # Try each dex and fee tier
        pair_resolved = False
        for dex in dexes:
            if pair_resolved:
                break
            for fee in fee_tiers:
                # Create canonical key for deduplication
                pair_key = f"{chain}:{sorted([pair.token_a, pair.token_b])[0]}/{sorted([pair.token_a, pair.token_b])[1]}:{dex}:{fee}"
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                
                # Query pool resolver
                pool_addr = resolver.resolve(
                    chain=chain,
                    dex=dex,
                    symbol_a=pair.token_a,
                    symbol_b=pair.token_b,
                    fee=fee,
                    rpc_url=rpc_url,
                )
                
                if pool_addr:
                    resolved.append(RuntimePair(
                        chain=chain,
                        token_a=pair.token_a,
                        token_b=pair.token_b,
                        addr_a=addr_a,
                        addr_b=addr_b,
                        dex=dex,
                        fee=fee,
                        pool_address=pool_addr,
                    ))
                    pair_resolved = True
                    stats.pairs_resolved += 1
                    break
        
        if not pair_resolved:
            stats.pairs_skipped_no_pool += 1
    
    # Collect resolver stats
    resolver_stats = resolver.get_stats()
    stats.pools_from_cache = resolver_stats["hits"] + resolver_stats["negative_hits"]
    stats.pools_from_rpc = resolver_stats["misses"]
    stats.rpc_calls = resolver_stats["rpc_calls"]
    
    # Save resolver cache for persistence
    resolver.flush()
    
    logger.info(
        "Discovery runtime: %d pairs resolved, %d skipped (tokens=%d, pool=%d, cap=%d)",
        stats.pairs_resolved,
        stats.pairs_skipped_no_tokens + stats.pairs_skipped_no_pool + stats.pairs_skipped_max_cap,
        stats.pairs_skipped_no_tokens,
        stats.pairs_skipped_no_pool,
        stats.pairs_skipped_max_cap,
    )
    
    return resolved, stats


def get_runtime_observability(stats: RuntimeStats) -> Dict[str, Any]:
    """
    Get observability dict for artifact stats.
    
    Returns dict to be merged into stats["discovery_runtime"].
    """
    return stats.to_dict()
