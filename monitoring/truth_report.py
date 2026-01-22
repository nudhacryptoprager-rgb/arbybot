# PATH: monitoring/truth_report.py
"""
Truth report module for ARBY.

SEMANTIC CONTRACT:
- mode: TruthReport data source ("REGISTRY", "DISCOVERY")
- run_mode: Scanner runtime ("SMOKE_SIMULATOR", "REGISTRY_REAL")

SCHEMA CONTRACT (v3.0.0) — KEEP BACKWARD COMPATIBLE:
- schema_version: MUST NOT change without explicit bump in SCHEMA_VERSION constant
- Bump requires: migration PR + test update + backward compat consideration
- top_opportunities[]: uses amount_in_numeraire (no ambiguous amount_in)
- health.gate_breakdown: canonical keys [revert, slippage, infra, other]

DEX COVERAGE CONTRACT:
- configured_dexes: DEXes in config (may not have quotes)
- dexes_active: DEXes that actually returned at least 1 quote
- dexes_passed_gates: DEXes that had at least 1 quote pass gates

GATE BREAKDOWN CONTRACT (canonical keys):
- revert: QUOTE_REVERT count
- slippage: SLIPPAGE_TOO_HIGH count
- infra: INFRA_RPC_ERROR count
- other: sum of all other reject reasons

RANKING CONTRACT (deterministic sort key):
===========================================
Opportunities are sorted by this key (all descending except spread_id):
  1. is_profitable DESC (True > False)
  2. net_pnl_usdc DESC (higher PnL first)
  3. net_pnl_bps DESC (higher bps first)
  4. confidence DESC (higher confidence first)
  5. spread_id ASC (alphabetical tiebreaker)

This ensures identical input → identical output order.
===========================================
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.format_money import format_money

logger = logging.getLogger("monitoring.truth_report")

# SCHEMA CONTRACT: Bump requires migration PR + test update
SCHEMA_VERSION = "3.0.0"

# GATE BREAKDOWN CONTRACT: Canonical keys that must be present
GATE_BREAKDOWN_KEYS = frozenset(["revert", "slippage", "infra", "other"])

# ERROR CODE MAPPING: Reject reason -> Gate breakdown category
ERROR_TO_GATE_CATEGORY = {
    "QUOTE_REVERT": "revert",
    "SLIPPAGE_TOO_HIGH": "slippage",
    "INFRA_RPC_ERROR": "infra",
}


@dataclass
class RPCHealthMetrics:
    """RPC health metrics consistent with reject histogram."""
    rpc_success_count: int = 0
    rpc_failed_count: int = 0
    quote_call_attempts: int = 0
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
        self.rpc_success_count += 1
        self.total_latency_ms += latency_ms
        self.quote_call_attempts += 1

    def record_failure(self) -> None:
        self.rpc_failed_count += 1
        self.quote_call_attempts += 1

    def record_quote_attempt(self) -> None:
        self.quote_call_attempts += 1

    def reconcile_with_rejects(self, reject_histogram: Dict[str, int]) -> None:
        infra_rpc_errors = reject_histogram.get("INFRA_RPC_ERROR", 0)
        if infra_rpc_errors > 0 and self.rpc_failed_count < infra_rpc_errors:
            self.rpc_failed_count = max(self.rpc_failed_count, infra_rpc_errors)
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


def map_error_to_gate_category(reject_reason: str) -> str:
    """Map reject reason to gate breakdown category."""
    return ERROR_TO_GATE_CATEGORY.get(reject_reason, "other")


def build_gate_breakdown(reject_histogram: Dict[str, int]) -> Dict[str, int]:
    """
    Build gate breakdown from reject histogram.
    
    CANONICAL CONTRACT: keys MUST be [revert, slippage, infra, other].
    This is the SINGLE SOURCE OF TRUTH for gate breakdown calculation.
    """
    breakdown = {"revert": 0, "slippage": 0, "infra": 0, "other": 0}
    
    for reason, count in reject_histogram.items():
        category = map_error_to_gate_category(reason)
        breakdown[category] += count
    
    assert set(breakdown.keys()) == GATE_BREAKDOWN_KEYS
    return breakdown


def build_dex_coverage(
    configured_dex_ids: Set[str],
    dexes_with_quotes: Set[str],
    dexes_passed_gates: Set[str],
) -> Dict[str, Any]:
    """Build DEX coverage metrics."""
    return {
        "configured_dexes": len(configured_dex_ids),
        "configured_dex_ids": sorted(configured_dex_ids),
        "dexes_active": len(dexes_with_quotes),
        "dexes_active_ids": sorted(dexes_with_quotes),
        "dexes_passed_gates": len(dexes_passed_gates),
        "dexes_passed_gates_ids": sorted(dexes_passed_gates),
    }


def build_health_section(
    scan_stats: Dict[str, Any],
    reject_histogram: Dict[str, int],
    rpc_metrics: Optional[RPCHealthMetrics] = None,
    configured_dex_ids: Optional[Set[str]] = None,
    dexes_with_quotes: Optional[Set[str]] = None,
    dexes_passed_gates: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Build the health section for truth_report."""
    if rpc_metrics is None:
        rpc_metrics = RPCHealthMetrics()

    rpc_metrics.reconcile_with_rejects(reject_histogram)

    sorted_rejects = sorted(
        reject_histogram.items(),
        key=lambda x: (-x[1], x[0])  # count DESC, reason ASC for stability
    )
    top_rejects = [[reason, count] for reason, count in sorted_rejects[:5]]

    gate_breakdown = build_gate_breakdown(reject_histogram)

    dexes_active = scan_stats.get("dexes_active", 0)
    if dexes_with_quotes is not None:
        dexes_active = len(dexes_with_quotes)

    health = {
        "rpc_success_rate": round(rpc_metrics.rpc_success_rate, 3),
        "rpc_avg_latency_ms": rpc_metrics.avg_latency_ms,
        "rpc_total_requests": rpc_metrics.rpc_total_requests,
        "rpc_failed_requests": rpc_metrics.rpc_failed_count,
        "quote_fetch_rate": round(scan_stats.get("quote_fetch_rate", 0.0), 3),
        "quote_gate_pass_rate": round(scan_stats.get("quote_gate_pass_rate", 0.0), 3),
        "chains_active": scan_stats.get("chains_active", 0),
        "dexes_active": dexes_active,
        "pairs_covered": scan_stats.get("pairs_covered", 0),
        "pools_scanned": scan_stats.get("pools_scanned", 0),
        "top_reject_reasons": top_rejects,
        "gate_breakdown": gate_breakdown,
    }

    if configured_dex_ids is not None and dexes_with_quotes is not None:
        health["dex_coverage"] = build_dex_coverage(
            configured_dex_ids,
            dexes_with_quotes,
            dexes_passed_gates or set(),
        )

    return health


