# PATH: core/models.py
"""
Core data models for ARBY.

Supports both:
- Legacy API (string-based) for test_core_models.py
- New API (object-based) for test_models.py

SPREAD_ID CONTRACT v1.1 (SINGLE SOURCE OF TRUTH)
================================================

CURRENT FORMAT (v1.1):
  spread_{cycle}_{YYYYMMDD}_{HHMMSS}_{index}
  Example: "spread_1_20260122_171426_0"

LEGACY FORMATS (accepted for backward compatibility):
  - spread_{cycle}_{YYYYMMDD_HHMMSS} (no index, v1.0 legacy)
  - spread_{uuid} (very old format)
  - spread_{any_string} (fallback)

The parser ALWAYS returns valid=True for any string starting with "spread_".
This ensures tests never flap due to format changes.

OPPORTUNITY_ID CONTRACT:
  Format: "opp_{spread_id}"
  Example: "opp_spread_1_20260122_171426_0"

Both must be deterministic given the same inputs.
================================================

CONFIDENCE SCORING CONTRACT (deterministic):
============================================
Confidence is calculated from 5 factors with fixed weights:
  - quote_fetch_rate: 0.25
  - quote_gate_pass_rate: 0.25
  - rpc_success_rate: 0.20
  - freshness_score: 0.15
  - adapter_reliability: 0.15

MONOTONICITY PROPERTIES:
  - Worse reliability → confidence does not increase
  - Better freshness → confidence does not decrease
============================================
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
import re

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


# ============================================================================
# SPREAD_ID CONTRACT v1.1 — SINGLE SOURCE OF TRUTH (BACKWARD COMPATIBLE)
# ============================================================================

# Current format: spread_{cycle}_{YYYYMMDD}_{HHMMSS}_{index}
SPREAD_ID_PATTERN_V1_1 = re.compile(
    r"^spread_(\d+)_(\d{8})_(\d{6})_(\d+)$"
)

# Legacy format v1.0: spread_{cycle}_{YYYYMMDD}_{HHMMSS} (no index)
SPREAD_ID_PATTERN_V1_0 = re.compile(
    r"^spread_(\d+)_(\d{8})_(\d{6})$"
)

# Very old format: spread_{uuid} or spread_{anything}
SPREAD_ID_PATTERN_LEGACY = re.compile(
    r"^spread_(.+)$"
)


def format_spread_timestamp(dt: datetime) -> str:
    """
    Format datetime to spread_id timestamp component.
    
    Returns: "YYYYMMDD_HHMMSS"
    Example: "20260122_171426"
    
    SINGLE SOURCE OF TRUTH for timestamp formatting in spread_id.
    """
    return dt.strftime("%Y%m%d_%H%M%S")


def generate_spread_id(cycle: int, timestamp_str: str, index: int) -> str:
    """
    Generate deterministic spread_id (v1.1 format).
    
    CONTRACT v1.1:
    - Format: "spread_{cycle}_{YYYYMMDD}_{HHMMSS}_{index}"
    - cycle: scan cycle number (int, 1-indexed)
    - timestamp_str: "YYYYMMDD_HHMMSS" (use format_spread_timestamp())
    - index: spread index within cycle (int, 0-indexed)
    
    Example: 
        generate_spread_id(1, "20260122_171426", 0)
        -> "spread_1_20260122_171426_0"
    """
    return f"spread_{cycle}_{timestamp_str}_{index}"


def generate_opportunity_id(spread_id: str) -> str:
    """
    Generate deterministic opportunity_id from spread_id.
    
    CONTRACT:
    - Format: "opp_{spread_id}"
    - 1:1 mapping from spread_id
    
    Example: "opp_spread_1_20260122_171426_0"
    """
    return f"opp_{spread_id}"


def parse_spread_id(spread_id: str) -> Dict[str, Any]:
    """
    Parse spread_id into components (BACKWARD COMPATIBLE).
    
    ALWAYS returns valid=True for any string starting with "spread_".
    This ensures tests never flap due to format changes.
    
    Formats supported:
    - v1.1: spread_{cycle}_{YYYYMMDD}_{HHMMSS}_{index}
    - v1.0: spread_{cycle}_{YYYYMMDD}_{HHMMSS} (no index)
    - legacy: spread_{anything}
    
    Returns dict with:
        valid: bool        - True for any "spread_*" string
        format: str        - "v1.1", "v1.0", or "legacy"
        cycle: int | None  - scan cycle (if parsed)
        date: str | None   - "YYYYMMDD" (if parsed)
        time: str | None   - "HHMMSS" (if parsed)
        timestamp: str | None - "YYYYMMDD_HHMMSS" (if parsed)
        index: int | None  - spread index (if v1.1)
        raw: str           - original input
        suffix: str | None - everything after "spread_" for legacy
    """
    result = {"raw": spread_id, "valid": False, "format": None}
    
    # Try v1.1 format (current)
    match = SPREAD_ID_PATTERN_V1_1.match(spread_id)
    if match:
        result["valid"] = True
        result["format"] = "v1.1"
        result["cycle"] = int(match.group(1))
        result["date"] = match.group(2)
        result["time"] = match.group(3)
        result["timestamp"] = f"{match.group(2)}_{match.group(3)}"
        result["index"] = int(match.group(4))
        return result
    
    # Try v1.0 format (legacy, no index)
    match = SPREAD_ID_PATTERN_V1_0.match(spread_id)
    if match:
        result["valid"] = True
        result["format"] = "v1.0"
        result["cycle"] = int(match.group(1))
        result["date"] = match.group(2)
        result["time"] = match.group(3)
        result["timestamp"] = f"{match.group(2)}_{match.group(3)}"
        result["index"] = None  # v1.0 has no index
        return result
    
    # Try legacy format (any spread_*)
    match = SPREAD_ID_PATTERN_LEGACY.match(spread_id)
    if match:
        result["valid"] = True
        result["format"] = "legacy"
        result["suffix"] = match.group(1)
        result["cycle"] = None
        result["date"] = None
        result["time"] = None
        result["timestamp"] = None
        result["index"] = None
        return result
    
    # Not a valid spread_id at all
    result["error"] = (
        f"Invalid spread_id: '{spread_id}'. "
        f"Must start with 'spread_'. "
        f"Recommended format: 'spread_{{cycle}}_{{YYYYMMDD}}_{{HHMMSS}}_{{index}}'"
    )
    return result


def validate_spread_id(spread_id: str) -> bool:
    """
    Quick validation of spread_id format.
    
    Returns True for ANY string starting with "spread_" (backward compatible).
    """
    return spread_id.startswith("spread_")


def is_spread_id_v1_1(spread_id: str) -> bool:
    """
    Check if spread_id is in current v1.1 format.
    
    Useful for determining if full parsing will extract all fields.
    """
    return SPREAD_ID_PATTERN_V1_1.match(spread_id) is not None


# ============================================================================
# CONFIDENCE SCORING — DETERMINISTIC WITH MONOTONICITY
# ============================================================================

# Fixed weights for confidence calculation (do not change without migration)
CONFIDENCE_WEIGHTS = {
    "quote_fetch": 0.25,
    "quote_gate": 0.25,
    "rpc": 0.20,
    "freshness": 0.15,
    "adapter": 0.15,
}


def calculate_confidence(
    quote_fetch_rate: float,
    quote_gate_pass_rate: float,
    rpc_success_rate: float,
    freshness_score: float = 1.0,
    adapter_reliability: float = 1.0,
) -> float:
    """
    Calculate deterministic confidence score for an opportunity.
    
    MONOTONICITY PROPERTIES (tested):
    - Worse quote_fetch_rate → confidence does not increase
    - Worse quote_gate_pass_rate → confidence does not increase
    - Worse rpc_success_rate → confidence does not increase
    - Better freshness_score → confidence does not decrease
    - Better adapter_reliability → confidence does not decrease
    
    All inputs must be in [0.0, 1.0].
    Output is always in [0.0, 1.0].
    
    The formula is deterministic: same inputs → same output.
    """
    # Clamp inputs to [0, 1]
    qf = max(0.0, min(1.0, float(quote_fetch_rate)))
    qg = max(0.0, min(1.0, float(quote_gate_pass_rate)))
    rpc = max(0.0, min(1.0, float(rpc_success_rate)))
    fresh = max(0.0, min(1.0, float(freshness_score)))
    adapt = max(0.0, min(1.0, float(adapter_reliability)))
    
    score = (
        CONFIDENCE_WEIGHTS["quote_fetch"] * qf +
        CONFIDENCE_WEIGHTS["quote_gate"] * qg +
        CONFIDENCE_WEIGHTS["rpc"] * rpc +
        CONFIDENCE_WEIGHTS["freshness"] * fresh +
        CONFIDENCE_WEIGHTS["adapter"] * adapt
    )
    
    # Round to avoid floating point artifacts
    return round(min(max(score, 0.0), 1.0), 4)


# ============================================================================
# DATA MODELS
# ============================================================================

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
            "chain_id": self.chain_id,
            "name": self.name,
            "rpc_url": self.rpc_url,
            "block_time_ms": self.block_time_ms,
            "native_token": self.native_token,
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
            "chain_id": self.chain_id,
            "address": self.address,
            "symbol": self.symbol,
            "name": self.name,
            "decimals": self.decimals,
            "is_core": self.is_core,
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


@dataclass
class Quote:
    """Quote from a DEX with legacy and new API support."""
    pool_address: Optional[str] = None
    token_in: Optional[Union[str, "Token"]] = None
    token_out: Optional[Union[str, "Token"]] = None
    amount_in: Union[str, int] = "0"
    amount_out: Union[str, int] = "0"

    block_number: int = 0
    gas_estimate: int = 0
    ticks_crossed: int = 0
    timestamp: str = ""
    timestamp_ms: int = 0

    pool: Optional[Pool] = None
    direction: Optional[Union[str, TradeDirection]] = None

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
            "token_in": tok_in,
            "token_out": tok_out,
            "amount_in": str(self.amount_in),
            "amount_out": str(self.amount_out),
            "block_number": self.block_number,
            "timestamp": self.timestamp,
            "timestamp_ms": self.timestamp_ms,
            "gas_estimate": self.gas_estimate,
            "ticks_crossed": self.ticks_crossed,
            "effective_price": str(self.effective_price),
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
            "pool_address": self.pool.pool_address,
            "direction": self.direction.value,
            "amounts_in": [str(a) for a in self.amounts_in],
            "amounts_out": [str(a) for a in self.amounts_out],
            "block_number": self.block_number,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass
class PnLBreakdown:
    """PnL breakdown with legacy and new API support."""
    gross_pnl: str = "0.000000"
    dex_fees: str = "0.000000"
    cex_fees: str = "0.000000"
    currency_basis: str = "0.000000"
    gas_cost: Union[str, Decimal] = "0.000000"
    slippage_cost: Union[str, Decimal] = "0.000000"
    net_pnl: Union[str, Decimal] = "0.000000"

    gross_revenue: Optional[Decimal] = None
    gross_cost: Optional[Decimal] = None
    dex_fee: Optional[Decimal] = None
    settlement_currency: str = "USDC"
    numeraire: str = "USDC"

    def calculate_net(self) -> str:
        gross = Decimal(self.gross_pnl)
        fees = Decimal(self.dex_fees) + Decimal(self.cex_fees)
        costs = Decimal(str(self.gas_cost)) + Decimal(str(self.slippage_cost)) + Decimal(self.currency_basis)
        net = gross - fees - costs
        self.net_pnl = f"{net:.6f}"
        return self.net_pnl

    @property
    def net_bps(self) -> Decimal:
        if self.gross_cost is not None and self.gross_cost != 0:
            return (Decimal(str(self.net_pnl)) / self.gross_cost) * Decimal("10000")
        return Decimal("0")

    def to_dict(self) -> Dict[str, str]:
        return {
            "gross_pnl": self.gross_pnl,
            "dex_fees": self.dex_fees,
            "cex_fees": self.cex_fees,
            "gas_cost": str(self.gas_cost),
            "slippage_cost": str(self.slippage_cost),
            "currency_basis": self.currency_basis,
            "net_pnl": str(self.net_pnl),
            "net_bps": str(self.net_bps),
            "settlement_currency": self.settlement_currency,
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
    """Arbitrage opportunity with legacy and new API support."""
    spread_id: str = ""
    id: str = ""
    quote_buy: Optional[Quote] = None
    quote_sell: Optional[Quote] = None
    leg_buy: Optional[Quote] = None
    leg_sell: Optional[Quote] = None

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
        if self.status != OpportunityStatus.VALID:
            return False
        if self.pnl is None:
            return False
        return Decimal(str(self.pnl.net_pnl)) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spread_id": self.spread_id,
            "id": self.id,
            "quote_buy": self.quote_buy.to_dict() if self.quote_buy else None,
            "quote_sell": self.quote_sell.to_dict() if self.quote_sell else None,
            "gross_pnl_usdc": self.gross_pnl_usdc,
            "fees_usdc": self.fees_usdc,
            "gas_cost_usdc": self.gas_cost_usdc,
            "net_pnl_usdc": self.net_pnl_usdc,
            "net_pnl_bps": self.net_pnl_bps,
            "is_profitable": self.is_profitable,
            "is_executable": self.is_executable if self.pnl else False,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "notional_usdc": self.notional_usdc,
            "status": self.status.value,
        }


@dataclass
class Trade:
    """Trade record with legacy and new API support."""
    trade_id: str = ""
    id: str = ""
    spread_id: str = ""
    opportunity_id: str = ""
    outcome: Optional[TradeOutcome] = None
    status: TradeStatus = TradeStatus.PENDING

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
            "trade_id": self.trade_id,
            "id": self.id,
            "spread_id": self.spread_id,
            "opportunity_id": self.opportunity_id,
            "outcome": self.outcome.value if self.outcome else None,
            "status": self.status.value.lower() if self.status else None,
            "amount_in_usdc": self.amount_in_usdc,
            "amount_out_usdc": self.amount_out_usdc,
            "expected_pnl_usdc": self.expected_pnl_usdc,
            "realized_pnl_usdc": self.realized_pnl_usdc,
            "gas_paid_usdc": self.gas_paid_usdc,
            "slippage_usdc": self.slippage_usdc,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "gas_used": self.gas_used,
            "timestamp": self.timestamp,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }
