# PATH: core/models.py
"""
Core data models for ARBY.

Contains Token, Pool, Quote, Opportunity, Trade, and other domain models.
All money fields use Decimal/string per Roadmap 3.2.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from core.constants import DexType, PoolStatus, RejectReason, TradeOutcome
from core.format_money import format_money


@dataclass
class Token:
    """
    Token representation for DEX operations.
    
    Immutable once created. Used for pool definitions and quotes.
    """
    chain_id: int
    address: str
    symbol: str
    name: str
    decimals: int = 18
    is_core: bool = False  # True for tokens in core_tokens.yaml
    
    def __post_init__(self):
        # Normalize address to lowercase
        self.address = self.address.lower()
    
    def __hash__(self):
        return hash((self.chain_id, self.address.lower()))
    
    def __eq__(self, other):
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
        }


@dataclass
class Pool:
    """
    Liquidity pool representation.
    
    Represents a single pool on a DEX. Pool address may be empty if
    not yet discovered/computed.
    """
    chain_id: int
    pool_address: str
    dex_type: DexType
    dex_id: str  # e.g., "uniswap_v3", "camelot_v3"
    token0: Token
    token1: Token
    fee: int = 0  # Fee tier in hundredths of bip (3000 = 0.30%)
    status: PoolStatus = PoolStatus.ACTIVE
    
    def __post_init__(self):
        # Normalize address
        self.pool_address = self.pool_address.lower() if self.pool_address else ""
    
    def __hash__(self):
        return hash((self.chain_id, self.pool_address.lower(), self.dex_id))
    
    @property
    def pair_symbol(self) -> str:
        return f"{self.token0.symbol}/{self.token1.symbol}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "pool_address": self.pool_address,
            "dex_type": self.dex_type.value,
            "dex_id": self.dex_id,
            "token0": self.token0.to_dict(),
            "token1": self.token1.to_dict(),
            "fee": self.fee,
            "status": self.status.value,
        }


@dataclass
class Quote:
    """
    Quote from a DEX.
    
    Per Roadmap M1.1: Contains block_number, timestamp, gas_estimate, ticks_crossed.
    
    amount_in/amount_out are int (wei) for internal calculations,
    but converted to string when serialized.
    """
    pool_address: str
    token_in: str
    token_out: str
    amount_in: int  # wei as int for calculations
    amount_out: int  # wei as int for calculations
    
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
    
    # Extended fields for adapter compatibility
    pool: Optional[Pool] = None
    direction: str = ""  # "0to1" or "1to0"
    token_in_obj: Optional[Token] = None
    token_out_obj: Optional[Token] = None
    timestamp_ms: int = 0
    sqrt_price_x96_after: Optional[int] = None
    latency_ms: int = 0
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.timestamp_ms:
            self.timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pool_address": self.pool_address,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "amount_in": str(self.amount_in),  # Convert to string for JSON
            "amount_out": str(self.amount_out),  # Convert to string for JSON
            "block_number": self.block_number,
            "timestamp": self.timestamp,
            "gas_estimate": self.gas_estimate,
            "ticks_crossed": self.ticks_crossed,
            "chain_id": self.chain_id,
            "dex": self.dex,
            "fee_tier": self.fee_tier,
            "price": self.price,
        }


@dataclass
class Opportunity:
    """
    Arbitrage opportunity between two quotes.
    
    All money fields as strings per Roadmap 3.2.
    """
    spread_id: str
    quote_buy: Quote
    quote_sell: Quote
    
    # PnL (all as string)
    gross_pnl_usdc: str = "0.000000"
    fees_usdc: str = "0.000000"
    gas_cost_usdc: str = "0.000000"
    net_pnl_usdc: str = "0.000000"
    net_pnl_bps: str = "0.00"
    
    # Status
    is_profitable: bool = False
    is_executable: bool = False
    reject_reason: Optional[RejectReason] = None
    
    # Confidence
    confidence: float = 0.0
    
    # Metadata
    timestamp: str = ""
    notional_usdc: str = "0.000000"
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "spread_id": self.spread_id,
            "quote_buy": self.quote_buy.to_dict(),
            "quote_sell": self.quote_sell.to_dict(),
            "gross_pnl_usdc": self.gross_pnl_usdc,
            "fees_usdc": self.fees_usdc,
            "gas_cost_usdc": self.gas_cost_usdc,
            "net_pnl_usdc": self.net_pnl_usdc,
            "net_pnl_bps": self.net_pnl_bps,
            "is_profitable": self.is_profitable,
            "is_executable": self.is_executable,
            "reject_reason": self.reject_reason.value if self.reject_reason else None,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "notional_usdc": self.notional_usdc,
        }


@dataclass
class Trade:
    """
    Executed trade record.
    
    All money fields as strings per Roadmap 3.2.
    """
    trade_id: str
    spread_id: str
    outcome: TradeOutcome
    
    # Amounts (string)
    amount_in_usdc: str = "0.000000"
    amount_out_usdc: str = "0.000000"
    
    # PnL (string)
    expected_pnl_usdc: str = "0.000000"
    realized_pnl_usdc: str = "0.000000"
    
    # Costs (string)
    gas_paid_usdc: str = "0.000000"
    slippage_usdc: str = "0.000000"
    
    # Execution details
    tx_hash: Optional[str] = None
    block_number: int = 0
    timestamp: str = ""
    
    # Error info
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "spread_id": self.spread_id,
            "outcome": self.outcome.value,
            "amount_in_usdc": self.amount_in_usdc,
            "amount_out_usdc": self.amount_out_usdc,
            "expected_pnl_usdc": self.expected_pnl_usdc,
            "realized_pnl_usdc": self.realized_pnl_usdc,
            "gas_paid_usdc": self.gas_paid_usdc,
            "slippage_usdc": self.slippage_usdc,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "timestamp": self.timestamp,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


@dataclass 
class PnLBreakdown:
    """
    PnL breakdown per Roadmap M1.4.
    
    Every "profit" has breakdown: fee + gas + slippage + currency basis.
    All fields as string.
    """
    gross_pnl: str = "0.000000"
    dex_fees: str = "0.000000"
    cex_fees: str = "0.000000"
    gas_cost: str = "0.000000"
    slippage_cost: str = "0.000000"
    currency_basis: str = "0.000000"  # USDC/USDT conversion cost
    net_pnl: str = "0.000000"
    
    numeraire: str = "USDC"
    
    def calculate_net(self) -> str:
        """Calculate net PnL from components."""
        from decimal import Decimal
        
        gross = Decimal(self.gross_pnl)
        fees = Decimal(self.dex_fees) + Decimal(self.cex_fees)
        costs = Decimal(self.gas_cost) + Decimal(self.slippage_cost) + Decimal(self.currency_basis)
        
        net = gross - fees - costs
        self.net_pnl = format_money(net)
        return self.net_pnl
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "gross_pnl": self.gross_pnl,
            "dex_fees": self.dex_fees,
            "cex_fees": self.cex_fees,
            "gas_cost": self.gas_cost,
            "slippage_cost": self.slippage_cost,
            "currency_basis": self.currency_basis,
            "net_pnl": self.net_pnl,
            "numeraire": self.numeraire,
        }
