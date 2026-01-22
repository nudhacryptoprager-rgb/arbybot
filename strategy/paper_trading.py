# PATH: strategy/paper_trading.py
"""
Paper trading module for ARBY.

Provides PaperTrade and PaperSession classes for simulating trades
without actual execution.

All money values are stored as Decimal-strings per Roadmap 3.2 compliance.

TRACEABILITY CONTRACT:
Every PaperTrade has:
- spread_id: Spread identifier (can be empty for edge cases)
- opportunity_id: Links to truth_report opportunities (auto-generated if not provided)

Note: Empty spread_id is allowed for edge-case tolerance. The auto-generated
opportunity_id will be "opp_" prefix + spread_id (even if empty).
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.format_money import format_money, format_money_short

logger = logging.getLogger("arby.paper_trading")


@dataclass
class PaperTrade:
    """
    Represents a simulated paper trade.
    
    All money fields are stored as strings (Roadmap 3.2 compliance).
    
    Traceability fields:
    - spread_id: Identifies the spread (can be empty for edge cases)
    - opportunity_id: Links to truth_report (auto-generated from spread_id)
    """
    spread_id: str
    outcome: str  # WOULD_EXECUTE, REJECTED, BLOCKED
    numeraire: str = "USDC"
    amount_in_numeraire: str = "0.000000"
    expected_pnl_numeraire: str = "0.000000"
    expected_pnl_bps: str = "0.00"
    gas_price_gwei: str = "0.00"
    gas_estimate: int = 0
    timestamp: str = ""
    chain_id: int = 0
    
    # Linking fields for traceability
    opportunity_id: str = ""
    
    # DEX context
    dex_a: str = ""
    dex_b: str = ""
    pool_a: str = ""
    pool_b: str = ""
    token_in: str = ""
    token_out: str = ""
    
    reject_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        
        # Auto-generate opportunity_id if not provided
        # Works even with empty spread_id (will be "opp_")
        if not self.opportunity_id:
            self.opportunity_id = f"opp_{self.spread_id}"
        
        # Ensure money fields are strings
        self.amount_in_numeraire = str(self.amount_in_numeraire)
        self.expected_pnl_numeraire = str(self.expected_pnl_numeraire)
        self.expected_pnl_bps = str(self.expected_pnl_bps)
        self.gas_price_gwei = str(self.gas_price_gwei)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization. No floats in output."""
        return {
            "spread_id": self.spread_id,
            "opportunity_id": self.opportunity_id,
            "outcome": self.outcome,
            "numeraire": self.numeraire,
            "amount_in_numeraire": self.amount_in_numeraire,
            "expected_pnl_numeraire": self.expected_pnl_numeraire,
            "expected_pnl_bps": self.expected_pnl_bps,
            "gas_price_gwei": self.gas_price_gwei,
            "gas_estimate": self.gas_estimate,
            "timestamp": self.timestamp,
            "chain_id": self.chain_id,
            "dex_buy": self.dex_a,
            "dex_sell": self.dex_b,
            "dex_a": self.dex_a,
            "dex_b": self.dex_b,
            "pool_a": self.pool_a,
            "pool_b": self.pool_b,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "reject_reason": self.reject_reason,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())


