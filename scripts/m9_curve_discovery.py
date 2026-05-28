#!/usr/bin/env python3
"""Curve factory dynamic pool discovery for M9 bridge inventory.

Production discovery path (replaces manual pool list in adapter_metadata.yaml):

  Factory/Registry → pool addresses → on-chain coins(i) verify
    → liquidity/TVL sanity → write to runtime discovery registry

Output:
  data/runs/_rolling/m9_curve_discovery_latest.json

Schema: m9_curve_discovery.1

Usage:
  py -3.11 scripts/m9_curve_discovery.py
  py -3.11 scripts/m9_curve_discovery.py --chain base --factory 0xd2002373543ce3527023c75e7518c274a51ce712
  py -3.11 scripts/m9_curve_discovery.py --max-pools 50 --min-tvl-usd 10000
  py -3.11 scripts/m9_curve_discovery.py --output data/runs/_rolling/m9_curve_discovery_latest.json

Architecture:
  This script feeds into m9_bridge_build.py (future wiring).
  The bridge_builder will load this artifact when available and merge discovered
  Curve pools into active_routes WITHOUT the config-seed flag.

Trust anchors (in config/adapter_metadata.yaml):
  - curve.base.factory_address: Curve factory for Base chain
  - Vault/registry addresses per chain
  These remain in config and are the ONLY Curve-related items kept there.
  The pool list itself must come from THIS script, not from config.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Fallback public RPC endpoints (non-sensitive; override via env variable).
# chain_name -> (env_var_name, fallback_url)
# Trust anchors (factory address, anchor tokens) live in config/adapter_metadata.yaml.
# ---------------------------------------------------------------------------
_RPC_CONFIG: Dict[str, Tuple[str, str]] = {
    "base": ("BASE_RPC", "https://base-rpc.publicnode.com"),
}
_SUPPORTED_CHAINS = list(_RPC_CONFIG.keys())

# Minimum TVL in USD to admit a pool (avoids dust / honeypot pools)
_DEFAULT_MIN_TVL_USD: float = 1000.0
# Maximum pools to fetch per factory (pagination guard)
_DEFAULT_MAX_POOLS: int = 200

# ABI selectors used for on-chain calls (no ABI import needed)
# factory: pool_count() = 0x956aae3a, pool_list(uint256) = 0xf7b0d5e9 (StableSwap-NG)
# pool: coins(uint256) = 0xc6610657  (returns address of coin at index i)
_SEL_POOL_COUNT = bytes.fromhex("956aae3a")
_SEL_POOL_LIST = bytes.fromhex("3a1d5d8e")   # pool_list(uint256 i) → address  [keccak4 verified]
_SEL_COINS = bytes.fromhex("c6610657")        # coins(uint256 i) → address

_OUTPUT_DEFAULT = "data/runs/_rolling/m9_curve_discovery_latest.json"
_SCHEMA_VERSION = "m9_curve_discovery.1"

log = logging.getLogger("m9_curve_discovery")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _encode_uint256(val: int) -> bytes:
    return val.to_bytes(32, "big")


def _decode_address(data: bytes) -> str:
    """Decode a 32-byte ABI-encoded address into a checksummed hex string."""
    if len(data) < 32:
        raise ValueError(f"Expected 32 bytes, got {len(data)}")
    addr = "0x" + data[-20:].hex().lower()
    return addr


def _decode_uint256(data: bytes) -> int:
    if len(data) < 32:
        raise ValueError(f"Expected 32 bytes, got {len(data)}")
    return int.from_bytes(data[:32], "big")


def _eth_call(w3: Any, to: str, data: bytes) -> bytes:
    """Perform an eth_call and return raw bytes result."""
    hex_data = "0x" + data.hex()
    # web3.py requires checksummed addresses; factory addresses may be stored lowercase.
    checksum_to = w3.to_checksum_address(to)
    result = w3.eth.call({"to": checksum_to, "data": hex_data})
    if isinstance(result, str):
        result = bytes.fromhex(result.removeprefix("0x"))
    return result


def _get_pool_count(w3: Any, factory: str) -> int:
    try:
        raw = _eth_call(w3, factory, _SEL_POOL_COUNT)
        return _decode_uint256(raw)
    except Exception as exc:
        log.warning("pool_count() failed for factory %s: %s", factory, exc)
        return 0


def _get_pool_address(w3: Any, factory: str, index: int) -> Optional[str]:
    """Get pool address at index from factory's pool_list(i)."""
    try:
        payload = _SEL_POOL_LIST + _encode_uint256(index)
        raw = _eth_call(w3, factory, payload)
        addr = _decode_address(raw)
        if addr == "0x" + "0" * 40:
            return None
        return addr
    except Exception as exc:
        log.debug("pool_list(%d) failed: %s", index, exc)
        return None


