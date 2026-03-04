# PATH: discovery/index_factories.py
"""
Factory-based pool discovery (Roadmap Appendix A Step 3).

Enumerates pools from Uniswap-style factories using:
1. factory.getPool(tokenA, tokenB, fee) for V3 factories
2. factory.getPair(tokenA, tokenB) for V2 factories

Only queries for token pairs that appear in intent.txt and have
verified addresses in the token registry.
"""

import logging
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from discovery.intent_loader import get_intent_universe, IntentPair
from discovery.verify import get_token_registry

logger = logging.getLogger("discovery.index_factories")

# Standard fee tiers for Uniswap V3 and forks (default fallback)
V3_FEE_TIERS = [100, 500, 3000, 10000]  # 0.01%, 0.05%, 0.3%, 1%


def get_dex_fee_tiers(chain: str, dex: str) -> List[int]:
    """Get fee tiers for a specific DEX from dexes.yaml.
    
    v3.2.17: Per-DEX fee tiers to handle pancakeswap_v3 fee=2500 etc.
    
    Args:
        chain: Chain key (e.g., "arbitrum_one")
        dex: DEX key (e.g., "pancakeswap_v3")
        
    Returns:
        List of fee tiers for the DEX, or V3_FEE_TIERS as fallback
    """
    try:
        from config import load_dexes
        dexes_config = load_dexes()
        chain_dexes = dexes_config.get(chain, {})
        dex_config = chain_dexes.get(dex, {})
        fee_tiers = dex_config.get("fee_tiers")
        if fee_tiers and isinstance(fee_tiers, list):
            return fee_tiers
    except Exception:
        pass
    return V3_FEE_TIERS


def get_dex_adapter_type(chain: str, dex: str) -> Optional[str]:
    """Get adapter type for a DEX from dexes.yaml.
    
    v3.2.17: Needed for Algebra vs UniswapV3 factory discovery.
    
    Args:
        chain: Chain key
        dex: DEX key
        
    Returns:
        Adapter type string (e.g., "uniswap_v3", "algebra", "ve33")
    """
    try:
        from config import load_dexes
        dexes_config = load_dexes()
        chain_dexes = dexes_config.get(chain, {})
        dex_config = chain_dexes.get(dex, {})
        return dex_config.get("adapter_type")
    except Exception:
        return None


def get_chain_dexes(chain: str, adapter_types: Optional[List[str]] = None) -> List[str]:
    """Get all configured DEXes for a chain from dexes.yaml.
    
    v3.2.17: Single source of truth for discovery DEX list.
    
    Args:
        chain: Chain key
        adapter_types: Optional filter for adapter types (e.g., ["uniswap_v3", "algebra"])
        
    Returns:
        List of DEX keys configured for the chain
    """
    try:
        from config import load_dexes
        dexes_config = load_dexes()
        chain_dexes = dexes_config.get(chain, {})
        
        if not adapter_types:
            return list(chain_dexes.keys())
        
        # Filter by adapter type
        result = []
        for dex_key, dex_cfg in chain_dexes.items():
            if dex_cfg.get("adapter_type") in adapter_types:
                result.append(dex_key)
        return result
    except Exception:
        # Fallback to FACTORY_ADDRESSES
        return list(FACTORY_ADDRESSES.get(chain, {}).keys())

# v2.0.4: V3 Factory ABI for getPool() queries - single source of truth
# RESTORE CONTRACT: This is the canonical ABI for all V3 factory getPool() calls
V3_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "uint24", "name": "", "type": "uint24"},
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# Known factory addresses per (chain, dex)
FACTORY_ADDRESSES: Dict[str, Dict[str, str]] = {
    "arbitrum_one": {
        "uniswap_v3": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "sushiswap_v3": "0x1af415a1EbA07a4986a52B6f2e7dE7003D82231e",
        # V2 factories
        "uniswap_v2": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",  # legacy on mainnet
        "sushiswap_v2": "0xc35DADB65012eC5796536bD9864eD8773aBc74C4",
    },
    "base": {
        "uniswap_v3": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
        "aerodrome": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da",
    },
    "ethereum": {
        "uniswap_v3": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "uniswap_v2": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
    },
    "linea": {
        "lynex_v3": "0x622b2c98123D303ae067DB4925CD6282B3A08D0F",  # Algebra adapter
    },
    "mantle": {
        "agni_v3": "0x25780dc8Fc3cfBD75F33bFDAB65e969b603b2035",  # Uniswap V3 fork
    },
}


