"""
strategy/paper_trading.py - Paper trading simulation with persistence.

Features:
- JSONL persistence for paper trades
- Cooldown/dedupe logic
- PnL tracking in bps and USDC
- Outcome categories: WOULD_EXECUTE, BLOCKED_EXEC, STALE, etc.

CONTRACT (Team Lead v4):
- token_in/token_out: REAL tokens of the trade (match spread_id/pair)
- numeraire: the currency for PnL calculation (usually USDC)
- amount_in_numeraire: trade size in numeraire
- expected_pnl_numeraire: expected profit in numeraire

EXAMPLE:
  spread_id: "WETH/ARB:uniswap_v3:sushiswap_v3:500"
  token_in: "WETH"
  token_out: "ARB"
  numeraire: "USDC"
  amount_in_numeraire: 300.0  # $300 worth of WETH
  expected_pnl_numeraire: 1.5  # $1.50 expected profit
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from core.logging import get_logger

logger = get_logger(__name__)


# Default numeraire for PnL calculations
DEFAULT_NUMERAIRE = "USDC"


class TradeOutcome(str, Enum):
    """Paper trade outcome categories."""
    WOULD_EXECUTE = "WOULD_EXECUTE"           # executable=true, profitable=true
    BLOCKED_EXEC = "BLOCKED_EXEC"             # executable=false, profitable=true
    UNPROFITABLE = "UNPROFITABLE"             # net_pnl_bps <= 0
    STALE = "STALE"                           # Block became stale before decision
    FAILED_REQUOTE = "FAILED_REQUOTE"         # Requote failed
    GATES_CHANGED = "GATES_CHANGED"           # Gates failed on revalidation
    COOLDOWN = "COOLDOWN"                     # Skipped due to cooldown


@dataclass
class PaperTrade:
    """
    A single paper trade record.
    
    CONTRACT (Dev Task v4 AC-4/AC-5):
    - token_in/token_out must match spread_id/pair (real tokens)
    - numeraire is the currency for PnL (usually USDC)
    - *_numeraire fields contain values in numeraire currency
    - Legacy fields (amount_in_usdc, expected_pnl_usdc) are supported via aliases
    
    SEMANTICS (AC-4: Paper vs Real execution):
    - economic_executable: passes gates + PnL > 0 (economic truth)
    - paper_execution_ready: economic + paper policy (ignores verification)
    - real_execution_ready: economic + verified + !blocked
    - blocked_reason_real: WHY not real_execution_ready
    """
    # Identity
    spread_id: str
    block_number: int
    timestamp: str
    
    # Trade details
    chain_id: int
    buy_dex: str
    sell_dex: str
    
    # REAL TOKENS (must match pair in spread_id) - AC-5
    token_in: str       # e.g., "WETH" for WETH/ARB spread
    token_out: str      # e.g., "ARB" for WETH/ARB spread
    
    fee: int
    amount_in_wei: str
    
    # Prices
    buy_price: str
    sell_price: str
    
    # PnL in basis points (relative)
    spread_bps: int
    gas_cost_bps: int
    net_pnl_bps: int
    gas_price_gwei: float
    
    # NUMERAIRE for PnL calculations (AC-5: source of truth)
    numeraire: str = DEFAULT_NUMERAIRE  # Currency for PnL (usually "USDC")
    amount_in_numeraire: float = 0.0    # Trade size in numeraire
    expected_pnl_numeraire: float = 0.0 # Expected profit in numeraire
    
    # Outcome
    outcome: str = TradeOutcome.WOULD_EXECUTE.value
    outcome_reason: dict = field(default_factory=dict)
    
    # AC-4: Separate paper vs real execution readiness
    economic_executable: bool = True        # Passes gates + PnL > 0
    paper_execution_ready: bool = True      # economic + paper policy (ignores verification)
    real_execution_ready: bool = False      # economic + verified + !blocked
    blocked_reason_real: str | None = None  # WHY not real_execution_ready
    
    # Legacy aliases (mapped to new fields in __post_init__)
    executable: bool = True                 # Legacy -> economic_executable
    execution_ready: bool = False           # Legacy -> real_execution_ready
    blocked_reason: str | None = None       # Legacy -> blocked_reason_real
    buy_verified: bool = True
    sell_verified: bool = True
    
    # AC-6: Revalidation with gates_changed semantics
    revalidated: bool = False
    revalidation_block: int | None = None
    # Separate paper vs real for revalidation
    would_still_paper_execute: bool | None = None
    would_still_real_execute: bool | None = None
    gates_actually_changed: bool = False    # True only if gates/quotes changed
    # Legacy field (mapped in __post_init__)
    would_still_execute: bool | None = None
    
    def __post_init__(self):
        """Sync legacy and new fields, ensure consistency."""
        # Sync executable with economic_executable
        if self.executable and not self.economic_executable:
            self.economic_executable = self.executable
        elif self.economic_executable and not self.executable:
            self.executable = self.economic_executable
        
        # Sync execution_ready with real_execution_ready
        if self.execution_ready and not self.real_execution_ready:
            self.real_execution_ready = self.execution_ready
        
        # Sync blocked_reason with blocked_reason_real
        if self.blocked_reason and not self.blocked_reason_real:
            self.blocked_reason_real = self.blocked_reason
        elif self.blocked_reason_real and not self.blocked_reason:
            self.blocked_reason = self.blocked_reason_real
        
        # AC-4: Paper policy = economic_executable (ignores verification)
        if self.economic_executable:
            self.paper_execution_ready = True
        
        # AC-4: Real policy = economic + verified
        if self.economic_executable and self.buy_verified and self.sell_verified:
            if self.blocked_reason_real is None:
                self.real_execution_ready = True
                self.execution_ready = True  # Legacy sync
        
        # Set blocked_reason_real if not real_execution_ready but economic_executable
        if self.economic_executable and not self.real_execution_ready:
            if self.blocked_reason_real is None:
                if not self.buy_verified or not self.sell_verified:
                    self.blocked_reason_real = "EXEC_DISABLED_NOT_VERIFIED"
                    self.blocked_reason = self.blocked_reason_real  # Legacy sync
        
        # Sync would_still_execute with would_still_paper_execute
        if self.would_still_execute is not None and self.would_still_paper_execute is None:
            self.would_still_paper_execute = self.would_still_execute
    
    # Legacy property aliases for backward compatibility (AC-5)
    @property
    def amount_in_usdc(self) -> float:
        """Legacy alias for amount_in_numeraire (when numeraire is USDC)."""
        if self.numeraire == "USDC":
            return self.amount_in_numeraire
        logger.warning(
            f"amount_in_usdc accessed but numeraire is {self.numeraire}, not USDC"
        )
        return self.amount_in_numeraire
    
    @property
    def expected_pnl_usdc(self) -> float:
        """Legacy alias for expected_pnl_numeraire (when numeraire is USDC)."""
        if self.numeraire == "USDC":
            return self.expected_pnl_numeraire
        logger.warning(
            f"expected_pnl_usdc accessed but numeraire is {self.numeraire}, not USDC"
        )
        return self.expected_pnl_numeraire
    
    @classmethod
    def from_legacy_kwargs(cls, **kwargs) -> "PaperTrade":
        """
        Create PaperTrade from legacy kwargs.
        
        Supports:
        - amount_in_usdc -> amount_in_numeraire
        - expected_pnl_usdc -> expected_pnl_numeraire
        
        This allows old code using amount_in_usdc to work without changes.
        """
        normalized = normalize_paper_trade_kwargs(kwargs)
        return cls(**normalized)
    
    def to_dict(self) -> dict:
        """
        Convert to dictionary for JSON serialization.
        
        AC-4: Includes both paper and real execution readiness.
        AC-5: Includes legacy aliases for backward compatibility.
        """
        result = asdict(self)
        # AC-5: Add legacy aliases for backward compatibility
        result["amount_in_usdc"] = self.amount_in_usdc
        result["expected_pnl_usdc"] = self.expected_pnl_usdc
        # AC-4: Ensure both paper and real readiness are explicit
        result["paper_execution_ready"] = self.paper_execution_ready
        result["real_execution_ready"] = self.real_execution_ready
        result["blocked_reason_real"] = self.blocked_reason_real
        # AC-6: Revalidation with gates_changed semantics
        result["would_still_paper_execute"] = self.would_still_paper_execute
        result["would_still_real_execute"] = self.would_still_real_execute
        result["gates_actually_changed"] = self.gates_actually_changed
        return result
    
    def validate_tokens_match_pair(self) -> list[str]:
        """
        Validate that token_in/token_out match spread_id pair.
        
        Returns list of violations (empty if valid).
        """
        violations = []
        
        # Extract pair from spread_id (format: "PAIR:buy_dex:sell_dex:fee")
        parts = self.spread_id.split(":")
        if len(parts) >= 1:
            pair = parts[0]  # e.g., "WETH/ARB"
            if "/" in pair:
                base, quote = pair.split("/", 1)
                
                # Check token_in matches base
                if self.token_in != base:
                    violations.append(
                        f"token_in ({self.token_in}) != pair base ({base})"
                    )
                
                # Check token_out matches quote
                if self.token_out != quote:
                    violations.append(
                        f"token_out ({self.token_out}) != pair quote ({quote})"
                    )
        
        return violations
    
    @classmethod
    def from_dict(cls, data: dict) -> "PaperTrade":
        """Create from dictionary with legacy support."""
        normalized = normalize_paper_trade_kwargs(data)
        return cls(**normalized)


def normalize_paper_trade_kwargs(kwargs: dict) -> dict:
    """
    Normalize legacy kwargs to current contract.
    
    Mappings:
    - amount_in_usdc -> amount_in_numeraire (+ numeraire="USDC")
    - expected_pnl_usdc -> expected_pnl_numeraire (+ numeraire="USDC")
    
    This allows backward compatibility with old call sites.
    """
    result = dict(kwargs)
    
    # Handle amount_in_usdc -> amount_in_numeraire
    if "amount_in_usdc" in result:
        if "amount_in_numeraire" not in result:
            result["amount_in_numeraire"] = result.pop("amount_in_usdc")
        else:
            # Both present, prefer numeraire, remove legacy
            del result["amount_in_usdc"]
        # Ensure numeraire is set
        if "numeraire" not in result:
            result["numeraire"] = "USDC"
    
    # Handle expected_pnl_usdc -> expected_pnl_numeraire
    if "expected_pnl_usdc" in result:
        if "expected_pnl_numeraire" not in result:
            result["expected_pnl_numeraire"] = result.pop("expected_pnl_usdc")
        else:
            # Both present, prefer numeraire, remove legacy
            del result["expected_pnl_usdc"]
        # Ensure numeraire is set
        if "numeraire" not in result:
            result["numeraire"] = "USDC"
    
    return result


class PaperSession:
    """
    Paper trading session with persistence.
    
    Stores trades in JSONL format for easy appending and analysis.
    Implements cooldown logic to avoid trading same spread repeatedly.
    """
    
    DEFAULT_COOLDOWN_BLOCKS = 10
    
    def __init__(
        self,
        trades_dir: Path,
        session_id: str | None = None,
        cooldown_blocks: int = DEFAULT_COOLDOWN_BLOCKS,
        simulate_blocked: bool = True,  # Policy: also simulate blocked trades
    ):
        self.trades_dir = trades_dir
        self.trades_dir.mkdir(parents=True, exist_ok=True)
        
        self.session_id = session_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.cooldown_blocks = cooldown_blocks
        self.simulate_blocked = simulate_blocked
        
        # JSONL file for this session
        self.trades_file = trades_dir / f"paper_trades_{self.session_id}.jsonl"
        
        # In-memory tracking for cooldown
        self._last_trade_block: dict[str, int] = {}  # spread_id -> last_block
        
        # Session stats
        self.stats = {
            "total_signals": 0,
            "would_execute": 0,
            "blocked_exec": 0,
            "unprofitable": 0,
            "cooldown_skipped": 0,
            "total_pnl_bps": 0,
            # AC-5: Source of truth is numeraire, not USDC legacy
            "total_pnl_numeraire": 0.0,
            "numeraire": "USDC",  # Track which numeraire we're using
        }
        
        logger.info(
            f"Paper session started: {self.session_id}",
            extra={"context": {
                "trades_file": str(self.trades_file),
                "cooldown_blocks": cooldown_blocks,
                "simulate_blocked": simulate_blocked,
            }}
        )
    
    def is_on_cooldown(self, spread_id: str, current_block: int) -> bool:
        """Check if spread is on cooldown."""
        last_block = self._last_trade_block.get(spread_id)
        if last_block is None:
            return False
        
        blocks_since = current_block - last_block
        return blocks_since < self.cooldown_blocks
    
    def record_trade(self, trade: PaperTrade) -> bool:
        """
        Record a paper trade.
        
        AC-5: Accumulates PnL via expected_pnl_numeraire (source of truth),
        not legacy expected_pnl_usdc.
        
        Returns:
            True if trade was recorded, False if skipped (cooldown)
        """
        self.stats["total_signals"] += 1
        
        # Check cooldown
        if self.is_on_cooldown(trade.spread_id, trade.block_number):
            trade.outcome = TradeOutcome.COOLDOWN.value
            trade.outcome_reason = {
                "last_block": self._last_trade_block.get(trade.spread_id),
                "cooldown_blocks": self.cooldown_blocks,
            }
            self.stats["cooldown_skipped"] += 1
            logger.debug(f"Cooldown skip: {trade.spread_id}")
            return False
        
        # AC-4: Determine outcome based on PAPER policy (not real execution)
        # Paper policy: economic_executable is enough (ignores verification)
        if trade.net_pnl_bps <= 0:
            trade.outcome = TradeOutcome.UNPROFITABLE.value
            self.stats["unprofitable"] += 1
        elif not trade.economic_executable:
            trade.outcome = TradeOutcome.BLOCKED_EXEC.value
            trade.outcome_reason = {
                "economic_executable": trade.economic_executable,
                "blocked_reason": trade.blocked_reason,
            }
            self.stats["blocked_exec"] += 1
            
            # Skip if policy doesn't allow simulating blocked
            if not self.simulate_blocked:
                logger.debug(f"Blocked skip (policy): {trade.spread_id}")
                return False
        else:
            trade.outcome = TradeOutcome.WOULD_EXECUTE.value
            self.stats["would_execute"] += 1
        
        # Update cooldown tracker
        self._last_trade_block[trade.spread_id] = trade.block_number
        
        # AC-5: Accumulate PnL via numeraire (source of truth)
        if trade.outcome == TradeOutcome.WOULD_EXECUTE.value:
            self.stats["total_pnl_bps"] += trade.net_pnl_bps
            self.stats["total_pnl_numeraire"] += trade.expected_pnl_numeraire
            # Track numeraire type
            if self.stats.get("numeraire") != trade.numeraire:
                logger.warning(
                    f"Numeraire mismatch: session={self.stats.get('numeraire')}, "
                    f"trade={trade.numeraire}"
                )
        
        # Persist to JSONL
        self._append_trade(trade)
        
        logger.info(
            f"Paper trade: {trade.outcome} {trade.spread_id} "
            f"net={trade.net_pnl_bps}bps ${trade.expected_pnl_numeraire:.2f} {trade.numeraire}",
            extra={"context": trade.to_dict()}
        )
        
        return True
    
    def _append_trade(self, trade: PaperTrade) -> None:
        """Append trade to JSONL file."""
        with open(self.trades_file, "a") as f:
            f.write(json.dumps(trade.to_dict()) + "\n")
    
    def load_trades(self) -> list[PaperTrade]:
        """Load all trades from JSONL file."""
        trades = []
        if not self.trades_file.exists():
            return trades
        
        with open(self.trades_file, "r") as f:
            for line in f:
                if line.strip():
                    trades.append(PaperTrade.from_dict(json.loads(line)))
        
        return trades
    
    def get_summary(self) -> dict:
        """Get session summary."""
        return {
            "session_id": self.session_id,
            "trades_file": str(self.trades_file),
            "cooldown_blocks": self.cooldown_blocks,
            "simulate_blocked": self.simulate_blocked,
            "stats": self.stats,
        }
    
    def get_pending_revalidation(self, current_block: int, min_blocks: int = 1) -> list[PaperTrade]:
        """
        Get trades pending revalidation.
        
        Returns trades that:
        - Have outcome WOULD_EXECUTE
        - Were not yet revalidated
        - Are at least min_blocks old
        
        Args:
            current_block: Current block number
            min_blocks: Minimum blocks since trade (default 1)
        
        Returns:
            List of trades needing revalidation
        """
        pending = []
        trades = self.load_trades()
        
        for trade in trades:
            if trade.outcome != TradeOutcome.WOULD_EXECUTE.value:
                continue
            if trade.revalidated:
                continue
            if current_block - trade.block_number < min_blocks:
                continue
            
            pending.append(trade)
        
        return pending
    
    def mark_revalidated(
        self,
        spread_id: str,
        original_block: int,
        revalidation_block: int,
        would_still_execute: bool,  # Legacy (= paper)
        new_net_pnl_bps: int | None = None,
        # AC-6: Separate paper vs real revalidation
        would_still_paper_execute: bool | None = None,
        would_still_real_execute: bool | None = None,
        gates_actually_changed: bool = False,
    ) -> bool:
        """
        Mark a trade as revalidated.
        
        AC-6: Properly tracks gates_actually_changed vs policy change.
        GATES_CHANGED outcome is only set if gates_actually_changed=True.
        
        Args:
            spread_id: Trade spread ID
            original_block: Original trade block
            revalidation_block: Block at which revalidation was done
            would_still_execute: Legacy (= paper policy)
            new_net_pnl_bps: Optional updated net PnL
            would_still_paper_execute: AC-6: Paper policy result
            would_still_real_execute: AC-6: Real policy result
            gates_actually_changed: AC-6: True only if quotes/gates changed
        
        Returns:
            True if trade was found and updated
        """
        # Default paper values from legacy if not provided
        if would_still_paper_execute is None:
            would_still_paper_execute = would_still_execute
        if would_still_real_execute is None:
            would_still_real_execute = would_still_execute
        
        trades = self.load_trades()
        found = False
        
        for trade in trades:
            if trade.spread_id == spread_id and trade.block_number == original_block:
                trade.revalidated = True
                trade.revalidation_block = revalidation_block
                # AC-6: Set both paper and real revalidation results
                trade.would_still_execute = would_still_execute  # Legacy
                trade.would_still_paper_execute = would_still_paper_execute
                trade.would_still_real_execute = would_still_real_execute
                trade.gates_actually_changed = gates_actually_changed
                
                # AC-6: Update stats ONLY if gates actually changed
                # Not just because policy/confidence changed
                if gates_actually_changed and not would_still_paper_execute:
                    if trade.outcome == TradeOutcome.WOULD_EXECUTE.value:
                        self.stats["would_execute"] -= 1
                        trade.outcome = TradeOutcome.GATES_CHANGED.value
                        trade.outcome_reason = {
                            "reason": "gates_actually_changed",
                            "revalidation_block": revalidation_block,
                            "new_net_pnl_bps": new_net_pnl_bps,
                        }
                elif not would_still_paper_execute and trade.outcome == TradeOutcome.WOULD_EXECUTE.value:
                    # Policy changed but gates didn't - different outcome
                    # Don't count as GATES_CHANGED for KPI
                    trade.outcome_reason = {
                        "reason": "policy_changed",  # Not gates
                        "revalidation_block": revalidation_block,
                        "new_net_pnl_bps": new_net_pnl_bps,
                        "gates_actually_changed": False,
                    }
                
                found = True
                break
        
        if found:
            # Rewrite entire file (simple but ok for paper trading volumes)
            with open(self.trades_file, "w") as f:
                for trade in trades:
                    f.write(json.dumps(trade.to_dict()) + "\n")
            
            logger.info(
                f"Revalidation: {spread_id} paper={would_still_paper_execute} "
                f"real={would_still_real_execute} gates_changed={gates_actually_changed}",
                extra={"context": {
                    "original_block": original_block,
                    "revalidation_block": revalidation_block,
                }}
            )
        
        return found


def calculate_usdc_value(
    amount_in_wei: int,
    implied_price: Decimal,
    token_in_decimals: int = 18,
) -> float:
    """
    Calculate USDC value of trade.
    
    For ETH trades: amount_in * implied_price = USDC value
    implied_price is already in USDC/ETH terms.
    """
    amount_in = Decimal(amount_in_wei) / Decimal(10 ** token_in_decimals)
    usdc_value = float(amount_in * implied_price)
    return usdc_value


def calculate_pnl_usdc(
    amount_in_wei: int,
    net_pnl_bps: int,
    implied_price: Decimal,
    token_in_decimals: int = 18,
) -> float:
    """
    Calculate expected PnL in USDC.
    
    PnL = trade_value_usdc * (net_pnl_bps / 10000)
    """
    trade_value_usdc = calculate_usdc_value(amount_in_wei, implied_price, token_in_decimals)
    pnl_usdc = trade_value_usdc * (net_pnl_bps / 10000)
    return pnl_usdc
