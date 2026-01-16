"""
monitoring/truth_report.py - Truth Report Generator.

Generates health and opportunity reports for M3 Opportunity Engine.

Reports include:
- Top opportunities by net_pnl_bps
- Reject histogram summary
- RPC health metrics
- Coverage stats (pairs, DEXes, chains)
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OpportunityRank:
    """
    A ranked opportunity.
    
    Team Lead Крок 3 (v4): Clear separation of metrics
    
    METRICS:
    - executable_economic: passes all gates, PnL > 0 (paper profitability truth)
    - execution_ready: executable_economic && verified && !blocked (can actually execute)
    - paper_would_execute: what paper trading would do (= executable_economic in paper mode)
    
    NOTES:
    - executable_economic is the "economic truth" - system thinks this would be profitable
    - execution_ready adds policy/verification layer - system allows execution
    - blocked_reason explains WHY execution_ready=False when executable_economic=True
    """
    rank: int
    spread_id: str
    buy_dex: str
    sell_dex: str
    pair: str
    fee: int
    amount_in: str
    spread_bps: int
    gas_cost_bps: int
    net_pnl_bps: int
    expected_pnl_usdc: float
    confidence: float = 0.0  # 0.0 - 1.0
    confidence_breakdown: dict | None = None  # Component scores
    
    # Team Lead Крок 3 (v4): Clear separation
    # executable_economic = passes all gates AND net_pnl > 0 (economic truth)
    executable_economic: bool = False
    
    # paper_would_execute = what paper trading would do (= executable_economic in paper mode)
    paper_would_execute: bool = False
    
    # execution_ready = executable_economic && verified && !blocked (actual execution permission)
    execution_ready: bool = False
    
    # blocked_reason = explains why execution_ready=False (policy/verification)
    blocked_reason: str | None = None
    
    # Legacy aliases for backward compatibility
    @property
    def executable(self) -> bool:
        """Legacy alias for executable_economic."""
        return self.executable_economic
    
    @property
    def paper_executable(self) -> bool:
        """Legacy alias for paper_would_execute."""
        return self.paper_would_execute


@dataclass
class HealthMetrics:
    """System health metrics."""
    # RPC
    rpc_success_rate: float
    rpc_avg_latency_ms: int
    rpc_total_requests: int
    
    # Quotes
    quote_fetch_rate: float
    quote_gate_pass_rate: float
    
    # Coverage
    chains_active: int
    dexes_active: int
    pairs_covered: int
    pools_scanned: int
    
    # Rejects
    top_reject_reasons: list[tuple[str, int]]


# =============================================================================
# SCHEMA VERSION (Team Lead Крок 8)
# =============================================================================

TRUTH_REPORT_SCHEMA_VERSION = "3.0.0"
"""
Schema version history:
- 1.0.0: Initial schema
- 2.0.0: Added spread_ids vs signals terminology
- 3.0.0: Added executable_economic, execution_ready separation
         Added blocked_reason to OpportunityRank
         Added notion_capital_usdc for PnL normalization
         Added schema_version field
