# PATH: monitoring/truth_report.py
"""
Truth report module for ARBY.

CONSISTENCY CONTRACT (M4):
- truth_report.health MUST match scan_stats for: quote_fetch_rate, quote_gate_pass_rate, rpc_success_rate
- truth_report.top_opportunities MUST preserve execution_blockers from scan.all_spreads
- If execution_ready_count == 0 in stats, NO opportunity can have is_execution_ready=True

SCHEMA CONTRACT (v3.0.0) — KEEP BACKWARD COMPATIBLE
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from core.format_money import format_money

logger = logging.getLogger("monitoring.truth_report")

SCHEMA_VERSION = "3.0.0"
GATE_BREAKDOWN_KEYS = frozenset(["revert", "slippage", "infra", "other"])

ERROR_TO_GATE_CATEGORY = {
    "QUOTE_REVERT": "revert",
    "SLIPPAGE_TOO_HIGH": "slippage",
    "INFRA_RPC_ERROR": "infra",
}

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
    """Calculate confidence score for an opportunity."""
    qf = max(0.0, min(1.0, float(quote_fetch_rate)))
    qg = max(0.0, min(1.0, float(quote_gate_pass_rate)))
    rpc = max(0.0, min(1.0, float(rpc_success_rate)))
    fresh = max(0.0, min(1.0, float(freshness_score)))
    adapt = max(0.0, min(1.0, float(adapter_reliability)))

    score = (
        CONFIDENCE_WEIGHTS["quote_fetch"] * qf
        + CONFIDENCE_WEIGHTS["quote_gate"] * qg
        + CONFIDENCE_WEIGHTS["rpc"] * rpc
        + CONFIDENCE_WEIGHTS["freshness"] * fresh
        + CONFIDENCE_WEIGHTS["adapter"] * adapt
    )
    return min(max(score, 0.0), 1.0)


@dataclass
class RPCHealthMetrics:
    """RPC health metrics."""
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

    def record_rpc_call(self, success: bool, latency_ms: Union[int, float] = 0) -> None:
        """Record an RPC call result."""
        latency_int = int(latency_ms)
        if success:
            self.rpc_success_count += 1
            self.total_latency_ms += latency_int
        else:
            self.rpc_failed_count += 1

    def record_success(self, latency_ms: int = 0) -> None:
        self.record_rpc_call(success=True, latency_ms=latency_ms)
        self.quote_call_attempts += 1

    def record_failure(self) -> None:
        self.record_rpc_call(success=False, latency_ms=0)
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
    return ERROR_TO_GATE_CATEGORY.get(reject_reason, "other")


def build_gate_breakdown(reject_histogram: Dict[str, int]) -> Dict[str, int]:
    """Build gate breakdown from reject histogram."""
    breakdown = {"revert": 0, "slippage": 0, "infra": 0, "other": 0}
    for reason, count in reject_histogram.items():
        category = map_error_to_gate_category(reason)
        breakdown[category] += count
    assert set(breakdown.keys()) == GATE_BREAKDOWN_KEYS
    return breakdown


def build_blocker_histogram(all_spreads: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Build execution blocker histogram from all spreads.
    
    STEP 4: Shows why spreads are blocked even if gates passed.
    """
    histogram: Dict[str, int] = {}
    for spread in all_spreads:
        blockers = spread.get("execution_blockers", [])
        for blocker in blockers:
            histogram[blocker] = histogram.get(blocker, 0) + 1
    return histogram


