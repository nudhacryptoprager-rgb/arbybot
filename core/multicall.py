# PATH: core/multicall.py
"""
Multicall batching for V3 pool data.

Batches multiple contract reads into a single RPC call using the Multicall3 contract.
This reduces RPC latency by ~80% for bulk pool scans.

Usage:
    from core.multicall import MulticallBatcher, get_multicall_batcher
    
    batcher = get_multicall_batcher(rpc_url, block_num)
    results = batcher.batch_slot0([pool_addr1, pool_addr2, ...])
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("core.multicall")

# Multicall3 deployed on all major chains at same address
# See: https://github.com/mds1/multicall
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"

# ABI for Multicall3 aggregate3 function
MULTICALL3_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "target", "type": "address"},
                    {"name": "allowFailure", "type": "bool"},
                    {"name": "callData", "type": "bytes"},
                ],
                "name": "calls",
                "type": "tuple[]",
            }
        ],
        "name": "aggregate3",
        "outputs": [
            {
                "components": [
                    {"name": "success", "type": "bool"},
                    {"name": "returnData", "type": "bytes"},
                ],
                "name": "returnData",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

# V3 Pool function selectors
V3_SLOT0_SELECTOR = "0x3850c7bd"  # slot0()
V3_LIQUIDITY_SELECTOR = "0x1a686502"  # liquidity()
V3_TOKEN0_SELECTOR = "0x0dfe1681"  # token0()
V3_TOKEN1_SELECTOR = "0xd21220a7"  # token1()
V3_FEE_SELECTOR = "0xddca3f43"  # fee()

# ERC20 function selectors
ERC20_DECIMALS_SELECTOR = "0x313ce567"  # decimals()
ERC20_SYMBOL_SELECTOR = "0x95d89b41"  # symbol()


class MulticallBatcher:
    """
    Batches multiple contract reads into a single RPC call.
    
    Attributes:
        rpc_url: RPC endpoint URL
        block_num: Block number to query at
        stats: Execution statistics
    """
    
    def __init__(self, rpc_url: str, block_num: int):
        self.rpc_url = rpc_url
        self.block_num = block_num
        self.stats = {
            "calls_made": 0,
            "calls_batched": 0,
            "calls_failed": 0,
            "rpc_calls": 0,
            "latency_ms_total": 0,  # v2.3.0: Total latency for averaging
        }
        # v2.2.0 Fix Step 4: Track call types explicitly
        # v2.3.0: Track success/fail per field
        self.call_types: Dict[str, int] = {
            "slot0": 0,
            "liquidity": 0,
            "token0": 0,
            "token1": 0,
            "decimals": 0,
            "symbol": 0,
            "fee": 0,
        }
        self.call_success: Dict[str, int] = {k: 0 for k in self.call_types}
        self.call_fail: Dict[str, int] = {k: 0 for k in self.call_types}
        self._w3 = None
        self._multicall = None
    
    def _ensure_web3(self) -> bool:
        """Initialize web3 connection if needed."""
        if self._w3 is not None:
            return True
        
        if os.environ.get("ARBY_SKIP_RPC") == "1":
            return False
        
        try:
            from web3 import Web3
            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 10}))
            self._multicall = self._w3.eth.contract(
                address=Web3.to_checksum_address(MULTICALL3_ADDRESS),
                abi=MULTICALL3_ABI
            )
            return True
        except Exception as e:
            logger.debug("Failed to initialize web3: %s", e)
            return False
    
    def _encode_calls(self, pool_addresses: List[str], selector: str) -> List[Tuple[str, bool, bytes]]:
        """Encode calls for multicall."""
        from web3 import Web3
        calls = []
        for addr in pool_addresses:
            calls.append((
                Web3.to_checksum_address(addr),
                True,  # allowFailure
                bytes.fromhex(selector[2:])  # callData (remove 0x prefix)
            ))
        return calls
    
    def _execute_multicall(self, calls: List[Tuple[str, bool, bytes]]) -> Optional[List[Tuple[bool, bytes]]]:
        """Execute multicall and return results."""
        if not self._ensure_web3():
            return None
        
        if not calls:
            return []
        
        try:
            self.stats["rpc_calls"] += 1
            results = self._multicall.functions.aggregate3(calls).call(
                block_identifier=self.block_num
            )
            return results
        except Exception as e:
            logger.debug("Multicall failed: %s", e)
            self.stats["calls_failed"] += len(calls)
            return None
    
    def batch_slot0(self, pool_addresses: List[str]) -> Dict[str, Optional[Tuple[int, int, int]]]:
        """
        Batch read slot0() from multiple V3 pools.
        
        Args:
            pool_addresses: List of pool contract addresses
            
        Returns:
            Dict mapping address -> (sqrtPriceX96, tick, liquidity) or None on failure
        """
        if not pool_addresses:
            return {}
        
        calls = self._encode_calls(pool_addresses, V3_SLOT0_SELECTOR)
        self.stats["calls_batched"] += len(calls)
        self.stats["calls_made"] += 1
        self.call_types["slot0"] += len(pool_addresses)  # v2.2.0: Track call type
        
        results = self._execute_multicall(calls)
        if results is None:
            # v2.3.0: Track all as failed when RPC fails
            self.call_fail["slot0"] += len(pool_addresses)
            return {addr: None for addr in pool_addresses}
        
        output = {}
        for i, addr in enumerate(pool_addresses):
            success, data = results[i]
            if success and len(data) >= 64:
                try:
                    # slot0 returns: sqrtPriceX96, tick, observationIndex, observationCardinality, ...
                    sqrt_price = int.from_bytes(data[0:32], "big")
                    tick = int.from_bytes(data[32:64], "big", signed=True)
                    output[addr] = (sqrt_price, tick, 0)  # liquidity from separate call
                    self.call_success["slot0"] += 1  # v2.3.0: Track success
                except Exception:
                    output[addr] = None
                    self.call_fail["slot0"] += 1  # v2.3.0: Track fail
            else:
                output[addr] = None
                self.call_fail["slot0"] += 1  # v2.3.0: Track fail
        
        return output
    
    def batch_liquidity(self, pool_addresses: List[str]) -> Dict[str, Optional[int]]:
        """
        Batch read liquidity() from multiple V3 pools.
        
        Args:
            pool_addresses: List of pool contract addresses
            
        Returns:
            Dict mapping address -> liquidity or None on failure
        """
        if not pool_addresses:
            return {}
        
        calls = self._encode_calls(pool_addresses, V3_LIQUIDITY_SELECTOR)
        self.stats["calls_batched"] += len(calls)
        self.stats["calls_made"] += 1
        self.call_types["liquidity"] += len(pool_addresses)  # v2.2.0: Track call type
        
        results = self._execute_multicall(calls)
        if results is None:
            self.call_fail["liquidity"] += len(pool_addresses)  # v2.3.0
            return {addr: None for addr in pool_addresses}
        
        output = {}
        for i, addr in enumerate(pool_addresses):
            success, data = results[i]
            if success and len(data) >= 16:
                try:
                    liquidity = int.from_bytes(data[0:16], "big")
                    output[addr] = liquidity
                    self.call_success["liquidity"] += 1  # v2.3.0
                except Exception:
                    output[addr] = None
                    self.call_fail["liquidity"] += 1  # v2.3.0
            else:
                output[addr] = None
                self.call_fail["liquidity"] += 1  # v2.3.0
        
        return output
    
    def batch_token_info(self, pool_addresses: List[str]) -> Dict[str, Optional[Tuple[str, str, int]]]:
        """
        Batch read token0(), token1(), fee() from multiple V3 pools.
        
        Args:
            pool_addresses: List of pool contract addresses
            
        Returns:
            Dict mapping address -> (token0, token1, fee) or None on failure
        """
        if not pool_addresses:
            return {}
        
        # Build calls: token0, token1, fee for each pool
        calls = []
        for addr in pool_addresses:
            from web3 import Web3
            checksum = Web3.to_checksum_address(addr)
            calls.append((checksum, True, bytes.fromhex(V3_TOKEN0_SELECTOR[2:])))
            calls.append((checksum, True, bytes.fromhex(V3_TOKEN1_SELECTOR[2:])))
            calls.append((checksum, True, bytes.fromhex(V3_FEE_SELECTOR[2:])))
        
        self.stats["calls_batched"] += len(calls)
        self.stats["calls_made"] += 1
        
        # v2.2.1 Fix Step 6: Track call types for token_info
        self.call_types["token0"] += len(pool_addresses)
        self.call_types["token1"] += len(pool_addresses)
        self.call_types["fee"] += len(pool_addresses)
        
        results = self._execute_multicall(calls)
        if results is None:
            return {addr: None for addr in pool_addresses}
        
        output = {}
        for i, addr in enumerate(pool_addresses):
            base_idx = i * 3
            try:
                # token0
                s0, d0 = results[base_idx]
                token0 = "0x" + d0[-20:].hex() if s0 and len(d0) >= 20 else None
                
                # token1
                s1, d1 = results[base_idx + 1]
                token1 = "0x" + d1[-20:].hex() if s1 and len(d1) >= 20 else None
                
                # fee
                s2, d2 = results[base_idx + 2]
                fee = int.from_bytes(d2[-4:], "big") if s2 and len(d2) >= 4 else None
                
                if token0 and token1 and fee is not None:
                    output[addr] = (token0, token1, fee)
                else:
                    output[addr] = None
            except Exception:
                output[addr] = None
        
        return output
    
    def batch_decimals(self, token_addresses: List[str]) -> Dict[str, Optional[int]]:
        """
        Batch read decimals() from multiple ERC20 tokens.
        
        Args:
            token_addresses: List of token contract addresses
            
        Returns:
            Dict mapping address -> decimals or None on failure
        """
        if not token_addresses:
            return {}
        
        calls = self._encode_calls(token_addresses, ERC20_DECIMALS_SELECTOR)
        self.stats["calls_batched"] += len(calls)
        self.stats["calls_made"] += 1
        
        # v2.2.0 Fix Step 5: Track decimals call type
        self.call_types["decimals"] += len(token_addresses)
        
        results = self._execute_multicall(calls)
        if results is None:
            return {addr: None for addr in token_addresses}
        
        output = {}
        for i, addr in enumerate(token_addresses):
            success, data = results[i]
            if success and len(data) >= 1:
                try:
                    # decimals is typically uint8, returned as uint256
                    decimals = int.from_bytes(data[-1:], "big")
                    output[addr] = decimals
                except Exception:
                    output[addr] = None
            else:
                output[addr] = None
        
        return output
    
    def batch_full_pool_data(
        self, pool_addresses: List[str]
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Batch fetch all pool data: slot0 + liquidity in one call.
        
        Args:
            pool_addresses: List of pool contract addresses
            
        Returns:
            Dict mapping address -> full pool data or None
        """
        if not pool_addresses:
            return {}
        
        # Build all calls: slot0 + liquidity for each pool
        calls = []
        for addr in pool_addresses:
            from web3 import Web3
            checksum = Web3.to_checksum_address(addr)
            calls.append((checksum, True, bytes.fromhex(V3_SLOT0_SELECTOR[2:])))
            calls.append((checksum, True, bytes.fromhex(V3_LIQUIDITY_SELECTOR[2:])))
        
        self.stats["calls_batched"] += len(calls)
        self.stats["calls_made"] += 1
        
        results = self._execute_multicall(calls)
        if results is None:
            return {addr: None for addr in pool_addresses}
        
        output = {}
        for i, addr in enumerate(pool_addresses):
            base_idx = i * 2
            try:
                # slot0
                s0, d0 = results[base_idx]
                if s0 and len(d0) >= 64:
                    sqrt_price = int.from_bytes(d0[0:32], "big")
                    tick = int.from_bytes(d0[32:64], "big", signed=True)
                else:
                    output[addr] = None
                    continue
                
                # liquidity
                s1, d1 = results[base_idx + 1]
                liquidity = int.from_bytes(d1[0:16], "big") if s1 and len(d1) >= 16 else 0
                
                output[addr] = {
                    "sqrt_price_x96": sqrt_price,
                    "tick": tick,
                    "liquidity": liquidity,
                }
            except Exception:
                output[addr] = None
        
        return output
    
    def get_stats(self) -> Dict[str, Any]:
        """Get batcher statistics including call types and success/fail breakdown."""
        stats = dict(self.stats)
        stats["call_types"] = dict(self.call_types)  # v2.2.0: Include call types
        stats["call_success"] = dict(self.call_success)  # v2.3.0: Per-field success counts
        stats["call_fail"] = dict(self.call_fail)  # v2.3.0: Per-field fail counts
        return stats