class DiscoveredPool(NamedTuple):
    """Pool discovered from factory."""
    chain: str
    dex: str
    address: str
    token0: str
    token1: str
    token0_symbol: str
    token1_symbol: str
    fee_tier: Optional[int]  # None for V2


class PoolIndex:
    """
    Index of discovered pools per chain.
    
    Pools are discovered by querying factory.getPool() for each intent pair
    and each fee tier.
    """
    
    def __init__(self):
        self._pools: Dict[str, List[DiscoveredPool]] = {}  # chain -> list of pools
        self._indexed_pairs: Dict[str, set] = {}  # chain -> set of (tokenA, tokenB, dex)
    
    def add_pool(self, pool: DiscoveredPool) -> None:
        """Add a discovered pool."""
        if pool.chain not in self._pools:
            self._pools[pool.chain] = []
        self._pools[pool.chain].append(pool)
    
    def get_pools(self, chain: str) -> List[DiscoveredPool]:
        """Get all pools for a chain."""
        return self._pools.get(chain, [])
    
    def get_pools_for_pair(
        self,
        chain: str,
        symbol_a: str,
        symbol_b: str,
    ) -> List[DiscoveredPool]:
        """Get all pools for a specific pair (any fee tier, any dex)."""
        pools = []
        for pool in self.get_pools(chain):
            syms = {pool.token0_symbol.upper(), pool.token1_symbol.upper()}
            if {symbol_a.upper(), symbol_b.upper()} == syms:
                pools.append(pool)
        return pools
    
    def mark_indexed(self, chain: str, token_a: str, token_b: str, dex: str) -> None:
        """Mark a pair as indexed for a dex."""
        if chain not in self._indexed_pairs:
            self._indexed_pairs[chain] = set()
        key = tuple(sorted([token_a.lower(), token_b.lower()])) + (dex,)
        self._indexed_pairs[chain].add(key)
    
    def is_indexed(self, chain: str, token_a: str, token_b: str, dex: str) -> bool:
        """Check if pair has been indexed for a dex."""
        if chain not in self._indexed_pairs:
            return False
        key = tuple(sorted([token_a.lower(), token_b.lower()])) + (dex,)
        return key in self._indexed_pairs[chain]
    
    def stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        return {
            "chains": list(self._pools.keys()),
            "pools_per_chain": {c: len(p) for c, p in self._pools.items()},
            "total_pools": sum(len(p) for p in self._pools.values()),
        }


def get_factory_address(chain: str, dex: str) -> Optional[str]:
    """Get factory address for chain/dex combo.
    
    v3.2.17: Prefers config/dexes.yaml, falls back to FACTORY_ADDRESSES.
    """
    # v3.2.17: Try dexes.yaml first (single source of truth)
    try:
        from config import load_dexes
        dexes_config = load_dexes()
        chain_dexes = dexes_config.get(chain, {})
        dex_config = chain_dexes.get(dex, {})
        factory = dex_config.get("factory")
        if factory:
            return factory
    except Exception:
        pass  # Fall back to hardcoded
    
    # Legacy fallback
    chain_factories = FACTORY_ADDRESSES.get(chain, {})
    return chain_factories.get(dex)


def query_v3_pool(
    rpc_url: str,
    factory_address: str,
    token_a: str,
    token_b: str,
    fee: int,
) -> Optional[str]:
    """
    Query Uniswap V3 factory.getPool(tokenA, tokenB, fee).
    
    Returns pool address or None if not found.
    """
    import os
    
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None
    
    try:
        from web3 import Web3
    except ImportError:
        logger.warning("web3 not installed")
        return None
    
    # v2.0.4: Use module-level V3_FACTORY_ABI (single source of truth)
    
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(factory_address),
            abi=V3_FACTORY_ABI,
        )
        
        pool_addr = factory.functions.getPool(
            Web3.to_checksum_address(token_a),
            Web3.to_checksum_address(token_b),
            fee,
        ).call()
        
        # Zero address means pool doesn't exist
        if pool_addr == "0x0000000000000000000000000000000000000000":
            return None
        
        return pool_addr.lower()
        
    except Exception as e:
        logger.debug("getPool failed: %s", e)
        return None


