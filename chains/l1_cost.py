"""
L1 Cost Estimator Module — Arbitrum + OP-Stack (Base).

v2.2.0: Added OP-Stack GasPriceOracle for Base L1 data fee estimation.
v2.1.0: Live L1 gas pricing for Arbitrum One.

Arbitrum charges L1 data fees based on calldata/compression. The NodeInterface
precompile provides gasEstimateL1Component() for accurate estimates.

OP-Stack (Base/Optimism) charges L1 data fees via GasPriceOracle precompile
at 0x420000000000000000000000000000000000000F. Post-Ecotone (EIP-4844),
uses blob base fee + base fee scalar for L1 data pricing.

NodeInterface address on Arbitrum: 0x00000000000000000000000000000000000000C8
GasPriceOracle address on OP-Stack: 0x420000000000000000000000000000000000000F

Sources:
- Config: l1_data_gas_units * l1_gas_price_gwei (heuristic)
- Onchain: NodeInterface.gasEstimateL1Component() (Arbitrum, accurate)
- Onchain: GasPriceOracle.getL1Fee(data) (OP-Stack, accurate)
- Default: Hardcoded fallback

Usage:
    from chains.l1_cost import get_l1_cost_with_source, get_l1_fee_bps
    
    cost, source = get_l1_cost_with_source(w3, calldata, config)
    # cost = wei, source = "onchain" | "config" | "default"
    
    l1_bps = get_l1_fee_bps(w3, chain="base", trade_size_wei=1e18)
    # Returns L1 data fee as basis points of trade size
"""

import logging
from typing import Optional, Tuple, Any

# E1.33: Hoist Web3 to module-level so tests can patch chains.l1_cost.Web3
# without triggering real network I/O from the public-RPC fallback path.
try:  # pragma: no cover - import shim
    from web3 import Web3  # type: ignore
except Exception:  # pragma: no cover
    Web3 = None  # type: ignore

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
# R36: Updated from 30 gwei (pre-EIP-4844) to 3 gwei (post-blob era, Mar 2024+)
DEFAULT_L1_DATA_GAS_UNITS = 2000
DEFAULT_L1_GAS_PRICE_GWEI = 3


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
    # SwapRouter02 exactInputSingle (Base/OP-Stack chains, selector 0x04e45aaf)
    # 7 ABI params × 32 bytes each = 224 bytes + 4-byte selector = 228 bytes.
    # This matches the actual calldata size for a Uniswap V3 / Aerodrome swap
    # which GasPriceOracle.getL1Fee uses to compute the exact L1 data fee.
    selector = bytes.fromhex("04e45aaf")  # SwapRouter02 exactInputSingle

    def _pad_addr(addr: str) -> bytes:
        return bytes.fromhex(addr[2:].lower().zfill(64))

    # ABI-encode the 7 exactInputSingle params (32 bytes each):
    #   tokenIn, tokenOut, fee (uint24), recipient (address),
    #   amountIn, amountOutMinimum, sqrtPriceLimitX96
    params = (
        _pad_addr(token_in)
        + _pad_addr(token_out)
        + fee.to_bytes(32, "big")
        + _pad_addr("0x0000000000000000000000000000000000000000")  # recipient
        + amount_in.to_bytes(32, "big")
        + (0).to_bytes(32, "big")  # amountOutMinimum
        + (0).to_bytes(32, "big")  # sqrtPriceLimitX96
    )

    return selector + params  # 4 + 224 = 228 bytes


# ============================================================
# OP-Stack (Base / Optimism) L1 Data Fee
# ============================================================

# GasPriceOracle precompile on OP-Stack chains
OP_GAS_PRICE_ORACLE_ADDRESS = "0x420000000000000000000000000000000000000F"

