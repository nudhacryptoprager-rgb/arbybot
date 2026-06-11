#!/usr/bin/env python3
"""
CLI to verify token addresses on-chain.

Usage:
    py -3.11 scripts/verify_tokens.py --chain arbitrum_one
    py -3.11 scripts/verify_tokens.py --chain arbitrum_one --token MAGIC
    py -3.11 scripts/verify_tokens.py --chain arbitrum_one --all-new
"""

import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discovery.verify import verify_token_onchain, get_token_registry
from core.rpc_urls import get_rpc_url


def main():
    parser = argparse.ArgumentParser(description="Verify token addresses on-chain")
    parser.add_argument("--chain", default="arbitrum_one", help="Chain to verify tokens for")
    parser.add_argument("--token", default=None, help="Single token symbol to verify")
    parser.add_argument("--all-new", action="store_true", help="Verify all v2.4.0 discovery tokens")
    args = parser.parse_args()
    
    # v2.4.0 discovery tokens
    NEW_TOKENS = ["rETH", "MAGIC", "FRAX", "LUSD", "GNS", "GRAIL", "JOE", "USDE", "TBTC", "DPX"]
    
    registry = get_token_registry()
    rpc_url = get_rpc_url(args.chain)
    
    if not rpc_url:
        print(f"ERROR: No RPC URL for chain {args.chain}")
        sys.exit(1)
    
    tokens_to_verify = []
    if args.token:
        tokens_to_verify = [args.token]
    elif args.all_new:
        tokens_to_verify = NEW_TOKENS
    else:
        # Default: verify all tokens in registry for the chain
        all_tokens = registry.get_all_tokens(args.chain)
        tokens_to_verify = list(all_tokens.keys())
    
    print(f"Verifying {len(tokens_to_verify)} tokens on {args.chain}")
    print(f"RPC: {rpc_url[:50]}...")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for symbol in tokens_to_verify:
        addr = registry.get_address(args.chain, symbol)
        if not addr:
            print(f"  {symbol}: NOT IN REGISTRY")
            failed += 1
            continue
        
        success, info, err = verify_token_onchain(addr, rpc_url, expected_symbol=symbol)
        
        if success:
            print(f"  {symbol}: OK (decimals={info.decimals}, name={info.name})")
            passed += 1
        else:
            print(f"  {symbol}: FAIL - {err}")
            failed += 1
    
    print("=" * 60)
    print(f"RESULT: {passed} passed, {failed} failed")
    
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
