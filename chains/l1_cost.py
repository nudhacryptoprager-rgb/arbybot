"""
Arbitrum L1 Cost Estimator Module.

v2.1.0: Live L1 gas pricing for Arbitrum One.

Arbitrum charges L1 data fees based on calldata/compression. The NodeInterface
precompile provides gasEstimateL1Component() for accurate estimates.

NodeInterface address on Arbitrum: 0x00000000000000000000000000000000000000C8

Sources:
- Config: l1_data_gas_units * l1_gas_price_gwei (heuristic)
- Onchain: NodeInterface.gasEstimateL1Component() (accurate)
- Default: Hardcoded fallback

Usage:
    from chains.l1_cost import estimate_l1_cost_wei, get_l1_cost_with_source
    
    cost, source = get_l1_cost_with_source(w3, calldata, config)
    # cost = wei, source = "onchain" | "config" | "default"
"""

import logging
from typing import Optional, Tuple, Any

logger = logging.getLogger("chains.l1_cost")

# Arbitrum NodeInterface precompile
NODE_INTERFACE_ADDRESS = "0x00000000000000000000000000000000000000C8"

# NodeInterface ABI (minimal - just gasEstimateL1Component)
NODE_INTERFACE_ABI = [
    {
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "contractCreation", "type": "bool"},
            {"name": "data", "type": "bytes"}
        ],
        "name": "gasEstimateL1Component",
        "outputs": [
            {"name": "gasEstimateForL1", "type": "uint64"},
            {"name": "baseFee", "type": "uint256"},
            {"name": "l1BaseFeeEstimate", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

# Default L1 cost parameters (fallback)
DEFAULT_L1_DATA_GAS_UNITS = 2000
DEFAULT_L1_GAS_PRICE_GWEI = 30


def estimate_l1_cost_onchain(
    w3,  # Web3 instance
    to_address: str = "0x0000000000000000000000000000000000000000",
    calldata: bytes = b"",
    contract_creation: bool = False,
) -> Optional[int]:
    """
    Query NodeInterface for live L1 gas estimate.
    
    Args:
        w3: Web3 instance connected to Arbitrum
        to_address: Target contract address (or zero for estimation)
        calldata: Transaction calldata
        contract_creation: True if this creates a contract
        
    Returns:
        L1 gas cost in wei, or None if query fails
    """
    try:
        node_interface = w3.eth.contract(
            address=w3.to_checksum_address(NODE_INTERFACE_ADDRESS),
            abi=NODE_INTERFACE_ABI
        )
        
        result = node_interface.functions.gasEstimateL1Component(
            w3.to_checksum_address(to_address),
            contract_creation,
            calldata
        ).call()
        
        gas_estimate_for_l1 = result[0]  # uint64
        base_fee = result[1]  # uint256 (wei)
        l1_base_fee_estimate = result[2]  # uint256
        
        # L1 cost = gasEstimateForL1 * baseFee
        l1_cost_wei = gas_estimate_for_l1 * base_fee
        
        logger.debug("NodeInterface L1 cost: gas=%d, baseFee=%d, l1BaseFee=%d, cost=%d wei",
                    gas_estimate_for_l1, base_fee, l1_base_fee_estimate, l1_cost_wei)
        
        return l1_cost_wei
        
    except Exception as e:
        logger.debug("NodeInterface query failed: %s", e)
        return None


def estimate_l1_cost_from_config(config: dict) -> int:
    """
    Calculate L1 cost from config parameters.
    
    Args:
        config: Dict with l1_data_gas_units and l1_gas_price_gwei
        
    Returns:
        L1 gas cost in wei
    """
    l1_data_gas = config.get("l1_data_gas_units", DEFAULT_L1_DATA_GAS_UNITS)
    l1_gas_price = config.get("l1_gas_price_gwei", DEFAULT_L1_GAS_PRICE_GWEI)
    
    return int(l1_data_gas * l1_gas_price * 1e9)


def estimate_l1_cost_default() -> int:
    """
    Return default L1 cost (hardcoded fallback).
    
    Returns:
        L1 gas cost in wei (default: ~$0.12 at ETH=$2000)
    """
    return int(DEFAULT_L1_DATA_GAS_UNITS * DEFAULT_L1_GAS_PRICE_GWEI * 1e9)


def get_l1_cost_with_source(
    w3: Optional[Any] = None,
    calldata: bytes = b"",
    config: Optional[dict] = None,
    to_address: str = "0x0000000000000000000000000000000000000000",
    prefer_onchain: bool = True,
) -> Tuple[int, str]:
    """
    Get L1 cost estimate with source tracking.
    
    Priority:
    1. Onchain (NodeInterface) if w3 provided and prefer_onchain=True
    2. Config if config dict provided
    3. Default fallback
    
    Args:
        w3: Optional Web3 instance for live query
        calldata: Transaction calldata (for onchain estimate)
        config: Optional config dict with l1_* parameters
        to_address: Target contract address
        prefer_onchain: Try onchain first (default True)
        
    Returns:
        Tuple of (cost_wei, source)
        source: "onchain" | "config" | "default"
    """
    # Try onchain first
    if w3 is not None and prefer_onchain:
        try:
            cost = estimate_l1_cost_onchain(w3, to_address, calldata)
            if cost is not None:
                return (cost, "onchain")
        except Exception as e:
            logger.debug("Onchain L1 estimate failed: %s", e)
    
    # Try config
    if config is not None:
        if "l1_data_gas_units" in config or "l1_gas_price_gwei" in config:
            return (estimate_l1_cost_from_config(config), "config")
    
    # Default fallback
    return (estimate_l1_cost_default(), "default")


def create_sample_swap_calldata(
    token_in: str,
    token_out: str,
    amount_in: int,
    fee: int = 3000,
) -> bytes:
    """
    Create sample swap calldata for L1 estimation.
    
    This creates minimal V3 exactInputSingle calldata for
    L1 gas estimation purposes.
    
    Args:
        token_in: Input token address
        token_out: Output token address  
        amount_in: Input amount in wei
        fee: Pool fee tier
        
    Returns:
        Sample calldata bytes
    """
    # V3 exactInputSingle selector + params (simplified)
    # This is approximate - real calldata may be different
    selector = bytes.fromhex("414bf389")  # exactInputSingle
    
    # Simplified encoding (not ABI-compliant but representative size)
    # Real implementation would use web3.eth.codec.encode
    params = (
        bytes.fromhex(token_in[2:].lower().zfill(64)) +
        bytes.fromhex(token_out[2:].lower().zfill(64)) +
        fee.to_bytes(32, "big") +
        amount_in.to_bytes(32, "big")
    )
    
    return selector + params
