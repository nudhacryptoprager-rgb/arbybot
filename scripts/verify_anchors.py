#!/usr/bin/env python3
"""
scripts/verify_anchors.py - Verify trust anchors via on-chain calls.

SEMANTIC VERIFICATION:
1. chain_id matches RPC response
2. Factory contracts exist AND respond to getPool/getPair
3. Quoter/Router contracts exist (for execution readiness)

Usage:
    python scripts/verify_anchors.py --chain arbitrum_one
    python scripts/verify_anchors.py --all
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Add project root to path (scripts are not part of the package)
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from dotenv import load_dotenv
import httpx

from core.logging import get_logger, setup_logging

logger = get_logger("arby.verify_anchors")


# =============================================================================
# ABI ENCODINGS (precomputed function selectors)
# =============================================================================

# keccak256("getPool(address,address,uint24)")[:4] = 0x1698ee82
SELECTOR_GET_POOL = "0x1698ee82"

# keccak256("getPair(address,address)")[:4] = 0xe6a43905
SELECTOR_GET_PAIR = "0xe6a43905"

# Zero address for comparison
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def encode_get_pool(token_a: str, token_b: str, fee: int) -> str:
    """Encode getPool(address,address,uint24) call data."""
    # Remove 0x prefix and pad to 32 bytes
    token_a_padded = token_a[2:].lower().zfill(64)
    token_b_padded = token_b[2:].lower().zfill(64)
    fee_padded = hex(fee)[2:].zfill(64)
    return f"{SELECTOR_GET_POOL}{token_a_padded}{token_b_padded}{fee_padded}"


def encode_get_pair(token_a: str, token_b: str) -> str:
    """Encode getPair(address,address) call data."""
    token_a_padded = token_a[2:].lower().zfill(64)
    token_b_padded = token_b[2:].lower().zfill(64)
    return f"{SELECTOR_GET_PAIR}{token_a_padded}{token_b_padded}"


def decode_address(hex_result: str) -> str:
    """Decode address from eth_call result."""
    if not hex_result or hex_result == "0x":
        return ZERO_ADDRESS
    # Take last 40 chars (20 bytes) as address
    clean = hex_result.replace("0x", "").zfill(64)
    return "0x" + clean[-40:]


# =============================================================================
# CONFIG LOADING
# =============================================================================

def load_config() -> tuple[dict, dict, dict]:
    """Load chains.yaml, dexes.yaml, core_tokens.yaml."""
    config_dir = Path(__file__).parent.parent / "config"
    
    with open(config_dir / "chains.yaml") as f:
        chains = yaml.safe_load(f)
    
    with open(config_dir / "dexes.yaml") as f:
        dexes = yaml.safe_load(f)
    
    with open(config_dir / "core_tokens.yaml") as f:
        tokens = yaml.safe_load(f)
    
    return chains, dexes, tokens


def get_rpc_urls(chain_config: dict) -> list[str]:
    """Get all RPC URLs with API key substitution."""
    load_dotenv()
    api_key = os.getenv("ALCHEMY_API_KEY", "")
    
    urls = []
    for url in chain_config.get("rpc_urls", []):
        resolved = url.replace("${ALCHEMY_API_KEY}", api_key)
        # Only include if API key present or not needed
        if api_key or "alchemy" not in resolved.lower():
            urls.append(resolved)
    
    return urls


# =============================================================================
# RPC CALLS WITH FAILOVER
# =============================================================================

async def rpc_call_with_failover(
    client: httpx.AsyncClient,
    rpc_urls: list[str],
    method: str,
    params: list,
) -> tuple[Any, str | None]:
    """
    Make RPC call with failover across multiple endpoints.
    
    Returns:
        (result, used_rpc_url) or (None, None) if all failed
    """
    last_error = None
    
    for rpc_url in rpc_urls:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }
        
        try:
            resp = await client.post(rpc_url, json=payload, timeout=10.0)
            result = resp.json()
            
            if "result" in result:
                return result["result"], rpc_url
            
            if "error" in result:
                last_error = result["error"]
                logger.debug(f"RPC error from {rpc_url}: {last_error}")
                continue
                
        except Exception as e:
            last_error = str(e)
            logger.debug(f"RPC failed for {rpc_url}: {e}")
            continue
    
    logger.warning(f"All RPC endpoints failed. Last error: {last_error}")
    return None, None


async def get_chain_id(client: httpx.AsyncClient, rpc_urls: list[str]) -> tuple[int | None, str | None]:
    """Get chain ID with failover."""
    result, used_rpc = await rpc_call_with_failover(client, rpc_urls, "eth_chainId", [])
    if result:
        return int(result, 16), used_rpc
    return None, None


async def get_code(client: httpx.AsyncClient, rpc_urls: list[str], address: str) -> tuple[str | None, str | None]:
    """Check if address has code with failover."""
    result, used_rpc = await rpc_call_with_failover(client, rpc_urls, "eth_getCode", [address, "latest"])
    return result, used_rpc


async def eth_call(
    client: httpx.AsyncClient,
    rpc_urls: list[str],
    to: str,
    data: str,
) -> tuple[str | None, str | None]:
    """Make eth_call with failover."""
    result, used_rpc = await rpc_call_with_failover(
        client, rpc_urls, "eth_call",
        [{"to": to, "data": data}, "latest"]
    )
    return result, used_rpc


# =============================================================================
# SEMANTIC VERIFICATION
# =============================================================================

async def verify_v3_factory_semantic(
    client: httpx.AsyncClient,
    rpc_urls: list[str],
    factory_address: str,
    token_a: str,
    token_b: str,
    fee: int,
) -> tuple[bool, str | None]:
    """
    Verify V3 factory responds to getPool with real tokens.
    
    Returns:
        (success, pool_address_or_none)
    """
    call_data = encode_get_pool(token_a, token_b, fee)
    result, _ = await eth_call(client, rpc_urls, factory_address, call_data)
    
    if result and result != "0x":
        pool_address = decode_address(result)
        # Valid if returns non-zero address
        if pool_address != ZERO_ADDRESS:
            return True, pool_address
        # Zero address means pool doesn't exist (but factory works)
        return True, None
    
    return False, None


async def verify_v2_factory_semantic(
    client: httpx.AsyncClient,
    rpc_urls: list[str],
    factory_address: str,
    token_a: str,
    token_b: str,
) -> tuple[bool, str | None]:
    """
    Verify V2 factory responds to getPair with real tokens.
    
    Returns:
        (success, pair_address_or_none)
    """
    call_data = encode_get_pair(token_a, token_b)
    result, _ = await eth_call(client, rpc_urls, factory_address, call_data)
    
    if result and result != "0x":
        pair_address = decode_address(result)
        if pair_address != ZERO_ADDRESS:
            return True, pair_address
        return True, None
    
    return False, None


# =============================================================================
# DEX VERIFICATION
# =============================================================================

async def verify_dex(
    client: httpx.AsyncClient,
    rpc_urls: list[str],
    dex_key: str,
    dex_config: dict,
    core_tokens: dict,
) -> dict:
    """
    Verify a single DEX with semantic checks.
    
    Returns verification result with separate quoting/execution status.
    """
    adapter_type = dex_config.get("adapter_type", "unknown")
    
    result = {
        "dex_key": dex_key,
        "name": dex_config.get("name", dex_key),
        "adapter_type": adapter_type,
        "factory": dex_config.get("factory"),
        "router": dex_config.get("router"),
        "quoter": dex_config.get("quoter_v2") or dex_config.get("quoter"),
        "factory_exists": False,
        "factory_responds": False,
        "router_exists": False,
        "quoter_exists": False,
        "sample_pool": None,
        "verified_for_quoting": False,
        "verified_for_execution": False,
        "status": "UNKNOWN",
        "issues": [],
    }
    
    # Check factory exists
    factory = result["factory"]
    if factory:
        code, _ = await get_code(client, rpc_urls, factory)
        result["factory_exists"] = code is not None and code != "0x" and len(code) > 10
    
    if not result["factory_exists"]:
        result["status"] = "FACTORY_NOT_FOUND"
        result["issues"].append("Factory contract not found or empty")
        return result
    
    # Semantic verify: try to call factory with real tokens
    weth = core_tokens.get("WETH", {}).get("address")
    usdc = core_tokens.get("USDC", {}).get("address")
    
    if weth and usdc:
        if adapter_type in ("uniswap_v3", ):
            # Try common fee tiers
            for fee in [500, 3000, 10000]:
                success, pool = await verify_v3_factory_semantic(
                    client, rpc_urls, factory, weth, usdc, fee
                )
                if success:
                    result["factory_responds"] = True
                    result["sample_pool"] = pool
                    break
        
        elif adapter_type in ("uniswap_v2", "ve33"):
            success, pair = await verify_v2_factory_semantic(
                client, rpc_urls, factory, weth, usdc
            )
            if success:
                result["factory_responds"] = True
                result["sample_pool"] = pair
        
        elif adapter_type == "algebra":
            # Algebra uses different interface, just check factory exists for now
            result["factory_responds"] = result["factory_exists"]
    else:
        # No tokens to test with, assume factory works if exists
        result["factory_responds"] = result["factory_exists"]
        result["issues"].append("No WETH/USDC for semantic verify")
    
    # Check router exists
    router = result["router"]
    if router:
        code, _ = await get_code(client, rpc_urls, router)
        result["router_exists"] = code is not None and code != "0x" and len(code) > 10
    
    # Check quoter exists (for V3)
    quoter = result["quoter"]
    if quoter:
        code, _ = await get_code(client, rpc_urls, quoter)
        result["quoter_exists"] = code is not None and code != "0x" and len(code) > 10
    
    # Determine verification status
    # QUOTING: needs factory (semantic) + quoter (for V3) or factory (for V2)
    if adapter_type == "uniswap_v3":
        result["verified_for_quoting"] = result["factory_responds"] and result["quoter_exists"]
        if not result["quoter_exists"]:
            result["issues"].append("Quoter not found - cannot fetch quotes")
    else:
        result["verified_for_quoting"] = result["factory_responds"]
    
    # EXECUTION: needs quoting + router
    result["verified_for_execution"] = result["verified_for_quoting"] and result["router_exists"]
    if not result["router_exists"]:
        result["issues"].append("Router not found - cannot execute trades")
    
    # Set status
    if result["verified_for_execution"]:
        result["status"] = "FULLY_VERIFIED"
    elif result["verified_for_quoting"]:
        result["status"] = "QUOTING_ONLY"
    elif result["factory_exists"]:
        result["status"] = "PARTIAL"
    else:
        result["status"] = "FAILED"
    
    return result


# =============================================================================
# CHAIN VERIFICATION
# =============================================================================

async def verify_chain(
    chain_key: str,
    chain_config: dict,
    dex_configs: dict,
    token_configs: dict,
) -> dict:
    """Verify a single chain's trust anchors with failover."""
    results = {
        "chain_key": chain_key,
        "chain_id_config": chain_config.get("chain_id"),
        "chain_id_rpc": None,
        "chain_id_match": False,
        "rpc_reachable": False,
        "rpc_used": None,
        "dexes": {},
        "summary": {
            "total": 0,
            "fully_verified": 0,
            "quoting_only": 0,
            "partial": 0,
            "failed": 0,
        },
        "status": "UNKNOWN",
        "recommendation": None,
    }
    
    rpc_urls = get_rpc_urls(chain_config)
    if not rpc_urls:
        results["status"] = "NO_RPC"
        results["recommendation"] = "Add valid RPC URLs to chains.yaml"
        return results
    
    async with httpx.AsyncClient() as client:
        # Check chain ID with failover
        chain_id, used_rpc = await get_chain_id(client, rpc_urls)
        results["chain_id_rpc"] = chain_id
        results["rpc_used"] = used_rpc
        results["rpc_reachable"] = chain_id is not None
        
        if chain_id is not None:
            results["chain_id_match"] = chain_id == chain_config.get("chain_id")
        
        if not results["rpc_reachable"]:
            results["status"] = "RPC_UNREACHABLE"
            results["recommendation"] = "Check RPC URLs and API keys"
            return results
        
        if not results["chain_id_match"]:
            results["status"] = "CHAIN_ID_MISMATCH"
            results["recommendation"] = f"Config says {chain_config.get('chain_id')}, RPC says {chain_id}"
            return results
        
        # Verify each DEX
        for dex_key, dex_config in (dex_configs or {}).items():
            dex_result = await verify_dex(
                client, rpc_urls, dex_key, dex_config, token_configs or {}
            )
            results["dexes"][dex_key] = dex_result
            
            # Update summary
            results["summary"]["total"] += 1
            if dex_result["status"] == "FULLY_VERIFIED":
                results["summary"]["fully_verified"] += 1
            elif dex_result["status"] == "QUOTING_ONLY":
                results["summary"]["quoting_only"] += 1
            elif dex_result["status"] == "PARTIAL":
                results["summary"]["partial"] += 1
            else:
                results["summary"]["failed"] += 1
    
    # Determine overall status
    s = results["summary"]
    if s["fully_verified"] == s["total"] and s["total"] > 0:
        results["status"] = "FULLY_VERIFIED"
    elif s["fully_verified"] + s["quoting_only"] > 0:
        results["status"] = "PARTIALLY_VERIFIED"
        results["recommendation"] = "Some DEXes missing router - execution limited"
    elif s["partial"] > 0:
        results["status"] = "NEEDS_WORK"
        results["recommendation"] = "DEX configs need quoter/router addresses"
    else:
        results["status"] = "VERIFICATION_FAILED"
        results["recommendation"] = "Check all DEX addresses in dexes.yaml"
    
    return results


