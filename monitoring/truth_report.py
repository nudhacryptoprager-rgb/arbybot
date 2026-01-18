# PATH: monitoring/truth_report.py
"""
Truth report module for ARBY.

Generates truthful metrics and health reports for scan cycles.
Ensures RPC health consistency with reject histogram.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.format_money import format_money, format_money_short

logger = logging.getLogger("monitoring.truth_report")

SCHEMA_VERSION = "3.0.0"


@dataclass
class RPCHealthMetrics:
    """
    RPC health metrics that are consistent with reject histogram.
    
    Key invariant: if infra_rpc_error_count > 0, then some request metric > 0
    """
    # Successful RPC calls
    rpc_success_count: int = 0
    
    # Failed RPC calls (timeouts, connection errors, etc.)
    rpc_failed_count: int = 0
    
    # Total quote attempts (may differ from RPC calls due to caching)
    quote_call_attempts: int = 0
    
    # Latency tracking
    total_latency_ms: int = 0
    
    @property
    def rpc_total_requests(self) -> int:
        return self.rpc_success_count + self.rpc_failed_count
    
    @property
    def rpc_success_rate(self) -> float:
        if self.rpc_total_requests == 0:
            return 0.0
        return self.rpc_success_count / self.rpc_total_requests
    
    @property
    def avg_latency_ms(self) -> int:
        if self.rpc_success_count == 0:
            return 0
        return self.total_latency_ms // self.rpc_success_count
    
    def record_success(self, latency_ms: int = 0) -> None:
        """Record a successful RPC call."""
        self.rpc_success_count += 1
        self.total_latency_ms += latency_ms
        self.quote_call_attempts += 1
    
    def record_failure(self) -> None:
        """Record a failed RPC call."""
        self.rpc_failed_count += 1
        self.quote_call_attempts += 1
    
    def record_quote_attempt(self) -> None:
        """Record a quote attempt (may be cached)."""
        self.quote_call_attempts += 1
    
    def reconcile_with_rejects(self, reject_histogram: Dict[str, int]) -> None:
        """
        Ensure health metrics are consistent with reject histogram.
        
        If INFRA_RPC_ERROR exists in rejects, our rpc_failed_count should
        reflect that (at minimum).
        """
        infra_rpc_errors = reject_histogram.get("INFRA_RPC_ERROR", 0)
        
        # If we have INFRA_RPC_ERROR rejects but no tracked failures, reconcile
        if infra_rpc_errors > 0 and self.rpc_failed_count < infra_rpc_errors:
            # The rejects themselves prove RPC calls were attempted
            self.rpc_failed_count = max(self.rpc_failed_count, infra_rpc_errors)
        
        # Also ensure quote_call_attempts is at least as large as tracked calls
        if self.quote_call_attempts < self.rpc_total_requests:
            self.quote_call_attempts = self.rpc_total_requests
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "rpc_success_rate": round(self.rpc_success_rate, 3),
            "rpc_avg_latency_ms": self.avg_latency_ms,
            "rpc_total_requests": self.rpc_total_requests,
            "rpc_failed_requests": self.rpc_failed_count,
            "quote_call_attempts": self.quote_call_attempts,
        }


def calculate_confidence(
    quote_fetch_rate: float,
    quote_gate_pass_rate: float,
    rpc_success_rate: float,
    freshness_score: float = 1.0,
    adapter_reliability: float = 1.0,
) -> float:
    """
    Calculate confidence score for an opportunity.
    
    Args:
        quote_fetch_rate: Rate of successful quote fetches (0-1)
        quote_gate_pass_rate: Rate of quotes passing gates (0-1)
        rpc_success_rate: Rate of successful RPC calls (0-1)
        freshness_score: Block freshness score (0-1)
        adapter_reliability: Adapter reliability score (0-1)
    
    Returns:
        Confidence score between 0 and 1
    """
    # Weighted average of factors
    weights = {
        "quote_fetch": 0.25,
        "quote_gate": 0.25,
        "rpc": 0.20,
        "freshness": 0.15,
        "adapter": 0.15,
    }
    
    score = (
        weights["quote_fetch"] * quote_fetch_rate
        + weights["quote_gate"] * quote_gate_pass_rate
        + weights["rpc"] * rpc_success_rate
        + weights["freshness"] * freshness_score
        + weights["adapter"] * adapter_reliability
    )
    
    return min(max(score, 0.0), 1.0)


def build_health_section(
    scan_stats: Dict[str, Any],
    reject_histogram: Dict[str, int],
    rpc_metrics: Optional[RPCHealthMetrics] = None,
) -> Dict[str, Any]:
    """
    Build the health section for truth_report.
    
    Ensures RPC health is consistent with observed rejects.
    """
    # Initialize RPC metrics if not provided
    if rpc_metrics is None:
        rpc_metrics = RPCHealthMetrics()
    
    # CRITICAL: Reconcile with reject histogram
    rpc_metrics.reconcile_with_rejects(reject_histogram)
    
    # Format top reject reasons
    sorted_rejects = sorted(
        reject_histogram.items(),
        key=lambda x: x[1],
        reverse=True
    )
    top_rejects = [[reason, count] for reason, count in sorted_rejects[:5]]
    
    # Build health dict
    health = {
        "rpc_success_rate": round(rpc_metrics.rpc_success_rate, 3),
        "rpc_avg_latency_ms": rpc_metrics.avg_latency_ms,
        "rpc_total_requests": rpc_metrics.rpc_total_requests,
        "rpc_failed_requests": rpc_metrics.rpc_failed_count,
        "quote_fetch_rate": round(scan_stats.get("quote_fetch_rate", 0.0), 3),
        "quote_gate_pass_rate": round(scan_stats.get("quote_gate_pass_rate", 0.0), 3),
        "chains_active": scan_stats.get("chains_active", 0),
        "dexes_active": scan_stats.get("dexes_active", 0),
        "pairs_covered": scan_stats.get("pairs_covered", 0),
        "pools_scanned": scan_stats.get("pools_scanned", 0),
        "top_reject_reasons": top_rejects,
    }
    
    return health


@dataclass
class TruthReport:
    """
    Truth report for a scan cycle.
    
    All money values are strings per Roadmap 3.2.
    """
    timestamp: str = ""
    mode: str = "REGISTRY"
    health: Dict[str, Any] = field(default_factory=dict)
    top_opportunities: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    revalidation: Dict[str, Any] = field(default_factory=dict)
    cumulative_pnl: Dict[str, Any] = field(default_factory=dict)
    pnl: Dict[str, Any] = field(default_factory=dict)
    pnl_normalized: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "schema_version": SCHEMA_VERSION,
            "timestamp": self.timestamp,
            "mode": self.mode,
            "health": self.health,
            "top_opportunities": self.top_opportunities,
            "stats": self.stats,
            "revalidation": self.revalidation,
            "cumulative_pnl": self.cumulative_pnl,
            "pnl": self.pnl,
            "pnl_normalized": self.pnl_normalized,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    def save(self, path: Path) -> None:
        """Save report to file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        logger.info(f"Truth report saved: {path}")


