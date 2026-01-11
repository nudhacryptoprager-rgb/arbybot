"""
core/models.py - Core data models.

All monetary values are in wei (int) or Decimal. NO FLOATS.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from core.constants import (
    DexType,
    OpportunityStatus,
    PoolStatus,
    TokenStatus,
    TradeDirection,
    TradeStatus,
)
from core.exceptions import ErrorCode


@dataclass(frozen=True)
class ChainInfo:
    """Chain configuration (from chains.yaml)."""
    
    chain_id: int
    chain_key: str  # e.g., "arbitrum_one"
    name: str
    native_symbol: str
    explorer_url: str
    rpc_urls: list[str]
    ws_urls: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Token:
    """Verified token information."""
    
    chain_id: int
    address: str  # checksummed
    symbol: str
    name: str
    decimals: int
    is_core: bool = False
    status: TokenStatus = TokenStatus.VERIFIED
    
    def __hash__(self) -> int:
        return hash((self.chain_id, self.address.lower()))
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Token):
            return False
        return (
            self.chain_id == other.chain_id
            and self.address.lower() == other.address.lower()
        )


@dataclass(frozen=True)
class Pool:
    """Verified pool information."""
    
    chain_id: int
    dex_id: str  # e.g., "uniswap_v3_arbitrum"
    dex_type: DexType
    pool_address: str  # checksummed
    token0: Token
    token1: Token
    fee: int  # For V3: fee tier in hundredths of bip; For V2: 0
    status: PoolStatus = PoolStatus.ACTIVE
    
    def __hash__(self) -> int:
        return hash((self.chain_id, self.pool_address.lower()))
    
    @property
    def pair_key(self) -> str:
        """Canonical pair key (sorted alphabetically)."""
        symbols = sorted([self.token0.symbol, self.token1.symbol])
        return f"{symbols[0]}/{symbols[1]}"


@dataclass
class Quote:
    """
    Single directional quote from a DEX.
    
    All amounts in wei (int). No floats.
    """
    
    # Identity
    pool: Pool
    direction: TradeDirection
    
    # Tokens (explicit for correct decimal handling)
    token_in: Token
    token_out: Token
    
    # Amounts (in wei)
    amount_in: int  # What you pay
    amount_out: int  # What you receive
    
    # Freshness
    block_number: int
    timestamp_ms: int  # Unix timestamp in milliseconds
    
    # Metadata for executability
    gas_estimate: int
    ticks_crossed: int = 0  # V3 only
    sqrt_price_x96_after: int | None = None  # V3 only
    
    # For debugging
    latency_ms: int = 0
    
    @property
    def is_fresh(self) -> bool:
        """Check if quote is fresh (uses centralized freshness rules)."""
        from core.time import is_quote_fresh
        return is_quote_fresh(self.timestamp_ms)
    
    @property
    def effective_price(self) -> Decimal:
        """
        Price as Decimal (amount_out / amount_in), normalized by decimals.
        Used for comparison only, not for PnL calculation.
        """
        if self.amount_in == 0:
            return Decimal("0")
        
        # Use explicit token decimals
        normalized_in = Decimal(self.amount_in) / Decimal(10**self.token_in.decimals)
        normalized_out = Decimal(self.amount_out) / Decimal(10**self.token_out.decimals)
        
        return normalized_out / normalized_in


@dataclass
class QuoteCurve:
    """Quote curve at multiple sizes for slippage estimation."""
    
    pool: Pool
    direction: TradeDirection
    quotes: list[Quote]  # Sorted by amount_in ascending
    block_number: int
    timestamp_ms: int
    
    @property
    def sizes_usd(self) -> list[Decimal]:
        """USD values of each quote size."""
        # TODO: Implement with price oracle
        return []


@dataclass
class RejectReason:
    """Structured reject reason with code and details."""
    
    code: ErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class PnLBreakdown:
    """
    Detailed PnL breakdown in a single currency.
    
    All amounts in the settlement currency (e.g., USDC).
    Values are Decimal for precision.
    """
    
    # Gross
    gross_revenue: Decimal  # What we receive (in settlement currency)
    gross_cost: Decimal  # What we pay (in settlement currency)
    
    # Costs breakdown
    gas_cost: Decimal  # Gas in settlement currency
    dex_fee: Decimal  # DEX swap fee
    slippage_cost: Decimal  # Estimated slippage impact
    
    # Net
    net_pnl: Decimal  # Final P&L
    
    # Metadata
    settlement_currency: str  # e.g., "USDC"
    
    @property
    def net_bps(self) -> Decimal:
        """Net PnL in basis points of gross cost."""
        if self.gross_cost == 0:
            return Decimal("0")
        return (self.net_pnl / self.gross_cost) * Decimal("10000")
    
    def to_dict(self) -> dict[str, Any]:
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


@dataclass
class Opportunity:
    """
    A potential arbitrage opportunity.
    
    Contains quotes from both legs and computed PnL.
    """
    
    # Identity
    id: str  # UUID
    created_at: datetime
    
    # Legs
    leg_buy: Quote  # Where we buy the asset
    leg_sell: Quote  # Where we sell the asset
    
    # PnL
    pnl: PnLBreakdown | None = None
    
    # Evaluation
    status: OpportunityStatus = OpportunityStatus.VALID
    reject_reason: RejectReason | None = None
    confidence: Decimal = Decimal("0")
    
    # Ranking
    rank_score: Decimal = Decimal("0")
    
    @property
    def is_executable(self) -> bool:
        """Check if opportunity is valid and executable."""
        return (
            self.status == OpportunityStatus.VALID
            and self.pnl is not None
            and self.pnl.net_pnl > 0
            and self.reject_reason is None
        )
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "leg_buy_pool": self.leg_buy.pool.pool_address,
            "leg_sell_pool": self.leg_sell.pool.pool_address,
            "pnl": self.pnl.to_dict() if self.pnl else None,
            "status": self.status.value,
            "reject_reason": self.reject_reason.to_dict() if self.reject_reason else None,
            "confidence": str(self.confidence),
            "rank_score": str(self.rank_score),
        }


@dataclass
class Trade:
    """
    Executed or pending trade.
    """
    
    # Identity
    id: str  # UUID
    opportunity_id: str
    created_at: datetime
    
    # Status
    status: TradeStatus = TradeStatus.PENDING
    
    # Execution details
    tx_hash: str | None = None
    block_number: int | None = None
    gas_used: int | None = None
    gas_price: int | None = None  # in wei
    
    # Realized PnL (after execution)
    realized_pnl: PnLBreakdown | None = None
    
    # Errors
    error_code: ErrorCode | None = None
    error_message: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "opportunity_id": self.opportunity_id,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "gas_used": self.gas_used,
            "gas_price": self.gas_price,
            "realized_pnl": self.realized_pnl.to_dict() if self.realized_pnl else None,
            "error_code": self.error_code.value if self.error_code else None,
            "error_message": self.error_message,
        }
