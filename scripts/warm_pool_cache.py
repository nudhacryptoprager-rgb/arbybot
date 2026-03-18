#!/usr/bin/env python
# PATH: scripts/warm_pool_cache.py
"""
Warm Pool Cache CLI - Pre-populate pool resolver caches from intent.txt.

v1.2.0: Fixed MulticallBatcher import, added pair diagnostics to JSON output.
v1.1.0: Added --check-liquidity, --dex audit mode, adapter_type-based fee tiers.

PURPOSE:
    Read config/intent.txt and warm pool_resolver_cache_<chain>.json
    strictly by intent-pairs. Reports diagnostics per chain/dex/pair.

DIAGNOSTICS:
    - no_token: Token not found in core_tokens.yaml
    - no_pool: Factory.getPool() returned zero address
    - no_quoter: DEX has no quoter contract configured
    - zero_liquidity: Pool exists but liquidity=0 (requires --check-liquidity)
    - single_dex_only: Pair found on only 1 DEX (no cross-DEX arb possible)

USAGE:
    # Warm all chains in intent.txt
    py -3.11 scripts/warm_pool_cache.py
    
    # Warm specific chain
    py -3.11 scripts/warm_pool_cache.py --chain scroll
    
    # Show detailed diagnostics
    py -3.11 scripts/warm_pool_cache.py --chain scroll --verbose
    
    # Rank DEXes by cross-dex coverage (for finding 2nd DEX candidates)
    py -3.11 scripts/warm_pool_cache.py --chain scroll --rank-dexes
    
    # Check pool liquidity (adds RPC calls)
    py -3.11 scripts/warm_pool_cache.py --chain scroll --check-liquidity
    
    # Audit a candidate DEX not yet in dexes.yaml
    py -3.11 scripts/warm_pool_cache.py --chain scroll --dex izi_swap --dex pancakeswap_v3

OUTPUT:
    - Warms data/cache/pool_resolver_cache_<chain>.json
    - Prints summary statistics per chain
    - With --rank-dexes: shows candidates for 2nd DEX by cross_dex_pairs potential
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from discovery.intent_loader import load_intent, IntentPair
from discovery.pool_resolver import get_pool_resolver, PoolResolver
from discovery.verify import get_token_registry

logger = logging.getLogger("scripts.warm_pool_cache")

__version__ = "1.2.0"


@dataclass
class PairDiagnostic:
    """Diagnostic result for a single pair."""
    chain: str
    pair: str  # e.g., "WETH/USDC"
    token_a: str
    token_b: str
    token_a_addr: Optional[str] = None
    token_b_addr: Optional[str] = None
    
    # Per-DEX results: dex_key -> pool_address or diagnostic
    dex_results: Dict[str, str] = field(default_factory=dict)
    
    # Diagnostics
    no_token: List[str] = field(default_factory=list)  # Missing tokens
    no_pool: List[str] = field(default_factory=list)   # DEXes with no pool
    no_quoter: List[str] = field(default_factory=list)  # DEXes with no quoter
    zero_liquidity: List[str] = field(default_factory=list)  # Pools with 0 liquidity
    pool_found: List[str] = field(default_factory=list)  # DEXes with valid pool
    
    @property
    def dex_count(self) -> int:
        """Number of DEXes with valid pools."""
        return len(self.pool_found)
    
    @property
    def is_cross_dex(self) -> bool:
        """True if pair found on 2+ DEXes."""
        return self.dex_count >= 2
    
    @property
    def status(self) -> str:
        """Overall status of this pair."""
        if self.no_token:
            return "NO_TOKEN"
        if not self.pool_found:
            return "NO_POOL"
        if not self.is_cross_dex:
            return "SINGLE_DEX"
        return "CROSS_DEX"


@dataclass
class ChainSummary:
    """Summary of warm results for a chain."""
    chain: str
    total_pairs: int = 0
    cross_dex_pairs: int = 0
    single_dex_pairs: int = 0
    no_pool_pairs: int = 0
    no_token_pairs: int = 0
    
    # Per-DEX coverage
    dex_coverage: Dict[str, int] = field(default_factory=dict)  # dex -> pair_count
    
    pair_diagnostics: List[PairDiagnostic] = field(default_factory=list)
    
    @property
    def coverage_rate(self) -> float:
        """Percentage of pairs with at least one pool."""
        if self.total_pairs == 0:
            return 0.0
        return (self.cross_dex_pairs + self.single_dex_pairs) / self.total_pairs * 100
    
    @property
    def cross_dex_rate(self) -> float:
        """Percentage of pairs with cross-DEX coverage."""
        if self.total_pairs == 0:
            return 0.0
        return self.cross_dex_pairs / self.total_pairs * 100


def get_chain_dexes(chain: str) -> List[str]:
    """Get list of DEXes for a chain from dexes.yaml."""
    dexes_path = Path("config/dexes.yaml")
    if not dexes_path.exists():
        logger.warning("dexes.yaml not found")
        return []
    
    import yaml
    with open(dexes_path) as f:
        dexes_config = yaml.safe_load(f) or {}
    
    chain_dexes = dexes_config.get(chain, {})
    if not chain_dexes:
        return []
    
    return list(chain_dexes.keys())


def get_dex_fee_tiers(chain: str, dex: str) -> List[Optional[int]]:
    """
    Get fee tiers to try for a DEX.
    
    Uses adapter_type from dexes.yaml (canonical) instead of name matching.
    Priority:
    1. Explicit fee_tiers in dexes.yaml
    2. Default based on adapter_type
    3. Fallback to [None]
    """
    dexes_path = Path("config/dexes.yaml")
    if not dexes_path.exists():
        return [None]
    
    import yaml
    with open(dexes_path) as f:
        dexes_config = yaml.safe_load(f) or {}
    
    dex_config = dexes_config.get(chain, {}).get(dex, {})
    
    # 1. Explicit fee_tiers in config (highest priority)
    if "fee_tiers" in dex_config:
        return dex_config["fee_tiers"]
    
    # 2. Default based on adapter_type
    adapter_type = dex_config.get("adapter_type", "")
    
    if adapter_type == "uniswap_v3":
        return [100, 500, 3000, 10000]  # Standard Uniswap V3 fee tiers
    elif adapter_type == "algebra":
        return [0]  # Algebra uses dynamic fees (fee_tier=0)
    elif adapter_type == "ve33":
        return [0, 1]  # 0=volatile, 1=stable
    
    # 3. Fallback: try no fee tier
    return [None]


def warm_pair(
    chain: str,
    pair: IntentPair,
    dexes: List[str],
    resolver: PoolResolver,
    rpc_url: str,
    verbose: bool = False,
) -> PairDiagnostic:
    """Warm cache for a single pair across all DEXes."""
    from discovery.verify import get_token_registry
    
    registry = get_token_registry()
    
    diag = PairDiagnostic(
        chain=chain,
        pair=f"{pair.token_a}/{pair.token_b}",
        token_a=pair.token_a,
        token_b=pair.token_b,
    )
    
    # Resolve token addresses
    addr_a = registry.get_address(chain, pair.token_a)
    addr_b = registry.get_address(chain, pair.token_b)
    
    diag.token_a_addr = addr_a
    diag.token_b_addr = addr_b
    
    if not addr_a:
        diag.no_token.append(pair.token_a)
    if not addr_b:
        diag.no_token.append(pair.token_b)
    
    if diag.no_token:
        if verbose:
            logger.warning(f"  {diag.pair}: NO_TOKEN {diag.no_token}")
        return diag
    
    # Try each DEX
    for dex in dexes:
        fee_tiers = get_dex_fee_tiers(chain, dex)
        pool_found = False
        
        for fee in fee_tiers:
            try:
                pool = resolver.resolve(
                    chain=chain,
                    dex=dex,
                    symbol_a=pair.token_a,
                    symbol_b=pair.token_b,
                    fee=fee,
                    rpc_url=rpc_url,
                )
                
                if pool and pool != "0x0000000000000000000000000000000000000000":
                    diag.dex_results[f"{dex}:{fee}"] = pool
                    pool_found = True
                    if dex not in diag.pool_found:
                        diag.pool_found.append(dex)
                    if verbose:
                        logger.info(f"  {diag.pair} @ {dex}:{fee} -> {pool[:10]}...")
                    # Don't break - try all fee tiers for coverage
                    
            except Exception as e:
                if "quoter" in str(e).lower():
                    if dex not in diag.no_quoter:
                        diag.no_quoter.append(dex)
                if verbose:
                    logger.debug(f"  {diag.pair} @ {dex}:{fee}: {e}")
        
        if not pool_found and dex not in diag.no_pool and dex not in diag.no_quoter:
            diag.no_pool.append(dex)
    
    return diag


def warm_chain(
    chain: str,
    pairs: List[IntentPair],
    rpc_url: Optional[str] = None,
    verbose: bool = False,
    check_liquidity: bool = False,
    extra_dexes: Optional[List[str]] = None,
) -> ChainSummary:
    """Warm cache for all pairs on a chain."""
    from core.rpc_urls import get_rpc_url
    
    # Get RPC URL
    if not rpc_url:
        # Try to get from environment or default
        rpc_url = get_rpc_url(chain)
    
    if not rpc_url:
        logger.error(f"No RPC URL for chain {chain}")
        return ChainSummary(chain=chain)
    
    # Get DEXes for this chain
    dexes = get_chain_dexes(chain)
    configured_dexes = set(dexes)  # DEXes actually configured in dexes.yaml
    
    # Add extra DEXes from --dex flag (for auditing candidates not in dexes.yaml)
    # Note: Extra DEXes without config in dexes.yaml will fail pool resolution
    if extra_dexes:
        for dex in extra_dexes:
            if dex not in dexes:
                dexes.append(dex)
                if dex not in configured_dexes:
                    logger.warning(f"  WARN: DEX '{dex}' not in dexes.yaml for chain '{chain}' - "
                                   f"add factory/quoter config or expect NO_POOL results")
    
    if not dexes:
        logger.warning(f"No DEXes configured for chain {chain}")
        return ChainSummary(chain=chain)
    
    logger.info(f"Warming {chain}: {len(pairs)} pairs, {len(dexes)} DEXes")
    logger.info(f"  DEXes: {', '.join(dexes)}")
    logger.info(f"  RPC: {rpc_url}")
    if check_liquidity:
        logger.info(f"  Liquidity check: ENABLED")
    
    # Get chain-scoped resolver
    resolver = get_pool_resolver(chain)
    
    summary = ChainSummary(chain=chain, total_pairs=len(pairs))
    
    # Collect all pool addresses for batch liquidity check
    pool_addresses_map = {}  # pool_address -> (diag, dex)
    
    for pair in pairs:
        diag = warm_pair(chain, pair, dexes, resolver, rpc_url, verbose)
        summary.pair_diagnostics.append(diag)
        
        # Collect pool addresses for liquidity check
        if check_liquidity:
            for dex_fee, pool_addr in diag.dex_results.items():
                if pool_addr and pool_addr != "0x0000000000000000000000000000000000000000":
                    pool_addresses_map[pool_addr] = (diag, dex_fee.split(":")[0])
        
        # Update counters
        if diag.status == "NO_TOKEN":
            summary.no_token_pairs += 1
        elif diag.status == "NO_POOL":
            summary.no_pool_pairs += 1
        elif diag.status == "SINGLE_DEX":
            summary.single_dex_pairs += 1
        elif diag.status == "CROSS_DEX":
            summary.cross_dex_pairs += 1
        
        # Update DEX coverage
        for dex in diag.pool_found:
            summary.dex_coverage[dex] = summary.dex_coverage.get(dex, 0) + 1
    
    # Batch liquidity check if enabled
    if check_liquidity and pool_addresses_map:
        logger.info(f"Checking liquidity for {len(pool_addresses_map)} pools...")
        try:
            from core.multicall import MulticallBatcher
            
            # Use block 0 (latest) for liquidity check
            mc = MulticallBatcher(rpc_url, 0)
            
            pool_list = list(pool_addresses_map.keys())
            try:
                liquidities = mc.batch_liquidity(pool_list)
            except Exception as batch_err:
                # Multicall decode failure — fall back to per-pool calls
                logger.warning(f"Batch liquidity failed, falling back to per-pool: {batch_err}")
                liquidities = {}
                for addr in pool_list:
                    try:
                        single = mc.batch_liquidity([addr])
                        liquidities.update(single)
                    except Exception:
                        liquidities[addr] = None
            
            zero_count = 0
            for pool_addr, liq in liquidities.items():
                if liq is not None and liq == 0:
                    diag, dex = pool_addresses_map[pool_addr]
                    if dex not in diag.zero_liquidity:
                        diag.zero_liquidity.append(dex)
                        zero_count += 1
            
            if zero_count > 0:
                logger.warning(f"Found {zero_count} pools with zero liquidity")
        except Exception as e:
            logger.warning(f"Liquidity check failed: {e}")
    
    # Save cache
    resolver._save_cache()
    
    return summary


def rank_dexes_for_chain(summary: ChainSummary) -> List[Tuple[str, int, int]]:
    """
    Rank DEXes by potential cross-DEX contribution.
    
    Returns list of (dex, current_coverage, potential_cross_dex_gain).
    """
    rankings = []
    
    for dex, coverage in sorted(summary.dex_coverage.items(), key=lambda x: -x[1]):
        # Calculate how many single-dex pairs this DEX could promote to cross-dex
        # if we added another DEX
        potential_gain = 0
        for diag in summary.pair_diagnostics:
            if diag.status == "SINGLE_DEX" and dex in diag.pool_found:
                potential_gain += 1
        
        rankings.append((dex, coverage, potential_gain))
    
    return rankings


def print_summary(summary: ChainSummary, verbose: bool = False, rank_dexes: bool = False):
    """Print summary for a chain."""
    print(f"\n{'='*60}")
    print(f"CHAIN: {summary.chain}")
    print(f"{'='*60}")
    print(f"  Total pairs:       {summary.total_pairs}")
    print(f"  Cross-DEX pairs:   {summary.cross_dex_pairs} ({summary.cross_dex_rate:.1f}%)")
    print(f"  Single-DEX pairs:  {summary.single_dex_pairs}")
    print(f"  No pool:           {summary.no_pool_pairs}")
    print(f"  No token:          {summary.no_token_pairs}")
    print(f"  Coverage rate:     {summary.coverage_rate:.1f}%")
    
    print(f"\nDEX Coverage:")
    for dex, count in sorted(summary.dex_coverage.items(), key=lambda x: -x[1]):
        print(f"  {dex}: {count} pairs")
    
    if rank_dexes:
        print(f"\nDEX Ranking (for 2nd DEX candidates):")
        rankings = rank_dexes_for_chain(summary)
        for dex, coverage, gain in rankings:
            print(f"  {dex}: {coverage} pairs, +{gain} potential cross-DEX")
    
    if verbose:
        print(f"\nPair Details:")
        for diag in summary.pair_diagnostics:
            status_icon = {
                "CROSS_DEX": "+",
                "SINGLE_DEX": "~",
                "NO_POOL": "x",
                "NO_TOKEN": "?",
            }.get(diag.status, "?")
            dexes_str = ", ".join(diag.pool_found) if diag.pool_found else "none"
            issues = []
            if diag.no_token:
                issues.append(f"no_token:{diag.no_token}")
            if diag.no_pool:
                issues.append(f"no_pool:{diag.no_pool}")
            if diag.no_quoter:
                issues.append(f"no_quoter:{diag.no_quoter}")
            issues_str = "; ".join(issues) if issues else ""
            print(f"  {status_icon} {diag.pair}: {diag.status} [{dexes_str}] {issues_str}")


def main():
    parser = argparse.ArgumentParser(
        description="Warm pool resolver caches from intent.txt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--chain",
        type=str,
        help="Specific chain to warm (default: all chains in intent.txt)",
    )
    parser.add_argument(
        "--intent-file",
        type=str,
        default="config/intent.txt",
        help="Path to intent file (default: config/intent.txt)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed diagnostics per pair",
    )
    parser.add_argument(
        "--rank-dexes",
        action="store_true",
        help="Rank DEXes by cross-DEX contribution potential",
    )
    parser.add_argument(
        "--rpc-url",
        type=str,
        help="Override RPC URL (for single-chain mode)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--check-liquidity",
        action="store_true",
        help="Check pool liquidity via multicall (slower, requires RPC)",
    )
    parser.add_argument(
        "--dex",
        type=str,
        action="append",
        help="Audit specific DEX (can specify multiple times). Use for finding 2nd DEX candidates not yet in dexes.yaml",
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s %(name)s: %(message)s",
    )
    
    print(f"Warm Pool Cache v{__version__}")
    print(f"Intent file: {args.intent_file}")
    
    # Load intent universe
    try:
        universe = load_intent(Path(args.intent_file))
    except Exception as e:
        logger.error(f"Failed to load intent file: {e}")
        return 1
    
    chains = universe.get_all_chains()
    if args.chain:
        if args.chain not in chains:
            logger.error(f"Chain '{args.chain}' not in intent file. Available: {chains}")
            return 1
        chains = [args.chain]
    
    print(f"Chains to warm: {', '.join(chains)}")
    
    summaries = []
    for chain in chains:
        pairs = universe.get_pairs_for_chain(chain)
        summary = warm_chain(
            chain,
            pairs,
            rpc_url=args.rpc_url,
            verbose=args.verbose,
            check_liquidity=args.check_liquidity,
            extra_dexes=args.dex,
        )
        summaries.append(summary)
        
        if not args.json:
            print_summary(summary, args.verbose, args.rank_dexes)
    
    if args.json:
        output = {
            "version": __version__,
            "summaries": [
                {
                    "chain": s.chain,
                    "total_pairs": s.total_pairs,
                    "cross_dex_pairs": s.cross_dex_pairs,
                    "single_dex_pairs": s.single_dex_pairs,
                    "no_pool_pairs": s.no_pool_pairs,
                    "no_token_pairs": s.no_token_pairs,
                    "coverage_rate": s.coverage_rate,
                    "cross_dex_rate": s.cross_dex_rate,
                    "dex_coverage": s.dex_coverage,
                    # v1.1.1: Include pair-level diagnostics for audit artifact generation
                    "pair_diagnostics": [
                        {
                            "pair": d.pair,
                            "status": d.status,
                            "dex_count": d.dex_count,
                            "pool_found": d.pool_found,
                            "no_token": d.no_token,
                            "no_pool": d.no_pool,
                            "no_quoter": d.no_quoter,
                            "zero_liquidity": d.zero_liquidity,
                            "dex_results": d.dex_results,
                        }
                        for d in s.pair_diagnostics
                    ],
                }
                for s in summaries
            ],
        }
        print(json.dumps(output, indent=2))
    
    # Summary across all chains
    if not args.json and len(summaries) > 1:
        print(f"\n{'='*60}")
        print("OVERALL SUMMARY")
        print(f"{'='*60}")
        total_pairs = sum(s.total_pairs for s in summaries)
        total_cross = sum(s.cross_dex_pairs for s in summaries)
        total_single = sum(s.single_dex_pairs for s in summaries)
        total_no_pool = sum(s.no_pool_pairs for s in summaries)
        print(f"  Total pairs:     {total_pairs}")
        print(f"  Cross-DEX:       {total_cross}")
        print(f"  Single-DEX:      {total_single}")
        print(f"  No pool:         {total_no_pool}")
        if total_pairs > 0:
            print(f"  Cross-DEX rate:  {total_cross/total_pairs*100:.1f}%")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
