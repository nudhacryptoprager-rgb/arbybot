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
    """A ranked opportunity."""
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
    executable: bool
    confidence: float  # 0.0 - 1.0


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


@dataclass
class TruthReport:
    """Complete truth report."""
    timestamp: str
    mode: str
    
    # Health
    health: HealthMetrics
    
    # Top opportunities
    top_opportunities: list[OpportunityRank]
    
    # Stats
    total_spreads: int
    profitable_spreads: int
    executable_spreads: int
    blocked_spreads: int
    
    # Cumulative PnL
    total_pnl_bps: int
    total_pnl_usdc: float
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "mode": self.mode,
            "health": asdict(self.health),
            "top_opportunities": [asdict(o) for o in self.top_opportunities],
            "stats": {
                "total_spreads": self.total_spreads,
                "profitable_spreads": self.profitable_spreads,
                "executable_spreads": self.executable_spreads,
                "blocked_spreads": self.blocked_spreads,
            },
            "cumulative_pnl": {
                "total_bps": self.total_pnl_bps,
                "total_usdc": self.total_pnl_usdc,
            },
        }


def calculate_confidence(spread: dict) -> float:
    """
    Calculate confidence score for a spread (0.0 - 1.0).
    
    Factors:
    - Executability (both DEXes verified)
    - Spread size (higher = more confident it's real)
    - Gas cost ratio (if gas is small fraction of spread, more confident)
    - Price sanity (if prices are close to anchor, more confident)
    """
    score = 0.0
    
    # Base: is it executable?
    if spread.get("executable"):
        score += 0.4
    else:
        score += 0.1  # Still has some value for analysis
    
    # Spread quality
    spread_bps = spread.get("spread_bps", 0)
    gas_bps = spread.get("gas_cost_bps", 0)
    net_bps = spread.get("net_pnl_bps", 0)
    
    if net_bps > 0:
        # Profitable
        score += 0.2
        
        # Gas ratio (if gas is < 30% of spread, good)
        if spread_bps > 0:
            gas_ratio = gas_bps / spread_bps
            if gas_ratio < 0.3:
                score += 0.2
            elif gas_ratio < 0.5:
                score += 0.1
    
    # Both legs have verified execution
    buy_leg = spread.get("buy_leg", {})
    sell_leg = spread.get("sell_leg", {})
    
    if buy_leg.get("verified_for_execution") and sell_leg.get("verified_for_execution"):
        score += 0.2
    
    return min(score, 1.0)


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
        
        for quote in cycle.get("quotes", []):
            pairs_seen.add(quote.get("pair"))
        
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
    
    # Calculate spread stats
    profitable_spreads = [s for s in all_spreads if s.get("net_pnl_bps", 0) > 0]
    executable_spreads = [s for s in profitable_spreads if s.get("executable")]
    blocked_spreads = [s for s in profitable_spreads if not s.get("executable")]
    
    # Rank opportunities by confidence × net_pnl
    ranked = []
    for spread in all_spreads:
        confidence = calculate_confidence(spread)
        net_bps = spread.get("net_pnl_bps", 0)
        
        # Get pair from legs
        buy_leg = spread.get("buy_leg", {})
        pair = "UNKNOWN"  # TODO: Get from spread
        
        ranked.append({
            "spread": spread,
            "confidence": confidence,
            "score": confidence * net_bps,  # Combined score
        })
    
    # Sort by score descending
    ranked.sort(key=lambda x: x["score"], reverse=True)
    
    # Build top opportunities
    top_opportunities = []
    for i, item in enumerate(ranked[:top_n]):
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
            executable=spread.get("executable", False),
            confidence=round(item["confidence"], 3),
        ))
    
    # Cumulative PnL from paper session
    total_pnl_bps = 0
    total_pnl_usdc = 0.0
    
    if paper_session_stats:
        total_pnl_bps = paper_session_stats.get("total_pnl_bps", 0)
        total_pnl_usdc = paper_session_stats.get("total_pnl_usdc", 0.0)
    
    return TruthReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        mode=mode,
        health=health,
        top_opportunities=top_opportunities,
        total_spreads=len(all_spreads),
        profitable_spreads=len(profitable_spreads),
        executable_spreads=len(executable_spreads),
        blocked_spreads=len(blocked_spreads),
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
                f"  #{opp.rank} [{exec_mark}] {opp.buy_dex}→{opp.sell_dex}: "
                f"{opp.net_pnl_bps} bps (${opp.expected_pnl_usdc:.2f}) "
                f"conf={opp.confidence:.0%}"
            )
    
    print("=" * 60 + "\n")