def _get_execution_blockers(run_mode: str, opp: Dict[str, Any]) -> List[str]:
    """Determine why opportunity is not execution-ready."""
    blockers = []

    if run_mode == "SMOKE_SIMULATOR":
        blockers.append("SMOKE_MODE_NO_EXECUTION")

    try:
        pnl = Decimal(str(opp.get("net_pnl_usdc", "0")))
        if pnl <= 0:
            blockers.append("NOT_PROFITABLE")
    except Exception:
        blockers.append("INVALID_PNL")

    confidence = opp.get("confidence", 0.0)
    if confidence < 0.5:
        blockers.append("LOW_CONFIDENCE")

    if opp.get("reject_reason"):
        blockers.append(f"REJECTED:{opp.get('reject_reason')}")

    return blockers


def _opportunity_sort_key(opp: Dict[str, Any]) -> Tuple:
    """
    RANKING CONTRACT: Deterministic sort key for opportunities.
    
    Sort order (all DESC except spread_id ASC):
      1. is_profitable DESC (True > False)
      2. net_pnl_usdc DESC
      3. net_pnl_bps DESC
      4. confidence DESC
      5. spread_id ASC (tiebreaker)
    
    Using negative for DESC, positive for ASC.
    """
    try:
        net_pnl = Decimal(str(opp.get("net_pnl_usdc", "0")))
    except Exception:
        net_pnl = Decimal("0")
    
    try:
        net_bps = Decimal(str(opp.get("net_pnl_bps", "0")))
    except Exception:
        net_bps = Decimal("0")
    
    is_profitable = 1 if opp.get("is_profitable", False) else 0
    confidence = float(opp.get("confidence", 0.0))
    spread_id = opp.get("spread_id", "zzz")
    
    return (
        -is_profitable,  # DESC: True (1) first
        -net_pnl,        # DESC: higher PnL first
        -net_bps,        # DESC: higher bps first
        -confidence,     # DESC: higher confidence first
        spread_id,       # ASC: alphabetical tiebreaker
    )


