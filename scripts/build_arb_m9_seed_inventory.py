#!/usr/bin/env python3
"""Build a minimal Arbitrum M9 seed inventory by querying the Camelot V3 factory.

Queries Camelot V3 (Algebra protocol) factory.poolByPair() for key pairs,
then combines with known Uniswap V3 and SushiSwap V3 pool addresses to
produce a multi-DEX M9 inventory with triangular arb potential.

Output: data/tmp/m9_arb_bridge.json

Usage:
    $env:ARBITRUM_RPC = "https://arbitrum-one-rpc.publicnode.com"
    py -3.11 scripts/build_arb_m9_seed_inventory.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Token addresses on Arbitrum One (verified in docs/artifacts/pool_whitelist.json
# and config/real_minimal.yaml — cross-referenced with core_tokens.yaml)
# ---------------------------------------------------------------------------
_WETH  = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
_USDC  = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
_USDT  = "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"
_ARB   = "0x912CE59144191C1204E64559FE8253a0e49E6548"
_WBTC  = "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f"

# ---------------------------------------------------------------------------
# Camelot V3 (Algebra) factory — config/dexes.yaml:arbitrum_one.camelot_v3
# ---------------------------------------------------------------------------
_CAMELOT_FACTORY = "0x1a3c9B1d2F0529D97f2afC5136Cc23e58f1FD35B"

# ---------------------------------------------------------------------------
# Known Uniswap V3 + SushiSwap V3 pool addresses on Arbitrum One
# Source: docs/artifacts/pool_whitelist.json + config/real_minimal.yaml
# Only productive fee tiers included (500 and/or 3000 — verified non-empty).
# ---------------------------------------------------------------------------
_KNOWN_POOLS: list[dict] = [
    # Uniswap V3 — WETH/USDC
    {"pair_id": "USDC_WETH", "dex_id": "uniswap_v3", "fee": 500,
     "pool_address": "0xC6962004f452bE9203591991D15f6b388e09E8D0"},
    {"pair_id": "USDC_WETH", "dex_id": "uniswap_v3", "fee": 3000,
     "pool_address": "0xc473e2aEE3441BF9240Be85eb122aBB059A3B57c"},
    # SushiSwap V3 — WETH/USDC
    {"pair_id": "USDC_WETH", "dex_id": "sushiswap_v3", "fee": 500,
     "pool_address": "0xf3Eb87C1F6020982173C908E7eB31aA66c1f0296"},
    # Uniswap V3 — WETH/USDT
    {"pair_id": "USDT_WETH", "dex_id": "uniswap_v3", "fee": 500,
     "pool_address": "0x641C00A822e8b671738d32a431a4Fb6074E5c79d"},
    # SushiSwap V3 — WETH/USDT
    {"pair_id": "USDT_WETH", "dex_id": "sushiswap_v3", "fee": 500,
     "pool_address": "0x96aDA81328abCe21939A51D971A63077e16db26E"},
    # Uniswap V3 — ARB/WETH
    {"pair_id": "ARB_WETH", "dex_id": "uniswap_v3", "fee": 500,
     "pool_address": "0xC6F780497A95e246EB9449f5e4770916DCd6396A"},
    # SushiSwap V3 — ARB/WETH
    {"pair_id": "ARB_WETH", "dex_id": "sushiswap_v3", "fee": 3000,
     "pool_address": "0xB3942c9FFA04efBC1Fa746e146bE7565c76E3dC1"},
]

# Algebra factory ABI — minimal poolByPair view function
_ALGEBRA_FACTORY_ABI = [
    {
        "name": "poolByPair",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"},
        ],
        "outputs": [{"name": "pool", "type": "address"}],
    }
]

_ZERO_ADDR = "0x0000000000000000000000000000000000000000"


def _query_algebra_pool(w3: object, factory_addr: str, token_a: str, token_b: str) -> Optional[str]:
    """Query Algebra factory.poolByPair(tokenA, tokenB) → pool address or None."""
    try:
        from web3 import Web3  # type: ignore[import]
        factory = w3.eth.contract(  # type: ignore[attr-defined]
            address=Web3.to_checksum_address(factory_addr),
            abi=_ALGEBRA_FACTORY_ABI,
        )
        pool: str = factory.functions.poolByPair(
            Web3.to_checksum_address(token_a),
            Web3.to_checksum_address(token_b),
        ).call()
        if pool == _ZERO_ADDR or not pool.startswith("0x"):
            return None
        return pool
    except Exception as exc:
        print(f"  WARN: poolByPair({token_a[:10]}.., {token_b[:10]}..) failed: {exc}", file=sys.stderr)
        return None


def main() -> int:
    # Resolve Arbitrum RPC URL
    rpc_url = os.environ.get("ARBITRUM_RPC") or os.environ.get("ARBITRUM_ONE_RPC")
    if not rpc_url:
        # Fallback: try core.rpc_urls
        try:
            from core.rpc_urls import get_rpc_url
            rpc_url = get_rpc_url("arbitrum")
        except Exception:
            rpc_url = "https://arbitrum-one-rpc.publicnode.com"

    print(f"Connecting to Arbitrum RPC: {rpc_url}")
    try:
        from web3 import Web3  # type: ignore[import]
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 15}))
        if not w3.is_connected():
            print(f"ERROR: cannot connect to {rpc_url}", file=sys.stderr)
            return 1
        block = w3.eth.block_number
        print(f"Connected OK — block #{block}")
    except ImportError:
        print("ERROR: web3 not installed. Run: pip install web3", file=sys.stderr)
        return 1

    output_path = Path("data/tmp/m9_arb_bridge.json")
    active_routes: list[dict] = []
    route_idx = 0

    # --- Camelot V3 (Algebra) pool discovery via factory.poolByPair() ---
    camelot_queries: list[tuple[str, str, str]] = [
        ("USDC_WETH", _USDC, _WETH),
        ("USDT_WETH", _USDT, _WETH),
        ("ARB_WETH",  _ARB,  _WETH),
    ]

    print("\n[Camelot V3 / Algebra] querying factory.poolByPair()...")
    camelot_found = 0
    for pair_id, tok_a, tok_b in camelot_queries:
        pool = _query_algebra_pool(w3, _CAMELOT_FACTORY, tok_a, tok_b)
        if pool:
            camelot_found += 1
            route_idx += 1
            entry = {
                "pair_id": pair_id,
                "dex_id": "camelot_v3",
                "pool_address": pool.lower(),
                "fee": 0,
                "factory_class": "ALGEBRA",
                "adapter_type": "algebra",
                "route_id": f"arb_camelot_{route_idx:04d}",
                "factory_verified": True,
            }
            active_routes.append(entry)
            print(f"  {pair_id}: {pool}")
        else:
            print(f"  {pair_id}: NOT FOUND (pool may not exist or RPC error)")

    # --- Known Uniswap V3 / SushiSwap V3 routes ---
    print(f"\n[Known V3 pools] adding {len(_KNOWN_POOLS)} routes...")
    for pool_entry in _KNOWN_POOLS:
        route_idx += 1
        dex_id = pool_entry["dex_id"]
        adapter_type = "uniswap_v3"
        factory_class = "UNISWAP_V3" if "uniswap" in dex_id else "SUSHISWAP_V3"
        entry = {
            "pair_id": pool_entry["pair_id"],
            "dex_id": dex_id,
            "pool_address": pool_entry["pool_address"].lower(),
            "fee": pool_entry["fee"],
            "factory_class": factory_class,
            "adapter_type": adapter_type,
            "route_id": f"arb_known_{route_idx:04d}",
            "factory_verified": True,
        }
        active_routes.append(entry)
        print(f"  {dex_id} {pool_entry['pair_id']} fee={pool_entry['fee']}: {pool_entry['pool_address']}")

    # --- Write inventory ---
    inventory = {
        "schema_version": "bridge.1.0",
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "inventory_source": "arb_seed_manual",
        "chain": "arbitrum_one",
        "camelot_pools_found": camelot_found,
        "active_routes": active_routes,
        "active_routes_count": len(active_routes),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(inventory, fh, indent=2)

    print(f"\nWrote {len(active_routes)} routes ({camelot_found} Algebra + "
          f"{len(_KNOWN_POOLS)} known V3) → {output_path}")
    print("\nNext step:")
    print("  $env:ARBITRUM_RPC='https://arbitrum-one-rpc.publicnode.com'")
    print("  py -3.11 -u -m m9.graph_arb.runner \\")
    print("      --chain arbitrum --duration-minutes 2 \\")
    print("      --config config/exotic_arbitrum_anchor.yaml \\")
    print("      --inventory data/tmp/m9_arb_bridge.json \\")
    print("      --quote-backend raw_http --quote-workers 1 --no-prequote \\")
    print("      --artifact-path data/runs/_rolling/m9_arb_latest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
