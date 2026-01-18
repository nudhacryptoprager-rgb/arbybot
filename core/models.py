# PATH: core/models.py
"""
Core data models for ARBY.

Contains Token, Pool, Quote, Opportunity, Trade, and other domain models.
All money fields use Decimal/string per Roadmap 3.2.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from core.constants import (
    DexType,
    TokenStatus,
    PoolStatus,
    TradeDirection,
    TradeStatus,
    OpportunityStatus,
    TradeOutcome,
    DEFAULT_QUOTE_FRESHNESS_MS,
)

if TYPE_CHECKING:
    from core.exceptions import ErrorCode


# =============================================================================
# CHAIN INFO
# =============================================================================

@dataclass
class ChainInfo:
    """Information about a blockchain network."""
    
    chain_id: int
    name: str
    rpc_url: str = ""
    block_time_ms: int = 12000  # 12 seconds default
    native_token: str = "ETH"
    explorer_url: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "name": self.name,
            "rpc_url": self.rpc_url,
            "block_time_ms": self.block_time_ms,
            "native_token": self.native_token,
            "explorer_url": self.explorer_url,
        }


# =============================================================================
# TOKEN
# =============================================================================

@dataclass
class Token:
    """Token on a specific chain."""
    
    chain_id: int
    address: str
    symbol: str
    name: str
    decimals: int
    is_core: bool = False
    status: TokenStatus = TokenStatus.VERIFIED
    
    def __hash__(self) -> int:
        """Hash by chain_id and normalized address."""
        return hash((self.chain_id, self.address.lower()))
    
    def __eq__(self, other: object) -> bool:
        """Equal if same chain_id and address (case-insensitive)."""
        if not isinstance(other, Token):
            return False
        return (
            self.chain_id == other.chain_id
            and self.address.lower() == other.address.lower()
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "address": self.address,
            "symbol": self.symbol,
            "name": self.name,
            "decimals": self.decimals,
            "is_core": self.is_core,
            "status": self.status.value,
        }


# =============================================================================
# POOL
# =============================================================================

@dataclass
class Pool:
    """Liquidity pool on a DEX."""
    
    chain_id: int
    dex_id: str
    dex_type: DexType
    pool_address: str
    token0: Token
    token1: Token
    fee: int = 0  # Fee in hundredths of a bip (e.g., 500 = 0.05%)
    status: PoolStatus = PoolStatus.ACTIVE
    
    def __hash__(self) -> int:
        """Hash by chain_id and pool_address."""
        return hash((self.chain_id, self.pool_address.lower()))
    
    def __eq__(self, other: object) -> bool:
        """Equal if same chain_id and pool_address."""
        if not isinstance(other, Pool):
            return False
        return (
            self.chain_id == other.chain_id
            and self.pool_address.lower() == other.pool_address.lower()
        )
    
    @property
    def pair_key(self) -> str:
        """Canonical pair key (sorted alphabetically)."""
        symbols = sorted([self.token0.symbol, self.token1.symbol])
        return f"{symbols[0]}/{symbols[1]}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "dex_id": self.dex_id,
            "dex_type": self.dex_type.value,
            "pool_address": self.pool_address,
            "token0": self.token0.to_dict(),
            "token1": self.token1.to_dict(),
            "fee": self.fee,
            "status": self.status.value,
            "pair_key": self.pair_key,
        }


# =============================================================================
# QUOTE
# =============================================================================

@dataclass
class Quote:
    """
    Quote from a DEX.
    
    Per Roadmap M1.1: Contains pool, direction, block_number, timestamp_ms, gas_estimate, ticks_crossed.
    """
    pool: Pool
    direction: TradeDirection
    token_in: Token
    token_out: Token
    amount_in: int  # wei
    amount_out: int  # wei
    block_number: int
    timestamp_ms: int
    gas_estimate: int
    ticks_crossed: int = 0
    sqrt_price_x96_after: Optional[int] = None
    latency_ms: int = 0
    
    @property
    def is_fresh(self) -> bool:
        """Check if quote is fresh (within freshness threshold)."""
        from core.time import now_ms
        age_ms = now_ms() - self.timestamp_ms
        return age_ms <= DEFAULT_QUOTE_FRESHNESS_MS
    
    @property
    def effective_price(self) -> Decimal:
        """
        Calculate effective price (amount_out / amount_in) normalized by decimals.
        
        Returns price in terms of token_out per token_in.
        """
        if self.amount_in == 0:
            return Decimal("0")
        
        # Normalize by decimals
        amount_in_normalized = Decimal(self.amount_in) / Decimal(10 ** self.token_in.decimals)
        amount_out_normalized = Decimal(self.amount_out) / Decimal(10 ** self.token_out.decimals)
        
        if amount_in_normalized == 0:
            return Decimal("0")
        
        return amount_out_normalized / amount_in_normalized
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pool_address": self.pool.pool_address,
            "direction": self.direction.value,
            "token_in": self.token_in.symbol,
            "token_out": self.token_out.symbol,
            "amount_in": str(self.amount_in),
            "amount_out": str(self.amount_out),
            "block_number": self.block_number,
            "timestamp_ms": self.timestamp_ms,
            "gas_estimate": self.gas_estimate,
            "ticks_crossed": self.ticks_crossed,
            "effective_price": str(self.effective_price),
            "is_fresh": self.is_fresh,
        }


# =============================================================================
# QUOTE CURVE
# =============================================================================

@dataclass
class QuoteCurve:
    """Quote curve for analyzing price impact."""
    
    pool: Pool
    direction: TradeDirection
    amounts_in: List[int]
    amounts_out: List[int]
    block_number: int
    timestamp_ms: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pool_address": self.pool.pool_address,
            "direction": self.direction.value,
            "amounts_in": [str(a) for a in self.amounts_in],
            "amounts_out": [str(a) for a in self.amounts_out],
            "block_number": self.block_number,
            "timestamp_ms": self.timestamp_ms,
        }


# =============================================================================
# PNL BREAKDOWN
# =============================================================================

@dataclass
class PnLBreakdown:
    """
    PnL breakdown per Roadmap M1.4.
    
    Every "profit" has breakdown: revenue, cost, gas, fees, slippage.
    """
    gross_revenue: Decimal
    gross_cost: Decimal
    gas_cost: Decimal
    dex_fee: Decimal
    slippage_cost: Decimal
    net_pnl: Decimal
    settlement_currency: str = "USDC"
    
    @property
    def net_bps(self) -> Decimal:
        """Calculate net PnL in basis points."""
        if self.gross_cost == 0:
            return Decimal("0")
        return (self.net_pnl / self.gross_cost) * Decimal("10000")
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "gross_revenue": str(self.gross_revenue),
            "gross_cost": str(self.gross_cost),
            "gas_cost": str(self.gas_cost),
            "dex_fee": str(self.dex_fee),
            "slippage_cost": str(self.slippage_cost),
            "net_pnl": str(self.net_pnl),
            "net_bps": str(self.net_bps),
            "settlement_currency": self.settlement_currency,
        }


# =============================================================================
# REJECT REASON (Model, not Enum)
# =============================================================================

@dataclass
class RejectReason:
    """Reject reason with error code and details."""
    
    code: "ErrorCode"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }


# =============================================================================
# OPPORTUNITY
# =============================================================================

@dataclass
class Opportunity:
    """
    Arbitrage opportunity between two legs.
    """
    id: str
    created_at: datetime
    leg_buy: Quote
    leg_sell: Quote
    pnl: Optional[PnLBreakdown] = None
    status: OpportunityStatus = OpportunityStatus.VALID
    reject_reason: Optional[RejectReason] = None
    confidence: float = 0.0
    
    @property
    def is_executable(self) -> bool:
        """Check if opportunity is executable."""
        if self.status != OpportunityStatus.VALID:
            return False
        if self.pnl is None:
            return False
        if self.pnl.net_pnl <= 0:
            return False
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "leg_buy": self.leg_buy.to_dict(),
            "leg_sell": self.leg_sell.to_dict(),
            "pnl": self.pnl.to_dict() if self.pnl else None,
            "status": self.status.value,
            "reject_reason": self.reject_reason.to_dict() if self.reject_reason else None,
            "confidence": self.confidence,
            "is_executable": self.is_executable,
        }


# =============================================================================
# TRADE
# =============================================================================

@dataclass
class Trade:
    """
    Executed trade record.
    """
    id: str
    opportunity_id: str
    created_at: datetime
    status: TradeStatus = TradeStatus.PENDING
    tx_hash: Optional[str] = None
    gas_used: Optional[int] = None
    block_number: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "opportunity_id": self.opportunity_id,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value.lower(),
            "tx_hash": self.tx_hash,
            "gas_used": self.gas_used,
            "block_number": self.block_number,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


# =============================================================================
# LEGACY MODELS (for backwards compatibility)
# =============================================================================

@dataclass
class LegacyQuote:
    """
    Legacy Quote model for backwards compatibility.
    
    Per Roadmap M1.1: Contains block_number, timestamp, gas_estimate, ticks_crossed
    """
    pool_address: str
    token_in: str
    token_out: str
    amount_in: str  # wei as string
    amount_out: str  # wei as string
    
    # Metadata per M1.1
    block_number: int = 0
    timestamp: str = ""
    gas_estimate: int = 0
    ticks_crossed: int = 0
    
    # Source info
    chain_id: int = 0
    dex: str = ""
    fee_tier: int = 0
    
    # Price (derived)
    price: str = "0"  # amount_out / amount_in normalized
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pool_address": self.pool_address,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "amount_in": self.amount_in,
            "amount_out": self.amount_out,
            "block_number": self.block_number,
            "timestamp": self.timestamp,
            "gas_estimate": self.gas_estimate,
            "ticks_crossed": self.ticks_crossed,
            "chain_id": self.chain_id,
            "dex": self.dex,
            "fee_tier": self.fee_tier,
            "price": self.price,
        }