"""


# =============================================================================
# BLOCKED REASONS (Team Lead Крок 3)
# =============================================================================

class BlockedReason:
    """First-class blocked reasons for execution."""
    EXEC_DISABLED_NOT_VERIFIED = "EXEC_DISABLED_NOT_VERIFIED"
    EXEC_DISABLED_CONFIG = "EXEC_DISABLED_CONFIG"
    EXEC_DISABLED_QUARANTINE = "EXEC_DISABLED_QUARANTINE"
    EXEC_DISABLED_RISK = "EXEC_DISABLED_RISK"
    EXEC_DISABLED_REVALIDATION_FAILED = "EXEC_DISABLED_REVALIDATION_FAILED"
    EXEC_DISABLED_GATES_CHANGED = "EXEC_DISABLED_GATES_CHANGED"
    EXEC_DISABLED_COOLDOWN = "EXEC_DISABLED_COOLDOWN"


@dataclass
class TruthReport:
    """
    Complete truth report.
    
    Schema version: {TRUTH_REPORT_SCHEMA_VERSION}
    
    TERMINOLOGY (Team Lead Крок 1):
    - spread_id: унікальний spread (pair + buy_dex + sell_dex + fee tiers + direction)
    - signal: spread_id × (size bucket або route variant)
    
    METRICS (Team Lead Крок 3):
    - executable_economic: passes all gates, PnL > 0 (paper profitability)
    - execution_ready: executable_economic && verified && !blocked (can execute)
    
    So: signals_total >= spread_ids_total always
    """
    # Required fields (no defaults) - must come first
    timestamp: str
    mode: str
    health: HealthMetrics
    top_opportunities: list[OpportunityRank]
    
    # Optional fields (with defaults) - must come after required
    # Schema version for backward compatibility
    schema_version: str = TRUTH_REPORT_SCHEMA_VERSION
    
    # Stats - RENAMED for clarity (Team Lead Крок 1)
    # spread_ids = unique spreads (pair+dexes+fee+direction)
    # signals = spread_ids × size/route variants
    spread_ids_total: int = 0
    spread_ids_profitable: int = 0
    spread_ids_executable: int = 0
    signals_total: int = 0
    signals_profitable: int = 0
    signals_executable: int = 0
    
    # Legacy aliases for backwards compatibility
    @property
    def total_spreads(self) -> int:
        return self.spread_ids_total
    
    @property
    def profitable_spreads(self) -> int:
        return self.spread_ids_profitable
    
    @property
    def executable_spreads(self) -> int:
        return self.spread_ids_executable
    
    # Blocked breakdown (Team Lead Крок 3)
    blocked_spreads: int = 0
    blocked_reasons: dict | None = None  # {BlockedReason: count}
    top_blocked_reasons: list[tuple[str, int]] | None = None
    
    # Execution readiness
    paper_executable_count: int = 0
    execution_ready_count: int = 0
    
    # Revalidation stats (Team Lead Крок 5)
    revalidation_total: int = 0
    revalidation_passed: int = 0
    revalidation_gates_changed: int = 0
    
    # PnL fields
    total_pnl_bps: int = 0
    total_pnl_usdc: float = 0.0
    signal_pnl_bps: int = 0
    signal_pnl_usdc: float = 0.0
    would_execute_pnl_bps: int = 0
    would_execute_pnl_usdc: float = 0.0
    
    # Team Lead Крок 9: Notion capital for PnL normalization
    # "прив'яжи до фіксованого notion-capital або перестань показувати cumulative у SMOKE"
    notion_capital_usdc: float = 0.0  # 0 = not set (raw cumulative)
    normalized_return_pct: float | None = None  # total_pnl_usdc / notion_capital * 100
    
    def validate_invariants(self) -> list[str]:
        """
        Validate report invariants (Team Lead Крок 2).
        
        Returns list of violations (empty if all OK).
        """
        violations = []
        
        # Invariant 1: profitable <= total
        if self.spread_ids_profitable > self.spread_ids_total:
            violations.append(
                f"spread_ids_profitable ({self.spread_ids_profitable}) > "
                f"spread_ids_total ({self.spread_ids_total})"
            )
        
        # Invariant 2: executable <= total
        if self.spread_ids_executable > self.spread_ids_total:
            violations.append(
                f"spread_ids_executable ({self.spread_ids_executable}) > "
                f"spread_ids_total ({self.spread_ids_total})"
            )
        
        # Invariant 3: signals >= spread_ids
        if self.signals_total < self.spread_ids_total:
            violations.append(
                f"signals_total ({self.signals_total}) < "
                f"spread_ids_total ({self.spread_ids_total})"
            )
        
        # Invariant 4: execution_ready <= paper_executable
        if self.execution_ready_count > self.paper_executable_count:
            violations.append(
                f"execution_ready_count ({self.execution_ready_count}) > "
                f"paper_executable_count ({self.paper_executable_count})"
            )
        
        return violations
    
    def to_dict(self) -> dict:
        # Validate before serializing
        violations = self.validate_invariants()
        
        # Convert opportunities - handle properties that asdict can't serialize
        opportunities_list = []
        for o in self.top_opportunities:
            opp_dict = {
                "rank": o.rank,
                "spread_id": o.spread_id,
                "buy_dex": o.buy_dex,
                "sell_dex": o.sell_dex,
                "pair": o.pair,
                "fee": o.fee,
                "amount_in": o.amount_in,
                "spread_bps": o.spread_bps,
                "gas_cost_bps": o.gas_cost_bps,
                "net_pnl_bps": o.net_pnl_bps,
                "expected_pnl_usdc": o.expected_pnl_usdc,
                "confidence": o.confidence,
                "confidence_breakdown": o.confidence_breakdown,
                # Team Lead Крок 3: Clear separation of metrics
                "executable_economic": o.executable_economic,
                "paper_would_execute": o.paper_would_execute,
                "execution_ready": o.execution_ready,
                "blocked_reason": o.blocked_reason,
                # Legacy aliases
                "executable": o.executable,  # = executable_economic
                "paper_executable": o.paper_executable,  # = paper_would_execute
            }
            opportunities_list.append(opp_dict)
        
        result = {
            # Team Lead Крок 8: Schema version for backward compatibility
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "mode": self.mode,
            "health": asdict(self.health),
            "top_opportunities": opportunities_list,
            # Team Lead Крок 1: Clear terminology
            "stats": {
                # Spread IDs (unique)
                "spread_ids_total": self.spread_ids_total,
                "spread_ids_profitable": self.spread_ids_profitable,
                "spread_ids_executable": self.spread_ids_executable,
                # Signals (spread × size variants)
                "signals_total": self.signals_total,
                "signals_profitable": self.signals_profitable,
                "signals_executable": self.signals_executable,
                # Execution
                "paper_executable_count": self.paper_executable_count,
                "execution_ready_count": self.execution_ready_count,
                # Blocked
                "blocked_spreads": self.blocked_spreads,
            },
            # Revalidation stats (Team Lead Крок 5)
            "revalidation": {
                "total": self.revalidation_total,
                "passed": self.revalidation_passed,
                "gates_changed": self.revalidation_gates_changed,
                "gates_changed_pct": round(
                    self.revalidation_gates_changed / max(1, self.revalidation_total) * 100, 1
                ),
            },
            # PnL
            "cumulative_pnl": {
                "total_bps": self.total_pnl_bps,
                "total_usdc": self.total_pnl_usdc,
                # Team Lead Крок 9: notion capital warning
                "warning": "Raw cumulative - not normalized to capital" if self.notion_capital_usdc == 0 else None,
            },
            "pnl": {
                "signal_pnl_bps": self.signal_pnl_bps,
                "signal_pnl_usdc": self.signal_pnl_usdc,
                "would_execute_pnl_bps": self.would_execute_pnl_bps,
                "would_execute_pnl_usdc": self.would_execute_pnl_usdc,
                # Team Lead Крок 9: normalized return if capital set
                "notion_capital_usdc": self.notion_capital_usdc,
                "normalized_return_pct": self.normalized_return_pct,
            },
        }
        
        # Clean up None values from PnL warning
        if result["cumulative_pnl"].get("warning") is None:
            del result["cumulative_pnl"]["warning"]
        
        # Add blocked reasons breakdown (Team Lead Крок 3)
        if self.blocked_reasons:
            result["blocked_reasons_breakdown"] = self.blocked_reasons
        if self.top_blocked_reasons:
            result["top_blocked_reasons"] = self.top_blocked_reasons
        
        # Add invariant violations if any
        if violations:
            result["invariant_violations"] = violations
        
        return result


def calculate_plausibility(
    spread: dict,
    spread_bps: int,
    gas_bps: int,
    buy_leg: dict,
    sell_leg: dict,
) -> float:
    """
    Calculate plausibility score as function of proximity to thresholds.
    
    Team Lead Крок 7:
    "Confidence scoring: прибрати константи типу plausibility=0.8 як дефолт;
    plausibility має бути функцією (напр. штраф за близькість до порогів sanity/ticks/gas)."
    
    Score is reduced by:
    - Proximity to spread threshold (very high spreads are suspicious)
    - Proximity to gas threshold (high gas = risky)
    - Proximity to ticks threshold (many ticks = risky)
    - Price deviation from anchor (if available)
    
    Returns:
        Plausibility score 0.0 - 1.0
    """
    score = 1.0
    
    # 1. Spread threshold proximity
    # Very high spreads are suspicious - likely bad data
    MAX_PLAUSIBLE_BPS = 500
    NORMAL_SPREAD_BPS = 50
    
    if spread_bps <= 0:
        return 0.0
    elif spread_bps <= NORMAL_SPREAD_BPS:
        spread_penalty = 0.0  # Normal range
    else:
        # Gradual penalty as spread approaches threshold
        proximity = min(1.0, (spread_bps - NORMAL_SPREAD_BPS) / (MAX_PLAUSIBLE_BPS - NORMAL_SPREAD_BPS))
        spread_penalty = proximity * 0.4  # Max 40% penalty for spread
        
        if spread_bps > MAX_PLAUSIBLE_BPS:
            spread_penalty = 0.6  # Above threshold = very suspicious
    
    score -= spread_penalty
    
    # 2. Gas threshold proximity
    # High gas estimates relative to spread are risky
    if spread_bps > 0 and gas_bps > 0:
        gas_ratio = gas_bps / spread_bps
        if gas_ratio > 0.5:  # Gas > 50% of spread
            gas_penalty = min(0.3, (gas_ratio - 0.5) * 0.6)
            score -= gas_penalty
    
    # 3. Ticks threshold proximity
    MAX_TICKS_NORMAL = 10
    MAX_TICKS_SUSPICIOUS = 20
    
    buy_ticks = buy_leg.get("ticks_crossed") or 0
    sell_ticks = sell_leg.get("ticks_crossed") or 0
    max_ticks = max(buy_ticks, sell_ticks)
    
    if max_ticks > MAX_TICKS_NORMAL:
        if max_ticks > MAX_TICKS_SUSPICIOUS:
            ticks_penalty = 0.3
        else:
            proximity = (max_ticks - MAX_TICKS_NORMAL) / (MAX_TICKS_SUSPICIOUS - MAX_TICKS_NORMAL)
            ticks_penalty = proximity * 0.2
        score -= ticks_penalty
    
    # 4. Price deviation proximity (if available in spread details)
    deviation_bps = spread.get("price_deviation_bps", 0) or 0
    MAX_DEVIATION_NORMAL = 1500  # 15%
    MAX_DEVIATION_SUSPICIOUS = 2500  # 25%
    
    if deviation_bps > MAX_DEVIATION_NORMAL:
        if deviation_bps > MAX_DEVIATION_SUSPICIOUS:
            deviation_penalty = 0.3
        else:
            proximity = (deviation_bps - MAX_DEVIATION_NORMAL) / (MAX_DEVIATION_SUSPICIOUS - MAX_DEVIATION_NORMAL)
            deviation_penalty = proximity * 0.2
        score -= deviation_penalty
    
    # 5. Leg-specific issues
    # Both legs should have similar latencies
    buy_latency = buy_leg.get("latency_ms", 0) or 0
    sell_latency = sell_leg.get("latency_ms", 0) or 0
    
    if buy_latency > 0 and sell_latency > 0:
        latency_ratio = max(buy_latency, sell_latency) / min(buy_latency, sell_latency)
        if latency_ratio > 3:  # One leg took 3x longer
            score -= 0.1
    
    return max(0.0, min(1.0, score))


def calculate_confidence(
    spread: dict,
    rpc_success_rate: float = 1.0,
    block_age_ms: int = 0,
    price_sanity_history: dict | None = None,
    gas_history: dict | None = None,
) -> tuple[float, dict]:
    """
    Calculate confidence score for a spread (0.0 - 1.0).
    
    Returns:
        Tuple of (confidence_score, breakdown_dict)
    
    Components:
    - freshness: quote latency + block age
    - ticks: penalty for high ticks_crossed
    - verification: both DEXes verified for execution
    - profitability: net_pnl_bps quality
    - gas_efficiency: gas_cost_bps / spread_bps ratio
    - rpc_health: provider reliability
    - plausibility: economic sanity check
    - price_sanity_penalty: penalty for borderline PRICE_SANITY (Team Lead Крок 7)
    - gas_penalty: penalty for QUOTE_GAS_TOO_HIGH history (Team Lead Крок 7)
    """
    breakdown = {}
    
    # Get spread data
    spread_bps = spread.get("spread_bps", 0)
    gas_bps = spread.get("gas_cost_bps", 0)
    net_bps = spread.get("net_pnl_bps", 0)
    buy_leg = spread.get("buy_leg", {})
    sell_leg = spread.get("sell_leg", {})
    
    # Team Lead Крок 5: Ensure gas_cost_bps is non-zero when we have gas data
    # If gas_bps is 0 but we have gas estimates, calculate rough gas cost
    if gas_bps == 0:
        buy_gas = buy_leg.get("gas_estimate", 0) or 0
        sell_gas = sell_leg.get("gas_estimate", 0) or 0
        total_gas = buy_gas + sell_gas
        
        if total_gas > 0:
            # Estimate gas cost: ~0.01-0.02 gwei on L2, ~$0.01-0.05 per trade
            # Rough: 200k gas * 0.02 gwei * $3000/ETH = $0.012
            # As BPS of $100 trade: ~1-2 bps
            amount_in = int(spread.get("amount_in", 0) or 0)
            if amount_in > 0:
                # Estimate: 1 bps per 100k gas for 0.1 ETH trades
                # Scale inversely with amount
                base_gas_bps = max(1, total_gas // 100_000)
                size_factor = 10**17 / max(amount_in, 10**16)  # 0.1 ETH reference
                gas_bps = max(1, int(base_gas_bps * size_factor))
                
                # Update spread for reporting
                spread["gas_cost_bps_estimated"] = gas_bps
    
    # 1. FRESHNESS SCORE (0.0 - 1.0)
    # Lower latency = better
    buy_latency = buy_leg.get("latency_ms", 0) or 0
    sell_latency = sell_leg.get("latency_ms", 0) or 0
    avg_latency = (buy_latency + sell_latency) / 2 if buy_latency and sell_latency else max(buy_latency, sell_latency)
    
    # Latency scoring: <100ms = 1.0, >500ms = 0.5, >1000ms = 0.2
    if avg_latency <= 100:
        latency_score = 1.0
    elif avg_latency <= 500:
        latency_score = 1.0 - (avg_latency - 100) / 800  # Linear decay
    else:
        latency_score = max(0.2, 0.5 - (avg_latency - 500) / 1000)
    
    # Block age scoring: <5s = 1.0, >10s = 0.5
    if block_age_ms <= 5000:
        block_score = 1.0
    elif block_age_ms <= 10000:
        block_score = 1.0 - (block_age_ms - 5000) / 10000
    else:
        block_score = 0.5
    
    freshness_score = (latency_score * 0.6 + block_score * 0.4)
    breakdown["freshness"] = round(freshness_score, 3)
    
    # 2. TICKS SCORE (0.0 - 1.0)
    # Lower ticks = better (less slippage risk)
    buy_ticks = buy_leg.get("ticks_crossed") or 0
    sell_ticks = sell_leg.get("ticks_crossed") or 0
    max_ticks = max(buy_ticks, sell_ticks)
    
    # Ticks scoring: 0-5 = 1.0, 5-10 = 0.8, 10-15 = 0.5, >15 = 0.2
    if max_ticks <= 5:
        ticks_score = 1.0
    elif max_ticks <= 10:
        ticks_score = 1.0 - (max_ticks - 5) * 0.04
    elif max_ticks <= 15:
        ticks_score = 0.8 - (max_ticks - 10) * 0.06
    else:
        ticks_score = max(0.2, 0.5 - (max_ticks - 15) * 0.02)
    
    breakdown["ticks"] = round(ticks_score, 3)
    
    # 3. VERIFICATION SCORE (0.0 - 1.0)
    buy_verified = buy_leg.get("verified_for_execution", False)
    sell_verified = sell_leg.get("verified_for_execution", False)
    
    if buy_verified and sell_verified:
        verification_score = 1.0
    elif buy_verified or sell_verified:
        verification_score = 0.5
    else:
        verification_score = 0.2
    
    breakdown["verification"] = verification_score
    
    # 4. PROFITABILITY SCORE (0.0 - 1.0)
    # Higher net_pnl_bps = better
    if net_bps <= 0:
        profit_score = 0.0
    elif net_bps < 5:
        profit_score = 0.3  # Marginal
    elif net_bps < 20:
        profit_score = 0.6  # Decent
    elif net_bps < 50:
        profit_score = 0.8  # Good
    else:
        profit_score = 1.0  # Excellent
    
    breakdown["profitability"] = profit_score
    
    # 5. GAS EFFICIENCY SCORE (0.0 - 1.0)
    # Lower gas_ratio = better
    if spread_bps > 0:
        gas_ratio = gas_bps / spread_bps
        if gas_ratio < 0.1:
            gas_score = 1.0
        elif gas_ratio < 0.3:
            gas_score = 0.8
        elif gas_ratio < 0.5:
            gas_score = 0.5
        else:
            gas_score = 0.2
    else:
        gas_score = 0.0
    
    breakdown["gas_efficiency"] = gas_score
    
    # 6. RPC HEALTH SCORE (0.0 - 1.0)
    # Direct from provider stats
    rpc_score = min(1.0, max(0.0, rpc_success_rate))
    breakdown["rpc_health"] = round(rpc_score, 3)
    
    # 7. PLAUSIBILITY SCORE - Team Lead Крок 7
    # NOT a constant - calculated as function of proximity to thresholds
    # Штраф за близькість до порогів sanity/ticks/gas
    plausibility_score = calculate_plausibility(
        spread=spread,
        spread_bps=spread_bps,
        gas_bps=gas_bps,
        buy_leg=buy_leg,
        sell_leg=sell_leg,
    )
    
    breakdown["plausibility"] = round(plausibility_score, 3)
    
    # 8. PRICE SANITY PENALTY (Team Lead Крок 7)
    # Penalty for spreads from combinations with PRICE_SANITY history
    price_sanity_penalty = 0.0
    if price_sanity_history:
        pair = spread.get("pair", "")
        buy_dex = buy_leg.get("dex", spread.get("buy_dex", ""))
        sell_dex = sell_leg.get("dex", spread.get("sell_dex", ""))
        fee = spread.get("fee", 0)
        
        # Check if this combination has price sanity issues
        for combo_key in [f"{pair}_{buy_dex}_{fee}", f"{pair}_{sell_dex}_{fee}"]:
            failure_rate = price_sanity_history.get(combo_key, 0)
            if failure_rate > 0.3:  # >30% failure rate
                price_sanity_penalty = max(price_sanity_penalty, failure_rate * 0.3)
    
    breakdown["price_sanity_penalty"] = round(price_sanity_penalty, 3)
    
    # 9. GAS HISTORY PENALTY (Team Lead Крок 7)
    # Penalty for spreads from combinations with QUOTE_GAS_TOO_HIGH history
    gas_penalty = 0.0
    if gas_history:
        pair = spread.get("pair", "")
        buy_dex = buy_leg.get("dex", spread.get("buy_dex", ""))
        sell_dex = sell_leg.get("dex", spread.get("sell_dex", ""))
        fee = spread.get("fee", 0)
        
        # Check if this combination has gas issues
        for combo_key in [f"{pair}_{buy_dex}_{fee}", f"{pair}_{sell_dex}_{fee}"]:
            failure_rate = gas_history.get(combo_key, 0)
            if failure_rate > 0.3:  # >30% failure rate
                gas_penalty = max(gas_penalty, failure_rate * 0.2)
    
    breakdown["gas_penalty"] = round(gas_penalty, 3)
    
    # WEIGHTED AVERAGE
    weights = {
        "freshness": 0.12,
        "ticks": 0.12,
        "verification": 0.18,
        "profitability": 0.15,
        "gas_efficiency": 0.10,
        "rpc_health": 0.08,
        "plausibility": 0.15,
    }
    
    base_score = sum(breakdown[k] * weights[k] for k in weights)
    
    # Apply penalties (subtract from base score)
    total_penalty = price_sanity_penalty + gas_penalty
    total_score = max(0.0, base_score - total_penalty)
    
    # Hard caps: Team Lead Крок 5 - use paper_executable
    paper_executable = spread.get("paper_executable", spread.get("executable", False))
    if not paper_executable:
        total_score = min(total_score, 0.5)
    if net_bps <= 0:
        total_score = min(total_score, 0.3)
    
    breakdown["final"] = round(total_score, 3)
    
    return round(total_score, 3), breakdown


def calculate_confidence_simple(spread: dict) -> float:
    """Simple wrapper for backwards compatibility."""
    score, _ = calculate_confidence(spread)
    return score


def generate_truth_report(
    snapshot: dict,
    paper_session_stats: dict | None = None,
    top_n: int = 10,
) -> TruthReport:
    """
    Generate truth report from scan snapshot.
    
    Args:
        snapshot: Scan snapshot dict
        paper_session_stats: Optional cumulative paper trading stats
        top_n: Number of top opportunities to include
    """
    cycle_summaries = snapshot.get("cycle_summaries", [])
    mode = snapshot.get("mode", "UNKNOWN")
    
    # Aggregate metrics across cycles
    total_attempted = 0
    total_fetched = 0
    total_passed = 0
    total_pools = 0
    all_spreads = []
    all_reject_reasons: dict[str, int] = {}
    rpc_total_requests = 0
    rpc_successful_requests = 0
    rpc_latency_weighted = 0
    rpc_endpoint_count = 0
    chains_seen = set()
    dexes_seen = set()
    pairs_seen = set()
    
    for cycle in cycle_summaries:
        total_attempted += cycle.get("quotes_attempted", 0)
        total_fetched += cycle.get("quotes_fetched", 0)
        total_passed += cycle.get("quotes_passed_gates", 0)
        total_pools += cycle.get("pools_scanned", 0)
        
        chains_seen.add(cycle.get("chain"))
        
        for dex in cycle.get("dexes_passed_gate", []):
            dexes_seen.add(dex.get("dex_key"))
        
        # Get pairs from cycle summary (not from quotes which may be empty)
        for pair in cycle.get("pairs_scanned", []):
            if pair:
                pairs_seen.add(pair)
        
        # Spreads
        all_spreads.extend(cycle.get("spreads", []))
        
        # Reject reasons (support both old and new field names)
        reject_reasons = cycle.get("reject_reasons_histogram") or cycle.get("quote_reject_reasons", {})
        for reason, count in reject_reasons.items():
            all_reject_reasons[reason] = all_reject_reasons.get(reason, 0) + count
        
        # RPC stats - weighted by total_requests
        for url, stats in cycle.get("rpc_stats", {}).items():
            requests = stats.get("total_requests", 0)
            if requests > 0:
                success_rate = stats.get("success_rate", 0)
                latency = stats.get("avg_latency_ms", 0)
                
                rpc_total_requests += requests
                rpc_successful_requests += int(requests * success_rate)
                rpc_latency_weighted += latency * requests
                rpc_endpoint_count += 1
    
    # Calculate health metrics
    fetch_rate = total_fetched / total_attempted if total_attempted > 0 else 0.0
    gate_pass_rate = total_passed / total_fetched if total_fetched > 0 else 0.0
    
    # Weighted RPC stats
    rpc_success_rate = rpc_successful_requests / rpc_total_requests if rpc_total_requests > 0 else 0.0
    rpc_avg_latency = int(rpc_latency_weighted / rpc_total_requests) if rpc_total_requests > 0 else 0
    
    # Top reject reasons
    sorted_rejects = sorted(all_reject_reasons.items(), key=lambda x: x[1], reverse=True)
    top_rejects = sorted_rejects[:5]
    
    health = HealthMetrics(
        rpc_success_rate=round(rpc_success_rate, 3),
        rpc_avg_latency_ms=rpc_avg_latency,
        rpc_total_requests=rpc_total_requests,
        quote_fetch_rate=round(fetch_rate, 3),
        quote_gate_pass_rate=round(gate_pass_rate, 3),
        chains_active=len(chains_seen),
        dexes_active=len(dexes_seen),
        pairs_covered=len(pairs_seen),
        pools_scanned=total_pools,
        top_reject_reasons=top_rejects,
    )
    
    # Calculate spread stats - Team Lead Крок 1-2: Clear terminology
    # all_spreads = all signals (spread × size variants)
    # unique_spreads = unique spread_ids
    
    # First, deduplicate spreads by spread_id (keep latest/last occurrence per id)
    spreads_by_id: dict[str, dict] = {}
    for spread in all_spreads:
        spread_id = spread.get("id", "")
        if spread_id:
            spreads_by_id[spread_id] = spread  # Last wins (most recent)
    unique_spreads = list(spreads_by_id.values())
    
    # SIGNALS = all spreads (including duplicates/size variants)
    signals_total = len(all_spreads)
    signals_profitable = len([s for s in all_spreads if s.get("net_pnl_bps", 0) > 0])
    signals_executable = len([s for s in all_spreads if s.get("executable")])
    
    # SPREAD_IDS = unique spreads only
    spread_ids_total = len(unique_spreads)
    spread_ids_profitable = len([s for s in unique_spreads if s.get("net_pnl_bps", 0) > 0])
    spread_ids_executable = len([s for s in unique_spreads if s.get("executable")])
    
    # Blocked spreads (profitable but not executable)
    profitable_spreads = [s for s in unique_spreads if s.get("net_pnl_bps", 0) > 0]
    executable_spreads = [s for s in profitable_spreads if s.get("executable")]
    blocked_spreads = [s for s in profitable_spreads if not s.get("executable")]
    
    # Blocked reasons breakdown (Team Lead Крок 3)
    blocked_reasons_count: dict[str, int] = {}
    for spread in blocked_spreads:
        # Determine blocked reason
        reason = spread.get("blocked_reason", BlockedReason.EXEC_DISABLED_NOT_VERIFIED)
        blocked_reasons_count[reason] = blocked_reasons_count.get(reason, 0) + 1
    
    # Sort blocked reasons by count
    top_blocked = sorted(blocked_reasons_count.items(), key=lambda x: x[1], reverse=True)
    
    # Get block age from last cycle
    block_age_ms = 0
    if cycle_summaries:
        last_cycle = cycle_summaries[-1]
        block_pin = last_cycle.get("block_pin", {})
        block_age_ms = block_pin.get("age_ms", 0) or 0
    
    # Rank opportunities by confidence × net_pnl
    ranked = []
    for spread in unique_spreads:
        confidence, breakdown = calculate_confidence(
            spread,
            rpc_success_rate=rpc_success_rate,
            block_age_ms=block_age_ms,
        )
        net_bps = spread.get("net_pnl_bps", 0)
        
        ranked.append({
            "spread": spread,
            "confidence": confidence,
            "confidence_breakdown": breakdown,
            "score": confidence * net_bps,  # Combined score
        })
    
    # Sort by score descending
    ranked.sort(key=lambda x: x["score"], reverse=True)
    
    # Filter out noise: minimum net_pnl_bps threshold
    MIN_NET_PNL_BPS = 5  # Ignore opportunities with < 5 bps
    ranked = [r for r in ranked if r["spread"].get("net_pnl_bps", 0) >= MIN_NET_PNL_BPS]
    
    # Filter for top opportunities: executable-only
    # Non-executable spreads are blocked and cannot be acted upon
    ranked_executable = [r for r in ranked if r["spread"].get("executable", False)]
    
    # Build top opportunities (executable-only)
    top_opportunities = []
    for i, item in enumerate(ranked_executable[:top_n]):
        spread = item["spread"]
        buy_leg = spread.get("buy_leg", {})
        sell_leg = spread.get("sell_leg", {})
        
        # Calculate expected USDC using implied_price from spread
        amount_in = int(spread.get("amount_in", "0"))
        net_bps = spread.get("net_pnl_bps", 0)
        
        # Get implied_price from buy leg (price in quote per base)
        buy_price_str = buy_leg.get("price", "0")
        try:
            implied_price = float(buy_price_str) if buy_price_str else 0.0
        except (ValueError, TypeError):
            implied_price = 0.0
        
        # Calculate notional value and expected PnL
        amount_base = amount_in / 10**18  # Assuming 18 decimals for base token
        notional_usdc = amount_base * implied_price
        expected_usdc = notional_usdc * (net_bps / 10000) if net_bps > 0 else 0.0
        
        # Get pair from spread (or derive from legs)
        pair = spread.get("pair", "")
        if not pair:
            token_in = spread.get("token_in_symbol", buy_leg.get("token_in_symbol", ""))
            token_out = spread.get("token_out_symbol", buy_leg.get("token_out_symbol", ""))
            pair = f"{token_in}/{token_out}" if token_in and token_out else "UNKNOWN"
        
        # Team Lead Крок 3: Determine execution status
        is_executable = spread.get("executable", False)
        is_verified = spread.get("verified_for_execution", False)
        blocked_reason = spread.get("blocked_reason")
        
        # executable_economic = passes all gates AND net_pnl > 0
        executable_economic = is_executable and net_bps > 0
        
        # paper_would_execute = what paper trading would do
        paper_would_execute = executable_economic  # In paper mode, ignore verification
        
        # execution_ready = executable_economic AND verified AND not blocked
        execution_ready = executable_economic and is_verified and not blocked_reason
        
        # If not execution_ready but executable_economic, explain why
        if executable_economic and not execution_ready:
            if not is_verified:
                blocked_reason = BlockedReason.EXEC_DISABLED_NOT_VERIFIED
            elif blocked_reason is None:
                blocked_reason = BlockedReason.EXEC_DISABLED_CONFIG
        
        top_opportunities.append(OpportunityRank(
            rank=i + 1,
            spread_id=spread.get("id", ""),
            buy_dex=buy_leg.get("dex", spread.get("buy_dex", "")),
            sell_dex=sell_leg.get("dex", spread.get("sell_dex", "")),
            pair=pair,
            fee=spread.get("fee", 0),
            amount_in=spread.get("amount_in", "0"),
            spread_bps=spread.get("spread_bps", 0),
            gas_cost_bps=spread.get("gas_cost_bps", 0),
            net_pnl_bps=net_bps,
            expected_pnl_usdc=round(expected_usdc, 4),
            # Team Lead Крок 3: Clear separation
            executable_economic=executable_economic,
            paper_would_execute=paper_would_execute,
            execution_ready=execution_ready,
            blocked_reason=blocked_reason,
            confidence=round(item["confidence"], 3),
            confidence_breakdown=item.get("confidence_breakdown"),
        ))
    
    # Cumulative PnL from paper session
    total_pnl_bps = 0
    total_pnl_usdc = 0.0
    
    # Revalidation stats from paper session
    revalidation_total = 0
    revalidation_passed = 0
    revalidation_gates_changed = 0
    
    if paper_session_stats:
        total_pnl_bps = paper_session_stats.get("total_pnl_bps", 0)
        total_pnl_usdc = paper_session_stats.get("total_pnl_usdc", 0.0)
        revalidation_total = paper_session_stats.get("revalidation_total", 0)
        revalidation_passed = paper_session_stats.get("revalidation_passed", 0)
        revalidation_gates_changed = paper_session_stats.get("revalidation_gates_changed", 0)
    
    return TruthReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        mode=mode,
        health=health,
        top_opportunities=top_opportunities,
        # Team Lead Крок 1: Clear terminology
        spread_ids_total=spread_ids_total,
        spread_ids_profitable=spread_ids_profitable,
        spread_ids_executable=spread_ids_executable,
        signals_total=signals_total,
        signals_profitable=signals_profitable,
        signals_executable=signals_executable,
        # Blocked
        blocked_spreads=len(blocked_spreads),
        blocked_reasons=blocked_reasons_count if blocked_reasons_count else None,
        top_blocked_reasons=top_blocked if top_blocked else None,
        # Execution
        paper_executable_count=spread_ids_executable,
        execution_ready_count=0,  # TODO: implement real execution readiness check
        # Revalidation
        revalidation_total=revalidation_total,
        revalidation_passed=revalidation_passed,
        revalidation_gates_changed=revalidation_gates_changed,
        # PnL
        total_pnl_bps=total_pnl_bps,
        total_pnl_usdc=total_pnl_usdc,
    )


def save_truth_report(report: TruthReport, output_dir: Path) -> Path:
    """Save truth report to file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = output_dir / f"truth_report_{timestamp}.json"
    
    with open(filepath, "w") as f:
        json.dump(report.to_dict(), f, indent=2)
    
    logger.info(f"Truth report saved: {filepath}")
    return filepath