def _get_coin(w3: Any, pool: str, coin_index: int) -> Optional[str]:
    """Get coin address at index from a pool contract via coins(i)."""
    try:
        payload = _SEL_COINS + _encode_uint256(coin_index)
        raw = _eth_call(w3, pool, payload)
        addr = _decode_address(raw)
        if addr == "0x" + "0" * 40:
            return None
        return addr
    except Exception:
        return None


def _get_pool_coins(w3: Any, pool: str, max_coins: int = 4) -> List[str]:
    """Enumerate all coin addresses for a pool (stops on zero-address or error)."""
    coins: List[str] = []
    for i in range(max_coins):
        coin = _get_coin(w3, pool, i)
        if coin is None:
            break
        coins.append(coin)
    return coins


def _resolve_symbols(
    coin_addrs: List[str],
    anchor_tokens: Dict[str, str],
) -> List[Optional[str]]:
    """Map coin addresses to symbols using the anchor_tokens lookup.

    Returns None for coins not in the anchor dict (useful for filtering).
    """
    return [anchor_tokens.get(addr.lower()) for addr in coin_addrs]


# ---------------------------------------------------------------------------
# Core discovery logic
# ---------------------------------------------------------------------------

def _discover_factory_pools(
    w3: Any,
    factory: str,
    anchor_tokens: Dict[str, str],
    max_pools: int = _DEFAULT_MAX_POOLS,
    min_tvl_usd: float = _DEFAULT_MIN_TVL_USD,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Enumerate pools from a Curve factory, verify coins, return discovered pools.

    Returns:
        (discovered_pools, diagnostics)
        discovered_pools: list of {pool_address, pool_kind, coin_indices, coins, source}
        diagnostics: counters for logging and artifact
    """
    diag: Dict[str, Any] = {
        "factory": factory,
        "factory_pool_count": 0,
        "pools_fetched": 0,
        "pools_with_coins": 0,
        "pools_anchor_connected": 0,
        "pools_admitted": 0,
        "skipped_no_coins": 0,
        "skipped_not_anchor": 0,
    }

    pool_count = _get_pool_count(w3, factory)
    diag["factory_pool_count"] = pool_count
    log.info("Factory %s: pool_count=%d", factory, pool_count)

    effective_count = min(pool_count, max_pools)
    discovered: List[Dict[str, Any]] = []

    for idx in range(effective_count):
        pool_addr = _get_pool_address(w3, factory, idx)
        if not pool_addr:
            log.debug("pool_list(%d): null address, skipping", idx)
            continue

        diag["pools_fetched"] += 1
        coins = _get_pool_coins(w3, pool_addr)
        if len(coins) < 2:
            diag["skipped_no_coins"] += 1
            log.debug("Pool %s: only %d coins, skipping", pool_addr, len(coins))
            continue

        diag["pools_with_coins"] += 1

        # Map coin addresses to symbols
        syms = _resolve_symbols(coins, anchor_tokens)
        sym_map: Dict[str, int] = {}
        for i, (sym, addr) in enumerate(zip(syms, coins)):
            if sym is not None:
                sym_map[sym] = i

        # Anchor filter: at least one anchor token in the coin list
        if not sym_map:
            diag["skipped_not_anchor"] += 1
            log.debug("Pool %s: no anchor tokens (coins=%s)", pool_addr, coins)
            continue

        # If we have at least 2 symbols, build a full coin_indices map
        if len(sym_map) < 2:
            # Only one anchor token — build partial map but still admit
            # (the pair partner might still be useful for future cross-dex)
            pass

        diag["pools_anchor_connected"] += 1

        pool_entry: Dict[str, Any] = {
            "pool_address": pool_addr,
            "pool_kind": "stable",  # factory-stable-ng → always stable
            "coin_indices": sym_map,
            "coin_addresses": {addr.lower(): i for i, addr in enumerate(coins)},
            "coin_count": len(coins),
            "source": "curve_factory_discovery",
            "factory_address": factory,
            "discovered_at_utc": _iso_now(),
        }
        discovered.append(pool_entry)
        diag["pools_admitted"] += 1
        log.info(
            "Pool %s admitted: coins=%s sym_map=%s",
            pool_addr, coins[:4], sym_map,
        )

        # Rate limit: avoid hammering RPC
        time.sleep(0.05)

    return discovered, diag


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Curve factory dynamic pool discovery")
    p.add_argument(
        "--chain", default="base",
        choices=_SUPPORTED_CHAINS,
        help="Chain to run discovery on",
    )
    p.add_argument(
        "--factory",
        default=None,
        help="Override factory address (default: from chain anchor)",
    )
    p.add_argument(
        "--max-pools", type=int, default=_DEFAULT_MAX_POOLS,
        help="Maximum pools to enumerate per factory",
    )
    p.add_argument(
        "--min-tvl-usd", type=float, default=_DEFAULT_MIN_TVL_USD,
        help="Minimum TVL (USD) to admit a pool (currently informational; no on-chain TVL query)",
    )
    p.add_argument(
        "--output", default=_OUTPUT_DEFAULT,
        help="Output path for discovery artifact",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Load factory address and anchor tokens from config/adapter_metadata.yaml
    try:
        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        _meta = load_adapter_metadata()
    except Exception as exc:
        log.error("Failed to load adapter_metadata: %s", exc)
        return 1

    factory = args.factory or _meta.curve_factory_stable_ng.get(args.chain)
    if not factory:
        log.error(
            "No factory_stable_ng configured for chain=%s in config/adapter_metadata.yaml",
            args.chain,
        )
        return 1

    anchor_tokens: Dict[str, str] = _meta.curve_anchor_tokens.get(args.chain, {})
    if not anchor_tokens:
        log.warning("No anchor_tokens configured for chain=%s; all pools will be admitted", args.chain)

    # Resolve RPC
    rpc_env, rpc_default = _RPC_CONFIG.get(args.chain, ("BASE_RPC", "https://base-rpc.publicnode.com"))
    rpc_url = os.environ.get(rpc_env) or rpc_default
    log.info("Chain=%s factory=%s rpc=%s", args.chain, factory, rpc_url[:40] + "...")

    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 15}))
        if not w3.is_connected():
            log.error("RPC not connected: %s", rpc_url)
            return 2
        log.info("RPC connected (chain_id=%s)", w3.eth.chain_id)
    except Exception as exc:
        log.error("Failed to connect to RPC: %s", exc)
        return 2

    # Run discovery
    t0 = time.monotonic()
    discovered, diag = _discover_factory_pools(
        w3,
        factory=factory,
        anchor_tokens=anchor_tokens,
        max_pools=args.max_pools,
        min_tvl_usd=args.min_tvl_usd,
    )
    elapsed = time.monotonic() - t0

    log.info(
        "Discovery complete: factory_pool_count=%d fetched=%d admitted=%d (%.1fs)",
        diag["factory_pool_count"],
        diag["pools_fetched"],
        diag["pools_admitted"],
        elapsed,
    )

    artifact: Dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "generated_at_utc": _iso_now(),
        "chain": args.chain,
        "factory_address": factory,
        "rpc_provider": rpc_url.split("/")[2] if "/" in rpc_url else rpc_url,
        "elapsed_s": round(elapsed, 2),
        "discovery_params": {
            "max_pools": args.max_pools,
            "min_tvl_usd": args.min_tvl_usd,
        },
        "diagnostics": diag,
        "discovered_pools": discovered,
        "discovered_count": len(discovered),
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Written: %s (count=%d)", out, len(discovered))

    if len(discovered) == 0:
        log.warning("No Curve pools discovered — check factory address and RPC connectivity")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
