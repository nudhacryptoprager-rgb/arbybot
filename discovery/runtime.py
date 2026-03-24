# PATH: discovery/runtime.py
"""
Discovery Runtime Module - Dynamic universe expansion at runtime.

v2.4.0: Added for discovery_runtime mode.
R28.8: Removed artificial caps and adapter_type filters. All registered adapters
       now participate in discovery. See OPERATIONAL CONTRACT below.

PURPOSE:
    When discovery_runtime=true in config, this module expands the trading
    universe by resolving intent.txt pairs to pool addresses via factory.getPool().
    
CONTRACT:
    - Default: discovery_runtime=false (use hardcoded pairs from config/pairs)
    - When enabled:
        1. Reads pairs from config/intent.txt
        2. Filters to pairs with both tokens resolvable in core_tokens.yaml
        3. Uses discovery/pool_resolver.py to resolve pool addresses
        4. Respects discovery_runtime_max_pairs cap (default: 100)
        5. Returns deterministic ordering (sorted by canonical_key)
    - Observability: stats in stats["discovery_runtime"]
    
OPERATIONAL CONTRACT (R28.8):
    TRUTH GATES (must keep):
    - require_cross_dex: For DEX-DEX arb, pair must exist on 2+ DEXes
    - Quarantine: Pools can be quarantined for bad behavior
    - Confidence scoring: Spreads below threshold are advisory
    
    REMOVED SUPPRESSION (R28.8):
    - adapter_types filter: Now None (all registered adapters participate)
    - DEFAULT_MAX_PAIRS cap: Raised from 20 to 100
    
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
    decimals_a: int = 18
    decimals_b: int = 18
    
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
    pools_resolved: int = 0  # Total pools (may be > pairs_resolved)
    pairs_skipped_no_tokens: int = 0
    pairs_skipped_no_pool: int = 0
    pairs_skipped_max_cap: int = 0
    pairs_skipped_single_dex: int = 0  # Added for cross-dex filtering
    pairs_skipped_excluded: int = 0  # R24: excluded_pair_hints enforcement
    intent_pairs_count: int = 0  # R39h: Total intent pairs for this chain (before any filtering)
    pools_from_cache: int = 0
    pools_from_rpc: int = 0
    rpc_calls: int = 0
    rpc_cap_triggered: bool = False  # True if ARBY_RESOLVER_MAX_RPC_CALLS limited queries
    dexes_queried: List[str] = field(default_factory=list)
    cross_dex_pairs_count: int = 0  # Pairs with pools on 2+ dexes
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "enabled": self.enabled,
            "pairs_evaluated": self.pairs_evaluated,
            "pairs_resolved": self.pairs_resolved,
            "pools_resolved": self.pools_resolved,
            "pairs_skipped_no_tokens": self.pairs_skipped_no_tokens,
            "pairs_skipped_no_pool": self.pairs_skipped_no_pool,
            "pairs_skipped_max_cap": self.pairs_skipped_max_cap,
            "pairs_skipped_single_dex": self.pairs_skipped_single_dex,
            "pairs_skipped_excluded": self.pairs_skipped_excluded,
            "intent_pairs_count": self.intent_pairs_count,
            "pools_from_cache": self.pools_from_cache,
            "pools_from_rpc": self.pools_from_rpc,
            "rpc_calls": self.rpc_calls,
            "rpc_cap_triggered": self.rpc_cap_triggered,
            "dexes_queried": self.dexes_queried,
            "cross_dex_pairs_count": self.cross_dex_pairs_count,
            "error": self.error,
        }


# v2.0.4: Import V3_FEE_TIERS from canonical source (discovery/index_factories.py)
# RESTORE CONTRACT: discovery/index_factories.V3_FEE_TIERS is the single source of truth
# v3.2.17: Added get_chain_dexes and get_dex_fee_tiers for dexes.yaml as single source
from discovery.index_factories import (
    V3_FEE_TIERS,
    get_chain_dexes,
    get_dex_adapter_type,
    get_dex_fee_tiers,
)

# Default max pairs to resolve per cycle
# R28.8: Raised from 20 to 100 — full-universe scan, not artificial suppression
DEFAULT_MAX_PAIRS = 100


def _matches_excluded_hint(pair_display: str, hints: List[str]) -> bool:
    """Check if a pair like 'WETH/USDT' matches any excluded_pair_hints glob.

    Supported patterns:
        'TOKEN_A/TOKEN_B' — exact match
        'TOKEN/*'         — any pair where TOKEN is on the left
        '*/TOKEN'         — any pair where TOKEN is on the right
    """
    a, _, b = pair_display.partition("/")
    if not b:
        return False
    a_up, b_up = a.upper(), b.upper()
    for hint in hints:
        h = hint.strip()
        if not h:
            continue
        ha, _, hb = h.partition("/")
        ha_up, hb_up = ha.upper(), hb.upper()
        if ha_up == "*" and hb_up == b_up:
            return True
        if hb_up == "*" and ha_up == a_up:
            return True
        if ha_up == a_up and hb_up == b_up:
            return True
    return False


def resolve_runtime_pairs(
    chain: str,
    dexes: Optional[List[str]] = None,
    max_pairs: int = DEFAULT_MAX_PAIRS,
    fee_tiers: Optional[List[int]] = None,
    rpc_url: Optional[str] = None,
    require_cross_dex: bool = False,
    excluded_pair_hints: Optional[List[str]] = None,
) -> tuple[List[RuntimePair], RuntimeStats]:
    """
    Resolve intent.txt pairs to pool addresses via factory.getPool().
    
    Args:
        chain: Chain key (e.g., "arbitrum_one")
        dexes: List of DEX keys to query (default: all V3 dexes for chain)
        max_pairs: Maximum pairs to resolve per call (deterministic cap)
        fee_tiers: V3 fee tiers to query (default: [100, 500, 3000, 10000])
        rpc_url: RPC URL (optional, will use default if not provided)
        require_cross_dex: If True, only include pairs with pools on 2+ dexes
        excluded_pair_hints: Glob patterns to exclude (e.g. ['cbBTC/*', '*/USDT'])
        
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
        # v3.2.17: Removed FACTORY_ADDRESSES import - now uses get_chain_dexes()
    except ImportError as e:
        logger.warning("Discovery runtime dependencies not available: %s", e)
        stats.enabled = False
        stats.error = f"ImportError: {e}"
        return [], stats
    
    # Get intent universe
    universe = get_intent_universe()
    registry = get_token_registry()
    resolver = get_pool_resolver(chain)  # v3.2.16: Chain-scoped cache
    
    # Get pairs for chain
    intent_pairs = universe.get_pairs_for_chain(chain)
    if not intent_pairs:
        logger.debug("No intent pairs for chain %s", chain)
        stats.error = f"no_intent_pairs_for_{chain}"
        return [], stats
    
    # v3.2.17: Determine dexes to query from dexes.yaml (single source of truth)
    # R28.8: Include ALL adapter types — ve33 and uniswap_v2 were silently excluded
    if dexes is None:
        dexes = get_chain_dexes(chain, adapter_types=None)
    stats.dexes_queried = dexes
    
    # v3.2.17: fee_tiers now handled per-DEX inside the loop (see below)
    
    # Sort pairs deterministically for consistent ordering
    sorted_pairs = sorted(intent_pairs, key=lambda p: p.canonical_key)
    stats.intent_pairs_count = len(sorted_pairs)  # R39h: Before any filtering
    
    resolved: List[RuntimePair] = []
    seen_pairs: Set[str] = set()  # Dedupe by canonical pair key (without dex/fee)
    
    for pair in sorted_pairs:
        # v3.2.17: Fix cap logic - max_pairs means unique PAIRS, not pools
        if len(seen_pairs) >= max_pairs:
            stats.pairs_skipped_max_cap += len(sorted_pairs) - len(seen_pairs) - stats.pairs_skipped_max_cap
            break
        
        # Canonical pair key for deduplication
        canonical_pair = f"{chain}:{sorted([pair.token_a, pair.token_b])[0]}/{sorted([pair.token_a, pair.token_b])[1]}"
        if canonical_pair in seen_pairs:
            continue
        
        stats.pairs_evaluated += 1
        
        # R24: Enforce excluded_pair_hints BEFORE token/pool resolution
        if excluded_pair_hints:
            display_fwd = f"{pair.token_a}/{pair.token_b}"
            display_rev = f"{pair.token_b}/{pair.token_a}"
            if _matches_excluded_hint(display_fwd, excluded_pair_hints) or \
               _matches_excluded_hint(display_rev, excluded_pair_hints):
                stats.pairs_skipped_excluded += 1
                logger.debug(
                    "Skipping pair %s: matched excluded_pair_hints",
                    display_fwd,
                )
                continue
        
        # Resolve token info (address + decimals)
        token_a_info = registry.get_token(chain, pair.token_a)
        token_b_info = registry.get_token(chain, pair.token_b)
        
        if not token_a_info or not token_b_info:
            stats.pairs_skipped_no_tokens += 1
            logger.debug(
                "Skipping pair %s/%s: missing token info (a=%s, b=%s)",
                pair.token_a, pair.token_b, bool(token_a_info), bool(token_b_info)
            )
            continue
        
        addr_a = token_a_info.address
        addr_b = token_b_info.address
        decimals_a = token_a_info.decimals
        decimals_b = token_b_info.decimals
        
        # Collect ALL valid pools for this pair (for cross-dex detection)
        pair_pools: List[RuntimePair] = []
        dexes_with_pools: Set[str] = set()
        
        for dex in dexes:
            adapter_type = get_dex_adapter_type(chain, dex) or "unknown"
            
            # Per-adapter fee/variant semantics:
            # - uniswap_v3: real fee tiers (100/500/3000/10000, etc.)
            # - algebra: dynamic fee pools -> use fee=0 sentinel (canonical)
            # - ve33: stable/volatile variants -> use fee=0 (volatile), fee=1 (stable)
            # - v2/unknown: use fee=0 sentinel (canonical)
            if adapter_type == "uniswap_v3":
                dex_fee_tiers = fee_tiers if fee_tiers is not None else get_dex_fee_tiers(chain, dex)
            elif adapter_type == "algebra":
                dex_fee_tiers = [0]
            elif adapter_type == "ve33":
                dex_fee_tiers = fee_tiers if fee_tiers is not None else [0, 1]
            else:
                dex_fee_tiers = [0]
            
            for fee in dex_fee_tiers:
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
                    pair_pools.append(RuntimePair(
                        chain=chain,
                        token_a=pair.token_a,
                        token_b=pair.token_b,
                        addr_a=addr_a,
                        addr_b=addr_b,
                        dex=dex,
                        fee=fee,
                        pool_address=pool_addr,
                        decimals_a=decimals_a,
                        decimals_b=decimals_b,
                    ))
                    dexes_with_pools.add(dex)
        
        if not pair_pools:
            stats.pairs_skipped_no_pool += 1
            continue
        
        # Cross-dex filtering
        is_cross_dex = len(dexes_with_pools) >= 2
        if is_cross_dex:
            stats.cross_dex_pairs_count += 1
        
        if require_cross_dex and not is_cross_dex:
            stats.pairs_skipped_single_dex += 1
            logger.debug(
                "Skipping pair %s/%s: single dex only (%s)",
                pair.token_a, pair.token_b, list(dexes_with_pools)
            )
            continue
        
        # Add ALL pools for this pair (one per DEX/fee combination)
        # This preserves route coverage for cross-DEX arbitrage
        seen_pairs.add(canonical_pair)
        resolved.extend(pair_pools)
        stats.pairs_resolved += 1
        stats.pools_resolved += len(pair_pools)
    
    # Collect resolver stats
    resolver_stats = resolver.get_stats()
    stats.pools_from_cache = resolver_stats["hits"] + resolver_stats["negative_hits"]
    stats.pools_from_rpc = resolver_stats["misses"]
    stats.rpc_calls = resolver_stats["rpc_calls"]
    stats.rpc_cap_triggered = resolver_stats.get("cap_triggered", False)
    
    # Save resolver cache for persistence
    resolver.flush()
    
    logger.info(
        "Discovery runtime: %d pairs (%d pools, %d cross-dex), skipped: tokens=%d, pool=%d, single_dex=%d, excluded=%d, cap=%d",
        stats.pairs_resolved,
        stats.pools_resolved,
        stats.cross_dex_pairs_count,
        stats.pairs_skipped_no_tokens,
        stats.pairs_skipped_no_pool,
        stats.pairs_skipped_single_dex,
        stats.pairs_skipped_excluded,
        stats.pairs_skipped_max_cap,
    )
    
    return resolved, stats