def build_dex_coverage(
    configured_dex_ids: Set[str],
    dexes_with_quotes: Set[str],
    dexes_passed_gates: Set[str],
) -> Dict[str, Any]:
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
    rpc_stats: Optional[Dict[str, Any]] = None,
    all_spreads: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Build health section for truth_report.
    
    CONSISTENCY CONTRACT (STEP 1):
    - quote_fetch_rate: from scan_stats (computed: quotes_fetched/quotes_total)
    - quote_gate_pass_rate: from scan_stats (computed: gates_passed/quotes_fetched)
    - rpc_success_rate: from rpc_stats if provided, else rpc_metrics, else compute from scan_stats
    """
    if rpc_metrics is None:
        rpc_metrics = RPCHealthMetrics()

    rpc_metrics.reconcile_with_rejects(reject_histogram)

    sorted_rejects = sorted(
        reject_histogram.items(),
        key=lambda x: (-x[1], x[0])
    )
    top_rejects = [[reason, count] for reason, count in sorted_rejects[:5]]

    gate_breakdown = build_gate_breakdown(reject_histogram)

    # STEP 1: Use scan_stats as source of truth for rates
    quotes_fetched = scan_stats.get("quotes_fetched", 0)
    quotes_total = scan_stats.get("quotes_total", 0)
    gates_passed = scan_stats.get("gates_passed", 0)

    # Compute rates from scan_stats (source of truth)
    if quotes_total > 0:
        quote_fetch_rate = quotes_fetched / quotes_total
    else:
        quote_fetch_rate = scan_stats.get("quote_fetch_rate", 0.0)

    if quotes_fetched > 0:
        quote_gate_pass_rate = gates_passed / quotes_fetched
    else:
        quote_gate_pass_rate = scan_stats.get("quote_gate_pass_rate", 0.0)

    # RPC success rate: prefer rpc_stats (from RPCClient), fallback to rpc_metrics
    if rpc_stats and rpc_stats.get("total_requests", 0) > 0:
        rpc_success_rate = rpc_stats.get("success_rate", 0.0)
        rpc_total_requests = rpc_stats.get("total_requests", 0)
        rpc_failed_requests = rpc_stats.get("total_failure", 0)
        # Estimate avg latency from rpc_metrics if available
        rpc_avg_latency_ms = rpc_metrics.avg_latency_ms
    else:
        rpc_success_rate = rpc_metrics.rpc_success_rate
        rpc_total_requests = rpc_metrics.rpc_total_requests
        rpc_failed_requests = rpc_metrics.rpc_failed_count
        rpc_avg_latency_ms = rpc_metrics.avg_latency_ms

    dexes_active = scan_stats.get("dexes_active", 0)
    if dexes_with_quotes is not None:
        dexes_active = len(dexes_with_quotes)

    health = {
        "rpc_success_rate": round(rpc_success_rate, 3),
        "rpc_avg_latency_ms": rpc_avg_latency_ms,
        "rpc_total_requests": rpc_total_requests,
        "rpc_failed_requests": rpc_failed_requests,
        "quote_fetch_rate": round(quote_fetch_rate, 3),
        "quote_gate_pass_rate": round(quote_gate_pass_rate, 3),
        "quotes_fetched": quotes_fetched,
        "quotes_total": quotes_total,
        "gates_passed": gates_passed,
        "chains_active": scan_stats.get("chains_active", 0),
        "dexes_active": dexes_active,
        "pairs_covered": scan_stats.get("pairs_covered", 0),
        "pools_scanned": scan_stats.get("pools_scanned", 0),
        "top_reject_reasons": top_rejects,
        "gate_breakdown": gate_breakdown,
    }

    # STEP 4: Add blocker histogram
    if all_spreads:
        health["blocker_histogram"] = build_blocker_histogram(all_spreads)

    if configured_dex_ids is not None and dexes_with_quotes is not None:
        health["dex_coverage"] = build_dex_coverage(
            configured_dex_ids,
            dexes_with_quotes,
            dexes_passed_gates or set(),
        )

    return health


def _get_execution_blockers(
    run_mode: str,
    opp: Dict[str, Any],
    execution_disabled: bool = False,
) -> List[str]:
    """
    Determine execution blockers for opportunity.
    
    CONSISTENCY CONTRACT (STEP 3):
    - If opp already has execution_blockers, PRESERVE them
    - Only add computed blockers if not already present
    """
    # STEP 3: Preserve existing blockers from scan
    existing_blockers = opp.get("execution_blockers", [])
    if existing_blockers:
        return list(existing_blockers)  # Return as-is from scan

    # Compute blockers if not present
    blockers = []

    if run_mode == "SMOKE_SIMULATOR":
        blockers.append("SMOKE_MODE_NO_EXECUTION")

    # If execution globally disabled (M4), add blocker
    if execution_disabled:
        blockers.append("EXECUTION_DISABLED_M4")

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
    """Deterministic sort key for opportunities."""
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
        -is_profitable,
        -net_pnl,
        -net_bps,
        -confidence,
        spread_id,
    )


def rank_opportunities(opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
    rpc_stats: Optional[Dict[str, Any]] = None,
) -> TruthReport:
    """
    Build truth report with CONSISTENT metrics from scan_stats.
    
    CONSISTENCY CONTRACT:
    - health metrics MUST match scan_stats
    - top_opportunities MUST preserve execution_blockers from all_spreads
    - If execution_ready_count == 0, NO opportunity can be is_execution_ready=True
    """
    # Check if execution is disabled globally
    execution_ready_count = scan_stats.get("execution_ready_count", 0)
    execution_disabled = (execution_ready_count == 0)

    health = build_health_section(
        scan_stats,
        reject_histogram,
        rpc_metrics,
        configured_dex_ids,
        dexes_with_quotes,
        dexes_passed_gates,
        rpc_stats=rpc_stats,
        all_spreads=all_spreads,
    )

    # STEP 2 & 3: Build top_opportunities from all_spreads with preserved blockers
    normalized_opps = []
    source_spreads = all_spreads if all_spreads else opportunities

    for opp in source_spreads:
        pnl_usdc = opp.get("net_pnl_usdc", "0.000000")
        try:
            is_profitable = Decimal(str(pnl_usdc)) > 0
        except Exception:
            is_profitable = False

        # Get blockers - preserve from source or compute
        blockers = _get_execution_blockers(run_mode, opp, execution_disabled)

        # CONSISTENCY: if execution_ready_count == 0, force is_execution_ready = False
        is_execution_ready = opp.get("is_execution_ready", False)
        if execution_disabled:
            is_execution_ready = False
        if blockers:
            is_execution_ready = False

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
            "execution_blockers": blockers,
            "is_execution_ready": is_execution_ready,
        }

        normalized_opps.append(normalized_opp)

    # RANKING CONTRACT: deterministic sort
    ranked_opps = rank_opportunities(normalized_opps)
    top_opps = ranked_opps[:10]

    stats = {
        "spread_ids_total": scan_stats.get("spread_ids_total", 0),
        "spread_ids_profitable": scan_stats.get("spread_ids_profitable", 0),
        "spread_ids_executable": scan_stats.get("spread_ids_executable", 0),
        "paper_executable_spreads": scan_stats.get("spread_ids_executable", 0),
        "signals_total": scan_stats.get("spread_ids_total", 0),
        "signals_profitable": scan_stats.get("spread_ids_profitable", 0),
        "signals_executable": scan_stats.get("spread_ids_executable", 0),
        "paper_executable_count": scan_stats.get("paper_executable_count", 0),
        "execution_ready_count": execution_ready_count,
        "blocked_spreads": scan_stats.get("blocked_spreads", 0),
        "quotes_fetched": scan_stats.get("quotes_fetched", 0),
        "quotes_total": scan_stats.get("quotes_total", 0),
        "gates_passed": scan_stats.get("gates_passed", 0),
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
    qf_pct = health.get("quote_fetch_rate", 0) * 100
    gate_pass = health.get("quote_gate_pass_rate", 0) * 100
    print(f"RPC: {rpc_pct:.1f}% success ({health.get('rpc_total_requests', 0)} requests)")
    print(f"Quotes: {health.get('quotes_fetched', 0)}/{health.get('quotes_total', 0)} fetched ({qf_pct:.1f}%)")
    print(f"Gates: {health.get('gates_passed', 0)} passed ({gate_pass:.1f}%)")

    breakdown = health.get("gate_breakdown", {})
    if breakdown:
        print(f"  Gate breakdown: revert={breakdown.get('revert', 0)}, "
              f"slippage={breakdown.get('slippage', 0)}, infra={breakdown.get('infra', 0)}")

    blocker_hist = health.get("blocker_histogram", {})
    if blocker_hist:
        print(f"  Blocker histogram: {blocker_hist}")

    print(f"Coverage: {health.get('chains_active', 0)} chains, "
          f"{health.get('dexes_active', 0)} DEXes, {health.get('pools_scanned', 0)} pools")

    print("\nTop reject reasons:")
    for reason, count in health.get("top_reject_reasons", []):
        print(f"  {reason}: {count}")

    print("\n--- STATS ---")
    stats = report.stats
    print(f"Spreads: {stats.get('spread_ids_total', 0)} total, "
          f"{stats.get('spread_ids_profitable', 0)} profitable")
    print(f"Execution ready: {stats.get('execution_ready_count', 0)}")
    print(f"Blocked: {stats.get('blocked_spreads', 0)}")

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