# Minimal ABI for GasPriceOracle (post-Ecotone / Fjord)
OP_GAS_PRICE_ORACLE_ABI = [
    {
        "inputs": [{"name": "_data", "type": "bytes"}],
        "name": "getL1Fee",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "l1BaseFee",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "baseFeeScalar",
        "outputs": [{"name": "", "type": "uint32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "blobBaseFeeScalar",
        "outputs": [{"name": "", "type": "uint32"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Default OP-Stack L1 fee (fallback when onchain query fails)
# Post-EIP-4844 blob era: ~$0.001–0.01 per swap tx on Base
DEFAULT_OP_L1_FEE_WEI = 5_000_000_000_000  # ~0.000005 ETH ≈ $0.01 @ ETH=$2k


# Representative swap calldata for L1 fee estimation (228 bytes).
# Pre-built once at import time to avoid rebuilding per call.
_REPRESENTATIVE_SWAP_CALLDATA: bytes = create_sample_swap_calldata(
    token_in="0x4200000000000000000000000000000000000006",   # WETH on Base
    token_out="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
    amount_in=10 ** 17,  # 0.1 WETH
    fee=500,
)


def estimate_op_l1_fee_onchain(
    w3,  # Web3 instance connected to Base/OP-Stack
    calldata: bytes = b"",
) -> Optional[int]:
    """
    Query OP-Stack GasPriceOracle for live L1 data fee.

    Uses the actual transaction calldata (or a representative 228-byte
    swap calldata) to call GasPriceOracle.getL1Fee(bytes) — this is
    the exact fee the L1 data poster would charge for this transaction.

    Args:
        w3: Web3 instance connected to Base or another OP-Stack chain
        calldata: Transaction calldata (affects L1 data cost)

    Returns:
        L1 data fee in wei, or None if query fails
    """
    try:
        oracle = w3.eth.contract(
            address=w3.to_checksum_address(OP_GAS_PRICE_ORACLE_ADDRESS),
            abi=OP_GAS_PRICE_ORACLE_ABI,
        )
        if not calldata:
            # Use representative swap calldata (228 bytes, SwapRouter02
            # exactInputSingle) — matches actual Base backrun tx size.
            calldata = _REPRESENTATIVE_SWAP_CALLDATA
        l1_fee_wei = oracle.functions.getL1Fee(calldata).call()
        logger.debug("OP-Stack GasPriceOracle L1 fee: %d wei", l1_fee_wei)
        return l1_fee_wei
    except Exception as e:
        logger.debug("OP-Stack GasPriceOracle query failed: %s", e)
        return None


def get_l1_cost_for_chain(
    w3: Optional[Any] = None,
    chain: str = "arbitrum",
    calldata: bytes = b"",
    config: Optional[dict] = None,
) -> Tuple[int, str]:
    """
    Get L1 cost estimate for a specific chain, auto-dispatching to the
    correct mechanism (NodeInterface for Arbitrum, GasPriceOracle for Base).

    Args:
        w3: Optional Web3 instance for live query
        chain: Chain name ("arbitrum", "base", etc.)
        calldata: Transaction calldata
        config: Optional config dict

    Returns:
        Tuple of (cost_wei, source)
    """
    chain_lower = chain.lower().replace("_one", "").replace("_", "")
    if chain_lower in ("base", "optimism"):
        if w3 is not None:
            cost = estimate_op_l1_fee_onchain(w3, calldata)
            if cost is not None:
                return (cost, "onchain_op")
        # R40.1: Public fallback — GasPriceOracle is a cheap read, try public RPCs
        # when primary w3 is unavailable or rate-limited (429).
        _PUBLIC_RPCS = {
            "base": ["https://base.publicnode.com", "https://mainnet.base.org"],
            "optimism": ["https://optimism.publicnode.com", "https://mainnet.optimism.io"],
        }
        for fallback_url in _PUBLIC_RPCS.get(chain_lower, []):
            try:
                if Web3 is None:  # pragma: no cover
                    break
                fb_w3 = Web3(Web3.HTTPProvider(fallback_url, request_kwargs={"timeout": 3}))
                cost = estimate_op_l1_fee_onchain(fb_w3, calldata)
                if cost is not None:
                    logger.debug("L1 cost from public fallback %s: %d wei", fallback_url, cost)
                    return (cost, "onchain_op_fallback")
            except Exception:
                continue
        return (DEFAULT_OP_L1_FEE_WEI, "default_op")
    else:
        # Arbitrum path
        return get_l1_cost_with_source(w3, calldata, config)


def get_l1_fee_bps(
    w3: Optional[Any] = None,
    chain: str = "base",
    trade_size_wei: int = 10**18,
    calldata: bytes = b"",
) -> float:
    """
    Return L1 data fee as basis points of trade size.

    This is the key integration point for the scoring pipeline:
    use this to get a dynamic gas floor that accounts for L1 data costs.

    Args:
        w3: Optional Web3 instance for live query
        chain: Chain name
        trade_size_wei: Trade notional in wei (denominated in trade token)
        calldata: Transaction calldata

    Returns:
        L1 data fee in basis points
    """
    if trade_size_wei <= 0:
        return 0.0
    l1_cost_wei, _source = get_l1_cost_for_chain(w3, chain, calldata)
    return (l1_cost_wei / trade_size_wei) * 10_000


def get_l1_fee_wei(
    chain: str = "base",
    calldata: bytes = b"",
) -> int:
    """Return L1 data fee in wei for a transaction on the given chain.

    Convenience wrapper around ``get_l1_cost_for_chain`` that:
    * For Base / OP-Stack: calls GasPriceOracle.getL1Fee via public RPC
      fallback when no w3 is provided.  Uses representative swap calldata
      when ``calldata`` is empty.
    * For other chains: returns 0 (no L1 data fee concept).
    * On any failure: returns ``DEFAULT_OP_L1_FEE_WEI`` for OP-Stack or 0.

    This is the entry point for the execution gate to get an accurate,
    cached L1 fee once per gate call rather than per candidate.

    Args:
        chain: Chain name (\"base\", \"optimism\", etc.)
        calldata: Optional actual transaction calldata; falls back to
            the representative 228-byte swap calldata when empty.

    Returns:
        L1 fee in wei (0 for non-OP-Stack chains).
    """
    _chain_lower = chain.lower().replace("_one", "").replace("_", "")
    if _chain_lower not in ("base", "optimism"):
        return 0
    fee_wei, _ = get_l1_cost_for_chain(w3=None, chain=chain, calldata=calldata)
    return int(fee_wei) if fee_wei else 0
