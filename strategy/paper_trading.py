"""
strategy/paper_trading.py - Paper trading simulation with persistence.

Features:
- JSONL persistence for paper trades
- Cooldown/dedupe logic
- PnL tracking in bps and USDC
- Outcome categories: WOULD_EXECUTE, BLOCKED_EXEC, STALE, etc.
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
    """A single paper trade record."""
    # Identity
    spread_id: str
    block_number: int
    timestamp: str
    
    # Trade details
    chain_id: int
    buy_dex: str
    sell_dex: str
    token_in: str
    token_out: str
    fee: int
    amount_in_wei: str
    
    # Prices
    buy_price: str
    sell_price: str
    
    # PnL
    spread_bps: int
    gas_cost_bps: int
    net_pnl_bps: int
    gas_price_gwei: float
    
    # USDC estimate
    amount_in_usdc: float = 0.0
    expected_pnl_usdc: float = 0.0
    
    # Outcome
    outcome: str = TradeOutcome.WOULD_EXECUTE.value
    outcome_reason: dict = field(default_factory=dict)
    
    # Execution status
    executable: bool = True
    buy_verified: bool = True
    sell_verified: bool = True
    
    # Revalidation (filled later if requote happens)
    revalidated: bool = False
    revalidation_block: int | None = None
    would_still_execute: bool | None = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "PaperTrade":
        """Create from dictionary."""
        return cls(**data)


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
            "total_pnl_usdc": 0.0,
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
        
        # Determine outcome based on profitability and executability
        if trade.net_pnl_bps <= 0:
            trade.outcome = TradeOutcome.UNPROFITABLE.value
            self.stats["unprofitable"] += 1
        elif not trade.executable:
            trade.outcome = TradeOutcome.BLOCKED_EXEC.value
            trade.outcome_reason = {
                "buy_verified": trade.buy_verified,
                "sell_verified": trade.sell_verified,
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
        
        # Accumulate PnL (only for WOULD_EXECUTE)
        if trade.outcome == TradeOutcome.WOULD_EXECUTE.value:
            self.stats["total_pnl_bps"] += trade.net_pnl_bps
            self.stats["total_pnl_usdc"] += trade.expected_pnl_usdc
        
        # Persist to JSONL
        self._append_trade(trade)
        
        logger.info(
            f"Paper trade: {trade.outcome} {trade.spread_id} "
            f"net={trade.net_pnl_bps}bps ${trade.expected_pnl_usdc:.2f}",
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
        would_still_execute: bool,
        new_net_pnl_bps: int | None = None,
    ) -> bool:
        """
        Mark a trade as revalidated.
        
        Updates the trade in-place in the JSONL file.
        
        Args:
            spread_id: Trade spread ID
            original_block: Original trade block
            revalidation_block: Block at which revalidation was done
            would_still_execute: Whether trade would still be profitable/executable
            new_net_pnl_bps: Optional updated net PnL
        
        Returns:
            True if trade was found and updated
        """
        trades = self.load_trades()
        found = False
        
        for trade in trades:
            if trade.spread_id == spread_id and trade.block_number == original_block:
                trade.revalidated = True
                trade.revalidation_block = revalidation_block
                trade.would_still_execute = would_still_execute
                
                # Update stats if trade would no longer execute
                if not would_still_execute and trade.outcome == TradeOutcome.WOULD_EXECUTE.value:
                    self.stats["would_execute"] -= 1
                    trade.outcome = TradeOutcome.GATES_CHANGED.value
                    trade.outcome_reason = {
                        "reason": "revalidation_failed",
                        "revalidation_block": revalidation_block,
                        "new_net_pnl_bps": new_net_pnl_bps,
                    }
                
                found = True
                break
        
        if found:
            # Rewrite entire file (simple but ok for paper trading volumes)
            with open(self.trades_file, "w") as f:
                for trade in trades:
                    f.write(json.dumps(trade.to_dict()) + "\n")
            
            logger.info(
                f"Revalidation: {spread_id} would_still_execute={would_still_execute}",
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
