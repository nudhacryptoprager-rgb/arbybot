"""Generate a minimal daily_report JSON from one or more run directories.

Usage (manual, initial):
  python scripts/generate_daily_report.py --run-dir data/runs/manual_run_20260205_131550 --out reports/

This is intentionally minimal: it reads `scan_*.json`, `truth_report_*.json`, and
`reject_histogram_*.json` from a run directory and builds `daily_report_<date>.json`.

Cost Model (v1.5.0):
  Dual PnL: reports both gas_only and paper_realistic (with slippage)
  - paper_net_pnl_usdc_gas_only: gas only (no slippage)
  - paper_net_pnl_usdc_realistic: gas + 5bps slippage (M4 paper simulation)
  Uses CostModelRegistry for unified cost models.
  Available models: paper_realistic, paper_conservative, gas_only
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional


# Import CostModelRegistry from m4.policy (canonical location)
# v2.6.1: Moved from scripts.ci_m4_execution_gate to avoid CLI-as-library pattern
try:
    from m4.policy import CostModelRegistry, CostModelConfig
    COST_MODEL_REGISTRY_AVAILABLE = True
except ImportError:
    COST_MODEL_REGISTRY_AVAILABLE = False
    CostModelConfig = None  # type: ignore


def load_json_first(path: Path, pattern: str):
    files = sorted(path.glob(pattern))
    if not files:
        return None
    with files[0].open("r", encoding="utf8") as fh:
        return json.load(fh)


def aggregate_run(
    run_dir: Path, 
    gas_usd_estimate: float | None = None, 
    slippage_usd_estimate: float = 0.0,
    cost_model_name: Optional[str] = None,
    session_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Aggregate a single run directory into a daily report.
    
    Args:
        run_dir: Path to run directory
        gas_usd_estimate: Gas cost in USD (legacy, prefer cost_model_name)
        slippage_usd_estimate: Slippage cost in USD (legacy)
        cost_model_name: Cost model from CostModelRegistry (v1.4.0)
            Available: paper_realistic, paper_conservative, gas_only
        session_context: Optional dict with session completion fields (v1.7.1):
            - session_goal: Short description of session goal
            - goal_status: REACHED | BLOCKED | IN_PROGRESS
            - close_allowed: True only if goal_status != IN_PROGRESS
            - remaining_blockers: List of blockers if not REACHED
            - primary_blocker_of_session: Main blocker this session addresses (v1.8.0)
            - blocker_status_before: Status at session start (v1.8.0)
            - blocker_status_after: Status at session end (v1.8.0)
            - docs_reread_confirmed: Agent confirmed reread of docs (v1.8.0)
    
    v1.5.0: Dual PnL - both gas_only and paper_realistic
    v1.7.1: Added session_context parameter for session completion gate
    v1.8.0: Added primary_blocker_of_session and blocker status fields
    """
    # Load both cost models for dual PnL (v1.5.0)
    gas_only_model = None
    paper_realistic_model = None
    if COST_MODEL_REGISTRY_AVAILABLE:
        registry = CostModelRegistry.default()
        try:
            gas_only_model = registry.get("gas_only")
        except ValueError:
            pass
        try:
            paper_realistic_model = registry.get("paper_realistic")
        except ValueError:
            pass
    
    # If cost_model_name is provided, use CostModelRegistry
    if cost_model_name and COST_MODEL_REGISTRY_AVAILABLE:
        cost_model_config = registry.get(cost_model_name)
        gas_usd_estimate = cost_model_config.gas_usd
        # slippage is calculated per-signal based on size and bps
        slippage_bps = cost_model_config.slippage_bps
    else:
        cost_model_config = None
        slippage_bps = 0
    
    # Search for artifacts in common locations: run_dir/, run_dir/reports/, run_dir/snapshots/
    def find_first(pattern: str):
        for candidate_dir in (run_dir, run_dir / "reports", run_dir / "snapshots"):
            if not candidate_dir.exists():
                continue
            files = sorted(candidate_dir.glob(pattern))
            if files:
                return files[0]
        return None

    scan_path = find_first("scan_*.json")
    truth_path = find_first("truth_report_*.json")
    reject_path = find_first("reject_histogram_*.json")
    scan = json.loads(scan_path.read_text(encoding="utf8")) if scan_path else {}
    truth = json.loads(truth_path.read_text(encoding="utf8")) if truth_path else {}
    reject = json.loads(reject_path.read_text(encoding="utf8")) if reject_path else {}

    # Minimal aggregations
    stats = truth.get("stats", {})
    infra = truth.get("infra", {})
    health = truth.get("health", {})

    # Derive structured health sections if not present or missing components
    if not (isinstance(health, dict) and health.get("rpc") and health.get("dex") and health.get("system")):
        rpc_success_rate = stats.get("rpc_success_rate") if isinstance(stats.get("rpc_success_rate"), (int, float)) else 1.0
        # compute p50 latency from scan.quotes latencies when available
        p50_latency = None
        try:
            qlat = []
            for q in (scan.get("quotes") or []):
                if q and isinstance(q.get("latency_ms"), (int, float)):
                    qlat.append(float(q.get("latency_ms")))
            if qlat:
                qlat.sort()
                n = len(qlat)
                mid = n // 2
                if n % 2 == 1:
                    p50_latency = qlat[mid]
                else:
                    p50_latency = (qlat[mid - 1] + qlat[mid]) / 2.0
        except Exception:
            p50_latency = None

        ws_connected_rate = 1.0 if infra.get("ws_connected") else 0.0

        quotes_total = stats.get("quotes_total") or 0
        quotes_fetched = stats.get("quotes_fetched") or 0
        quote_fetch_rate = (quotes_fetched / quotes_total) if quotes_total else None

        gates_passed = stats.get("gates_passed") or 0
        gate_pass_rate = (gates_passed / quotes_total) if quotes_total else None

        health = {
            "rpc": {
                "success_rate": rpc_success_rate,
                "p50_latency_ms": p50_latency,
                "ws_connected_rate": ws_connected_rate,
            },
            "dex": {
                "quote_fetch_rate": quote_fetch_rate,
                "revert_rate": 0,
            },
            "system": {
                "gate_pass_rate": gate_pass_rate,
                "artifacts_ok_rate": 1.0,
            },
        }

    # net_pnl_usdc: prefer truth.pnl.net_pnl_usdc or zero
    pnl = truth.get("pnl", {})
    gross_net_pnl_usdc = pnl.get("net_pnl_usdc") or 0.0

    # Calculate gross spread from spread_signals
    # gross_spread_usdc = sum of (spread_pct * size_usd) for all signals
    signals = truth.get("spread_signals") or []
    gross_spread_usdc = 0.0
    default_size_usd = 1000.0  # default size for paper PnL calculation
    for sig in signals:
        spread_pct = sig.get("spread_pct") or 0.0
        size_usd = sig.get("size_usd") or default_size_usd
        gross_spread_usdc += float(spread_pct) / 100.0 * float(size_usd)

    # Dual PnL calculation (v1.5.0):
    # Both gas_only (truth estimate) and paper_realistic (M4 simulation)
    # - If signals_total > 0: paper_net = gross_spread - gas - slippage
    # - If signals_total == 0: paper_net = 0 (no signals = no trade = no cost)
    
    # Calculate slippage USD from paper_realistic model
    slippage_usdc_realistic = 0.0
    if paper_realistic_model and len(signals) > 0:
        # Slippage = sum(size_usd * slippage_bps / 10000) for each signal
        for sig in signals:
            size = float(sig.get("size_usd") or default_size_usd)
            slippage_usdc_realistic += size * paper_realistic_model.slippage_bps / 10000
    
    # Paper PnL (gas_only) - matches truth_report estimate
    if gas_only_model:
        gas_only_gas = gas_only_model.gas_usd
    elif gas_usd_estimate is not None:
        gas_only_gas = gas_usd_estimate
    else:
        gas_only_gas = 0.10  # default
    
    if len(signals) > 0:
        paper_net_gas_only = gross_spread_usdc - gas_only_gas
    else:
        paper_net_gas_only = 0.0
    
    # Paper PnL (realistic) - matches M4 simulation
    if paper_realistic_model:
        realistic_gas = paper_realistic_model.gas_usd
    else:
        realistic_gas = gas_only_gas
    
    if len(signals) > 0:
        paper_net_realistic = gross_spread_usdc - realistic_gas - slippage_usdc_realistic
    else:
        paper_net_realistic = 0.0
    
    # Legacy paper_net uses gas_only for backwards compatibility
    paper_net = paper_net_gas_only
    pnl_available = True
    pnl_reason = None if len(signals) > 0 else "no_signals_no_cost"

    # quote_sanity_rate: quotes that passed price sanity / total quotes
    # This is NOT a "win rate" - it measures price sanity filtering
    # Note: health.system.gate_pass_rate uses gates_passed (different metric)
    quotes_total = truth.get("quotes_total") or scan.get("quotes_total") or 0
    passed = truth.get("price_sanity_passed") or scan.get("price_sanity_passed") or 0
    quote_sanity_rate = (passed / quotes_total) if quotes_total else None
    
    # signal_win_rate: net-positive signals / total signals
    # This is the actual "win rate" - profitable opportunities vs all detected
    signal_win_rate = None  # computed after signals are counted

    # rejects reasons
    reasons_counter = Counter()
    has_critical_rejects = False  # Track if there are POOL_MISSING or PRICE_OUTLIER rejects
    for r in (reject.get("rejects") or []):
        reason = r.get("reject_reason") or r.get("error") or r.get("suspect_reason") or "unknown"
        reasons_counter[reason] += 1
        # Check for critical reject types that invalidate PnL
        if reason in ("POOL_MISSING", "V3_SLOT0_FAILED", "PRICE_OUTLIER", "NO_ONCHAIN_PRICE"):
            has_critical_rejects = True

    top_rejects = [{"reason": k, "count": v} for k, v in reasons_counter.most_common(10)]
    
    # Additional check from reject histogram
    pool_missing_count = reject.get("pool_missing_count", 0)
    price_outlier_count = reject.get("price_outlier_count", 0)
    if pool_missing_count > 0 or price_outlier_count > 0:
        has_critical_rejects = True
    
    # If critical rejects exist, mark pnl as unavailable (data quality issue)
    if has_critical_rejects and pnl_available:
        pnl_available = False
        pnl_reason = "invalid_quotes_present"

    # tail losses: use suspect_summary examples if available
    # Minimum N=5 samples required to populate tail_losses; otherwise explain why empty
    tail_losses = []
    tail_losses_reason = None
    MIN_TAIL_SAMPLES = 5
    
    suspect_summary = truth.get("suspect_summary", {})
    examples = suspect_summary.get("examples", []) if suspect_summary else []
    
    if len(examples) >= MIN_TAIL_SAMPLES:
        for ex in examples[:5]:
            tail_losses.append({"pair": ex.get("pair"), "pnl_usdc": None, "reason": ex.get("reason")})
    elif len(examples) > 0:
        tail_losses_reason = f"insufficient_samples (got {len(examples)}, need {MIN_TAIL_SAMPLES})"
    else:
        tail_losses_reason = "no_suspects_detected"

    # Provenance
    artifacts = {
        "scan_path": str(scan_path) if scan_path else None,
        "truth_report_path": str(truth_path) if truth_path else None,
        "reject_histogram_path": str(reject_path) if reject_path else None,
    }

    # autosize: surface autosize decisions from truth if present
    # Also check config_params for autosize configuration
    autosize = truth.get("autosize") or {}
    config_params = truth.get("config_params") or {}
    autosize_config = config_params.get("autosize") or {}
    
    autosize_summary = None
    if autosize and autosize.get("new_size_usd"):
        # Runtime autosize decision exists
        autosize_summary = {
            "enabled": True,
            "new_size_usd": autosize.get("new_size_usd") or autosize.get("new_size") or None,
            "reason": autosize.get("reason"),
            "cooldown_remaining": autosize.get("cooldown_remaining"),
        }
    elif autosize_config.get("enabled"):
        # Autosize configured but no runtime decision yet
        autosize_summary = {
            "enabled": True,
            "new_size_usd": autosize_config.get("base_size_usd"),
            "reason": "configured_no_adjustment",
            "cooldown_remaining": 0,
            "config": {
                "base_size_usd": autosize_config.get("base_size_usd"),
                "min_size_usd": autosize_config.get("min_size_usd"),
                "max_size_usd": autosize_config.get("max_size_usd"),
                "impact_threshold_bps": autosize_config.get("impact_threshold_bps"),
            }
        }
    else:
        autosize_summary = {"enabled": False, "reason": "not_configured", "new_size_usd": None, "cooldown_remaining": 0}

    # SIGNALS vs OPPORTUNITIES CONTRACT:
    # ===================================
    # top_signals: ALL spread signals (raw detection, for debug/audit)
    # top_opportunities: ONLY net-positive filtered (actionable, for execution)
    #
    # An opportunity is defined as a signal where:
    #   - is_net_positive_est = true, AND
    #   - net_pnl_usdc_est >= min_net_pnl_usdc_est (from config, default 0)
    #
    # Therefore: top_opportunities ⊆ top_signals (subset)
    # We do NOT fallback to scan.quotes anymore to avoid noisy null entries.
    top_signals = []
    top_opportunities = []  # Net-positive only (filtered by min_net_pnl_usdc_est)
    # Read min_net_pnl_usdc_est threshold from config_params (0 = break-even or better)
    config_params = truth.get("config_params") or {}
    min_net_threshold = float(config_params.get("min_net_pnl_usdc_est", 0.0))
    signals = truth.get("spread_signals") or []
    if signals:
        # sort by net_pnl_usdc_est descending (most profitable first)
        def _sig_score(s):
            # Primary: net_pnl_usdc_est (profitability)
            net = float(s.get("net_pnl_usdc_est") or 0)
            # Secondary: spread_bps_exact
            spread = float(s.get("spread_bps_exact") or s.get("spread_bps") or 0)
            return (net, spread)  # sort by net first, then spread

        sorted_sigs = sorted(signals, key=_sig_score, reverse=True)
        for s in sorted_sigs[:5]:
            # require at least spread_pct or confidence to be valid opportunity
            if s.get("spread_pct") is None and s.get("confidence") is None:
                continue
            opp = {
                "pair": s.get("pair"),
                "buy_dex": s.get("buy_dex"),
                "sell_dex": s.get("sell_dex"),
                "spread_bps_exact": s.get("spread_bps_exact"),
                "spread_pct": s.get("spread_pct"),
                "spread_frac": s.get("spread_frac"),
                "gross_pnl_usdc_est": s.get("gross_pnl_usdc_est"),
                "net_pnl_usdc_est": s.get("net_pnl_usdc_est"),
                "is_net_positive_est": s.get("is_net_positive_est"),
                "net_negative_reason": s.get("net_negative_reason"),
                "size_usd": s.get("size_usd") or s.get("size") or None,
                "confidence": s.get("confidence"),
                "confidence_reasons": s.get("confidence_reasons"),
                "source": "signal",
            }
            top_signals.append(opp)
            # Also add to opportunities list if net-positive (above threshold)
            # Uses min_net_pnl_usdc_est from config (default 0 = break-even)
            net_pnl = float(s.get("net_pnl_usdc_est") or 0)
            if net_pnl >= min_net_threshold:
                top_opportunities.append(opp)
    # If no signals → top_signals remains empty (no fallback to scan quotes)
    # Add reason when empty
    opportunities_reason = None
    if not top_signals:
        spread_signals_count = len(signals)
        if spread_signals_count == 0:
            opportunities_reason = "no_spread_signals"
        else:
            opportunities_reason = "no_valid_signals"

    # top_quotes: sample top-2 quotes from scan.quotes with provenance fields
    # This provides a sample of raw scanner output with full provenance
    top_quotes = []
    raw_quotes = scan.get("quotes") or []
    scan_timestamp = scan.get("timestamp")  # use scan timestamp for all quotes
    for q in raw_quotes[:2]:  # take first 2 as sample
        if not q:
            continue
        # Build pair from token_in/token_out if not present
        pair = q.get("pair")
        if not pair:
            token_in = q.get("token_in") or "?"
            token_out = q.get("token_out") or "?"
            pair = f"{token_in}/{token_out}"
        quote_sample = {
            "dex_id": q.get("dex_id"),
            "pool_address": q.get("pool_address"),
            "block_number": q.get("block_number"),
            "price": q.get("price"),
            "fee": q.get("fee"),
            "amount_in_human": q.get("amount_in_human"),
            "amount_out_human": q.get("amount_out_human"),
            "tick": q.get("tick"),
            "sqrt_price_x96": q.get("sqrt_price_x96"),
            "pair": pair,
            "timestamp": q.get("timestamp") or scan_timestamp,
        }
        top_quotes.append(quote_sample)

    # Build cost_model block for transparency (v1.4.0: unified with CostModelRegistry)
    # v1.5.1: cost_model now shows both gas_only and realistic for dual PnL transparency
    if paper_realistic_model:
        cost_model = {
            "name": paper_realistic_model.name,
            "description": paper_realistic_model.description,
            "gas_usd": paper_realistic_model.gas_usd,
            "slippage_bps": paper_realistic_model.slippage_bps,
            "source": "CostModelRegistry",
            "pnl_field": "paper_net_pnl_usdc_realistic",
        }
    elif cost_model_config:
        cost_model = {
            "name": cost_model_config.name,
            "description": cost_model_config.description,
            "gas_usd": cost_model_config.gas_usd,
            "slippage_bps": cost_model_config.slippage_bps,
            "source": "CostModelRegistry",
        }
    else:
        cost_model = {
            "name": "gas_only" if gas_usd_estimate is not None else "none",
            "description": "Legacy gas estimate",
            "gas_usd": gas_usd_estimate,
            "slippage_bps": 0,
            "slippage_usd_estimate": slippage_usd_estimate if gas_usd_estimate is not None else None,
            "source": "legacy_params",
        }

    # v3.2.57: Theoretical Net Profit block (mandatory cost-aware reporting)
    # Reads from truth_report.execution_pnl_included for included-only cost breakdown
    # Shows: gross, gas, slippage, L1, total_cost, net
    # v3.2.65: CHANGED from execution_pnl (all signals) to execution_pnl_included (only tradeable)
    # This aligns with M4 execution_report.total_net_usdc semantics
    # v1.7.1: Also reads execution_report for M4 sim_net_usdc cross-verification
    execution_pnl_included = truth.get("execution_pnl_included") or {}
    execution_pnl_all = truth.get("execution_pnl") or {}  # For transparency
    cost_components = execution_pnl_included.get("cost_model_components") or {}
    
    # Try to read M4 execution_report for cross-verification
    exec_report_path = find_first("execution_report_*.json")
    exec_report = json.loads(exec_report_path.read_text(encoding="utf8")) if exec_report_path else {}
    m4_sim_net_usdc = exec_report.get("total_net_usdc")  # M4 simulation net (uses CostModelRegistry)
    
    # v3.2.68: INVARIANT FIX - net_pnl_usdc MUST equal execution_report.total_net_usdc
    # The canonical profit value comes from M4 execution_report (uses CostModelRegistry paper_realistic)
    # truth_report.execution_pnl_included uses per-chain gas config which may differ
    # To satisfy invariant: net_pnl_usdc == execution_report.total_net_usdc == run_summary.total_net_usdc
    # Use m4_sim_net_usdc as canonical net_pnl_usdc when available
    canonical_net_pnl = m4_sim_net_usdc if m4_sim_net_usdc is not None else float(execution_pnl_included.get("net_pnl_usdc") or 0)
    truth_net_pnl = float(execution_pnl_included.get("net_pnl_usdc") or 0)  # Keep for transparency
    
    # Also read M4 cost components for consistency
    exec_cost_model = exec_report.get("cost_model") or {}
    # Use execution_report cost model when available (canonical M4 semantics)
    if exec_cost_model:
        gas_usd_canonical = exec_cost_model.get("gas_usd", 0.1)
        slippage_bps_canonical = exec_cost_model.get("slippage_bps", 5)
    else:
        gas_usd_canonical = cost_components.get("gas_usd", 0)
        slippage_bps_canonical = cost_components.get("slippage_bps", 0)
    
    # Calculate total_cost from canonical values
    included_signals_count = exec_report.get("included_signals_count", 1) if exec_report else 1
    canonical_gas_total = gas_usd_canonical * included_signals_count
    canonical_slippage_total = cost_components.get("slippage_usd", 0)  # Keep per-signal slippage from truth
    canonical_l1_cost = cost_components.get("l1_cost_usd", 0)
    canonical_total_cost = canonical_gas_total + canonical_slippage_total + canonical_l1_cost
    
    theoretical_net_profit = {
        "gross_pnl_usdc": float(execution_pnl_included.get("gross_pnl_usdc") or 0),
        # v3.2.68: Use M4 cost model for consistency with execution_report
        "gas_usd": canonical_gas_total,
        "slippage_bps": slippage_bps_canonical,
        "slippage_usd": canonical_slippage_total,
        "l1_data_gas_units": cost_components.get("l1_data_gas_units", 0),
        "l1_gas_price_gwei": cost_components.get("l1_gas_price_gwei", 0),
        "l1_cost_usd": canonical_l1_cost,
        "total_cost_usd": canonical_total_cost,
        # v3.2.68: CANONICAL net_pnl = execution_report.total_net_usdc (invariant enforced)
        "net_pnl_usdc": canonical_net_pnl,
        # Keep truth value for transparency/debugging
        "truth_net_pnl_usdc": truth_net_pnl,
        # v3.2.65: Add all_signals_net_pnl_usdc for transparency
        "all_signals_net_pnl_usdc": float(execution_pnl_all.get("net_pnl_usdc") or 0),
        "cost_model_available": execution_pnl_included.get("cost_model_available", False),
        "cost_model_version": "paper_realistic" if m4_sim_net_usdc is not None else execution_pnl_included.get("cost_model_version"),
        # v3.2.68: m4_sim_net_usdc is now identical to net_pnl_usdc (invariant)
        "m4_sim_net_usdc": m4_sim_net_usdc,
        "m4_execution_report_path": str(exec_report_path) if exec_report_path else None,
        # Mode/source to clarify this is paper/simulated, not real execution
        "mode": "paper_simulated",
        "source": "execution_report.total_net_usdc" if m4_sim_net_usdc is not None else "truth_report.execution_pnl_included",
        "disclaimer": "Theoretical profit estimate based on paper cost model. Not real execution.",
    }

    # Extract gates_passed and quotes_fetched for explicit surfacing
    gates_passed = stats.get("gates_passed") or 0
    quotes_fetched = stats.get("quotes_fetched") or scan.get("quotes_fetched") or 0

    # Build human-readable summary
    spread_info = f"spreads={len(signals)}" if signals else "spreads=0"
    summary = f"quotes_fetched={quotes_fetched}, gates_passed={gates_passed}, {spread_info}, paper_pnl={paper_net:.2f}"

    # Top signal for summary (best spread)
    top_signal = None
    if signals:
        # Sort by spread_bps_exact (or spread_bps for backwards compat) descending
        sorted_signals = sorted(
            signals, 
            key=lambda s: s.get("spread_bps_exact") or s.get("spread_bps") or 0, 
            reverse=True
        )
        best = sorted_signals[0]
        top_signal = {
            "pair": best.get("pair"),
            "buy_dex": best.get("buy_dex"),
            "sell_dex": best.get("sell_dex"),
            "spread_bps_exact": best.get("spread_bps_exact"),
            "spread_bps_ui": int(best.get("spread_bps_ui") or best.get("spread_bps_int") or best.get("spread_bps_exact") or 0),
            "is_gross_positive": best.get("is_gross_positive"),
            "gross_pnl_usdc_est": best.get("gross_pnl_usdc_est"),
            "net_pnl_usdc_est": best.get("net_pnl_usdc_est"),
            "is_net_positive_est": best.get("is_net_positive_est"),
            "net_negative_reason": best.get("net_negative_reason"),
        }

    # Compute signal_win_rate now that we have signal counts
    if len(signals) > 0:
        signal_win_rate = len(top_opportunities) / len(signals)
    else:
        signal_win_rate = None

    # Coverage metrics: show what was scanned (explains why signals may be 0)
    quotes = scan.get("quotes") or []
    # Derive pair from token_in/token_out if pair field not present
    pairs_set = set()
    for q in quotes:
        pair = q.get("pair")
        if not pair and q.get("token_in") and q.get("token_out"):
            pair = f"{q['token_in']}/{q['token_out']}"
        if pair:
            pairs_set.add(pair)
    pairs_scanned = sorted(pairs_set)
    dexes_active_list = sorted(set(q.get("dex_id") for q in quotes if q.get("dex_id")))
    pools_quoted = len(set((q.get("dex_id"), q.get("pool_address")) for q in quotes if q.get("pool_address")))
    coverage = {
        "pairs_scanned": pairs_scanned,
        "pairs_count": len(pairs_scanned),
        "dexes_active_list": dexes_active_list,
        "dexes_active": len(dexes_active_list),
        "pools_quoted": pools_quoted,
        "min_spread_bps": truth.get("config_params", {}).get("min_spread_bps", 0),
    }

    report = {
        "schema_version": "m5:daily:v1.3",  # v3.2.58: Added session completion fields
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timezone": "UTC",
        "run_id": str(run_dir.name),
        "source_run_dir": str(run_dir),
        "summary": summary,
        "artifacts": artifacts,
        "period": {"from": date.today().isoformat(), "to": date.today().isoformat()},
        "runs_included": 1,
        "pnl_mode": "paper",
        "gross_spread_usdc": round(gross_spread_usdc, 6),
        # Dual PnL (v1.5.0)
        "paper_net_pnl_usdc": round(paper_net, 6),  # Legacy: gas_only
        "paper_net_pnl_usdc_gas_only": round(paper_net_gas_only, 6),  # Truth estimate (no slippage)
        "paper_net_pnl_usdc_realistic": round(paper_net_realistic, 6),  # M4 sim (with slippage)
        "slippage_usdc_realistic": round(slippage_usdc_realistic, 6),  # Slippage component
        "pnl_available": pnl_available,
        "pnl_reason": pnl_reason,
        "cost_model": cost_model,
        # v3.2.57: Theoretical Net Profit with full cost breakdown (MANDATORY)
        "theoretical_net_profit": theoretical_net_profit,
        # Rates
        "quote_sanity_rate": quote_sanity_rate,  # price_sanity_passed / quotes_total
        "signal_win_rate": signal_win_rate,  # net_positive / signals_total
        "paper_win_rate": signal_win_rate,  # alias for gate compat (signals-based)
        "checks_count": quotes_total,
        "quotes_fetched": quotes_fetched,
        "gates_passed": gates_passed,
        # Signals vs Opportunities (raw vs filtered)
        # signals_total: all detected spreads (raw, for debug)
        # opportunities_total: filtered by min_net_pnl_usdc_est threshold
        "signals_total": len(signals),
        "opportunities_total": len(top_opportunities),
        "spread_signals_count": len(signals),  # alias for signals_total
        "net_positive_signals_count": len(top_opportunities),  # alias for opportunities_total
        "top_signal": top_signal,
        # DEPRECATED: will be removed in schema v2. Use checks_count.
        "deprecated_legacy_trades_count": quotes_total,
        "tail_losses": tail_losses,
        "tail_losses_reason": tail_losses_reason,  # Explains empty tail_losses
        "top_reject_reasons": top_rejects,
        "autosize": autosize_summary,
        "top_signals": top_signals,  # All signals (for debug/audit)
        "top_opportunities": top_opportunities,  # Net-positive only (for action)
        "opportunities_reason": opportunities_reason,
        "coverage": coverage,  # Scan coverage (explains why signals may be 0)
        "top_quotes": top_quotes,
        "health": health,
        # v3.2.58: Session completion fields (MANDATORY per DOCS_POLICY.md section 9)
        # v1.7.1: Now respects session_context parameter from caller
        # v1.8.0: Added primary_blocker_of_session and blocker status fields
        # v3.2.68: run_type is now passed explicitly from caller
        "session": {
            "session_goal": (session_context or {}).get("session_goal"),
            "goal_status": (session_context or {}).get("goal_status", "IN_PROGRESS"),
            "close_allowed": (session_context or {}).get("close_allowed", False),
            "remaining_blockers": (session_context or {}).get("remaining_blockers", []),
            "evidence_session_run_dirs": (session_context or {}).get(
                "evidence_session_run_dirs", [str(run_dir.name)]
            ),
            "primary_blocker_of_session": (session_context or {}).get(
                "primary_blocker_of_session"
            ),
            "blocker_status_before": (session_context or {}).get("blocker_status_before"),
            "blocker_status_after": (session_context or {}).get("blocker_status_after"),
            "docs_reread_confirmed": (session_context or {}).get(
                "docs_reread_confirmed", False
            ),
            # v3.2.68: run_type from session_context, default "automated" if not provided
            # "automated" = CI/gate run, "manual" = human session via generate_daily_report CLI
            "run_type": (session_context or {}).get("run_type", "automated"),
        },
    }
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", required=True, help="One run directory to aggregate")
    p.add_argument("--out", help="Output directory for daily report", default=".")
    p.add_argument("--gas-usd-estimate", type=float, help="Optional gas USD estimate to enable cost model")
    p.add_argument("--slippage-usd-estimate", type=float, help="Optional slippage USD estimate to subtract from PnL", default=0.0)
    p.add_argument("--runs-root", help="Optional root to aggregate multiple runs for a date")
    p.add_argument("--date", help="Date to aggregate (YYYYMMDD) when using --runs-root")
    args = p.parse_args()

    run_dir = Path(args.run_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Multi-run aggregation mode
    if args.runs_root and args.date:
        runs_root = Path(args.runs_root)
        date_token = args.date
        candidates = []
        # More robust selection: read timestamp from scan/truth artifact inside runDir
        for d in runs_root.iterdir():
            if not d.is_dir():
                continue
            # try to read scan_*.json or truth_report_*.json
            sp = sorted(d.glob("scan_*.json"))[:1]
            tp = sorted(d.glob("truth_report_*.json"))[:1]
            ts = None
            try:
                if sp:
                    j = json.loads(sp[0].read_text(encoding="utf8"))
                    ts = j.get("timestamp")
                elif tp:
                    j = json.loads(tp[0].read_text(encoding="utf8"))
                    ts = j.get("timestamp")
            except Exception:
                ts = None
            if ts:
                # compare date prefix YYYY-MM-DD
                if ts.startswith(date_token) or ts.startswith(date_token.replace("-", "")):
                    candidates.append(d)
            else:
                # fallback: include if date token in folder name (legacy)
                if date_token in d.name:
                    candidates.append(d)

        reports = []
        for d in sorted(candidates):
            r = aggregate_run(d)
            reports.append(r)

        # Merge simple sums and lists
        merged = {
            "schema_version": "m5:daily:v1",
            "generated_at": date.today().isoformat(),
            "source_run_dirs": [r.get("source_run_dir") for r in reports],
            "runs_included": len(reports),
            "pnl_mode": "paper",
            "paper_net_pnl_usdc": sum((r.get("paper_net_pnl_usdc") or 0) for r in reports),
            "paper_win_rate": None,
            "checks_count": sum((r.get("checks_count") or 0) for r in reports),
            "legacy_trades_count": sum((r.get("checks_count") or 0) for r in reports),
            "top_reject_reasons": [],
            "tail_losses": [],
            "health": {},
        }
        # compute combined win_rate
        total_checks = merged["checks_count"]
        total_passed = sum(((r.get("paper_win_rate") or 0) * (r.get("checks_count") or 0)) for r in reports)
        merged["paper_win_rate"] = (total_passed / total_checks) if total_checks else None

        # aggregate top rejects
        counter = Counter()
        for r in reports:
            for t in r.get("top_reject_reasons") or []:
                counter[t.get("reason")] += t.get("count", 0)
        merged["top_reject_reasons"] = [{"reason": k, "count": v} for k, v in counter.most_common(10)]

        out_path = out_dir / f"daily_report_{args.date}.json"
        with out_path.open("w", encoding="utf8") as fh:
            json.dump(merged, fh, indent=2, ensure_ascii=False)
        print(f"Wrote {out_path}")
        return

    report = aggregate_run(run_dir, gas_usd_estimate=args.gas_usd_estimate, slippage_usd_estimate=args.slippage_usd_estimate)
    # default: write under run_dir/reports
    write_dir = run_dir / "reports"
    write_dir.mkdir(parents=True, exist_ok=True)
    out_path = write_dir / f"daily_report_{date.today().isoformat()}.json"
    with out_path.open("w", encoding="utf8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