def build_truth_report(
    scan_stats: Dict[str, Any],
    reject_histogram: Dict[str, int],
    opportunities: List[Dict[str, Any]],
    paper_session_stats: Optional[Dict[str, Any]] = None,
    rpc_metrics: Optional[RPCHealthMetrics] = None,
    mode: str = "REGISTRY",
) -> TruthReport:
    """
    Build a complete truth report from scan data.
    
    Args:
        scan_stats: Statistics from the scan cycle
        reject_histogram: Counts of reject reasons
        opportunities: List of opportunity dicts
        paper_session_stats: Stats from paper trading session
        rpc_metrics: RPC health metrics
        mode: Scan mode (REGISTRY, DISCOVERY, etc.)
    
    Returns:
        TruthReport instance with all fields populated
    """
    # Build health section with RPC consistency
    health = build_health_section(scan_stats, reject_histogram, rpc_metrics)
    
    # Top opportunities (limit to 10)
    top_opps = sorted(
        opportunities,
        key=lambda x: Decimal(str(x.get("net_pnl_usdc", "0"))),
        reverse=True
    )[:10]
    
    # Stats
    stats = {
        "spread_ids_total": scan_stats.get("spread_ids_total", 0),
        "spread_ids_profitable": scan_stats.get("spread_ids_profitable", 0),
        "spread_ids_executable": scan_stats.get("spread_ids_executable", 0),
        "signals_total": scan_stats.get("signals_total", 0),
        "signals_profitable": scan_stats.get("signals_profitable", 0),
        "signals_executable": scan_stats.get("signals_executable", 0),
        "paper_executable_count": scan_stats.get("paper_executable_count", 0),
        "execution_ready_count": scan_stats.get("execution_ready_count", 0),
        "blocked_spreads": scan_stats.get("blocked_spreads", 0),
    }
    
    # Revalidation stats
    revalidation = {
        "total": scan_stats.get("revalidation_total", 0),
        "passed": scan_stats.get("revalidation_passed", 0),
        "gates_changed": scan_stats.get("gates_changed", 0),
        "gates_changed_pct": format_money(
            scan_stats.get("gates_changed_pct", 0), decimals=1
        ),
    }
    
    # PnL from paper session (all as strings)
    paper_stats = paper_session_stats or {}
    
    total_pnl_usdc = paper_stats.get("total_pnl_usdc", "0.000000")
    would_execute_pnl_usdc = paper_stats.get("total_pnl_usdc", "0.000000")
    notion_capital = paper_stats.get("notion_capital_usdc", "10000.000000")
    
    # Calculate normalized return
    normalized_return_pct = None
    try:
        pnl_dec = Decimal(str(total_pnl_usdc))
        capital_dec = Decimal(str(notion_capital))
        if capital_dec > 0:
            normalized_return_pct = format_money(
                (pnl_dec / capital_dec) * 100, decimals=4
            )
    except Exception:
        pass
    
    cumulative_pnl = {
        "total_bps": scan_stats.get("total_pnl_bps", 0),
        "total_usdc": total_pnl_usdc,
    }
    
    pnl = {
        "signal_pnl_bps": scan_stats.get("signal_pnl_bps", 0),
        "signal_pnl_usdc": format_money(scan_stats.get("signal_pnl_usdc", 0)),
        "would_execute_pnl_bps": scan_stats.get("would_execute_pnl_bps", 0),
        "would_execute_pnl_usdc": would_execute_pnl_usdc,
    }
    
    pnl_normalized = {
        "notion_capital_numeraire": notion_capital,
        "normalized_return_pct": normalized_return_pct,
        "numeraire": "USDC",
    }
    
    return TruthReport(
        mode=mode,
        health=health,
        top_opportunities=top_opps,
        stats=stats,
        revalidation=revalidation,
        cumulative_pnl=cumulative_pnl,
        pnl=pnl,
        pnl_normalized=pnl_normalized,
    )


