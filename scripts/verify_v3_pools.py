#!/usr/bin/env python3
"""Verify V3 pool addresses via Factory.getPool() on Arbitrum.

This script queries the Uniswap V3 and SushiSwap V3 factories to verify
that pool addresses exist for given token pairs before adding them to config.

Usage:
    python scripts/verify_v3_pools.py                    # Verify default pairs
    python scripts/verify_v3_pools.py --pairs LINK/USDC ARB/USDT
    python scripts/verify_v3_pools.py --output pools.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from web3 import Web3
except ImportError:
    print("ERROR: web3 not installed. Run: pip install web3")
    sys.exit(1)

# RPC
RPC_URL = os.environ.get('ARBY_RPC_HTTP_PRIMARY', 'https://arb1.arbitrum.io/rpc')

# Factory addresses on Arbitrum
FACTORIES = {
    "uniswap_v3": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "sushiswap_v3": "0x1af415a1EbA07a4986a52B6f2e7dE7003D82231e",
}

# Tokens on Arbitrum (checksummed)
TOKENS = {
    "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
    "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
    "WBTC": "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",
    "ARB": "0x912CE59144191C1204E64559FE8253a0e49E6548",
    "LINK": "0xf97f4df75117a78c1A5a0DBb814Af92458539FB4",
    "wstETH": "0x5979D7b546E38E414F7E9822514be443A4800529",
    "GMX": "0xfc5A1A6EB076a2C7aD06eD22C90d7E710E35ad0a",
    "DAI": "0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1",
}

# Default pairs to verify (expansion targets)
DEFAULT_PAIRS = [
    ("LINK", "USDC"),
    ("ARB", "USDT"),
    ("LINK", "USDT"),
    ("LINK", "WETH"),
    ("ARB", "WETH"),
    ("ARB", "USDC"),
    ("WETH", "USDC"),
    ("WETH", "USDT"),
]

# Fee tiers to check
FEE_TIERS = [100, 500, 3000, 10000]

# Factory ABI (getPool function)
FACTORY_ABI = [{
    "inputs": [
        {"name": "tokenA", "type": "address"},
        {"name": "tokenB", "type": "address"},
        {"name": "fee", "type": "uint24"}
    ],
    "name": "getPool",
    "outputs": [{"name": "pool", "type": "address"}],
    "stateMutability": "view",
    "type": "function"
}]

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def parse_pair(pair_str: str) -> tuple[str, str]:
    """Parse 'TOKEN0/TOKEN1' string into tuple."""
    parts = pair_str.strip().upper().split("/")
    if len(parts) != 2:
        raise ValueError(f"Invalid pair format: {pair_str}, expected TOKEN0/TOKEN1")
    return parts[0], parts[1]


def verify_pools(
    pairs: list[tuple[str, str]],
    verbose: bool = False
) -> dict[str, Any]:
    """Verify pool addresses for given pairs across all factories and fee tiers.
    
    Returns dict with verification results.
    """
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    
    if not w3.is_connected():
        return {"error": f"Cannot connect to RPC: {RPC_URL}"}
    
    results = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "rpc": RPC_URL,
        "chain_id": w3.eth.chain_id,
        "factories": FACTORIES,
        "tokens": TOKENS,
        "pairs_checked": [],
        "verified_pools": [],
        "missing_pools": [],
        "summary": {
            "total_pairs": len(pairs),
            "pairs_with_pools": 0,
            "pairs_missing_all": 0,
        }
    }
    
    for base, quote in pairs:
        if base not in TOKENS:
            print(f"WARNING: Unknown token {base}, skipping pair {base}/{quote}")
            continue
        if quote not in TOKENS:
            print(f"WARNING: Unknown token {quote}, skipping pair {base}/{quote}")
            continue
        
        pair_key = f"{base}/{quote}"
        results["pairs_checked"].append(pair_key)
        
        base_addr = Web3.to_checksum_address(TOKENS[base])
        quote_addr = Web3.to_checksum_address(TOKENS[quote])
        
        found_any = False
        
        for dex_name, factory_addr in FACTORIES.items():
            factory = w3.eth.contract(
                address=Web3.to_checksum_address(factory_addr),
                abi=FACTORY_ABI
            )
            
            for fee in FEE_TIERS:
                try:
                    pool_addr = factory.functions.getPool(base_addr, quote_addr, fee).call()
                    
                    if pool_addr != ZERO_ADDRESS:
                        pool_info = {
                            "pair": pair_key,
                            "dex": dex_name,
                            "fee": fee,
                            "pool": pool_addr,
                            "base": base,
                            "quote": quote,
                        }
                        results["verified_pools"].append(pool_info)
                        found_any = True
                        
                        if verbose:
                            print(f"  [OK] {dex_name} {pair_key} fee={fee}: {pool_addr}")
                    elif verbose:
                        print(f"  [--] {dex_name} {pair_key} fee={fee}: no pool")
                        
                except Exception as e:
                    if verbose:
                        print(f"  [ERR] {dex_name} {pair_key} fee={fee}: {e}")
        
        if found_any:
            results["summary"]["pairs_with_pools"] += 1
        else:
            results["missing_pools"].append(pair_key)
            results["summary"]["pairs_missing_all"] += 1
    
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify V3 pool addresses on Arbitrum")
    parser.add_argument("--pairs", nargs="+", help="Pairs to verify (e.g., LINK/USDC ARB/USDT)")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()
    
    # Parse pairs
    if args.pairs:
        pairs = [parse_pair(p) for p in args.pairs]
    else:
        pairs = DEFAULT_PAIRS
    
    print(f"Pool Verifier (V3 Factories on Arbitrum)")
    print(f"RPC: {RPC_URL}")
    print(f"Pairs to check: {len(pairs)}")
    print("=" * 50)
    
    results = verify_pools(pairs, verbose=args.verbose)
    
    if "error" in results:
        print(f"[ERROR] {results['error']}")
        return 1
    
    # Summary
    print()
    print(f"Summary:")
    print(f"  Pairs checked: {results['summary']['total_pairs']}")
    print(f"  Pairs with pools: {results['summary']['pairs_with_pools']}")
    print(f"  Pairs missing all: {results['summary']['pairs_missing_all']}")
    print(f"  Total verified pools: {len(results['verified_pools'])}")
    
    if results["missing_pools"]:
        print(f"\nMissing pairs (no pools found):")
        for p in results["missing_pools"]:
            print(f"  - {p}")
    
    # Output
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {output_path}")
    else:
        # Default: save to gitignored location (data/runs/_rolling/)
        default_path = Path(__file__).parent.parent / "data" / "runs" / "_rolling" / "verified_pools.json"
        default_path.parent.mkdir(parents=True, exist_ok=True)
        with open(default_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {default_path}")
    
    # Exit code based on results
    if results["summary"]["pairs_missing_all"] > 0:
        print("\n[WARN] Some pairs have no pools on any DEX")
        return 0  # Still success, just warning
    
    print("\n[OK] All pairs have at least one verified pool")
    return 0


if __name__ == "__main__":
    sys.exit(main())