def query_v2_pair(
    rpc_url: str,
    factory_address: str,
    token_a: str,
    token_b: str,
) -> Optional[str]:
    """
    Query Uniswap V2 factory.getPair(tokenA, tokenB).
    
    Returns pair address or None if not found.
    """
    import os
    
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None
    
    try:
        from web3 import Web3
    except ImportError:
        logger.warning("web3 not installed")
        return None
    
    V2_FACTORY_ABI = [
        {
            "constant": True,
            "inputs": [
                {"internalType": "address", "name": "", "type": "address"},
                {"internalType": "address", "name": "", "type": "address"},
            ],
            "name": "getPair",
            "outputs": [{"internalType": "address", "name": "", "type": "address"}],
            "stateMutability": "view",
            "type": "function",
        }
    ]
    
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(factory_address),
            abi=V2_FACTORY_ABI,
        )
        
        pair_addr = factory.functions.getPair(
            Web3.to_checksum_address(token_a),
            Web3.to_checksum_address(token_b),
        ).call()
        
        # Zero address means pair doesn't exist
        if pair_addr == "0x0000000000000000000000000000000000000000":
            return None
        
        return pair_addr.lower()
        
    except Exception as e:
        logger.debug("getPair failed: %s", e)
        return None


# v3.2.17: Algebra factory ABI for poolByPair() - dynamic fee pools (Camelot, etc.)
ALGEBRA_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
        ],
        "name": "poolByPair",
        "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]


def query_algebra_pool(
    rpc_url: str,
    factory_address: str,
    token_a: str,
    token_b: str,
) -> Optional[str]:
    """
    Query Algebra factory.poolByPair(tokenA, tokenB).
    
    v3.2.17: Algebra DEXes (Camelot, THENA, etc.) use dynamic fees
    and have a single pool per pair (no fee tiers).
    
    Returns pool address or None if not found.
    """
    import os
    
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None
    
    try:
        from web3 import Web3
    except ImportError:
        logger.warning("web3 not installed")
        return None
    
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(factory_address),
            abi=ALGEBRA_FACTORY_ABI,
        )
        
        pool_addr = factory.functions.poolByPair(
            Web3.to_checksum_address(token_a),
            Web3.to_checksum_address(token_b),
        ).call()
        
        # Zero address means pool doesn't exist
        if pool_addr == "0x0000000000000000000000000000000000000000":
            return None
        
        return pool_addr.lower()
        
    except Exception as e:
        logger.debug("poolByPair failed: %s", e)
        return None