def print_truth_report(report: TruthReport) -> None:
    """Print truth report to console in formatted style."""
    print("\n" + "=" * 60)
    print("TRUTH REPORT")
    print("=" * 60)
    print(f"Timestamp: {report.timestamp}")
    print(f"Mode: {report.mode}")
    
    print("\n--- HEALTH ---")
    health = report.health
    rpc_pct = health.get("rpc_success_rate", 0) * 100
    print(f"RPC: {rpc_pct:.1f}% success ({health.get('rpc_total_requests', 0)} requests), "
          f"{health.get('rpc_avg_latency_ms', 0)}ms avg")
    print(f"Quotes: {health.get('quote_fetch_rate', 0)*100:.1f}% fetch, "
          f"{health.get('quote_gate_pass_rate', 0)*100:.1f}% pass gates")
    print(f"Coverage: {health.get('chains_active', 0)} chains, "
          f"{health.get('dexes_active', 0)} DEXes, "
          f"{health.get('pairs_covered', 0)} pairs")
    print(f"Pools scanned: {health.get('pools_scanned', 0)}")
    
    print("\nTop reject reasons:")
    for reason, count in health.get("top_reject_reasons", []):
        print(f"    {reason}: {count}")
    
    print("\n--- STATS ---")
    stats = report.stats
    print(f"Total spreads: {stats.get('spread_ids_total', 0)}")
    print(f"Profitable: {stats.get('spread_ids_profitable', 0)}")
    print(f"Executable: {stats.get('spread_ids_executable', 0)}")
    print(f"Blocked: {stats.get('blocked_spreads', 0)}")
    
    print("\n--- CUMULATIVE PNL ---")
    cpnl = report.cumulative_pnl
    print(f"Total: {cpnl.get('total_bps', 0)} bps (${cpnl.get('total_usdc', '0.000000')})")
    print("=" * 60 + "\n")