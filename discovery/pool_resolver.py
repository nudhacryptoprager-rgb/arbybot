# PATH: discovery/pool_resolver.py
"""
Intent→Pool Resolver with factory.getPool() and persistent cache.

v2.4.0: Added for discovery→runtime mode.
v2.5.0: Added rpc_concurrency guardrail and stats.

Purpose:
    Resolve intent pairs (WETH/USDC) to pool addresses via factory.getPool()
    instead of hardcoded pool addresses in config files.

Cache:
    - Stores resolved pools in data/cache/pool_resolver_cache.json
    - Key: chain:dex:tokenA:tokenB:fee (sorted tokens, lowercase)
    - Value: pool address or null (negative cache)

Guardrails:
    - ARBY_RESOLVER_MAX_RPC_CALLS: Max RPC calls per session (default: 50)
    - ARBY_SKIP_RPC: If "1", skip all RPC calls
    - Negative cache prevents repeated queries for non-existent pools

TODO:
    - Connect to chains.providers.RPCProvider for unified failover/metrics
    - Add negative cache TTL for eventual re-query

Usage:
    resolver = get_pool_resolver("arbitrum_one")  # v3.2.16: chain-scoped
    pool = resolver.resolve("arbitrum_one", "uniswap_v3", "WETH", "USDC", 500)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("discovery.pool_resolver")

# Legacy cache file path (use _get_cache_path() for chain-scoped)
CACHE_PATH_LEGACY = Path("data/cache/pool_resolver_cache.json")
# v3.2.16: Backwards compatibility alias
CACHE_PATH = CACHE_PATH_LEGACY

# Negative cache sentinel
NULL_POOL = "__NULL__"

# Guardrail: Max RPC calls per session (to prevent runaway queries)
MAX_RPC_CALLS_PER_SESSION = int(os.environ.get("ARBY_RESOLVER_MAX_RPC_CALLS", "50"))


# v3.2.16: Chain-scoped path helper
def _get_cache_path(chain_key: str | None = None) -> Path:
    """Get chain-scoped pool resolver cache path.
    
    v3.2.16: Chain-scoped paths to prevent arbitrum_one <-> linea pollution.
    
    Args:
        chain_key: Chain identifier (e.g., "arbitrum_one", "linea")
        
    Returns:
        Path to chain-scoped cache file, or legacy path if no chain_key
    """
    if chain_key and chain_key != "unknown":
        return Path(f"data/cache/pool_resolver_cache_{chain_key}.json")
    # Legacy path for backwards compatibility
    logger.warning(
        "LEGACY_CACHE_PATH: pool_resolver using legacy path (chain_key=%s)",
        chain_key,
    )
    return CACHE_PATH_LEGACY


@dataclass
class ResolverStats:
    """Statistics for resolver operations."""
    hits: int = 0
    misses: int = 0
    rpc_calls: int = 0
    rpc_calls_limited: int = 0  # Calls skipped due to limit
    resolved_count: int = 0
    failed_count: int = 0
    negative_hits: int = 0  # Cache hits for "no pool exists"


@dataclass
class PoolResolver:
    """
    Resolves intent pairs to pool addresses via factory.getPool().
    
    Caches results to minimize RPC calls.
    
    v3.2.16: Chain-scoped caching to prevent cross-chain pollution.
    """
    _cache: Dict[str, str] = field(default_factory=dict)
    _stats: ResolverStats = field(default_factory=ResolverStats)
    _dirty: bool = False
    _chain_key: str | None = None
    _cache_path: Path | None = None
    
    def __post_init__(self):
        # v3.2.16: Use chain-scoped path if chain_key provided
        if self._cache_path is None:
            self._cache_path = _get_cache_path(self._chain_key)
        self._load_cache()
    
    def _cache_key(
        self,
        chain: str,
        dex: str,
        token_a_addr: str,
        token_b_addr: str,
        fee: Optional[int],
    ) -> str:
        """Generate deterministic cache key."""
        # Sort tokens for consistency
        tokens = sorted([token_a_addr.lower(), token_b_addr.lower()])
        fee_str = str(fee) if fee else "v2"
        return f"{chain}:{dex}:{tokens[0]}:{tokens[1]}:{fee_str}"
    
    def _load_cache(self) -> None:
        """Load cache from disk."""
        cache_path = self._cache_path or CACHE_PATH_LEGACY
        if cache_path.exists():
            try:
                with open(cache_path, "r") as f:
                    data = json.load(f)
                    self._cache = data.get("pools", {})
                    logger.info("Loaded %d cached pools from %s", len(self._cache), cache_path)
            except Exception as e:
                logger.warning("Failed to load pool cache from %s: %s", cache_path, e)
                self._cache = {}
        else:
            self._cache = {}
    
    def _save_cache(self) -> None:
        """Save cache to disk."""
        if not self._dirty:
            return
        
        cache_path = self._cache_path or CACHE_PATH_LEGACY
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w") as f:
                json.dump({
                    "schema_version": "pool_resolver:v1.1",
                    "chain_key": self._chain_key,
                    "pools": self._cache,
                    "stats": {
                        "total_entries": len(self._cache),
                        "positive_entries": sum(1 for v in self._cache.values() if v != NULL_POOL),
                        "negative_entries": sum(1 for v in self._cache.values() if v == NULL_POOL),
                    },
                }, f, indent=2)
            self._dirty = False
            logger.debug("Saved pool cache (%d entries) to %s", len(self._cache), cache_path)
        except Exception as e:
            logger.warning("Failed to save pool cache to %s: %s", cache_path, e)
    
    def resolve(
        self,
        chain: str,
        dex: str,
        symbol_a: str,
        symbol_b: str,
        fee: Optional[int] = None,
        rpc_url: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Optional[str]:
        """
        Resolve a pair to pool address.
        
        Args:
            chain: Chain key (e.g., "arbitrum_one")
            dex: DEX key (e.g., "uniswap_v3")
            symbol_a: Token A symbol
            symbol_b: Token B symbol
            fee: Fee tier (V3 only)
            rpc_url: RPC URL (optional, will use default if not provided)
            force_refresh: Skip cache and query RPC
            
        Returns:
            Pool address or None if not found
        """
        from discovery.verify import get_token_registry
        from discovery.index_factories import query_v3_pool, query_v2_pair, get_factory_address
        from core.rpc_urls import get_rpc_url
        
        registry = get_token_registry()
        
        # Resolve symbols to addresses
        addr_a = registry.get_address(chain, symbol_a)
        addr_b = registry.get_address(chain, symbol_b)
        
        if not addr_a or not addr_b:
            logger.debug("Cannot resolve pair %s/%s: missing token addresses", symbol_a, symbol_b)
            return None
        
        # Check cache
        key = self._cache_key(chain, dex, addr_a, addr_b, fee)
        
        if not force_refresh and key in self._cache:
            cached = self._cache[key]
            if cached == NULL_POOL:
                self._stats.negative_hits += 1
                return None
            self._stats.hits += 1
            return cached
        
        self._stats.misses += 1
        
        # Guardrail: Check RPC call limit
        if self._stats.rpc_calls >= MAX_RPC_CALLS_PER_SESSION:
            self._stats.rpc_calls_limited += 1
            logger.debug(
                "RPC call limit reached (%d/%d), using cache only",
                self._stats.rpc_calls, MAX_RPC_CALLS_PER_SESSION
            )
            return None
        
        # Query RPC
        if rpc_url is None:
            rpc_url = get_rpc_url(chain)
        
        if not rpc_url or os.environ.get("ARBY_SKIP_RPC") == "1":
            logger.debug("RPC not available, cannot resolve pool")
            return None
        
        factory_addr = get_factory_address(chain, dex)
        if not factory_addr:
            logger.debug("No factory address for %s:%s", chain, dex)
            return None
        
        self._stats.rpc_calls += 1
        
        # Query factory
        if "v3" in dex.lower():
            if fee is None:
                logger.debug("V3 resolver requires fee tier")
                return None
            pool_addr = query_v3_pool(rpc_url, factory_addr, addr_a, addr_b, fee)
        else:
            pool_addr = query_v2_pair(rpc_url, factory_addr, addr_a, addr_b)
        
        # Update cache
        if pool_addr:
            self._cache[key] = pool_addr
            self._stats.resolved_count += 1
            self._dirty = True
            logger.debug("Resolved %s/%s on %s:%s fee=%s -> %s", symbol_a, symbol_b, chain, dex, fee, pool_addr)
        else:
            self._cache[key] = NULL_POOL  # Negative cache
            self._stats.failed_count += 1
            self._dirty = True
            logger.debug("No pool found for %s/%s on %s:%s fee=%s", symbol_a, symbol_b, chain, dex, fee)
        
        return pool_addr
    
    def resolve_all_fee_tiers(
        self,
        chain: str,
        dex: str,
        symbol_a: str,
        symbol_b: str,
        rpc_url: Optional[str] = None,
    ) -> List[Tuple[int, str]]:
        """
        Resolve a V3 pair across all fee tiers.
        
        Returns list of (fee, pool_address) tuples for existing pools.
        """
        from discovery.index_factories import V3_FEE_TIERS
        
        results = []
        for fee in V3_FEE_TIERS:
            pool = self.resolve(chain, dex, symbol_a, symbol_b, fee, rpc_url)
            if pool:
                results.append((fee, pool))
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get resolver statistics."""
        return {
            "cache_size": len(self._cache),
            "hits": self._stats.hits,
            "misses": self._stats.misses,
            "negative_hits": self._stats.negative_hits,
            "rpc_calls": self._stats.rpc_calls,
            "rpc_calls_limited": self._stats.rpc_calls_limited,
            "resolved_count": self._stats.resolved_count,
            "failed_count": self._stats.failed_count,
            "hit_rate": self._stats.hits / max(1, self._stats.hits + self._stats.misses),
            "max_rpc_calls": MAX_RPC_CALLS_PER_SESSION,
            "cap_triggered": self._stats.rpc_calls_limited > 0,  # True if limit caused skips
        }
    
    def flush(self) -> None:
        """Explicitly save cache to disk."""
        self._save_cache()
    
    def clear_cache(self) -> None:
        """Clear all cached entries."""
        self._cache = {}
        self._dirty = True
        self._save_cache()


# v3.2.16: Chain-scoped singletons
_resolvers: Dict[str, PoolResolver] = {}


def get_pool_resolver(chain_key: str | None = None) -> PoolResolver:
    """Get the chain-scoped pool resolver singleton.
    
    v3.2.16: Chain-scoped resolvers to prevent cross-chain pollution.
    
    Args:
        chain_key: Chain identifier for scoped caching (e.g., "arbitrum_one")
        
    Returns:
        PoolResolver instance for the specified chain
    """
    global _resolvers
    key = chain_key or "__legacy__"
    if key not in _resolvers:
        _resolvers[key] = PoolResolver(_chain_key=chain_key if chain_key else None)
    return _resolvers[key]


def resolve_intent_pool(
    chain: str,
    dex: str,
    symbol_a: str,
    symbol_b: str,
    fee: Optional[int] = None,
) -> Optional[str]:
    """
    Convenience function to resolve an intent pair to pool address.
    
    Uses the chain-scoped singleton resolver with caching.
    
    v3.2.16: Uses chain parameter for chain-scoped caching.
    """
    return get_pool_resolver(chain).resolve(chain, dex, symbol_a, symbol_b, fee)
