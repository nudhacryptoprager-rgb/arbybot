# PATH: execution/preflight.py
"""
M4.3 Preflight Evidence Module.

v1.0.2: Use QuoterV2 gasEstimate as primary gas source (no allowance needed)
v1.0.1: Stricter passed criteria (fallback gas doesn't count as pass)
v1.0.0: Provides eth_call / eth_estimateGas based preflight evidence
for top-N execution candidates before any actual transaction submission.

CONTRACT:
=========
- NEVER executes real transactions
- Uses eth_call for quoter simulation (extracts gasEstimate from QuoterV2)
- Falls back to eth_estimateGas only if QuoterV2 doesn't return gas
- Collects evidence of execution readiness
- Operates under kill_switch_active=True

OUTPUT:
=======
Returns PreflightEvidence with:
- leg1_eth_call_ok: bool (quoter simulation passed)
- leg2_eth_call_ok: bool
- leg1_gas_estimate: int | None (source: quoter_v2 or eth_estimateGas or fallback)
- leg2_gas_estimate: int | None
- errors: List[str]
- warnings: List[str]
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("execution.preflight")

# Maximum candidates to preflight (N)
MAX_PREFLIGHT_CANDIDATES = 3

# Default addresses (Arbitrum One)
QUOTER_V2_ADDRESS = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"  # Uniswap V3 QuoterV2


def adapt_opportunity_to_preflight_input(
    opportunity: Dict[str, Any],
    chain_key: str = "arbitrum_one",
) -> Dict[str, Any]:
    """
    Adapt an opportunity dict (from OpportunityEngine) to preflight input format.
    
    The preflight module expects leg1/leg2 structure with token addresses,
    but opportunities have symbol-based pair and flat buy_dex/sell_dex.
    
    Args:
        opportunity: Opportunity dict from OpportunityEngine.to_dict()
        chain_key: Chain for token address lookup
        
    Returns:
        Dict with leg1/leg2 structure suitable for collect_preflight_evidence()
    """
    from config import get_token_address
    
    pair = opportunity.get("pair", "")
    tokens = pair.split("/")
    token_in_symbol = tokens[0] if len(tokens) > 0 else ""
    token_out_symbol = tokens[1] if len(tokens) > 1 else ""
    
    # Map symbols to addresses
    token_in_addr = get_token_address(chain_key, token_in_symbol) or ""
    token_out_addr = get_token_address(chain_key, token_out_symbol) or ""
    
    diagnostics = opportunity.get("diagnostics", {})
    amount_in = opportunity.get("amount_in_wei", 10**18)
    
    # Build leg1 (buy leg): token_in -> token_out via buy_dex
    leg1 = {
        "dex_id": opportunity.get("buy_dex", ""),
        "pool_address": diagnostics.get("buy_pool", ""),
        "token_in": token_in_addr,
        "token_out": token_out_addr,
        "fee_tier": opportunity.get("buy_fee", 3000),
        "amount_in": amount_in,
    }
    
    # Build leg2 (sell leg): token_out -> token_in via sell_dex
    leg2 = {
        "dex_id": opportunity.get("sell_dex", ""),
        "pool_address": diagnostics.get("sell_pool", ""),
        "token_in": token_out_addr,  # reversed for sell
        "token_out": token_in_addr,
        "fee_tier": opportunity.get("sell_fee", 3000),
        "amount_in": amount_in,  # simplified; real calc would use quoted output
    }
    
    # Build route string
    route = f"{opportunity.get('buy_dex', '')}:{opportunity.get('buy_fee', 0)} -> {opportunity.get('sell_dex', '')}:{opportunity.get('sell_fee', 0)}"
    
    return {
        "spread_id": opportunity.get("spread_id", "unknown"),
        "pair": pair,
        "route": route,
        "spread_bps": float(opportunity.get("gross_spread_bps", 0)),
        "leg1": leg1,
        "leg2": leg2,
    }


@dataclass
class LegPreflightResult:
    """Result of preflight check for a single leg."""
    
    dex_id: str
    pool_address: str
    token_in: str
    token_out: str
    fee_tier: int
    amount_in: int
    
    # eth_call results
    eth_call_ok: bool = False
    eth_call_error: Optional[str] = None
    quoted_amount_out: Optional[int] = None
    
    # eth_estimateGas results
    gas_estimate: Optional[int] = None
    gas_estimate_error: Optional[str] = None
    gas_estimate_source: str = "none"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dex_id": self.dex_id,
            "pool_address": self.pool_address,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "fee_tier": self.fee_tier,
            "amount_in": self.amount_in,
            "eth_call_ok": self.eth_call_ok,
            "eth_call_error": self.eth_call_error,
            "quoted_amount_out": self.quoted_amount_out,
            "gas_estimate": self.gas_estimate,
            "gas_estimate_error": self.gas_estimate_error,
            "gas_estimate_source": self.gas_estimate_source,
        }


@dataclass
class PreflightEvidence:
    """Complete preflight evidence for an execution candidate."""
    
    spread_id: str
    pair: str
    route: str
    spread_bps: float
    
    leg1: Optional[LegPreflightResult] = None
    leg2: Optional[LegPreflightResult] = None
    
    # Overall status
    passed: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Evidence collection metadata
    evidence_source: str = "preflight_v1.0.2"
    block_number: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "spread_id": self.spread_id,
            "pair": self.pair,
            "route": self.route,
            "spread_bps": self.spread_bps,
            "leg1": self.leg1.to_dict() if self.leg1 else None,
            "leg2": self.leg2.to_dict() if self.leg2 else None,
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "evidence_source": self.evidence_source,
            "block_number": self.block_number,
        }


def run_eth_call_quote(
    w3,
    quoter_address: str,
    token_in: str,
    token_out: str,
    fee: int,
    amount_in: int,
    sqrt_price_limit: int = 0,
) -> Tuple[bool, Optional[int], Optional[int], Optional[str]]:
    """
    Run eth_call to simulate a quote.
    
    Uses QuoterV2.quoteExactInputSingle for accurate output estimation.
    
    Args:
        w3: Web3 instance
        quoter_address: QuoterV2 contract address
        token_in: Input token address
        token_out: Output token address
        fee: Pool fee tier
        amount_in: Input amount in wei
        sqrt_price_limit: Price limit (0 for no limit)
        
    Returns:
        (success, amount_out, gas_estimate, error_message)
        gas_estimate comes from QuoterV2 response (4th return value)
    """
    try:
        # QuoterV2.quoteExactInputSingle selector: 0xc6a5026a
        # struct QuoteExactInputSingleParams {
        #     address tokenIn;
        #     address tokenOut;
        #     uint256 amountIn;
        #     uint24 fee;
        #     uint160 sqrtPriceLimitX96;
        # }
        
        def encode_address(addr: str) -> bytes:
            clean = addr.lower().replace("0x", "")
            return bytes.fromhex(clean.zfill(64))
        
        def encode_uint256(val: int) -> bytes:
            return val.to_bytes(32, "big")
        
        def encode_uint24(val: int) -> bytes:
            return val.to_bytes(32, "big")
        
        def encode_uint160(val: int) -> bytes:
            return val.to_bytes(32, "big")
        
        selector = bytes.fromhex("c6a5026a")
        params = (
            encode_address(token_in) +
            encode_address(token_out) +
            encode_uint256(amount_in) +
            encode_uint24(fee) +
            encode_uint160(sqrt_price_limit)
        )
        calldata = selector + params
        
        result = w3.eth.call({
            "to": w3.to_checksum_address(quoter_address),
            "data": calldata.hex(),
        })
        
        # Decode result: returns (uint256 amountOut, uint160 sqrtPriceX96After, uint32 initializedTicksCrossed, uint256 gasEstimate)
        if len(result) >= 128:  # 4 x 32 bytes
            amount_out = int.from_bytes(result[:32], "big")
            # gas_estimate is at offset 96 (4th value)
            gas_estimate = int.from_bytes(result[96:128], "big")
            return True, amount_out, gas_estimate, None
        elif len(result) >= 32:
            # Fallback: old quoter that only returns amountOut
            amount_out = int.from_bytes(result[:32], "big")
            return True, amount_out, None, None
        
        return False, None, None, "Invalid response length"
        
    except Exception as e:
        error_msg = str(e)
        # Truncate long error messages
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "..."
        return False, None, None, error_msg


def run_eth_estimate_gas_swap(
    w3,
    router_address: str,
    token_in: str,
    token_out: str,
    fee: int,
    amount_in: int,
    sender_address: str,
) -> Tuple[Optional[int], Optional[str], str]:
    """
    Run eth_estimateGas for a swap transaction.
    
    Args:
        w3: Web3 instance
        router_address: Router contract address
        token_in: Input token address
        token_out: Output token address
        fee: Pool fee tier
        amount_in: Input amount in wei
        sender_address: Sender address (must have approvals)
        
    Returns:
        (gas_estimate, error_message, source)
        source: "eth_estimateGas" | "fallback" | "error"
    """
    try:
        from execution.gas_estimate import build_exact_input_single_calldata, GAS_ESTIMATE_MARGIN
        
        calldata = build_exact_input_single_calldata(
            token_in=token_in,
            token_out=token_out,
            fee=fee,
            recipient=sender_address,
            amount_in=amount_in,
            amount_out_min=0,
        )
        
        gas_estimate = w3.eth.estimate_gas({
            "from": w3.to_checksum_address(sender_address),
            "to": w3.to_checksum_address(router_address),
            "data": calldata.hex() if isinstance(calldata, bytes) else calldata,
        })
        
        # Add safety margin
        gas_with_margin = int(gas_estimate * GAS_ESTIMATE_MARGIN)
        return gas_with_margin, None, "eth_estimateGas"
        
    except Exception as e:
        error_msg = str(e)
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "..."
        
        # Return default fallback
        from execution.gas_estimate import DEFAULT_V3_SWAP_GAS
        return DEFAULT_V3_SWAP_GAS, error_msg, "fallback"


def collect_preflight_evidence(
    w3,
    spread_signal: Dict[str, Any],
    sender_address: str = "0x0000000000000000000000000000000000000001",  # Dummy for estimation
    current_block: Optional[int] = None,
) -> PreflightEvidence:
    """
    Collect preflight evidence for a spread signal.
    
    Args:
        w3: Web3 instance
        spread_signal: Spread signal dictionary with leg1/leg2 details
        sender_address: Address to use for gas estimation
        current_block: Current block number
        
    Returns:
        PreflightEvidence with eth_call and eth_estimateGas results
    """
    errors = []
    warnings = []
    
    spread_id = spread_signal.get("spread_id", "unknown")
    pair = spread_signal.get("pair", "unknown")
    route = spread_signal.get("route", "unknown")
    spread_bps = spread_signal.get("spread_bps", 0)
    
    evidence = PreflightEvidence(
        spread_id=spread_id,
        pair=pair,
        route=route,
        spread_bps=spread_bps,
        block_number=current_block,
    )
    
    # Extract leg details
    leg1_raw = spread_signal.get("leg1", {})
    leg2_raw = spread_signal.get("leg2", {})
    
    if not leg1_raw or not leg2_raw:
        errors.append("MISSING_LEGS: spread_signal missing leg1 or leg2")
        evidence.errors = errors
        return evidence
    
    # Collect leg1 evidence
    try:
        leg1 = LegPreflightResult(
            dex_id=leg1_raw.get("dex_id", "unknown"),
            pool_address=leg1_raw.get("pool_address", ""),
            token_in=leg1_raw.get("token_in", ""),
            token_out=leg1_raw.get("token_out", ""),
            fee_tier=leg1_raw.get("fee_tier", 3000),
            amount_in=leg1_raw.get("amount_in", 0),
        )
        
        # eth_call quote (also extracts gasEstimate from QuoterV2)
        quoter_gas = None
        if leg1.token_in and leg1.token_out and leg1.amount_in > 0:
            ok, amount_out, quoter_gas, err = run_eth_call_quote(
                w3=w3,
                quoter_address=QUOTER_V2_ADDRESS,
                token_in=leg1.token_in,
                token_out=leg1.token_out,
                fee=leg1.fee_tier,
                amount_in=leg1.amount_in,
            )
            leg1.eth_call_ok = ok
            leg1.quoted_amount_out = amount_out
            leg1.eth_call_error = err
            
            # v1.0.2: Use QuoterV2 gasEstimate as primary gas source
            if ok and quoter_gas and quoter_gas > 0:
                leg1.gas_estimate = quoter_gas
                leg1.gas_estimate_source = "quoter_v2"
            
            if not ok:
                warnings.append(f"LEG1_QUOTE_FAILED: {err}")
        
        # eth_estimateGas (fallback if quoter_v2 didn't provide gas)
        if leg1.gas_estimate is None:
            from execution.gas_estimate import get_router_address
            router = get_router_address(leg1.dex_id)
            if router and leg1.token_in and leg1.token_out:
                gas, err, source = run_eth_estimate_gas_swap(
                    w3=w3,
                    router_address=router,
                    token_in=leg1.token_in,
                    token_out=leg1.token_out,
                    fee=leg1.fee_tier,
                    amount_in=leg1.amount_in if leg1.amount_in > 0 else 10**18,
                    sender_address=sender_address,
                )
                leg1.gas_estimate = gas
                leg1.gas_estimate_error = err
                leg1.gas_estimate_source = source
                
                if err:
                    warnings.append(f"LEG1_GAS_FALLBACK: {source}")
            else:
                warnings.append(f"LEG1_NO_ROUTER: {leg1.dex_id}")
        
        evidence.leg1 = leg1
        
    except Exception as e:
        errors.append(f"LEG1_ERROR: {e}")
    
    # Collect leg2 evidence
    try:
        leg2 = LegPreflightResult(
            dex_id=leg2_raw.get("dex_id", "unknown"),
            pool_address=leg2_raw.get("pool_address", ""),
            token_in=leg2_raw.get("token_in", ""),
            token_out=leg2_raw.get("token_out", ""),
            fee_tier=leg2_raw.get("fee_tier", 3000),
            amount_in=leg2_raw.get("amount_in", 0),
        )
        
        # eth_call quote (also extracts gasEstimate from QuoterV2)
        quoter_gas = None
        if leg2.token_in and leg2.token_out and leg2.amount_in > 0:
            ok, amount_out, quoter_gas, err = run_eth_call_quote(
                w3=w3,
                quoter_address=QUOTER_V2_ADDRESS,
                token_in=leg2.token_in,
                token_out=leg2.token_out,
                fee=leg2.fee_tier,
                amount_in=leg2.amount_in,
            )
            leg2.eth_call_ok = ok
            leg2.quoted_amount_out = amount_out
            leg2.eth_call_error = err
            
            # v1.0.2: Use QuoterV2 gasEstimate as primary gas source
            if ok and quoter_gas and quoter_gas > 0:
                leg2.gas_estimate = quoter_gas
                leg2.gas_estimate_source = "quoter_v2"
            
            if not ok:
                warnings.append(f"LEG2_QUOTE_FAILED: {err}")
        
        # eth_estimateGas (fallback if quoter_v2 didn't provide gas)
        if leg2.gas_estimate is None:
            from execution.gas_estimate import get_router_address
            router = get_router_address(leg2.dex_id)
            if router and leg2.token_in and leg2.token_out:
                gas, err, source = run_eth_estimate_gas_swap(
                    w3=w3,
                    router_address=router,
                    token_in=leg2.token_in,
                    token_out=leg2.token_out,
                    fee=leg2.fee_tier,
                    amount_in=leg2.amount_in if leg2.amount_in > 0 else 10**18,
                    sender_address=sender_address,
                )
                leg2.gas_estimate = gas
                leg2.gas_estimate_error = err
                leg2.gas_estimate_source = source
                
                if err:
                    warnings.append(f"LEG2_GAS_FALLBACK: {source}")
            else:
                warnings.append(f"LEG2_NO_ROUTER: {leg2.dex_id}")
        
        evidence.leg2 = leg2
        
    except Exception as e:
        errors.append(f"LEG2_ERROR: {e}")
    
    # Determine overall pass
    # v1.0.2: Passed means: both legs have eth_call_ok=True OR real gas estimate (quoter_v2/eth_estimateGas, not fallback)
    def leg_ok(leg: Optional[LegPreflightResult]) -> bool:
        if not leg:
            return False
        if leg.eth_call_ok:
            return True
        if leg.gas_estimate is not None and leg.gas_estimate_source in ("eth_estimateGas", "quoter_v2"):
            return True
        return False
    
    leg1_ok = leg_ok(evidence.leg1)
    leg2_ok = leg_ok(evidence.leg2)
    evidence.passed = bool(leg1_ok and leg2_ok and len(errors) == 0)
    
    evidence.errors = errors
    evidence.warnings = warnings
    
    return evidence


def collect_top_n_preflight(
    w3,
    spread_signals: List[Dict[str, Any]],
    n: int = MAX_PREFLIGHT_CANDIDATES,
    sender_address: str = "0x0000000000000000000000000000000000000001",
    current_block: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Collect preflight evidence for top-N spread signals.
    
    Args:
        w3: Web3 instance
        spread_signals: List of spread signals, sorted by profitability
        n: Maximum number of candidates to preflight
        sender_address: Address for gas estimation
        current_block: Current block number
        
    Returns:
        Dictionary with preflight results suitable for artifact storage
    """
    # Limit to top N
    candidates = spread_signals[:n]
    
    results = []
    passed_count = 0
    errors_total = []
    warnings_total = []
    
    for signal in candidates:
        evidence = collect_preflight_evidence(
            w3=w3,
            spread_signal=signal,
            sender_address=sender_address,
            current_block=current_block,
        )
        
        results.append(evidence.to_dict())
        
        if evidence.passed:
            passed_count += 1
        
        errors_total.extend(evidence.errors)
        warnings_total.extend(evidence.warnings)
    
    return {
        "enabled": True,
        "candidates_count": len(candidates),
        "passed_count": passed_count,
        "results": results,
        "errors": errors_total,
        "warnings": warnings_total,
        "evidence_source": "preflight_v1.0.2",
        "block_number": current_block,
    }


def preflight_disabled_stub() -> Dict[str, Any]:
    """Return stub for disabled preflight."""
    return {
        "enabled": False,
        "candidates_count": 0,
        "passed_count": 0,
        "results": [],
        "errors": [],
        "warnings": [],
        "evidence_source": "preflight_v1.0.2",
        "block_number": None,
    }
