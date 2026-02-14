# PATH: dex/adapters/algebra.py
"""
Algebra-based DEX adapter (Sushiswap V3, Camelot, etc).

M5_0 REQUIREMENTS:
1. Include real pool address (0x...) in diagnostics
2. Include token0/token1/decimals for debugging
3. Direction sanity check (diagnostic flag, not gate)
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("dex.adapters.algebra")

# Minimum expected price for direction sanity (diagnostic only)
DIRECTION_SANITY_MIN = {
    ("WETH", "USDC"): Decimal("100"),
    ("WETH", "USDT"): Decimal("100"),
    ("WBTC", "USDC"): Decimal("1000"),
    ("WBTC", "USDT"): Decimal("1000"),
}


@dataclass
class AlgebraPool:
    """Pool information with hard facts."""
    dex_id: str
    pool_address: str  # MUST be real 0x... address
    token0: str
    token1: str
    token0_decimals: int
    token1_decimals: int
    fee: int
    
    # Optional debugging info
    sqrt_price_x96: Optional[int] = None
    tick: Optional[int] = None
    liquidity: Optional[int] = None
    
    @property
    def pool_key(self) -> str:
        """Pool key (for indexing, NOT for diagnostics)."""
        return f"pool:{self.dex_id}:{self.token0}:{self.token1}:{self.fee}"


@dataclass
class QuoteResult:
    """
    Quote result with diagnostics.
    
    CONTRACT:
    - pool_address: MUST be real 0x... address
    - diagnostics: MUST include hard facts
    """
    amount_out: int
    price: Decimal
    pool_address: str  # Real 0x... address
    fee: int
    
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    
    # Direction sanity (diagnostic flag)
    suspect_direction: bool = False
    suspect_reason: Optional[str] = None


class AlgebraAdapter:
    """
    Adapter for Algebra-based DEXes.
    
    DIAGNOSTICS CONTRACT:
    - pool_address: real 0x... (NOT pool key)
    - pool_key: for indexing (separate field)
    - token0, token1, decimals: hard facts
    - suspect_direction: diagnostic flag
    """
    
    def __init__(self, web3, quoter_address: str, dex_id: str = "sushiswap_v3"):
        self.web3 = web3
        self.quoter_address = quoter_address
        self.dex_id = dex_id
        
        # Pool registry: (token_in, token_out, fee) -> AlgebraPool
        self._pool_registry: Dict[Tuple[str, str, int], AlgebraPool] = {}
    
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
        Register pool with real address.
        
        CONTRACT: pool_address MUST be real 0x...
        """
        if not pool_address.startswith("0x"):
            logger.warning(f"Pool address should be 0x..., got: {pool_address}")
        
        pool = AlgebraPool(
            dex_id=self.dex_id,
            pool_address=pool_address,
            token0=token0,
            token1=token1,
            token0_decimals=token0_decimals,
            token1_decimals=token1_decimals,
            fee=fee,
        )
        
        key = (token_in, token_out, fee)
        self._pool_registry[key] = pool
    
    def get_pool(self, token_in: str, token_out: str, fee: int) -> Optional[AlgebraPool]:
        """Get pool info."""
        pool = self._pool_registry.get((token_in, token_out, fee))
        if pool:
            return pool
        # Try reverse
        return self._pool_registry.get((token_out, token_in, fee))
    
    def get_pool_address(self, token_in: str, token_out: str, fee: int) -> Optional[str]:
        """Get real pool address."""
        pool = self.get_pool(token_in, token_out, fee)
        return pool.pool_address if pool else None
    
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
        Get quote with full diagnostics.
        
        DIAGNOSTICS INCLUDE:
        - pool_address: real 0x...
        - pool_key: for indexing
        - token0, token1: hard facts
        - suspect_direction: diagnostic flag
        """
        pool = self.get_pool(token_in, token_out, fee)
        
        if pool is None:
            logger.warning(f"No pool: {self.dex_id}:{token_in}/{token_out}:{fee}")
            return None
        
        # Build diagnostics with HARD FACTS
        diagnostics: Dict[str, Any] = {
            "dex_id": self.dex_id,
            "pool_address": pool.pool_address,  # REAL 0x...
            "pool_key": pool.pool_key,          # For indexing
            "token_in": token_in,
            "token_out": token_out,
            "token0": pool.token0,
            "token1": pool.token1,
            "token0_decimals": pool.token0_decimals,
            "token1_decimals": pool.token1_decimals,
            "amount_in": str(amount_in),
            "fee": fee,
            "decimals_in": decimals_in,
            "decimals_out": decimals_out,
        }
        
        try:
            # Get quote from quoter
            amount_out = self._call_quoter(pool.pool_address, token_in, token_out, amount_in, fee)
            
            if amount_out is None or amount_out <= 0:
                diagnostics["error"] = "zero_amount_out"
                return None
            
            # Calculate price
            in_norm = Decimal(amount_in) / Decimal(10 ** decimals_in)
            out_norm = Decimal(amount_out) / Decimal(10 ** decimals_out)
            
            price = out_norm / in_norm if in_norm > 0 else Decimal("0")
            
            diagnostics["amount_out"] = str(amount_out)
            diagnostics["price"] = str(price)
            
            # Direction sanity (diagnostic flag)
            suspect_direction = False
            suspect_reason = None
            
            min_expected = DIRECTION_SANITY_MIN.get((token_in, token_out))
            if min_expected and price < min_expected:
                suspect_direction = True
                suspect_reason = f"price {price:.4f} < min {min_expected}"
                diagnostics["suspect_direction"] = True
                diagnostics["suspect_reason"] = suspect_reason
                
                logger.warning(
                    f"SUSPECT_DIRECTION: {self.dex_id}:{token_in}/{token_out}:{fee} "
                    f"price={price:.4f}. Pool: {pool.pool_address}"
                )
            
            return QuoteResult(
                amount_out=amount_out,
                price=price,
                pool_address=pool.pool_address,
                fee=fee,
                diagnostics=diagnostics,
                suspect_direction=suspect_direction,
                suspect_reason=suspect_reason,
            )
            
        except Exception as e:
            diagnostics["error"] = str(e)
            logger.error(f"Quote failed: {pool.pool_address}: {e}")
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
        Call Algebra quoter contract.
        
        Algebra/Camelot quoteExactInputSingle signature:
          function quoteExactInputSingle(
              address tokenIn,
              address tokenOut,
              uint256 amountIn,
              uint160 limitSqrtPrice
          ) external returns (uint256 amountOut, uint16 fee);
        
        Note: Algebra uses dynamic fees, fee is OUTPUT not input.
        """
        if self.web3 is None:
            logger.debug("No web3 instance, skipping quoter call")
            return None
        
        if not self.quoter_address:
            logger.debug("No quoter address, skipping quoter call")
            return None
        
        try:
            # Selector: keccak256("quoteExactInputSingle(address,address,uint256,uint160)")[:4]
            # = 0x2d58eb1d
            SELECTOR = "0x2d58eb1d"
            
            # Encode call data
            token_in_padded = token_in[2:].lower().zfill(64)
            token_out_padded = token_out[2:].lower().zfill(64)
            amount_in_hex = hex(amount_in)[2:].zfill(64)
            sqrt_price_limit = hex(0)[2:].zfill(64)  # 0 = no limit
            
            call_data = (
                f"{SELECTOR}"
                f"{token_in_padded}"
                f"{token_out_padded}"
                f"{amount_in_hex}"
                f"{sqrt_price_limit}"
            )
            
            # Call quoter
            result_hex = self.web3.eth.call({
                "to": self.web3.to_checksum_address(self.quoter_address),
                "data": call_data,
            }).hex()
            
            # Decode response: (uint256 amountOut, uint16 fee)
            if not result_hex or result_hex == "0x":
                logger.debug("Empty quoter response")
                return None
            
            data = result_hex[2:] if result_hex.startswith("0x") else result_hex
            if len(data) < 64:
                logger.debug("Quoter response too short: %d", len(data))
                return None
            
            amount_out = int(data[0:64], 16)
            # fee is in next 32 bytes (uint16 padded to 32)
            # dynamic_fee = int(data[64:128], 16) if len(data) >= 128 else None
            
            logger.debug(
                "Algebra quoter success: %s -> %s, amountOut=%d",
                token_in[:10], token_out[:10], amount_out
            )
            
            return amount_out
            
        except Exception as e:
            logger.debug("Algebra quoter call failed: %s", e)
            return None


def create_sushiswap_v3_adapter(web3, quoter_address: str) -> AlgebraAdapter:
    """Create Sushiswap V3 adapter."""
    return AlgebraAdapter(web3, quoter_address, dex_id="sushiswap_v3")


def create_camelot_adapter(web3, quoter_address: str) -> AlgebraAdapter:
    """Create Camelot adapter."""
    return AlgebraAdapter(web3, quoter_address, dex_id="camelot")