# Singleton batcher per (rpc_url, block_num)
_batchers: Dict[Tuple[str, int], MulticallBatcher] = {}


def get_multicall_batcher(rpc_url: str, block_num: int) -> MulticallBatcher:
    """Get or create a multicall batcher for the given RPC and block."""
    key = (rpc_url, block_num)
    if key not in _batchers:
        _batchers[key] = MulticallBatcher(rpc_url, block_num)
    return _batchers[key]


def clear_batchers() -> None:
    """Clear all cached batchers (for testing)."""
    global _batchers
    _batchers.clear()


def get_aggregate_multicall_stats() -> Dict[str, Any]:
    """
    Get aggregated stats across all multicall batchers.
    
    Returns:
        Dict with aggregated multicall metrics
    """
    total_calls_made = 0
    total_calls_batched = 0
    total_calls_failed = 0
    total_rpc_calls = 0
    total_latency_ms = 0
    # v2.2.0 Fix Step 4: Aggregate call types
    aggregated_call_types: Dict[str, int] = {}
    # v2.3.0: Per-field success/fail
    aggregated_call_success: Dict[str, int] = {}
    aggregated_call_fail: Dict[str, int] = {}
    
    for batcher in _batchers.values():
        stats = batcher.get_stats()
        total_calls_made += stats.get("calls_made", 0)
        total_calls_batched += stats.get("calls_batched", 0)
        total_calls_failed += stats.get("calls_failed", 0)
        total_rpc_calls += stats.get("rpc_calls", 0)
        total_latency_ms += stats.get("latency_ms_total", 0)
        # Aggregate call types
        for call_type, count in stats.get("call_types", {}).items():
            aggregated_call_types[call_type] = aggregated_call_types.get(call_type, 0) + count
        # v2.3.0: Aggregate success/fail per field
        for field, count in stats.get("call_success", {}).items():
            aggregated_call_success[field] = aggregated_call_success.get(field, 0) + count
        for field, count in stats.get("call_fail", {}).items():
            aggregated_call_fail[field] = aggregated_call_fail.get(field, 0) + count
    
    success_rate = 1.0
    if total_calls_batched > 0:
        success_rate = 1.0 - (total_calls_failed / total_calls_batched)
    
    # v2.2.0: Build list of requested fields that had calls
    requested_fields = [k for k, v in aggregated_call_types.items() if v > 0]
    
    # v2.3.0: Per-field success rates
    field_success_rates: Dict[str, float] = {}
    for field in requested_fields:
        total = aggregated_call_types.get(field, 0)
        success = aggregated_call_success.get(field, 0)
        if total > 0:
            field_success_rates[field] = round(success / total, 4)
    
    avg_latency_ms = 0
    if total_rpc_calls > 0:
        avg_latency_ms = total_latency_ms // total_rpc_calls
    
    return {
        "batchers_count": len(_batchers),
        "calls_made": total_calls_made,
        "calls_batched": total_calls_batched,
        "calls_failed": total_calls_failed,
        "rpc_calls": total_rpc_calls,
        "success_rate": round(success_rate, 4),
        "avg_latency_ms": avg_latency_ms,  # v2.3.0
        "call_types": aggregated_call_types,  # v2.2.0: Explicit call types
        "requested_fields": requested_fields,  # v2.2.0: List of fields fetched
        "field_success": aggregated_call_success,  # v2.3.0: Per-field success counts
        "field_fail": aggregated_call_fail,  # v2.3.0: Per-field fail counts
        "field_success_rates": field_success_rates,  # v2.3.0: Per-field success rates
    }