def print_truth_report(report: TruthReport) -> None:
    """Print truth report to console."""
    print("\n" + "=" * 60)
    print("TRUTH REPORT")
    print("=" * 60)
    print(f"Timestamp: {report.timestamp}")
    print(f"Mode: {report.mode}")
    
    print("\n--- HEALTH ---")
    h = report.health
    print(f"RPC: {h.rpc_success_rate:.1%} success ({h.rpc_total_requests} requests), {h.rpc_avg_latency_ms}ms avg")
    print(f"Quotes: {h.quote_fetch_rate:.1%} fetch, {h.quote_gate_pass_rate:.1%} pass gates")
    print(f"Coverage: {h.chains_active} chains, {h.dexes_active} DEXes, {h.pairs_covered} pairs")
    print(f"Pools scanned: {h.pools_scanned}")
    
    if h.top_reject_reasons:
        print("\nTop reject reasons:")
        for reason, count in h.top_reject_reasons:
            print(f"  {reason}: {count}")
    
    print("\n--- STATS ---")
    print(f"Total spreads: {report.total_spreads}")
    print(f"Profitable: {report.profitable_spreads}")
    print(f"Executable: {report.executable_spreads}")
    print(f"Blocked: {report.blocked_spreads}")
    
    print("\n--- CUMULATIVE PNL ---")
    print(f"Total: {report.total_pnl_bps} bps (${report.total_pnl_usdc:.2f})")
    
    if report.top_opportunities:
        print("\n--- TOP OPPORTUNITIES ---")
        for opp in report.top_opportunities:
            exec_mark = "✓" if opp.executable else "✗"
            print(
                f"  #{opp.rank} [{exec_mark}] {opp.pair} {opp.buy_dex}→{opp.sell_dex}: "
                f"{opp.net_pnl_bps} bps (${opp.expected_pnl_usdc:.2f}) "
                f"conf={opp.confidence:.0%}"
            )
            # Show confidence breakdown if available
            if opp.confidence_breakdown:
                b = opp.confidence_breakdown
                print(
                    f"       └─ fresh={b.get('freshness', 0):.0%} "
                    f"ticks={b.get('ticks', 0):.0%} "
                    f"verify={b.get('verification', 0):.0%} "
                    f"profit={b.get('profitability', 0):.0%} "
                    f"plaus={b.get('plausibility', 0):.0%}"
                )
    
    print("=" * 60 + "\n")
