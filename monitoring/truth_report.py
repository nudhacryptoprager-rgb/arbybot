# PATH: monitoring/truth_report.py
"""
Truth report module for ARBY.

METRICS CONTRACT:
- quotes_total = attempted
- quotes_fetched = got RPC response (amount > 0)
- gates_passed = passed all gates

STEP 5: Confidence formula consistency
- price_stability_factor = min(1.0, price_sanity_passed / max(1, quotes_fetched))
- Never 0.0 if price_sanity_passed > 0

STEP 6: Truthful profit breakdown
- If NO_COST_MODEL, net_pnl fields are None
- gross_pnl is always present
- cost breakdown fields present (may be None)

STEP 9: Execution semantics
- execution_enabled: false explicit
- is_actionable: false for signal-only
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

SCHEMA_VERSION = "3.2.0"  # Bumped for profit breakdown + execution semantics
GATE_BREAKDOWN_KEYS = frozenset(["revert", "slippage", "infra", "other", "sanity"])

ERROR_TO_GATE_CATEGORY = {
    "QUOTE_REVERT": "revert",
    "SLIPPAGE_TOO_HIGH": "slippage",
    "INFRA_RPC_ERROR": "infra",
    "INVALID_SIZE": "other",
    "PRICE_SANITY_FAIL": "sanity",
    "MINIMUM_REALISM_FAIL": "sanity",
}


def calculate_confidence(
    quote_fetch_rate: float,
    quote_gate_pass_rate: float,
    rpc_success_rate: float,
    freshness_score: float = 1.0,
    adapter_reliability: float = 1.0,
) -> float:
    """
    Calculate confidence score for opportunities.

    Weights:
    - quote_fetch_rate: 0.25
    - quote_gate_pass_rate: 0.25
    - rpc_success_rate: 0.25
    - freshness_score: 0.125
    - adapter_reliability: 0.125

    Returns: float in [0.0, 1.0]
    """
    # Clamp inputs to [0, 1]
    qfr = max(0.0, min(1.0, quote_fetch_rate))
    qgpr = max(0.0, min(1.0, quote_gate_pass_rate))
    rsr = max(0.0, min(1.0, rpc_success_rate))
    fs = max(0.0, min(1.0, freshness_score))
    ar = max(0.0, min(1.0, adapter_reliability))

    # Weighted average
    score = (
        qfr * 0.25 +
        qgpr * 0.25 +
        rsr * 0.25 +
        fs * 0.125 +
        ar * 0.125
    )

    # Clamp output to [0, 1]
    return max(0.0, min(1.0, score))


def calculate_price_stability_factor(
    price_sanity_passed: int,
    quotes_fetched: int,
    price_sanity_failed: int = 0,
) -> float:
    """
    STEP 5: Calculate price stability factor consistently.
    
    Never returns 0.0 if price_sanity_passed > 0.
    """
    if quotes_fetched <= 0:
        # No quotes fetched - can't assess stability
        return 0.5  # Neutral score
    
    if price_sanity_passed > 0:
        # At least some passed - calculate ratio
        total_checked = price_sanity_passed + price_sanity_failed
        if total_checked > 0:
            return min(1.0, price_sanity_passed / total_checked)
        return min(1.0, price_sanity_passed / quotes_fetched)
    
    # All failed or none passed
    if price_sanity_failed > 0:
        return 0.0
    
    # No sanity checks run
    return 0.5


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
    """Build gate breakdown with sanity category."""
    breakdown = {"revert": 0, "slippage": 0, "infra": 0, "other": 0, "sanity": 0}
    for reason, count in reject_histogram.items():
        category = map_error_to_gate_category(reason)
        breakdown[category] += count
    return breakdown


def build_blocker_histogram(all_spreads: List[Dict[str, Any]]) -> Dict[str, int]:
    histogram: Dict[str, int] = {}
    for spread in all_spreads:
        for blocker in spread.get("execution_blockers", []):
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
    if rpc_metrics is None:
        rpc_metrics = RPCHealthMetrics()

    rpc_metrics.reconcile_with_rejects(reject_histogram)

    sorted_rejects = sorted(reject_histogram.items(), key=lambda x: (-x[1], x[0]))
    top_rejects = [[reason, count] for reason, count in sorted_rejects[:5]]

    gate_breakdown = build_gate_breakdown(reject_histogram)

    quotes_fetched = scan_stats.get("quotes_fetched", 0)
    quotes_total = scan_stats.get("quotes_total", 0)
    gates_passed = scan_stats.get("gates_passed", 0)
    price_sanity_passed = scan_stats.get("price_sanity_passed", 0)
    price_sanity_failed = scan_stats.get("price_sanity_failed", 0)

    quote_fetch_rate = quotes_fetched / quotes_total if quotes_total > 0 else 0.0
    quote_gate_pass_rate = gates_passed / quotes_fetched if quotes_fetched > 0 else 0.0

    # STEP 5: Consistent price stability factor
    price_stability_factor = calculate_price_stability_factor(
        price_sanity_passed, quotes_fetched, price_sanity_failed
    )

    if rpc_stats and rpc_stats.get("total_requests", 0) > 0:
        rpc_success_rate = rpc_stats.get("success_rate", 0.0)
        rpc_total_requests = rpc_stats.get("total_requests", 0)
        rpc_failed_requests = rpc_stats.get("total_failure", 0)
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
        "price_sanity_passed": price_sanity_passed,
        "price_sanity_failed": price_sanity_failed,
        # STEP 5: Expose stability factor
        "price_stability_factor": round(price_stability_factor, 3),
        "top_reject_reasons": top_rejects,
        "gate_breakdown": gate_breakdown,
    }

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
    existing_blockers = opp.get("execution_blockers", [])
    if existing_blockers:
        return list(existing_blockers)

    blockers = []

    if run_mode == "SMOKE_SIMULATOR":
        blockers.append("SMOKE_MODE_NO_EXECUTION")

    if execution_disabled:
        blockers.append("EXECUTION_DISABLED_M4")

    try:
        pnl = Decimal(str(opp.get("signal_pnl_usdc") or opp.get("gross_pnl_usdc") or opp.get("net_pnl_usdc", "0")))
        if pnl <= 0:
            blockers.append("NOT_PROFITABLE")
    except Exception:
        blockers.append("INVALID_PNL")

    try:
        amount_in = opp.get("amount_in_numeraire", "0")
        if Decimal(str(amount_in)) <= 0:
            blockers.append("INVALID_SIZE")
    except:
        pass

    confidence = opp.get("confidence", 0.0)
    if confidence < 0.5:
        blockers.append("LOW_CONFIDENCE")

    if opp.get("reject_reason"):
        blockers.append(f"REJECTED:{opp.get('reject_reason')}")

    # STEP 6: No cost model blocker
    if not opp.get("cost_model_available", False):
        blockers.append("NO_COST_MODEL")

    return blockers


def _opportunity_sort_key(opp: Dict[str, Any]) -> Tuple:
    try:
        # Use gross_pnl if net is None (STEP 6)
        pnl_str = opp.get("net_pnl_usdc") or opp.get("gross_pnl_usdc") or opp.get("signal_pnl_usdc", "0")
        net_pnl = Decimal(str(pnl_str)) if pnl_str else Decimal("0")
    except Exception:
        net_pnl = Decimal("0")

    try:
        bps_str = opp.get("net_pnl_bps") or opp.get("signal_pnl_bps", "0")
        net_bps = Decimal(str(bps_str)) if bps_str else Decimal("0")
    except Exception:
        net_bps = Decimal("0")

    is_profitable = 1 if opp.get("is_profitable", False) else 0
    confidence = float(opp.get("confidence", 0.0))
    spread_id = opp.get("spread_id", "zzz")

    return (-is_profitable, -net_pnl, -net_bps, -confidence, spread_id)


def rank_opportunities(opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(opportunities, key=_opportunity_sort_key)


@dataclass
class TruthReport:
    timestamp: str = ""
    mode: str = "REGISTRY"
    run_mode: str = "SMOKE_SIMULATOR"
    # STEP 9: Explicit execution semantics
    execution_enabled: bool = False
    execution_blocker: str = "EXECUTION_DISABLED_M4"
    health: Dict[str, Any] = field(default_factory=dict)
    top_opportunities: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    revalidation: Dict[str, Any] = field(default_factory=dict)
    cumulative_pnl: Dict[str, Any] = field(default_factory=dict)
    pnl: Dict[str, Any] = field(default_factory=dict)
    pnl_normalized: Dict[str, Any] = field(default_factory=dict)
    # STEP 6: Cost model availability
    cost_model_available: bool = False

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "timestamp": self.timestamp,
            "mode": self.mode,
            "run_mode": self.run_mode,
            # STEP 9: Execution semantics
            "execution_enabled": self.execution_enabled,
            "execution_blocker": self.execution_blocker,
            # STEP 6: Cost model flag
            "cost_model_available": self.cost_model_available,
            "health": self.health,
            "top_opportunities": self.top_opportunities,
            "stats": self.stats,
            "revalidation": self.revalidation,
            "cumulative_pnl": self.cumulative_pnl,
            "pnl": self.pnl,
            "pnl_normalized": self.pnl_normalized,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

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
    # STEP 6: Cost model flag
    cost_model_available: bool = False,
) -> TruthReport:
    execution_ready_count = scan_stats.get("execution_ready_count", 0)
    execution_disabled = (execution_ready_count == 0)

    health = build_health_section(
        scan_stats, reject_histogram, rpc_metrics,
        configured_dex_ids, dexes_with_quotes, dexes_passed_gates,
        rpc_stats=rpc_stats, all_spreads=all_spreads,
    )

    normalized_opps = []
    source_spreads = all_spreads if all_spreads else opportunities

    # STEP 6: Aggregate PnL with cost awareness
    total_gross_pnl_usdc = Decimal("0")
    total_gas_estimate_usdc = Decimal("0")
    total_slippage_estimate_usdc = Decimal("0")
    total_net_pnl_usdc = Decimal("0") if cost_model_available else None

    for opp in source_spreads:
        # STEP 6: Get PnL components
        gross_pnl = opp.get("gross_pnl_usdc") or opp.get("signal_pnl_usdc") or opp.get("net_pnl_usdc", "0.000000")
        gas_estimate = opp.get("gas_estimate_usdc")
        slippage_estimate = opp.get("slippage_estimate_usdc")
        
        try:
            gross_dec = Decimal(str(gross_pnl))
            is_profitable = gross_dec > 0
            total_gross_pnl_usdc += gross_dec
            
            if gas_estimate is not None:
                total_gas_estimate_usdc += Decimal(str(gas_estimate))
            if slippage_estimate is not None:
                total_slippage_estimate_usdc += Decimal(str(slippage_estimate))
                
            # STEP 6: Only calculate net if cost model available
            if cost_model_available and gas_estimate is not None:
                net_pnl = gross_dec - Decimal(str(gas_estimate or "0")) - Decimal(str(slippage_estimate or "0"))
                if total_net_pnl_usdc is not None:
                    total_net_pnl_usdc += net_pnl
        except Exception:
            is_profitable = False

        blockers = _get_execution_blockers(run_mode, opp, execution_disabled)

        is_execution_ready = opp.get("is_execution_ready", False)
        if execution_disabled or blockers:
            is_execution_ready = False

        # STEP 9: is_actionable = False for signal-only
        is_actionable = is_execution_ready and not execution_disabled

        normalized_opp = {
            "spread_id": opp.get("spread_id", "unknown"),
            "opportunity_id": opp.get("opportunity_id") or opp.get("spread_id", "unknown"),
            "dex_buy": opp.get("dex_buy") or "unknown",
            "dex_sell": opp.get("dex_sell") or "unknown",
            "pool_buy": opp.get("pool_buy") or "unknown",
            "pool_sell": opp.get("pool_sell") or "unknown",
            "token_in": opp.get("token_in") or "unknown",
            "token_out": opp.get("token_out") or "unknown",
            "chain_id": opp.get("chain_id", 0),
            "amount_in_numeraire": opp.get("amount_in_numeraire") or "0",
            "amount_out_buy_numeraire": opp.get("amount_out_buy_numeraire") or "0",
            "amount_out_sell_numeraire": opp.get("amount_out_sell_numeraire") or "0",
            # STEP 6: Profit breakdown
            "gross_pnl_usdc": gross_pnl,
            "gas_estimate_usdc": gas_estimate,  # May be None
            "slippage_estimate_usdc": slippage_estimate,  # May be None
            "net_pnl_usdc": None if not cost_model_available else opp.get("net_pnl_usdc"),
            "net_pnl_bps": None if not cost_model_available else opp.get("net_pnl_bps"),
            # Legacy compatibility
            "signal_pnl_usdc": gross_pnl,
            "signal_pnl_bps": opp.get("signal_pnl_bps") or opp.get("net_pnl_bps", "0.00"),
            "confidence": opp.get("confidence", 0.0),
            "confidence_factors": opp.get("confidence_factors", {}),
            "is_profitable": is_profitable,
            "reject_reason": opp.get("reject_reason"),
            "execution_blockers": blockers,
            "is_execution_ready": is_execution_ready,
            # STEP 9: Explicit actionability
            "is_actionable": is_actionable,
            # STEP 6: Cost model flag per opportunity
            "cost_model_available": cost_model_available,
        }

        normalized_opps.append(normalized_opp)

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
        "dexes_active": scan_stats.get("dexes_active", 0),
        "price_sanity_passed": scan_stats.get("price_sanity_passed", 0),
        "price_sanity_failed": scan_stats.get("price_sanity_failed", 0),
    }

    revalidation = {
        "total": scan_stats.get("revalidation_total", 0),
        "passed": scan_stats.get("revalidation_passed", 0),
        "gates_changed": scan_stats.get("gates_changed", 0),
        "gates_changed_pct": format_money(scan_stats.get("gates_changed_pct", 0), decimals=1),
    }

    paper_stats = paper_session_stats or {}
    notion_capital = paper_stats.get("notion_capital_usdc", "10000.000000")

    gross_pnl_str = format_money(total_gross_pnl_usdc, decimals=6)
    gas_str = format_money(total_gas_estimate_usdc, decimals=6) if total_gas_estimate_usdc > 0 else None
    slippage_str = format_money(total_slippage_estimate_usdc, decimals=6) if total_slippage_estimate_usdc > 0 else None
    net_pnl_str = format_money(total_net_pnl_usdc, decimals=6) if total_net_pnl_usdc is not None else None

    normalized_return_pct = None
    try:
        capital_dec = Decimal(str(notion_capital))
        if capital_dec > 0:
            normalized_return_pct = format_money((total_gross_pnl_usdc / capital_dec) * 100, decimals=4)
    except Exception:
        pass

    # STEP 9: Determine execution blocker reason
    execution_blocker = "EXECUTION_DISABLED_M4"
    if run_mode == "SMOKE_SIMULATOR":
        execution_blocker = "SMOKE_MODE_NO_EXECUTION"

    return TruthReport(
        mode=mode,
        run_mode=run_mode,
        # STEP 9: Explicit execution semantics
        execution_enabled=not execution_disabled,
        execution_blocker=execution_blocker if execution_disabled else None,
        # STEP 6: Cost model flag
        cost_model_available=cost_model_available,
        health=health,
        top_opportunities=top_opps,
        stats=stats,
        revalidation=revalidation,
        cumulative_pnl={
            "total_bps": "0.00",
            "total_usdc": gross_pnl_str,
        },
        # STEP 6: Profit breakdown with cost awareness
        pnl={
            "gross_pnl_usdc": gross_pnl_str,
            "gas_estimate_usdc": gas_str,
            "slippage_estimate_usdc": slippage_str,
            "net_pnl_usdc": net_pnl_str,  # None if NO_COST_MODEL
            "cost_model_available": cost_model_available,
            # Legacy compatibility
            "signal_pnl_usdc": gross_pnl_str,
            "signal_pnl_bps": "0.00",
        },
        pnl_normalized={
            "notion_capital_numeraire": notion_capital,
            "normalized_return_pct": normalized_return_pct,
            "numeraire": "USDC",
        },
    )


def print_truth_report(report: TruthReport) -> None:
    """Print truth report with ASCII only (no emoji for Windows compatibility)."""
    print("\n" + "=" * 60)
    print("TRUTH REPORT")
    print("=" * 60)
    print(f"Timestamp: {report.timestamp}")
    print(f"Mode: {report.mode} | Run Mode: {report.run_mode}")
    # STEP 9: Show execution status
    exec_status = "ENABLED" if report.execution_enabled else f"DISABLED ({report.execution_blocker})"
    print(f"Execution: {exec_status}")

    print("\n--- HEALTH ---")
    health = report.health
    rpc_pct = health.get("rpc_success_rate", 0) * 100
    qf_pct = health.get("quote_fetch_rate", 0) * 100
    gp_pct = health.get("quote_gate_pass_rate", 0) * 100
    ps_factor = health.get("price_stability_factor", 0)
    print(f"RPC: {rpc_pct:.1f}% success ({health.get('rpc_total_requests', 0)} requests)")
    print(f"Quotes: {health.get('quotes_fetched', 0)}/{health.get('quotes_total', 0)} fetched ({qf_pct:.1f}%)")
    print(f"Gates: {health.get('gates_passed', 0)} passed ({gp_pct:.1f}%)")
    print(f"Price sanity: {health.get('price_sanity_passed', 0)} passed, {health.get('price_sanity_failed', 0)} failed")
    # STEP 5: Show price stability factor
    print(f"Price stability factor: {ps_factor:.3f}")
    print(f"DEXes active: {health.get('dexes_active', 0)}")

    print("\n--- STATS ---")
    stats = report.stats
    print(f"Spreads: {stats.get('spread_ids_total', 0)} total, {stats.get('spread_ids_profitable', 0)} profitable")

    print("\n--- PNL ---")
    pnl = report.pnl
    print(f"Gross PnL: ${pnl.get('gross_pnl_usdc', '0.000000')}")
    # STEP 6: Show cost breakdown if available
    if report.cost_model_available:
        print(f"Gas estimate: ${pnl.get('gas_estimate_usdc', '0.000000')}")
        print(f"Slippage estimate: ${pnl.get('slippage_estimate_usdc', '0.000000')}")
        print(f"Net PnL: ${pnl.get('net_pnl_usdc', '0.000000')}")
    else:
        print("[NO_COST_MODEL] Net PnL not calculated - gas/slippage estimates unavailable")

    print("\n--- TOP OPPORTUNITIES ---")
    if not report.top_opportunities:
        print("  (none)")
    for i, opp in enumerate(report.top_opportunities[:5], 1):
        # ASCII only: [+] for actionable, [-] for not actionable
        actionable = "[+]" if opp.get("is_actionable") else "[-]"
        dex_buy = opp.get("dex_buy", "?")
        dex_sell = opp.get("dex_sell", "?")
        # ASCII only: -> for cross-DEX, = for same-DEX
        cross = "->" if dex_buy != dex_sell else "="
        conf = opp.get("confidence", 0)
        gross = opp.get("gross_pnl_usdc", "0")
        print(f"  {i}. {actionable} {dex_buy}{cross}{dex_sell} "
              f"gross=${gross} (conf={conf:.2f})")

    print("=" * 60 + "\n")
