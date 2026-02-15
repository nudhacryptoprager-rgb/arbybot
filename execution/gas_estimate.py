"""
Execution-Grade Gas Estimation Module.

v2.1.0: Provides accurate gas estimates using eth_estimateGas
for actual swap transactions before execution.

For M4.2+ execution readiness:
- Uses real calldata (not quoter gas estimate)
- Includes router/adapter overhead
- Validates gas limit headroom
"""

import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("execution.gas_estimate")

# Standard swap gas estimates (fallback)
DEFAULT_V3_SWAP_GAS = 150_000
DEFAULT_V2_SWAP_GAS = 120_000
DEFAULT_MULTICALL_OVERHEAD = 30_000

# Safety margin for gas estimation
GAS_ESTIMATE_MARGIN = 1.2  # 20% headroom


def estimate_swap_gas(
    w3,  # Web3 instance
    swap_calldata: bytes,
    router_address: str,
    sender_address: str,
    value_wei: int = 0,
) -> Optional[int]:
    """
    Estimate gas for swap transaction using eth_estimateGas.
    
    Args:
        w3: Web3 instance
        swap_calldata: Encoded swap calldata
        router_address: Router/executor contract address
        sender_address: From address (must have necessary approvals)
        value_wei: ETH value to send (for ETH->token swaps)
        
    Returns:
        Gas estimate in units, or None if estimation fails
    """
    try:
        gas_estimate = w3.eth.estimate_gas({
            "from": w3.to_checksum_address(sender_address),
            "to": w3.to_checksum_address(router_address),
            "data": swap_calldata,
            "value": value_wei,
        })
        
        # Add safety margin
        gas_with_margin = int(gas_estimate * GAS_ESTIMATE_MARGIN)
        
        logger.debug("eth_estimateGas: %d (with margin: %d)", gas_estimate, gas_with_margin)
        return gas_with_margin
        
    except Exception as e:
        logger.debug("eth_estimateGas failed: %s", e)
        return None


def estimate_roundtrip_gas(
    w3,
    leg1_calldata: bytes,
    leg1_router: str,
    leg2_calldata: bytes,
    leg2_router: str,
    sender_address: str,
) -> Tuple[int, int, str]:
    """
    Estimate execution gas for both legs of a roundtrip.
    
    Args:
        w3: Web3 instance
        leg1_calldata: Leg 1 swap calldata
        leg1_router: Leg 1 router address
        leg2_calldata: Leg 2 swap calldata  
        leg2_router: Leg 2 router address
        sender_address: Executor address
        
    Returns:
        Tuple of (total_gas, estimated_gas_cost_wei, source)
        source: "eth_estimateGas" | "quoter" | "default"
    """
    leg1_gas = estimate_swap_gas(w3, leg1_calldata, leg1_router, sender_address)
    leg2_gas = estimate_swap_gas(w3, leg2_calldata, leg2_router, sender_address)
    
    source = "eth_estimateGas"
    
    # Fallback if estimation fails
    if leg1_gas is None:
        leg1_gas = DEFAULT_V3_SWAP_GAS
        source = "default"
    if leg2_gas is None:
        leg2_gas = DEFAULT_V3_SWAP_GAS
        source = "default"
    
    total_gas = leg1_gas + leg2_gas + DEFAULT_MULTICALL_OVERHEAD
    
    return total_gas, source


def get_router_address(dex_id: str, chain_id: int = 42161) -> Optional[str]:
    """
    Get router address for a DEX.
    
    Args:
        dex_id: DEX identifier
        chain_id: Chain ID (default Arbitrum One)
        
    Returns:
        Router address or None if unknown
    """
    # Arbitrum One routers
    ARBITRUM_ROUTERS = {
        "uniswap_v3": "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45",  # SwapRouter02
        "sushiswap_v3": "0x8A21F6768C1f8075791D08546Dadf6daA0bE820c",  # SushiSwap Router
        "camelot_v3": "0x1F721E2E82F6676FCE4eA07A5958cF098D339e18",  # CamelotRouter
    }
    
    if chain_id == 42161:
        return ARBITRUM_ROUTERS.get(dex_id)
    
    return None


def build_exact_input_single_calldata(
    token_in: str,
    token_out: str,
    fee: int,
    recipient: str,
    amount_in: int,
    amount_out_min: int = 0,
    sqrt_price_limit: int = 0,
) -> bytes:
    """
    Build V3 exactInputSingle calldata.
    
    This is a simplified version - real implementation would use
    web3 contract.encodeABI().
    
    Args:
        token_in: Input token address
        token_out: Output token address
        fee: Pool fee tier
        recipient: Token recipient address
        amount_in: Input amount in wei
        amount_out_min: Minimum output (0 for simulation)
        sqrt_price_limit: Price limit (0 for no limit)
        
    Returns:
        Encoded calldata bytes
    """
    # exactInputSingle selector: 0x414bf389
    selector = bytes.fromhex("414bf389")
    
    # For V3 SwapRouter.exactInputSingle:
    # struct ExactInputSingleParams {
    #     address tokenIn;
    #     address tokenOut;
    #     uint24 fee;
    #     address recipient;
    #     uint256 deadline;
    #     uint256 amountIn;
    #     uint256 amountOutMinimum;
    #     uint160 sqrtPriceLimitX96;
    # }
    # 
    # This is simplified - real encoding would use eth_abi
    return selector + b"\x00" * 256  # Placeholder


def validate_gas_headroom(
    estimated_gas: int,
    gas_limit: int,
    min_headroom_ratio: float = 0.1,
) -> Tuple[bool, str]:
    """
    Validate that gas estimate has sufficient headroom.
    
    Args:
        estimated_gas: Estimated gas units
        gas_limit: Maximum gas limit
        min_headroom_ratio: Minimum headroom (default 10%)
        
    Returns:
        Tuple of (is_valid, message)
    """
    if estimated_gas > gas_limit:
        return False, f"OVER_LIMIT: {estimated_gas}>{gas_limit}"
    
    headroom = (gas_limit - estimated_gas) / gas_limit
    if headroom < min_headroom_ratio:
        return False, f"LOW_HEADROOM: {headroom:.2%}<{min_headroom_ratio:.0%}"
    
    return True, f"OK: headroom={headroom:.2%}"
