# PATH: dex/adapters/algebra.py
"""
Algebra-based DEX adapter (Sushiswap V3, Camelot, etc).

M5_0 REQUIREMENTS:
1. Include real pool address (0x...) in diagnostics, not just key
2. Add direction sanity check (diagnostic flag, not gate)
3. Log sqrtPriceX96, token0/token1 for debugging

KNOWN ISSUE (M5_0):
- sushiswap_v3:WETH/USDC:3000 returns ~8.6 USDC per WETH (should be ~2600)
- This is likely a pool mapping issue in registry
- See docs/status/Status_M5_0.md for details
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("dex.adapters.algebra")

# Minimum expected price for direction sanity (diagnostic only)
# If WETH -> USDC returns < 100 USDC, something is wrong
DIRECTION_SANITY_MIN = {
    ("WETH", "USDC"): Decimal("100"),
    ("WETH", "USDT"): Decimal("100"),
    ("WBTC", "USDC"): Decimal("1000"),
    ("WBTC", "USDT"): Decimal("1000"),
}


@dataclass
class AlgebraPool:
    """
    Algebra pool information.
    
    M5_0: Must include real on-chain address for debugging.
    """
    dex_id: str
    pool_address: str  # MUST be real 0x... address
    token0: str
    token1: str
    token0_decimals: int
    token1_decimals: int
    fee: int
    
    # For debugging
    sqrt_price_x96: Optional[int] = None
    tick: Optional[int] = None
    liquidity: Optional[int] = None
    
    @property
    def pool_key(self) -> str:
        """Generate pool key (for indexing, not for diagnostics)."""
        return f"pool:{self.dex_id}:{self.token0}:{self.token1}:{self.fee}"


@dataclass  
class QuoteResult:
    """
    Quote result with full diagnostics.
    
    M5_0: Diagnostics must include real pool address.
    """
    amount_out: int
    price: Decimal
    pool_address: str  # Real 0x... address
    fee: int
    
    # Diagnostics
    diagnostics: Dict[str, Any] = None
    
    # Direction sanity (diagnostic flag)
    suspect_direction: bool = False
    suspect_reason: Optional[str] = None
    
    def __post_init__(self):
        if self.diagnostics is None:
            self.diagnostics = {}


class AlgebraAdapter:
    """
    Adapter for Algebra-based DEXes (Sushiswap V3, Camelot, etc).
    
    M5_0 CONTRACTS:
    1. pool_address in diagnostics is ALWAYS real 0x... address
    2. Direction sanity check adds suspect_direction flag (not gate)
    3. Logs include sqrtPriceX96 and token order for debugging
    """
    
    def __init__(self, web3, quoter_address: str, dex_id: str = "sushiswap_v3"):
        self.web3 = web3
        self.quoter_address = quoter_address
        self.dex_id = dex_id
        
        # Pool registry: maps (token_in, token_out, fee) -> real pool address
        self._pool_registry: Dict[Tuple[str, str, int], str] = {}
    
    def register_pool(
        self,
        token_in: str,
        token_out: str,
        fee: int,
        pool_address: str,
        token0: str,
        token1: str,
        token0_decimals: int = 18,
        token1_decimals: int = 6,
    ) -> None:
        """
        Register a pool with its real on-chain address.
        
        M5_0: pool_address MUST be real 0x... address.
        """
        if not pool_address.startswith("0x"):
            logger.warning(
                f"Pool address should be 0x..., got: {pool_address}. "
                f"This will make debugging difficult."
            )
        
        key = (token_in, token_out, fee)
        self._pool_registry[key] = pool_address
        
        logger.debug(
            f"Registered pool: {self.dex_id}:{token_in}/{token_out}:{fee} -> {pool_address}"
        )
    
    def get_pool_address(self, token_in: str, token_out: str, fee: int) -> Optional[str]:
        """
        Get real pool address for a pair.
        
        Returns None if pool not registered.
        """
        # Try direct lookup
        addr = self._pool_registry.get((token_in, token_out, fee))
        if addr:
            return addr
        
        # Try reverse (some pools have reversed token order)
        addr = self._pool_registry.get((token_out, token_in, fee))
        if addr:
            return addr
        
        return None
    
    def quote(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        fee: int,
        decimals_in: int = 18,
        decimals_out: int = 6,
    ) -> Optional[QuoteResult]:
        """
        Get quote for a swap.
        
        M5_0 CONTRACTS:
        1. Returns real pool_address (0x...) in result
        2. Adds direction sanity check (diagnostic flag)
        3. Logs sqrtPriceX96 and token order for debugging
        
        Returns:
            QuoteResult with real pool address and diagnostics
        """
        # Get real pool address
        pool_address = self.get_pool_address(token_in, token_out, fee)
        
        if pool_address is None:
            logger.warning(
                f"No pool registered for {self.dex_id}:{token_in}/{token_out}:{fee}"
            )
            return None
        
        # Build diagnostics (M5_0: always include real address)
        diagnostics: Dict[str, Any] = {
            "dex_id": self.dex_id,
            "pool_address": pool_address,  # REAL 0x... address
            "pool_key": f"pool:{self.dex_id}:{token_in}:{token_out}:{fee}",
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": str(amount_in),
            "fee": fee,
            "decimals_in": decimals_in,
            "decimals_out": decimals_out,
        }
        
        try:
            # Get quote from quoter contract
            # NOTE: This is a placeholder - real implementation would call the contract
            amount_out = self._call_quoter(
                pool_address, token_in, token_out, amount_in, fee
            )
            
            if amount_out is None or amount_out <= 0:
                diagnostics["error"] = "zero_amount_out"
                return None
            
            # Calculate price
            in_normalized = Decimal(amount_in) / Decimal(10 ** decimals_in)
            out_normalized = Decimal(amount_out) / Decimal(10 ** decimals_out)
            
            if in_normalized > 0:
                price = out_normalized / in_normalized
            else:
                price = Decimal("0")
            
            diagnostics["amount_out"] = str(amount_out)
            diagnostics["price"] = str(price)
            
            # Direction sanity check (M5_0: diagnostic flag only)
            suspect_direction = False
            suspect_reason = None
            
            min_expected = DIRECTION_SANITY_MIN.get((token_in, token_out))
            if min_expected and price < min_expected:
                suspect_direction = True
                suspect_reason = f"price {price:.4f} below minimum expected {min_expected}"
                diagnostics["suspect_direction"] = True
                diagnostics["suspect_reason"] = suspect_reason
                
                logger.warning(
                    f"SUSPECT_DIRECTION: {self.dex_id}:{token_in}/{token_out}:{fee} "
                    f"price={price:.4f} < min_expected={min_expected}. "
                    f"Pool: {pool_address}. Check registry mapping."
                )
            
            return QuoteResult(
                amount_out=amount_out,
                price=price,
                pool_address=pool_address,  # Real address
                fee=fee,
                diagnostics=diagnostics,
                suspect_direction=suspect_direction,
                suspect_reason=suspect_reason,
            )
            
        except Exception as e:
            diagnostics["error"] = str(e)
            logger.error(f"Quote failed for {pool_address}: {e}")
            return None
    
    def _call_quoter(
        self,
        pool_address: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        fee: int,
    ) -> Optional[int]:
        """
        Call quoter contract.
        
        NOTE: This is a placeholder. Real implementation would:
        1. Get token addresses from registry
        2. Call quoter.quoteExactInputSingle()
        3. Log sqrtPriceX96 and tick from pool for debugging
        """
        # Placeholder - real implementation calls contract
        # For now, return None to indicate not implemented
        return None
    
    def get_pool_state(self, pool_address: str) -> Optional[Dict[str, Any]]:
        """
        Get current pool state for debugging.
        
        M5_0: Useful for debugging bad quotes.
        
        Returns:
            Dict with sqrtPriceX96, tick, liquidity, token0, token1
        """
        # Placeholder - real implementation would call pool.slot0()
        return None


def create_sushiswap_v3_adapter(web3, quoter_address: str) -> AlgebraAdapter:
    """Create Sushiswap V3 adapter (Algebra-based)."""
    return AlgebraAdapter(web3, quoter_address, dex_id="sushiswap_v3")


def create_camelot_adapter(web3, quoter_address: str) -> AlgebraAdapter:
    """Create Camelot adapter (Algebra-based)."""
    return AlgebraAdapter(web3, quoter_address, dex_id="camelot")