class PaperSession:
    """
    Manages a paper trading session with trade recording and statistics.
    
    All money values are stored as Decimal-strings per Roadmap 3.2.
    """

    DEFAULT_COOLDOWN_SECONDS = 60

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
        notion_capital_usdc: str = "10000.000000",
    ):
        """
        Initialize a paper trading session.
        
        Args:
            output_dir: Directory to write paper_trades.jsonl
            cooldown_seconds: Dedup cooldown for same spread_id
            notion_capital_usdc: Notional capital for return calculation
        """
        self.output_dir = output_dir
        self.cooldown_seconds = cooldown_seconds
        self.notion_capital_usdc = str(notion_capital_usdc)

        self.trades: List[PaperTrade] = []
        self._seen_spreads: Dict[str, float] = {}

        # Stats
        self.stats: Dict[str, Any] = {
            "total_trades": 0,
            "would_execute_count": 0,
            "rejected_count": 0,
            "blocked_count": 0,
            "total_pnl_usdc": "0.000000",
            "total_pnl_bps": "0.00",
        }

        self._trades_file: Optional[Path] = None
        if self.output_dir:
            self.output_dir = Path(self.output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._trades_file = self.output_dir / "paper_trades.jsonl"

    def _is_duplicate(self, spread_id: str) -> bool:
        """Check if spread_id is in cooldown period."""
        if spread_id not in self._seen_spreads:
            return False
        last_seen = self._seen_spreads[spread_id]
        elapsed = time.time() - last_seen
        return elapsed < self.cooldown_seconds

    def _mark_seen(self, spread_id: str) -> None:
        """Mark spread_id as seen with current timestamp."""
        self._seen_spreads[spread_id] = time.time()

    def _write_trade(self, trade: PaperTrade) -> None:
        """Append trade to paper_trades.jsonl file."""
        if self._trades_file:
            with open(self._trades_file, "a", encoding="utf-8") as f:
                f.write(trade.to_json() + "\n")

    def record_trade(self, trade: PaperTrade) -> bool:
        """
        Record a paper trade to the session.
        
        Edge-case tolerant: allows empty spread_id (test requirement).
        
        Args:
            trade: PaperTrade instance to record
        
        Returns:
            True if recorded, False if duplicate/cooldown
        """
        # Check cooldown dedup
        if self._is_duplicate(trade.spread_id):
            logger.debug(
                f"Skipping duplicate trade: {trade.spread_id}",
                extra={"context": {"spread_id": trade.spread_id, "reason": "cooldown_dedup"}}
            )
            return False

        # Record the trade
        self.trades.append(trade)
        self._mark_seen(trade.spread_id)

        # Update stats
        self.stats["total_trades"] += 1

        if trade.outcome == "WOULD_EXECUTE":
            self.stats["would_execute_count"] += 1

            current_pnl = Decimal(str(self.stats.get("total_pnl_usdc", "0")))
            trade_pnl = Decimal(str(trade.expected_pnl_numeraire or "0"))
            self.stats["total_pnl_usdc"] = format_money(current_pnl + trade_pnl)

            current_bps = Decimal(str(self.stats.get("total_pnl_bps", "0")))
            trade_bps = Decimal(str(trade.expected_pnl_bps or "0"))
            self.stats["total_pnl_bps"] = format_money(current_bps + trade_bps, decimals=2)

        elif trade.outcome == "REJECTED":
            self.stats["rejected_count"] += 1
        elif trade.outcome == "BLOCKED":
            self.stats["blocked_count"] += 1

        pnl_formatted = format_money_short(trade.expected_pnl_numeraire)
        amount_formatted = format_money_short(trade.amount_in_numeraire)

        logger.info(
            f"Paper trade: {trade.outcome} {trade.spread_id or '(empty)'} "
            f"PnL: {pnl_formatted} {trade.numeraire} "
            f"Amount: {amount_formatted}",
            extra={
                "context": {
                    "spread_id": trade.spread_id,
                    "opportunity_id": trade.opportunity_id,
                    "outcome": trade.outcome,
                    "pnl": trade.expected_pnl_numeraire,
                    "amount": trade.amount_in_numeraire,
                    "numeraire": trade.numeraire,
                    "dex_buy": trade.dex_a,
                    "dex_sell": trade.dex_b,
                    "token_in": trade.token_in,
                    "token_out": trade.token_out,
                }
            }
        )

        # Write to file
        self._write_trade(trade)

        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        return {
            **self.stats,
            "notion_capital_usdc": self.notion_capital_usdc,
        }

    def get_pnl_summary(self) -> Dict[str, Any]:
        """Get PnL summary with normalized return."""
        total_pnl = Decimal(str(self.stats.get("total_pnl_usdc", "0")))
        notion_capital = Decimal(str(self.notion_capital_usdc))

        normalized_return_pct = None
        if notion_capital > 0:
            normalized_return_pct = format_money(
                (total_pnl / notion_capital) * 100, decimals=4
            )

        return {
            "total_pnl_usdc": self.stats.get("total_pnl_usdc", "0.000000"),
            "total_pnl_bps": self.stats.get("total_pnl_bps", "0.00"),
            "would_execute_count": self.stats.get("would_execute_count", 0),
            "notion_capital_usdc": self.notion_capital_usdc,
            "normalized_return_pct": normalized_return_pct,
        }

    def close(self) -> None:
        """Close the session and finalize any pending writes."""
        logger.info(
            f"Paper session closed: {self.stats['total_trades']} trades, "
            f"{self.stats['would_execute_count']} would execute",
            extra={"context": {"stats": self.stats}}
        )


def calculate_usdc_value(amount: str, price: str, decimals: int = 6) -> Decimal:
    """Calculate USDC value from amount and price."""
    return Decimal(str(amount)) * Decimal(str(price))


def calculate_pnl_usdc(
    buy_value: str,
    sell_value: str,
    fees: str = "0",
    gas_cost: str = "0",
) -> Decimal:
    """Calculate PnL in USDC."""
    return (
        Decimal(str(sell_value))
        - Decimal(str(buy_value))
        - Decimal(str(fees))
        - Decimal(str(gas_cost))
    )
