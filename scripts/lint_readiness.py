#!/usr/bin/env python3
# PATH: scripts/lint_readiness.py
"""
Lint Readiness Script (no RPC required)

Checks whether a chain is ready for scanning by comparing:
1. intent.txt symbols vs core_tokens.yaml addresses
2. dexes.yaml anchors (factory, quoter) per chain

USAGE:
  # Check all chains
  py -3.11 scripts/lint_readiness.py

  # Check specific chain
  py -3.11 scripts/lint_readiness.py --chain linea

  # JSON output
  py -3.11 scripts/lint_readiness.py --json

PURPOSE:
  Prevents blind NO_DATA runs by catching missing tokens/anchors before RPC call.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

INTENT_PATH = REPO_ROOT / "config" / "intent.txt"
CORE_TOKENS_PATH = REPO_ROOT / "config" / "core_tokens.yaml"
DEXES_PATH = REPO_ROOT / "config" / "dexes.yaml"


def load_intent() -> dict[str, set[str]]:
    """
    Load intent.txt and return {chain: set of symbols}.
    """
    chain_symbols: dict[str, set[str]] = defaultdict(set)
    
    with open(INTENT_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            # Format: chain:TOKENA/TOKENB
            if ":" in line:
                chain, pair = line.split(":", 1)
                chain = chain.strip()
                if "/" in pair:
                    base, quote = pair.split("/", 1)
                    chain_symbols[chain].add(base.strip())
                    chain_symbols[chain].add(quote.strip())
    
    return dict(chain_symbols)


def load_core_tokens() -> dict[str, dict[str, str]]:
    """
    Load core_tokens.yaml and return {chain: {symbol: address}}.
    """
    import yaml
    
    with open(CORE_TOKENS_PATH) as f:
        data = yaml.safe_load(f)
    
    result: dict[str, dict[str, str]] = {}
    
    # core_tokens.yaml structure: {chain: {symbol: {address, decimals, ...}}}
    for chain, tokens in data.items():
        if chain.startswith("#") or not isinstance(tokens, dict):
            continue
        result[chain] = {}
        for symbol, token_data in tokens.items():
            if isinstance(token_data, dict) and "address" in token_data:
                result[chain][symbol] = token_data["address"]
    
    return result


def load_dexes() -> dict[str, list[dict]]:
    """
    Load dexes.yaml and return {chain: [dex_configs]}.
    """
    import yaml
    
    with open(DEXES_PATH) as f:
        data = yaml.safe_load(f)
    
    result: dict[str, list[dict]] = defaultdict(list)
    
    # dexes.yaml structure: {chain: {dex_id: {factory, router, ...}}}
    for chain, dexes in data.items():
        if chain.startswith("#") or not isinstance(dexes, dict):
            continue
        for dex_id, dex_cfg in dexes.items():
            if isinstance(dex_cfg, dict):
                cfg = {"dex_id": dex_id, **dex_cfg}
                result[chain].append(cfg)
    
    return dict(result)


def check_chain_readiness(
    chain: str,
    intent_symbols: set[str],
    core_tokens: dict[str, str],
    dexes: list[dict]
) -> dict:
    """
    Check readiness for a single chain.
    
    Returns:
        {
            "chain": chain,
            "ready": True/False,
            "missing_tokens": [...],
            "available_tokens": [...],
            "dex_anchors": {...},
            "issues": [...]
        }
    """
    result = {
        "chain": chain,
        "ready": True,
        "missing_tokens": [],
        "available_tokens": [],
        "dex_anchors": {},
        "issues": [],
    }
    
    # Check tokens
    available = set(core_tokens.keys())
    result["available_tokens"] = sorted(available)
    missing = intent_symbols - available
    result["missing_tokens"] = sorted(missing)
    
    if missing:
        result["issues"].append(f"Missing {len(missing)} tokens in core_tokens.yaml: {', '.join(sorted(missing))}")
        result["ready"] = False
    
    # Check DEX anchors
    required_anchors = ["factory"]  # Minimum required
    for dex in dexes:
        dex_id = dex.get("dex_id", "unknown")
        anchors = {}
        for key in ["factory", "quoter", "quoter_v2", "router"]:
            val = dex.get(key)
            if val:
                anchors[key] = val[:10] + "..." if len(val) > 10 else val
        
        result["dex_anchors"][dex_id] = anchors
        
        # Check if factory exists
        if not dex.get("factory"):
            result["issues"].append(f"DEX {dex_id} missing factory address")
            result["ready"] = False
        
        # Check if quoter exists (needed for quoting)
        if not dex.get("quoter") and not dex.get("quoter_v2"):
            result["issues"].append(f"DEX {dex_id} missing quoter/quoter_v2 address")
            result["ready"] = False
    
    if not dexes:
        result["issues"].append("No DEXes configured for this chain")
        result["ready"] = False
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Check chain readiness for scanning")
    parser.add_argument("--chain", help="Specific chain to check (default: all)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    # Load data
    intent_symbols = load_intent()
    core_tokens = load_core_tokens()
    dexes_by_chain = load_dexes()
    
    # Get chains to check
    if args.chain:
        chains = [args.chain]
    else:
        # All chains from intent.txt
        chains = sorted(intent_symbols.keys())
    
    results = []
    
    for chain in chains:
        symbols = intent_symbols.get(chain, set())
        tokens = core_tokens.get(chain, {})
        dexes = dexes_by_chain.get(chain, [])
        
        result = check_chain_readiness(chain, symbols, tokens, dexes)
        results.append(result)
    
    # Output
    if args.json:
        print(json.dumps({"chains": results}, indent=2))
    else:
        print("Lint Readiness Check")
        print("=" * 60)
        print()
        
        for r in results:
            status = "✅ READY" if r["ready"] else "❌ NOT READY"
            print(f"Chain: {r['chain']} - {status}")
            
            # Tokens
            print(f"  Tokens in intent: {len(r['available_tokens']) + len(r['missing_tokens'])}")
            print(f"  Tokens in core_tokens.yaml: {len(r['available_tokens'])}")
            if r["missing_tokens"]:
                print(f"  Missing tokens: {', '.join(r['missing_tokens'][:5])}")
                if len(r["missing_tokens"]) > 5:
                    print(f"    ... and {len(r['missing_tokens']) - 5} more")
            
            # DEXes
            print(f"  DEXes configured: {len(r['dex_anchors'])}")
            for dex_id, anchors in r["dex_anchors"].items():
                anchor_list = ", ".join(f"{k}" for k in anchors.keys())
                print(f"    {dex_id}: {anchor_list}")
            
            # Issues
            if r["issues"]:
                print(f"  Issues:")
                for issue in r["issues"]:
                    print(f"    - {issue}")
            
            print()
    
    # Exit code
    all_ready = all(r["ready"] for r in results)
    return 0 if all_ready else 1


if __name__ == "__main__":
    sys.exit(main())
