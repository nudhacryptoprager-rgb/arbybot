# PATH: engine/opportunity_engine.py
"""
Opportunity Engine: Quotes -> Net PnL -> Ranked Opportunities

M4.2 CONTRACT:
- Takes raw quotes from scanner
- Calculates gas costs (from QuoterV2 or estimate)
- Calculates net PnL: spread - gas - fees
- Ranks opportunities by profit
- Applies quality gates (min profit, max gas, etc.)

v2.1.0: Unified with m4.policy.Thresholds for consistent gate definitions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from m4.policy import Thresholds  # v2.1.0: Policy-unified thresholds

logger = logging.getLogger("engine.opportunity_engine")


# =============================================================================
# GAS COST MODEL
# =============================================================================

@dataclass
class GasConfig:
    """Gas cost parameters for opportunity evaluation."""
    # Base gas for swap execution
    base_gas_units: int = 150_000  # Conservative base for V3 swap
    
    # Gas price in gwei (Arbitrum typical)
    gas_price_gwei: float = 0.1  # Arbitrum L2 gas is cheap
    
    # L1 data cost (Arbitrum batching overhead)
    l1_data_gas_units: int = 2_000  # Calldata compression overhead
    l1_gas_price_gwei: float = 30.0  # L1 gas price estimate
    
    # ETH price for USD conversion
    eth_usd_price: float = 2000.0
    
    # v2.1.0: Live gas tracking
    _live_mode: bool = False
    _last_updated: Optional[str] = None
    
    @classmethod
    def from_live(cls, w3, eth_price_usd: Optional[float] = None) -> "GasConfig":
        """
        Create GasConfig from live RPC data.
        
        v2.1.0: Fetches live gas price from the network.
        
        Args:
            w3: Web3 instance connected to the chain
            eth_price_usd: Optional live ETH price (if None, uses fallback 2000)
            
        Returns:
            GasConfig with live values
        """
        import datetime
        
        try:
            # Fetch live L2 gas price
            gas_price_wei = w3.eth.gas_price
            gas_price_gwei = gas_price_wei / 1e9
            
            # For Arbitrum, also try to estimate L1 calldata cost
            # This is harder, so we keep L1 estimate static for now
            l1_gas_price_gwei = 30.0  # TODO: Could query L1 gas oracle
            
            config = cls(
                gas_price_gwei=gas_price_gwei,
                l1_gas_price_gwei=l1_gas_price_gwei,
                eth_usd_price=eth_price_usd or 2000.0,
                _live_mode=True,
                _last_updated=datetime.datetime.utcnow().isoformat(),
            )
            return config
        except Exception:
            # Fallback to defaults on RPC failure
            return cls()
    
    def estimate_gas_cost_wei(self, gas_estimate: Optional[int] = None) -> int:
        """Estimate total gas cost in wei."""
        # Use quoter estimate if available, otherwise base estimate
        gas_units = gas_estimate or self.base_gas_units
        
        # L2 cost
        l2_cost_wei = int(gas_units * self.gas_price_gwei * 1e9)
        
        # L1 data cost
        l1_cost_wei = int(self.l1_data_gas_units * self.l1_gas_price_gwei * 1e9)
        
        return l2_cost_wei + l1_cost_wei
    
    def gas_cost_usd(self, gas_estimate: Optional[int] = None) -> float:
        """Calculate gas cost in USD."""
        gas_wei = self.estimate_gas_cost_wei(gas_estimate)
        gas_eth = gas_wei / 1e18
        return gas_eth * self.eth_usd_price


# =============================================================================
# OPPORTUNITY DATA MODEL
# =============================================================================

@dataclass
class Opportunity:
    """
    A scored arbitrage opportunity.
    
    CONTRACT:
    - spread_id: unique identifier (from core.models.generate_spread_id)
    - net_profit_usd: profit after gas and fees
    - gross_spread_bps: raw price difference in basis points
    - gate_passed: True if meets execution thresholds
    """
    spread_id: str
    pair: str  # e.g., "WETH/USDC"
    
    # DEX legs
    buy_dex: str
    sell_dex: str
    buy_fee: int
    sell_fee: int
    
    # Quotes (with amounts)
    buy_price: Decimal
    sell_price: Decimal
    amount_in_wei: int
    usd_notional: Optional[float] = None
    
    # Spread analysis
    gross_spread_bps: Decimal = Decimal("0")  # (sell - buy) / buy * 10000
    net_spread_bps: Decimal = Decimal("0")    # after fees
    
    # PnL breakdown
    gross_profit_usd: float = 0.0
    gas_cost_usd: float = 0.0
    fee_cost_usd: float = 0.0
    net_profit_usd: float = 0.0
    
    # Quality flags
    gate_passed: bool = False
    reject_reason: Optional[str] = None
    
    # Diagnostics
    buy_quote_source: str = "slot0"
    sell_quote_source: str = "slot0"
    buy_gas_estimate: Optional[int] = None
    sell_gas_estimate: Optional[int] = None
    
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_profitable(self) -> bool:
        """Check if opportunity has positive net profit."""
        return self.net_profit_usd > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "spread_id": self.spread_id,
            "pair": self.pair,
            "buy_dex": self.buy_dex,
            "sell_dex": self.sell_dex,
            "buy_fee": self.buy_fee,
            "sell_fee": self.sell_fee,
            "buy_price": str(self.buy_price),
            "sell_price": str(self.sell_price),
            "amount_in_wei": self.amount_in_wei,
            "usd_notional": self.usd_notional,
            "gross_spread_bps": str(self.gross_spread_bps),
            "net_spread_bps": str(self.net_spread_bps),
            "gross_profit_usd": round(self.gross_profit_usd, 4),
            "gas_cost_usd": round(self.gas_cost_usd, 4),
            "fee_cost_usd": round(self.fee_cost_usd, 4),
            "net_profit_usd": round(self.net_profit_usd, 4),
            "gate_passed": self.gate_passed,
            "reject_reason": self.reject_reason,
            "buy_quote_source": self.buy_quote_source,
            "sell_quote_source": self.sell_quote_source,
            "diagnostics": self.diagnostics,
        }


# =============================================================================
# OPPORTUNITY BUILDER
# =============================================================================

class OpportunityEngine:
    """
    Engine to build and score opportunities from quotes.
    
    Workflow:
    1. Group quotes by pair
    2. Find cross-DEX spreads
    3. Calculate net PnL
    4. Rank by profit
    5. Apply gates
    """
    
    def __init__(
        self,
        gas_config: Optional[GasConfig] = None,
        min_net_profit_usd: float = 0.50,  # Minimum net profit threshold
        max_gas_cost_usd: float = 5.00,     # Maximum acceptable gas
        min_gross_spread_bps: float = 5.0,  # Minimum raw spread
        max_gross_spread_bps: Optional[float] = None,  # v2.1.0: PRICE_OUTLIER cap (from Thresholds)
        max_notional_drift_pct: float = 50.0,  # v2.7.1: Aligned with spreads.py default
        target_notional_usd: float = 1000.0,   # v2.1.0: Target notional for drift calc
        suspect_spread_bps: Optional[float] = None,  # v2.1.0: SUSPECT_SPREAD threshold (from Thresholds)
    ):
        self.gas_config = gas_config or GasConfig()
        self.min_net_profit_usd = min_net_profit_usd
        self.max_gas_cost_usd = max_gas_cost_usd
        self.min_gross_spread_bps = min_gross_spread_bps
        # v2.1.0: Use policy thresholds as defaults
        self.max_gross_spread_bps = max_gross_spread_bps if max_gross_spread_bps is not None else float(Thresholds.SUSPECT_SPREAD_BPS_HARD)
        self.suspect_spread_bps = suspect_spread_bps if suspect_spread_bps is not None else float(Thresholds.SUSPECT_SPREAD_BPS)
        self.max_notional_drift_pct = max_notional_drift_pct
        self.target_notional_usd = target_notional_usd
    
    def build_opportunities(
        self,
        quotes: List[Dict[str, Any]],
        cycle: int = 0,
        timestamp: str = "",
    ) -> List[Opportunity]:
        """
        Build opportunities from a list of quotes.
        
        Args:
            quotes: Quote dicts from scanner (strategy.quotes)
            cycle: Current scan cycle
            timestamp: Run timestamp for spread_id
            
        Returns:
            List of scored opportunities, sorted by net_profit_usd descending
        """
        # Group quotes by pair
        by_pair: Dict[str, List[Dict]] = {}
        for q in quotes:
            pair = f"{q.get('token_in', '')}/{q.get('token_out', '')}"
            if pair not in by_pair:
                by_pair[pair] = []
            by_pair[pair].append(q)
        
        opportunities = []
        opp_index = 0
        
        for pair, pair_quotes in by_pair.items():
            # Find all cross-DEX combinations
            cross_dex_opps = self._find_cross_dex_opportunities(
                pair, pair_quotes, cycle, timestamp, opp_index
            )
            opportunities.extend(cross_dex_opps)
            opp_index += len(cross_dex_opps)
        
        # Sort by net profit (descending)
        opportunities.sort(key=lambda o: o.net_profit_usd, reverse=True)
        
        logger.info(
            "Built %d opportunities from %d quotes: profitable=%d, gated=%d",
            len(opportunities),
            len(quotes),
            sum(1 for o in opportunities if o.is_profitable),
            sum(1 for o in opportunities if o.gate_passed),
        )
        
        return opportunities
    
    def _find_cross_dex_opportunities(
        self,
        pair: str,
        quotes: List[Dict],
        cycle: int,
        timestamp: str,
        start_index: int,
    ) -> List[Opportunity]:
        """Find all cross-DEX arbitrage opportunities for a pair."""
        opportunities = []
        
        # Group by DEX
        by_dex: Dict[str, List[Dict]] = {}
        for q in quotes:
            dex = q.get("dex_id", "unknown")
            if dex not in by_dex:
                by_dex[dex] = []
            by_dex[dex].append(q)
        
        dexes = list(by_dex.keys())
        
        # Compare all DEX pairs
        for i, dex_a in enumerate(dexes):
            for dex_b in dexes[i + 1:]:
                for qa in by_dex[dex_a]:
                    for qb in by_dex[dex_b]:
                        opp = self._build_opportunity(
                            pair, qa, qb, cycle, timestamp,
                            start_index + len(opportunities)
                        )
                        if opp:
                            opportunities.append(opp)
        
        return opportunities
    
    def _build_opportunity(
        self,
        pair: str,
        quote_a: Dict,
        quote_b: Dict,
        cycle: int,
        timestamp: str,
        index: int,
    ) -> Optional[Opportunity]:
        """Build and score a single opportunity from two quotes."""
        try:
            # v2.0.9: Use price_exact (high precision) if available, fallback to price (rounded)
            price_a_str = quote_a.get("price_exact") or quote_a.get("price", "0")
            price_b_str = quote_b.get("price_exact") or quote_b.get("price", "0")
            price_a = Decimal(str(price_a_str))
            price_b = Decimal(str(price_b_str))
            
            if price_a <= 0 or price_b <= 0:
                return None
            
            # Determine buy/sell direction
            if price_a < price_b:
                buy_quote, sell_quote = quote_a, quote_b
                buy_price, sell_price = price_a, price_b
            else:
                buy_quote, sell_quote = quote_b, quote_a
                buy_price, sell_price = price_b, price_a
            
            # Calculate gross spread
            if buy_price > 0:
                gross_spread_bps = (sell_price - buy_price) / buy_price * Decimal("10000")
            else:
                gross_spread_bps = Decimal("0")
            
            # M4.2 FIX: fee_tier 500 = 0.05% = 5 bps, fee_tier 3000 = 0.30% = 30 bps
            # Formula: fee_bps = fee_tier / 100
            buy_fee = buy_quote.get("fee", 3000)
            sell_fee = sell_quote.get("fee", 3000)
            
            # v2.1.0 FIX: Fee model depends on quote source
            # - quoter_v2: amount_out already includes fee, so DON'T subtract fee_bps
            # - slot0: spot price without fee, so subtract fee_bps
            buy_source = buy_quote.get("quote_source", "slot0")
            sell_source = sell_quote.get("quote_source", "slot0")
            
            # Only apply fee if source is slot0 (spot price without fee)
            buy_fee_applicable = buy_fee if buy_source == "slot0" else 0
            sell_fee_applicable = sell_fee if sell_source == "slot0" else 0
            total_fee_bps = Decimal(buy_fee_applicable + sell_fee_applicable) / Decimal("100")
            
            # Net spread after fees (for slot0 sources only)
            net_spread_bps = gross_spread_bps - total_fee_bps
            
            # Get USD notional
            usd_notional = buy_quote.get("usd_notional") or sell_quote.get("usd_notional") or 1000.0
            
            # Calculate gross profit in USD (from NET spread, already deducted fees)
            gross_profit_usd = float(net_spread_bps / Decimal("10000")) * usd_notional
            
            # Calculate gas costs
            buy_gas = buy_quote.get("gas_estimate") or buy_quote.get("quoter_gas_estimate")
            sell_gas = sell_quote.get("gas_estimate") or sell_quote.get("quoter_gas_estimate")
            
            # Total gas: buy swap + sell swap
            total_gas = None
            if buy_gas and sell_gas:
                total_gas = buy_gas + sell_gas
            
            gas_cost_usd = self.gas_config.gas_cost_usd(total_gas)
            
            # Fee cost in USD (bps to fraction: divide by 10000)
            fee_cost_usd = float(total_fee_bps / Decimal("10000")) * usd_notional
            
            # Net profit (gross profit already has fees deducted, subtract gas)
            net_profit_usd = gross_profit_usd - gas_cost_usd
            
            # Generate spread_id
            from core.models import generate_spread_id
            spread_id = generate_spread_id(cycle, timestamp, index)
            
            # Apply gates
            gate_passed = True
            reject_reason = None
            
            # v2.1.0: No mixed-source opportunities - both legs must be quoter_v2
            # slot0 is diagnostic only, cannot be used for gated profit calculation
            is_mixed_source = (buy_source == "quoter_v2") != (sell_source == "quoter_v2")
            is_slot0_only = buy_source == "slot0" and sell_source == "slot0"
            is_quoter_both = buy_source == "quoter_v2" and sell_source == "quoter_v2"
            
            if is_mixed_source:
                gate_passed = False
                reject_reason = f"MIXED_SOURCE: buy={buy_source}, sell={sell_source} (require both quoter_v2)"
            elif is_slot0_only:
                gate_passed = False
                reject_reason = "SLOT0_DIAGNOSTIC: both legs slot0 (quoter_v2 required for M4.2)"
            # v2.1.0: SUSPECT_SPREAD_HARD gate (from Thresholds.SUSPECT_SPREAD_BPS_HARD)
            # Absurd spreads (>500bps for major pairs) indicate bad data/price inversion
            elif float(gross_spread_bps) > self.max_gross_spread_bps:
                gate_passed = False
                reject_reason = f"SUSPECT_SPREAD_HARD: {gross_spread_bps:.1f} > {self.max_gross_spread_bps:.1f} bps"
            elif net_profit_usd < self.min_net_profit_usd:
                gate_passed = False
                reject_reason = f"NET_PROFIT_TOO_LOW: {net_profit_usd:.2f} < {self.min_net_profit_usd:.2f}"
            elif gas_cost_usd > self.max_gas_cost_usd:
                gate_passed = False
                reject_reason = f"GAS_TOO_HIGH: {gas_cost_usd:.2f} > {self.max_gas_cost_usd:.2f}"
            elif float(gross_spread_bps) < self.min_gross_spread_bps:
                gate_passed = False
                reject_reason = f"SPREAD_TOO_LOW: {gross_spread_bps:.1f} < {self.min_gross_spread_bps:.1f} bps"
            else:
                # v2.1.0: NOTIONAL_DRIFT gate - ensure trade size is within expected range
                notional_drift_pct = abs(usd_notional - self.target_notional_usd) / self.target_notional_usd * 100
                if notional_drift_pct > self.max_notional_drift_pct:
                    gate_passed = False
                    reject_reason = f"NOTIONAL_DRIFT: {notional_drift_pct:.1f}% > {self.max_notional_drift_pct:.1f}%"
            
            return Opportunity(
                spread_id=spread_id,
                pair=pair,
                buy_dex=buy_quote.get("dex_id", "unknown"),
                sell_dex=sell_quote.get("dex_id", "unknown"),
                buy_fee=buy_fee,
                sell_fee=sell_fee,
                buy_price=buy_price,
                sell_price=sell_price,
                amount_in_wei=buy_quote.get("amount_in_wei", 0),
                usd_notional=usd_notional,
                gross_spread_bps=gross_spread_bps,
                net_spread_bps=net_spread_bps,
                gross_profit_usd=gross_profit_usd,
                gas_cost_usd=gas_cost_usd,
                fee_cost_usd=fee_cost_usd,
                net_profit_usd=net_profit_usd,
                gate_passed=gate_passed,
                reject_reason=reject_reason,
                buy_quote_source=buy_quote.get("quote_source", "slot0"),
                sell_quote_source=sell_quote.get("quote_source", "slot0"),
                buy_gas_estimate=buy_gas,
                sell_gas_estimate=sell_gas,
                diagnostics={
                    "buy_pool": buy_quote.get("pool_address"),
                    "sell_pool": sell_quote.get("pool_address"),
                    "buy_block": buy_quote.get("block_number"),
                    "sell_block": sell_quote.get("block_number"),
                },
            )
            
        except Exception as e:
            logger.debug("Failed to build opportunity: %s", e)
            return None
    
    def filter_profitable(
        self,
        opportunities: List[Opportunity],
    ) -> List[Opportunity]:
        """Filter to only profitable opportunities."""
        return [o for o in opportunities if o.is_profitable]
    
    def filter_gated(
        self,
        opportunities: List[Opportunity],
    ) -> List[Opportunity]:
        """Filter to only opportunities that pass gates."""
        return [o for o in opportunities if o.gate_passed]


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def evaluate_quotes(
    quotes: List[Dict[str, Any]],
    cycle: int = 0,
    timestamp: str = "",
    eth_usd_price: float = 2000.0,
    min_net_profit_usd: float = 0.50,
    gas_config: Optional[GasConfig] = None,
    target_notional_usd: float = 1000.0,  # v2.7.1: Config-driven
    max_notional_drift_pct: float = 50.0,  # v2.7.1: Aligned with spreads.py default
) -> Tuple[List[Dict], Dict[str, Any]]:
    """
    Convenience function to evaluate quotes and return opportunities.
    
    v2.1.0: Accepts optional gas_config for live gas pricing.
    v2.7.1: Accepts target_notional_usd and max_notional_drift_pct for config alignment.
    
    Returns:
        (opportunities_as_dicts, summary_stats)
    """
    if gas_config is None:
        gas_config = GasConfig(eth_usd_price=eth_usd_price)
    engine = OpportunityEngine(
        gas_config=gas_config,
        min_net_profit_usd=min_net_profit_usd,
        target_notional_usd=target_notional_usd,
        max_notional_drift_pct=max_notional_drift_pct,
    )
    
    opportunities = engine.build_opportunities(quotes, cycle, timestamp)
    
    # Build summary
    profitable = engine.filter_profitable(opportunities)
    gated = engine.filter_gated(opportunities)
    
    # v2.0.9: Use only gated opportunities for stats (excludes PRICE_OUTLIER etc.)
    max_gated_spread = max((float(o.gross_spread_bps) for o in gated), default=0.0)
    
    # v2.0.9: Quality warnings
    quality_warnings = []
    if max_gated_spread > 1000:  # >10% spread is suspicious even if gated
        quality_warnings.append(f"HIGH_GATED_SPREAD: max {max_gated_spread:.0f} bps")
    
    summary = {
        "total_opportunities": len(opportunities),
        "profitable_count": len(profitable),
        "gated_count": len(gated),
        "best_net_profit_usd": max((o.net_profit_usd for o in gated), default=0.0),
        "total_potential_usd": sum(o.net_profit_usd for o in gated),
        "avg_gas_cost_usd": (
            sum(o.gas_cost_usd for o in gated) / len(gated)
            if gated else 0.0
        ),
        "rejected_count": len(opportunities) - len(gated),
        "rejected_reasons": _count_reject_reasons(opportunities),
        "max_gated_spread_bps": max_gated_spread,  # v2.0.9: for quality monitoring
        "quality_warnings": quality_warnings,  # v2.0.9
    }
    
    # v2.8.0: Sort by net_profit_usd descending so roundtrip evaluates best candidates first
    gated_sorted = sorted(gated, key=lambda o: o.net_profit_usd, reverse=True)
    
    # Return only gated opportunities (excludes PRICE_OUTLIER, etc.)
    return [o.to_dict() for o in gated_sorted], summary


def _count_reject_reasons(opportunities: List[Opportunity]) -> Dict[str, int]:
    """Count rejection reasons from non-gated opportunities."""
    reasons: Dict[str, int] = {}
    for o in opportunities:
        if not o.gate_passed and o.reject_reason:
            # Extract reason type (e.g., "PRICE_OUTLIER" from "PRICE_OUTLIER: 12345.6 > 10000.0 bps")
            reason_type = o.reject_reason.split(":")[0] if ":" in o.reject_reason else o.reject_reason
            reasons[reason_type] = reasons.get(reason_type, 0) + 1
    return reasons