def index_intent_pairs(
    chain: str,
    dexes: Optional[List[str]] = None,
    rpc_url: Optional[str] = None,
) -> PoolIndex:
    """
    Index all intent pairs for a chain from factories.
    
    Args:
        chain: Chain to index (e.g., "arbitrum_one")
        dexes: List of DEX keys to query (default: all known for chain)
        rpc_url: RPC URL (default: from config)
        
    Returns:
        PoolIndex with discovered pools
    """
    import os
    from core.rpc_urls import get_rpc_url
    
    index = PoolIndex()
    universe = get_intent_universe()
    registry = get_token_registry()
    
    pairs = universe.get_chain_pairs(chain)
    if not pairs:
        logger.info("No intent pairs for chain %s", chain)
        return index
    
    if rpc_url is None:
        rpc_url = get_rpc_url(chain)
    
    if rpc_url is None or os.environ.get("ARBY_SKIP_RPC") == "1":
        logger.info("RPC unavailable for %s, skipping factory indexing", chain)
        return index
    
    chain_factories = FACTORY_ADDRESSES.get(chain, {})
    if dexes is None:
        dexes = list(chain_factories.keys())
    
    indexed_count = 0
    
    for pair in pairs:
        # Resolve symbols to addresses
        addr_a = registry.get_address(chain, pair.base)
        addr_b = registry.get_address(chain, pair.quote)
        
        if not addr_a:
            logger.debug("Unknown token: %s:%s", chain, pair.base)
            continue
        if not addr_b:
            logger.debug("Unknown token: %s:%s", chain, pair.quote)
            continue
        
        for dex in dexes:
            factory_addr = get_factory_address(chain, dex)
            if not factory_addr:
                continue
            
            if index.is_indexed(chain, addr_a, addr_b, dex):
                continue
            
            # V3-style DEXes
            if "v3" in dex.lower():
                for fee in V3_FEE_TIERS:
                    pool_addr = query_v3_pool(rpc_url, factory_addr, addr_a, addr_b, fee)
                    if pool_addr:
                        pool = DiscoveredPool(
                            chain=chain,
                            dex=dex,
                            address=pool_addr,
                            token0=addr_a,
                            token1=addr_b,
                            token0_symbol=pair.base,
                            token1_symbol=pair.quote,
                            fee_tier=fee,
                        )
                        index.add_pool(pool)
                        indexed_count += 1
                        logger.debug(
                            "Found %s pool: %s/%s fee=%d @ %s",
                            dex, pair.base, pair.quote, fee, pool_addr[:10]
                        )
            
            # V2-style DEXes
            elif "v2" in dex.lower():
                pair_addr = query_v2_pair(rpc_url, factory_addr, addr_a, addr_b)
                if pair_addr:
                    pool = DiscoveredPool(
                        chain=chain,
                        dex=dex,
                        address=pair_addr,
                        token0=addr_a,
                        token1=addr_b,
                        token0_symbol=pair.base,
                        token1_symbol=pair.quote,
                        fee_tier=None,
                    )
                    index.add_pool(pool)
                    indexed_count += 1
                    logger.debug(
                        "Found %s pair: %s/%s @ %s",
                        dex, pair.base, pair.quote, pair_addr[:10]
                    )
            
            index.mark_indexed(chain, addr_a, addr_b, dex)
    
    logger.info(
        "Indexed %d pools for %s from %d factories",
        indexed_count, chain, len(dexes)
    )
    
    return index


# =============================================================================
# SINGLETON INDEX
# =============================================================================

_pool_index: Optional[PoolIndex] = None


def get_pool_index() -> PoolIndex:
    """Get the singleton pool index."""
    global _pool_index
    if _pool_index is None:
        _pool_index = PoolIndex()
    return _pool_index


def reset_pool_index() -> None:
    """Reset the singleton (for testing)."""
    global _pool_index
    _pool_index = None


# =============================================================================
# DRY-RUN / CANDIDATE COUNT
# =============================================================================