def get_runtime_observability(stats: RuntimeStats) -> Dict[str, Any]:
    """
    Get observability dict for artifact stats.
    
    Returns dict to be merged into stats["discovery_runtime"].
    """
    return stats.to_dict()


def runtime_pairs_to_pair_configs(resolved_pairs: List[RuntimePair]) -> List:
    """
    Convert RuntimePairs to PairConfig objects for quoting.
    
    This function enables discovery_runtime to affect the quote universe.
    Aggregates fee_tiers from all pools per pair across DEXes.
    Stores pool_info with (dex, fee, address) mapping for quote pipeline.
    
    Args:
        resolved_pairs: List of RuntimePair objects from resolve_runtime_pairs()
        
    Returns:
        List of PairConfig objects usable by the quoting pipeline
    """
    from config.pairs import PairConfig
    from collections import defaultdict
    
    # Group pools by pair key to aggregate fee_tiers and pool_addresses
    pair_data = defaultdict(lambda: {
        "chain": None,
        "token_a": None,
        "token_b": None,
        "addr_a": None,
        "addr_b": None,
        "decimals_a": None,
        "decimals_b": None,
        "fee_tiers": set(),
        "pool_addresses": [],
        "pool_info": [],  # v2.6.0: [{dex, fee, address}, ...]
        "dexes": set(),
    })
    
    for rp in resolved_pairs:
        # Canonical pair key
        pair_key = f"{rp.chain}:{sorted([rp.token_a, rp.token_b])[0]}/{sorted([rp.token_a, rp.token_b])[1]}"
        
        data = pair_data[pair_key]
        if data["chain"] is None:
            data["chain"] = rp.chain
            data["token_a"] = rp.token_a
            data["token_b"] = rp.token_b
            data["addr_a"] = rp.addr_a
            data["addr_b"] = rp.addr_b
            data["decimals_a"] = rp.decimals_a
            data["decimals_b"] = rp.decimals_b
        
        if rp.fee is not None:
            data["fee_tiers"].add(rp.fee)
        data["pool_addresses"].append(rp.pool_address)
        data["pool_info"].append({
            "dex": rp.dex,
            "fee": rp.fee,
            "address": rp.pool_address,
        })
        data["dexes"].add(rp.dex)
    
    result = []
    for pair_key, data in sorted(pair_data.items()):
        # Default fee tiers if none collected
        fee_tiers = sorted(data["fee_tiers"]) if data["fee_tiers"] else [500, 3000]
        
        result.append(PairConfig(
            chain=data["chain"],
            token_in=data["token_a"],
            token_out=data["token_b"],
            token_in_address=data["addr_a"],
            token_out_address=data["addr_b"],
            token_in_decimals=data["decimals_a"],
            token_out_decimals=data["decimals_b"],
            fee_tiers=fee_tiers,
            pool_addresses=data["pool_addresses"],  # Pre-resolved for slot0/liquidity prefetch
            pool_info=data["pool_info"],  # v2.6.0: dex/fee/address mapping for quote pipeline
        ))
    
    return result
