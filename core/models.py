# PATH: core/models.py
"""
Core data models for ARBY.

Supports both:
- Legacy API (string-based) for test_core_models.py
- New API (object-based) for test_models.py
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

from core.constants import (
    DexType,
    TokenStatus,
    PoolStatus,
    TradeDirection,
    TradeStatus,
    OpportunityStatus,
    TradeOutcome,
)

if TYPE_CHECKING:
    from core.exceptions import ErrorCode


DEFAULT_QUOTE_FRESHNESS_MS = 3000


@dataclass
class ChainInfo:
    """Information about a blockchain network."""
    chain_id: int
    name: str
    rpc_url: str = ""
    block_time_ms: int = 12000
    native_token: str = "ETH"
    explorer_url: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id, "name": self.name, "rpc_url": self.rpc_url,
            "block_time_ms": self.block_time_ms, "native_token": self.native_token,
            "explorer_url": self.explorer_url,
        }


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
        return hash((self.chain_id, self.address.lower()))
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Token):
            return False
        return self.chain_id == other.chain_id and self.address.lower() == other.address.lower()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id, "address": self.address, "symbol": self.symbol,
            "name": self.name, "decimals": self.decimals, "is_core": self.is_core,
            "status": self.status.value,
        }


@dataclass
class Pool:
    """Liquidity pool on a DEX."""
    chain_id: int
    dex_id: str
    dex_type: DexType
    pool_address: str
    token0: Token
    token1: Token
    fee: int = 0
    status: PoolStatus = PoolStatus.ACTIVE
    
    def __hash__(self) -> int:
        return hash((self.chain_id, self.pool_address.lower()))
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Pool):
            return False
        return self.chain_id == other.chain_id and self.pool_address.lower() == other.pool_address.lower()
    
    @property
    def pair_key(self) -> str:
        symbols = sorted([self.token0.symbol, self.token1.symbol])
        return f"{symbols[0]}/{symbols[1]}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id, "dex_id": self.dex_id, "dex_type": self.dex_type.value,
            "pool_address": self.pool_address, "token0": self.token0.to_dict(),
            "token1": self.token1.to_dict(), "fee": self.fee, "status": self.status.value,
            "pair_key": self.pair_key,
        }


@dataclass
class Quote:
    """
    Quote from a DEX. Supports both legacy (string) and new (object) API.
    
    Legacy: Quote(pool_address=str, token_in=str, amount_in=str, ...)
    New: Quote(pool=Pool, direction=TradeDirection, token_in=Token, amount_in=int, timestamp_ms=int, ...)
    """
    # Legacy string-based fields
    pool_address: Optional[str] = None
    token_in: Optional[Union[str, "Token"]] = None
    token_out: Optional[Union[str, "Token"]] = None
    amount_in: Union[str, int] = "0"
    amount_out: Union[str, int] = "0"
    
    # Shared
    block_number: int = 0
    gas_estimate: int = 0
    ticks_crossed: int = 0
    timestamp: str = ""  # Legacy ISO string
    timestamp_ms: int = 0  # New ms timestamp
    
    # New object-based
    pool: Optional[Pool] = None
    direction: Optional[Union[str, TradeDirection]] = None
    
    # Extra
    sqrt_price_x96_after: Optional[int] = None
    latency_ms: int = 0
    chain_id: int = 0
    dex: str = ""
    fee_tier: int = 0
    price: str = "0"
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.timestamp_ms == 0:
            from core.time import now_ms
            self.timestamp_ms = now_ms()
        if self.pool is not None and self.pool_address is None:
            self.pool_address = self.pool.pool_address
    
    @property
    def is_fresh(self) -> bool:
        from core.time import now_ms
        return (now_ms() - self.timestamp_ms) <= DEFAULT_QUOTE_FRESHNESS_MS
    
    @property
    def effective_price(self) -> Decimal:
        amt_in = int(self.amount_in) if isinstance(self.amount_in, str) else self.amount_in
        amt_out = int(self.amount_out) if isinstance(self.amount_out, str) else self.amount_out
        if amt_in == 0:
            return Decimal("0")
        if isinstance(self.token_in, Token) and isinstance(self.token_out, Token):
            in_norm = Decimal(amt_in) / Decimal(10 ** self.token_in.decimals)
            out_norm = Decimal(amt_out) / Decimal(10 ** self.token_out.decimals)
            return out_norm / in_norm if in_norm else Decimal("0")
        return Decimal(amt_out) / Decimal(amt_in)
    
    def to_dict(self) -> Dict[str, Any]:
        tok_in = self.token_in.symbol if isinstance(self.token_in, Token) else self.token_in
        tok_out = self.token_out.symbol if isinstance(self.token_out, Token) else self.token_out
        return {
            "pool_address": self.pool_address or (self.pool.pool_address if self.pool else ""),
            "token_in": tok_in, "token_out": tok_out,
            "amount_in": str(self.amount_in), "amount_out": str(self.amount_out),
            "block_number": self.block_number, "timestamp": self.timestamp,
            "timestamp_ms": self.timestamp_ms, "gas_estimate": self.gas_estimate,
            "ticks_crossed": self.ticks_crossed, "effective_price": str(self.effective_price),
            "is_fresh": self.is_fresh,
            "direction": self.direction.value if isinstance(self.direction, TradeDirection) else self.direction,
        }


@dataclass
class QuoteCurve:
    """Quote curve for price impact analysis."""
    pool: Pool
    direction: TradeDirection
    amounts_in: List[int]
    amounts_out: List[int]
    block_number: int
    timestamp_ms: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pool_address": self.pool.pool_address, "direction": self.direction.value,
            "amounts_in": [str(a) for a in self.amounts_in],
            "amounts_out": [str(a) for a in self.amounts_out],
            "block_number": self.block_number, "timestamp_ms": self.timestamp_ms,
        }


@dataclass
class PnLBreakdown:
    """
    PnL breakdown. Supports both legacy (string) and new (Decimal) API.
    
    Legacy: gross_pnl, dex_fees, cex_fees (str) + calculate_net()
    New: gross_revenue, gross_cost, dex_fee (Decimal) + net_bps property
    """
    # Legacy string fields
    gross_pnl: str = "0.000000"
    dex_fees: str = "0.000000"
    cex_fees: str = "0.000000"
    currency_basis: str = "0.000000"
    gas_cost: Union[str, Decimal] = "0.000000"
    slippage_cost: Union[str, Decimal] = "0.000000"
    net_pnl: Union[str, Decimal] = "0.000000"
    
    # New Decimal fields
    gross_revenue: Optional[Decimal] = None
    gross_cost: Optional[Decimal] = None
    dex_fee: Optional[Decimal] = None
    
    settlement_currency: str = "USDC"
    numeraire: str = "USDC"
    
    def calculate_net(self) -> str:
        """Calculate net PnL (legacy API)."""
        gross = Decimal(self.gross_pnl)
        fees = Decimal(self.dex_fees) + Decimal(self.cex_fees)
        costs = Decimal(str(self.gas_cost)) + Decimal(str(self.slippage_cost)) + Decimal(self.currency_basis)
        net = gross - fees - costs
        self.net_pnl = f"{net:.6f}"
        return self.net_pnl
    
    @property
    def net_bps(self) -> Decimal:
        """Net PnL in basis points (new API)."""
        if self.gross_cost is not None and self.gross_cost != 0:
            return (Decimal(str(self.net_pnl)) / self.gross_cost) * Decimal("10000")
        return Decimal("0")
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "gross_pnl": self.gross_pnl, "dex_fees": self.dex_fees, "cex_fees": self.cex_fees,
            "gas_cost": str(self.gas_cost), "slippage_cost": str(self.slippage_cost),
            "currency_basis": self.currency_basis, "net_pnl": str(self.net_pnl),
            "net_bps": str(self.net_bps), "settlement_currency": self.settlement_currency,
        }


@dataclass
class RejectReason:
    """Reject reason with error code and details."""
    code: "ErrorCode"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code.value, "message": self.message, "details": self.details}


@dataclass
class Opportunity:
    """
    Arbitrage opportunity. Supports both legacy and new API.
    
    Legacy: spread_id, quote_buy/sell, net_pnl_usdc (str)
    New: id, leg_buy/sell, pnl (PnLBreakdown), is_executable property
    """
    spread_id: str = ""
    id: str = ""
    quote_buy: Optional[Quote] = None
    quote_sell: Optional[Quote] = None
    leg_buy: Optional[Quote] = None
    leg_sell: Optional[Quote] = None
    
    # Legacy money fields
    gross_pnl_usdc: str = "0.000000"
    fees_usdc: str = "0.000000"
    gas_cost_usdc: str = "0.000000"
    net_pnl_usdc: str = "0.000000"
    net_pnl_bps: str = "0.00"
    notional_usdc: str = "0.000000"
    
    pnl: Optional[PnLBreakdown] = None
    is_profitable: bool = False
    reject_reason: Optional[RejectReason] = None
    status: OpportunityStatus = OpportunityStatus.VALID
    confidence: float = 0.0
    timestamp: str = ""
    created_at: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        # Sync naming
        if self.spread_id and not self.id:
            self.id = self.spread_id
        elif self.id and not self.spread_id:
            self.spread_id = self.id
        if self.quote_buy and not self.leg_buy:
            self.leg_buy = self.quote_buy
        elif self.leg_buy and not self.quote_buy:
            self.quote_buy = self.leg_buy
        if self.quote_sell and not self.leg_sell:
            self.leg_sell = self.quote_sell
        elif self.leg_sell and not self.quote_sell:
            self.quote_sell = self.leg_sell
    
    @property
    def is_executable(self) -> bool:
        """Check if executable (new API)."""
        if self.status != OpportunityStatus.VALID:
            return False
        if self.pnl is None:
            return False
        return Decimal(str(self.pnl.net_pnl)) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "spread_id": self.spread_id, "id": self.id,
            "quote_buy": self.quote_buy.to_dict() if self.quote_buy else None,
            "quote_sell": self.quote_sell.to_dict() if self.quote_sell else None,
            "gross_pnl_usdc": self.gross_pnl_usdc, "fees_usdc": self.fees_usdc,
            "gas_cost_usdc": self.gas_cost_usdc, "net_pnl_usdc": self.net_pnl_usdc,
            "net_pnl_bps": self.net_pnl_bps, "is_profitable": self.is_profitable,
            "is_executable": self.is_executable if self.pnl else False,
            "confidence": self.confidence, "timestamp": self.timestamp,
            "notional_usdc": self.notional_usdc, "status": self.status.value,
        }


@dataclass
class Trade:
    """
    Trade record. Supports both legacy and new API.
    
    Legacy: trade_id, spread_id, outcome (TradeOutcome)
    New: id, opportunity_id, status (TradeStatus)
    """
    trade_id: str = ""
    id: str = ""
    spread_id: str = ""
    opportunity_id: str = ""
    outcome: Optional[TradeOutcome] = None
    status: TradeStatus = TradeStatus.PENDING
    
    # Legacy money
    amount_in_usdc: str = "0.000000"
    amount_out_usdc: str = "0.000000"
    expected_pnl_usdc: str = "0.000000"
    realized_pnl_usdc: str = "0.000000"
    gas_paid_usdc: str = "0.000000"
    slippage_usdc: str = "0.000000"
    
    tx_hash: Optional[str] = None
    block_number: int = 0
    gas_used: Optional[int] = None
    timestamp: str = ""
    created_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.trade_id and not self.id:
            self.id = self.trade_id
        elif self.id and not self.trade_id:
            self.trade_id = self.id
        if self.spread_id and not self.opportunity_id:
            self.opportunity_id = self.spread_id
        elif self.opportunity_id and not self.spread_id:
            self.spread_id = self.opportunity_id
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id, "id": self.id, "spread_id": self.spread_id,
            "opportunity_id": self.opportunity_id,
            "outcome": self.outcome.value if self.outcome else None,
            "status": self.status.value.lower() if self.status else None,
            "amount_in_usdc": self.amount_in_usdc, "amount_out_usdc": self.amount_out_usdc,
            "expected_pnl_usdc": self.expected_pnl_usdc, "realized_pnl_usdc": self.realized_pnl_usdc,
            "gas_paid_usdc": self.gas_paid_usdc, "slippage_usdc": self.slippage_usdc,
            "tx_hash": self.tx_hash, "block_number": self.block_number, "gas_used": self.gas_used,
            "timestamp": self.timestamp, "error_code": self.error_code, "error_message": self.error_message,
        }