def count_discovery_candidates(chain: str, dexes: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Count discovery candidates without making RPC calls (dry-run).
    
    Returns stats about how many pairs/pools could potentially be discovered
    based on intent.txt and core_tokens.yaml.
    
    Args:
        chain: Chain to analyze
        dexes: DEX list to consider (default: all known for chain)
        
    Returns:
        dict with candidate counts and details
    """
    universe = get_intent_universe()
    registry = get_token_registry()
    
    pairs = universe.get_pairs_for_chain(chain)
    chain_factories = FACTORY_ADDRESSES.get(chain, {})
    
    if dexes is None:
        dexes = list(chain_factories.keys())
    
    # Count pairs with fully resolved tokens
    resolvable_pairs = []
    unresolvable_pairs = []
    
    for pair in pairs:
        addr_a = registry.get_address(chain, pair.token_a)
        addr_b = registry.get_address(chain, pair.token_b)
        
        if addr_a and addr_b:
            resolvable_pairs.append({
                "token_a": pair.token_a,
                "token_b": pair.token_b,
                "addr_a": addr_a,
                "addr_b": addr_b,
            })
        else:
            unresolvable_pairs.append({
                "token_a": pair.token_a,
                "token_b": pair.token_b,
                "missing_a": not addr_a,
                "missing_b": not addr_b,
            })
    
    # Count potential pool queries (V3 = 4 fee tiers per pair per dex)
    v3_dexes = [d for d in dexes if "v3" in d.lower()]
    v2_dexes = [d for d in dexes if "v2" in d.lower()]
    
    potential_v3_queries = len(resolvable_pairs) * len(v3_dexes) * len(V3_FEE_TIERS)
    potential_v2_queries = len(resolvable_pairs) * len(v2_dexes)
    
    return {
        "chain": chain,
        "intent_pairs_total": len(pairs),
        "resolvable_pairs": len(resolvable_pairs),
        "unresolvable_pairs": len(unresolvable_pairs),
        "dexes_available": dexes,
        "v3_dexes": v3_dexes,
        "v2_dexes": v2_dexes,
        "potential_v3_queries": potential_v3_queries,
        "potential_v2_queries": potential_v2_queries,
        "total_potential_queries": potential_v3_queries + potential_v2_queries,
        "discovery_candidates_count": len(resolvable_pairs),
    }


# =============================================================================
# TARGETED POOL VERIFICATION (v2.3.2)
# =============================================================================

def verify_pool_exists(
    chain: str,
    dex: str,
    token_a: str,
    token_b: str,
    fee_tier: Optional[int] = None,
    rpc_url: Optional[str] = None,
) -> Optional[str]:
    """
    Verify if a pool exists via factory.getPool() / factory.getPair().
    
    This is used to reduce pool_missing_keys by querying the factory
    directly when a pool is not in the hardcoded whitelist.
    
    Args:
        chain: Chain key (e.g., "arbitrum_one")
        dex: DEX key (e.g., "uniswap_v3", "sushi")
        token_a: Token A address (checksummed or lowercase)
        token_b: Token B address (checksummed or lowercase)
        fee_tier: Fee tier for V3 (required for V3, ignored for V2)
        rpc_url: Optional RPC URL override
        
    Returns:
        Pool address if exists, None otherwise
        
    CONTRACT:
    - Returns lowercase pool address if found
    - Returns None if pool does not exist or RPC fails
    - Does NOT raise exceptions (fail-safe)
    """
    import os
    from core.rpc_urls import get_rpc_url
    
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None
    
    if rpc_url is None:
        rpc_url = get_rpc_url(chain)
    
    if not rpc_url:
        return None
    
    # Normalize dex key
    dex_lower = dex.lower()
    
    # Map common aliases
    dex_key = dex_lower
    if dex_lower == "sushi":
        dex_key = "sushiswap_v3"
    elif dex_lower == "uni":
        dex_key = "uniswap_v3"
    
    factory_addr = get_factory_address(chain, dex_key)
    if not factory_addr:
        # Try with _v2 suffix for V2 pools
        dex_key_v2 = dex_key.replace("_v3", "_v2")
        factory_addr = get_factory_address(chain, dex_key_v2)
        if factory_addr:
            # V2 pool
            return query_v2_pair(rpc_url, factory_addr, token_a, token_b)
        return None
    
    # V3 pool
    if "v3" in dex_key:
        if fee_tier is None:
            # Try common fee tiers
            for fee in V3_FEE_TIERS:
                result = query_v3_pool(rpc_url, factory_addr, token_a, token_b, fee)
                if result:
                    return result
            return None
        return query_v3_pool(rpc_url, factory_addr, token_a, token_b, fee_tier)
    
    # V2 pool
    return query_v2_pair(rpc_url, factory_addr, token_a, token_b)


def validate_pool_address(
    chain: str,
    dex: str,
    pool_address: str,
    token_a: str,
    token_b: str,
    fee_tier: Optional[int] = None,
    rpc_url: Optional[str] = None,
) -> bool:
    """
    Validate that a pool address matches the factory-returned address.
    
    Args:
        chain: Chain key
        dex: DEX key
        pool_address: Address to validate
        token_a: Token A address
        token_b: Token B address
        fee_tier: Fee tier for V3
        rpc_url: Optional RPC URL
        
    Returns:
        True if pool_address matches factory result, False otherwise
    """
    factory_addr = verify_pool_exists(
        chain=chain,
        dex=dex,
        token_a=token_a,
        token_b=token_b,
        fee_tier=fee_tier,
        rpc_url=rpc_url,
    )
    
    if factory_addr is None:
        return False
    
    return factory_addr.lower() == pool_address.lower()
