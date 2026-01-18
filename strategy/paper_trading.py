"""
PATCH for strategy/paper_trading.py

This file contains the FIXED version of the record_trade method.
Apply this fix around line 430-450.

BUG: ValueError: Unknown format code 'f' for object of type 'str'
CAUSE: Using :.2f format on string money values (Roadmap 3.2 compliance broke this)
FIX: Use format_money() function instead of :.2f format codes
"""

# Add this import at top of paper_trading.py:
# from core.format_money import format_money, format_money_short

# ============================================================================
# BEFORE (broken - line ~434):
# ============================================================================
"""
def record_trade(self, trade: PaperTrade) -> bool:
    ...
    logger.info(
        f"Paper trade: {trade.outcome} {trade.spread_id} "
        f"PnL: {trade.expected_pnl_numeraire:.2f} {trade.numeraire} "  # <-- CRASH HERE
        f"Amount: {trade.amount_in_numeraire:.2f}",  # <-- AND HERE
        extra={"context": {...}}
    )
    ...
"""

# ============================================================================
# AFTER (fixed):
# ============================================================================

def record_trade(self, trade: "PaperTrade") -> bool:
    """
    Record a paper trade to the session.
    
    Uses format_money() for safe string formatting of money values
    that may be str, Decimal, or numeric types.
    
    Args:
        trade: PaperTrade instance to record
        
    Returns:
        True if recorded, False if duplicate/cooldown
    """
    from core.format_money import format_money, format_money_short
    
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
    if trade.outcome == "WOULD_EXECUTE":
        self.stats["would_execute_count"] += 1
        # Safe addition with Decimal
        from decimal import Decimal
        current_pnl = Decimal(str(self.stats.get("total_pnl_usdc", "0")))
        trade_pnl = Decimal(str(trade.expected_pnl_numeraire or "0"))
        self.stats["total_pnl_usdc"] = str(current_pnl + trade_pnl)
    
    # Log with safe money formatting - NO :.2f on potentially string values!
    pnl_formatted = format_money_short(trade.expected_pnl_numeraire)
    amount_formatted = format_money_short(trade.amount_in_numeraire)
    
    logger.info(
        f"Paper trade: {trade.outcome} {trade.spread_id} "
        f"PnL: {pnl_formatted} {trade.numeraire} "
        f"Amount: {amount_formatted}",
        extra={
            "context": {
                "spread_id": trade.spread_id,
                "outcome": trade.outcome,
                "pnl": trade.expected_pnl_numeraire,
                "amount": trade.amount_in_numeraire,
                "numeraire": trade.numeraire,
            }
        }
    )
    
    return True


# ============================================================================
# Additional fixes needed in paper_trading.py - search for :.2f and replace:
# ============================================================================

# Pattern 1: f"{value:.2f}" where value might be string
# BEFORE: f"${total_pnl:.2f}"
# AFTER:  f"${format_money_short(total_pnl)}"

# Pattern 2: f"{value:.6f}" for full precision
# BEFORE: f"{amount:.6f}"  
# AFTER:  f"{format_money(amount)}"

# Pattern 3: In to_dict() or serialization
# BEFORE: "pnl": f"{self.pnl:.2f}"
# AFTER:  "pnl": format_money_short(self.pnl)