def rank_opportunities(opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rank opportunities using deterministic sort key.
    
    RANKING CONTRACT: Same input → same output order.
    """
    return sorted(opportunities, key=_opportunity_sort_key)


@dataclass
class TruthReport:
    """Truth report for a scan cycle. Schema contract 3.0.0."""
    timestamp: str = ""
    mode: str = "REGISTRY"
    run_mode: str = "SMOKE_SIMULATOR"
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
        return {
            "schema_version": SCHEMA_VERSION,
            "timestamp": self.timestamp,
            "mode": self.mode,
            "run_mode": self.run_mode,
            "health": self.health,
            "top_opportunities": self.top_opportunities,
            "stats": self.stats,
            "revalidation": self.revalidation,
            "cumulative_pnl": self.cumulative_pnl,
            "pnl": self.pnl,
            "pnl_normalized": self.pnl_normalized,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, path: Path) -> None:
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
    run_mode: str = "SMOKE_SIMULATOR",
    all_spreads: Optional[List[Dict[str, Any]]] = None,
    configured_dex_ids: Optional[Set[str]] = None,
    dexes_with_quotes: Optional[Set[str]] = None,
    dexes_passed_gates: Optional[Set[str]] = None,
) -> TruthReport:
    """Build truth report with execution_blockers for each opportunity."""
    health = build_health_section(
        scan_stats, reject_histogram, rpc_metrics,
        configured_dex_ids, dexes_with_quotes, dexes_passed_gates
    )

    normalized_opps = []
    for opp in opportunities:
        pnl_usdc = opp.get("net_pnl_usdc", "0.000000")
        try:
            is_profitable = Decimal(str(pnl_usdc)) > 0
        except Exception:
            is_profitable = False

        normalized_opp = {
            "spread_id": opp.get("spread_id", "unknown"),
            "opportunity_id": opp.get("opportunity_id") or opp.get("spread_id", "unknown"),
            "dex_buy": opp.get("dex_buy") or opp.get("dex_a") or "unknown",
            "dex_sell": opp.get("dex_sell") or opp.get("dex_b") or "unknown",
            "pool_buy": opp.get("pool_buy") or opp.get("pool_a") or "unknown",
            "pool_sell": opp.get("pool_sell") or opp.get("pool_b") or "unknown",
            "token_in": opp.get("token_in") or "unknown",
            "token_out": opp.get("token_out") or "unknown",
            "chain_id": opp.get("chain_id", 0),
            "amount_in_numeraire": opp.get("amount_in_numeraire") or opp.get("amount_in") or "0",
            "amount_out_numeraire": opp.get("amount_out_numeraire") or opp.get("amount_out") or "0",
            "net_pnl_usdc": pnl_usdc,
            "net_pnl_bps": opp.get("net_pnl_bps", "0.00"),
            "confidence": opp.get("confidence", 0.0),
            "is_profitable": is_profitable,
            "reject_reason": opp.get("reject_reason"),
        }

        blockers = _get_execution_blockers(run_mode, normalized_opp)
        normalized_opp["execution_blockers"] = blockers
        normalized_opp["is_execution_ready"] = len(blockers) == 0
        normalized_opps.append(normalized_opp)

    # RANKING CONTRACT: deterministic sort
    ranked_opps = rank_opportunities(normalized_opps)
    top_opps = ranked_opps[:10]

    # Fallback: include rejected spreads if no profitable opps
    if not top_opps and all_spreads:
        fallback_opps = []
        for spread in all_spreads[:5]:
            opp = {
                "spread_id": spread.get("spread_id", "unknown"),
                "opportunity_id": spread.get("opportunity_id") or spread.get("spread_id", "unknown"),
                "dex_buy": spread.get("dex_buy") or "unknown",
                "dex_sell": spread.get("dex_sell") or "unknown",
                "pool_buy": spread.get("pool_buy") or "unknown",
                "pool_sell": spread.get("pool_sell") or "unknown",
                "token_in": spread.get("token_in") or "unknown",
                "token_out": spread.get("token_out") or "unknown",
                "chain_id": spread.get("chain_id", 0),
                "amount_in_numeraire": spread.get("amount_in_numeraire") or "0",
                "amount_out_numeraire": spread.get("amount_out_numeraire") or "0",
                "net_pnl_usdc": spread.get("net_pnl_usdc", "0.000000"),
                "net_pnl_bps": spread.get("net_pnl_bps", "0.00"),
                "confidence": spread.get("confidence", 0.0),
                "is_profitable": False,
                "reject_reason": spread.get("reject_reason", "NOT_PROFITABLE"),
            }
            blockers = _get_execution_blockers(run_mode, opp)
            opp["execution_blockers"] = blockers
            opp["is_execution_ready"] = False
            fallback_opps.append(opp)
        top_opps = rank_opportunities(fallback_opps)

    stats = {
        "spread_ids_total": scan_stats.get("spread_ids_total", 0),
        "spread_ids_profitable": scan_stats.get("spread_ids_profitable", 0),
        "spread_ids_executable": scan_stats.get("spread_ids_executable", 0),
        "paper_executable_spreads": scan_stats.get("spread_ids_executable", 0),
        "signals_total": scan_stats.get("spread_ids_total", 0),
        "signals_profitable": scan_stats.get("spread_ids_profitable", 0),
        "signals_executable": scan_stats.get("spread_ids_executable", 0),
        "paper_executable_count": scan_stats.get("paper_executable_count", 0),
        "execution_ready_count": scan_stats.get("execution_ready_count", 0),
        "blocked_spreads": scan_stats.get("blocked_spreads", 0),
    }

    revalidation = {
        "total": scan_stats.get("revalidation_total", 0),
        "passed": scan_stats.get("revalidation_passed", 0),
        "gates_changed": scan_stats.get("gates_changed", 0),
        "gates_changed_pct": format_money(scan_stats.get("gates_changed_pct", 0), decimals=1),
    }

    paper_stats = paper_session_stats or {}
    total_pnl_usdc = paper_stats.get("total_pnl_usdc", "0.000000")
    notion_capital = paper_stats.get("notion_capital_usdc", "10000.000000")
    
    normalized_return_pct = None
    try:
        pnl_dec = Decimal(str(total_pnl_usdc))
        capital_dec = Decimal(str(notion_capital))
        if capital_dec > 0:
            normalized_return_pct = format_money((pnl_dec / capital_dec) * 100, decimals=4)
    except Exception:
        pass

    total_pnl_bps = paper_stats.get("total_pnl_bps", "0.00")

    return TruthReport(
        mode=mode,
        run_mode=run_mode,
        health=health,
        top_opportunities=top_opps,
        stats=stats,
        revalidation=revalidation,
        cumulative_pnl={"total_bps": total_pnl_bps, "total_usdc": total_pnl_usdc},
        pnl={
            "signal_pnl_bps": total_pnl_bps,
            "signal_pnl_usdc": total_pnl_usdc,
            "would_execute_pnl_bps": total_pnl_bps,
            "would_execute_pnl_usdc": total_pnl_usdc,
        },
        pnl_normalized={
            "notion_capital_numeraire": notion_capital,
            "normalized_return_pct": normalized_return_pct,
            "numeraire": "USDC",
        },
    )


def print_truth_report(report: TruthReport) -> None:
    """Print truth report to console."""
    print("\n" + "=" * 60)
    print("TRUTH REPORT")
    print("=" * 60)
    print(f"Timestamp: {report.timestamp}")
    print(f"Mode: {report.mode} | Run Mode: {report.run_mode}")

    print("\n--- HEALTH ---")
    health = report.health
    rpc_pct = health.get("rpc_success_rate", 0) * 100
    gate_pass = health.get("quote_gate_pass_rate", 0) * 100
    print(f"RPC: {rpc_pct:.1f}% success ({health.get('rpc_total_requests', 0)} requests)")
    print(f"Gates: {gate_pass:.1f}% pass rate")

    breakdown = health.get("gate_breakdown", {})
    if breakdown:
        print(f"  Breakdown: revert={breakdown.get('revert', 0)}, "
              f"slippage={breakdown.get('slippage', 0)}, infra={breakdown.get('infra', 0)}")

    print(f"Coverage: {health.get('chains_active', 0)} chains, "
          f"{health.get('dexes_active', 0)} DEXes (active), {health.get('pools_scanned', 0)} pools")

    dex_cov = health.get("dex_coverage")
    if dex_cov:
        print(f"  Configured: {dex_cov.get('configured_dexes', 0)} | "
              f"Active: {dex_cov.get('dexes_active', 0)} | "
              f"Passed gates: {dex_cov.get('dexes_passed_gates', 0)}")

    print("\nTop reject reasons:")
    for reason, count in health.get("top_reject_reasons", []):
        print(f"  {reason}: {count}")

    print("\n--- STATS ---")
    stats = report.stats
    print(f"Spreads: {stats.get('spread_ids_total', 0)} total, "
          f"{stats.get('spread_ids_profitable', 0)} profitable")
    print(f"Paper executable: {stats.get('paper_executable_spreads', 0)}")
    print(f"Execution ready: {stats.get('execution_ready_count', 0)}")

    print("\n--- TOP OPPORTUNITIES ---")
    if not report.top_opportunities:
        print("  (none)")
    for i, opp in enumerate(report.top_opportunities[:5], 1):
        ready = "🟢" if opp.get("is_execution_ready") else "🔴"
        blockers = opp.get("execution_blockers", [])
        blocker_str = f" [{', '.join(blockers[:2])}]" if blockers else ""
        print(f"  {i}. {ready} {opp.get('token_in')}->{opp.get('token_out')} "
              f"${opp.get('net_pnl_usdc')} ({opp.get('net_pnl_bps')} bps){blocker_str}")

    print("\n--- PNL ---")
    cpnl = report.cumulative_pnl
    print(f"Total: {cpnl.get('total_bps', 0)} bps (${cpnl.get('total_usdc', '0.000000')})")
    print("=" * 60 + "\n")