# =============================================================================
# MAIN
# =============================================================================

async def main(chain_filter: str | None = None):
    """Run verification."""
    setup_logging(level="INFO", json_output=False)
    
    chains, dexes, tokens = load_config()
    
    results = []
    chains_needing_disable = []
    
    for chain_key, chain_config in chains.items():
        if chain_filter and chain_filter != "all" and chain_key != chain_filter:
            continue
        
        if not chain_config.get("enabled", True):
            logger.info(f"Skipping disabled chain: {chain_key}")
            continue
        
        logger.info(f"Verifying chain: {chain_key}")
        
        result = await verify_chain(
            chain_key,
            chain_config,
            dexes.get(chain_key, {}),
            tokens.get(chain_key, {}),
        )
        results.append(result)
        
        # Check if chain should be disabled
        if result["status"] in ("VERIFICATION_FAILED", "NEEDS_WORK", "RPC_UNREACHABLE"):
            chains_needing_disable.append(chain_key)
        
        # Print summary
        print(f"\n{'='*60}")
        print(f"Chain: {chain_key}")
        print(f"{'='*60}")
        print(f"Chain ID (config): {result['chain_id_config']}")
        print(f"Chain ID (RPC):    {result['chain_id_rpc']}")
        print(f"Chain ID match:    {'✅' if result['chain_id_match'] else '❌'}")
        print(f"RPC reachable:     {'✅' if result['rpc_reachable'] else '❌'}")
        print(f"RPC used:          {result['rpc_used']}")
        print(f"Status:            {result['status']}")
        
        if result.get("recommendation"):
            print(f"Recommendation:    {result['recommendation']}")
        
        if result["dexes"]:
            print(f"\nDEXes ({result['summary']['total']} total):")
            for dex_key, dex_result in result["dexes"].items():
                status = dex_result["status"]
                if status == "FULLY_VERIFIED":
                    icon = "✅"
                elif status == "QUOTING_ONLY":
                    icon = "⚠️"
                else:
                    icon = "❌"
                
                print(f"  {dex_key}: {icon} {status}")
                
                if dex_result["issues"]:
                    for issue in dex_result["issues"]:
                        print(f"      ⚠ {issue}")
                
                if dex_result.get("sample_pool"):
                    print(f"      Sample pool: {dex_result['sample_pool']}")
    
    # Save results
    output_path = Path("data/reports/anchor_verification.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"Results saved to: {output_path}")
    
    # Recommendations
    if chains_needing_disable:
        print(f"\n⚠️  RECOMMENDATION: Disable these chains until fixed:")
        for chain in chains_needing_disable:
            print(f"   - {chain}")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Verify trust anchors")
    parser.add_argument("--chain", "-c", default="all", help="Chain to verify (or 'all')")
    args = parser.parse_args()
    
    asyncio.run(main(args.chain))
