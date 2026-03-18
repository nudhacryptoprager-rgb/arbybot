#!/usr/bin/env python3
"""
start.py - Multi-chain time-bounded online scan orchestrator.

Round-robins through a list of config files, running ci_m5_0_gate.py --online
for each. Only the primary rolling chain (run_kind=NORMAL) gets --refresh-rolling;
coverage configs skip rolling refresh to respect the rolling-discipline guardrail.

After all runs, writes a per-chain summary to --summary-file and prints a
console report including guardrails (e.g. "too good to be true" warning).

Runtime artifacts stay under data/runs/** and must never be committed.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
import shutil
import subprocess
import sys
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re
import glob as _glob

import yaml

RUNS_DIR = Path("data") / "runs"
CI_GATE = Path("scripts") / "ci_m5_0_gate.py"
HOT_PAIRS_CACHE_DIR = Path("data") / "cache"
HOT_LOOP_LATEST = Path("data") / "runs" / "_rolling" / "hot_loop_latest.json"
RUN_DIR_RE = re.compile(r"^\[ONLINE\] RunDir:\s*(.+)\s*$")
# R28.6: Match both legacy (ci_m5_gate_YYYYMMDD_HHMMSS) and new chain-scoped
# (ci_m5_gate_{chain_key}_YYYYMMDD_HHMMSS_{microseconds}) runDir patterns
CI_M5_DIR_RE = re.compile(r"^ci_m5_gate_(?:[a-z_]+_)?\d{8}_\d{6}(?:_\d+)?$")

# R28.11: Hot re-quote loop — every Nth cycle is a full universe sweep,
# intervening cycles reuse cached pairs (skip discovery, just re-quote).
FULL_SWEEP_INTERVAL = 5
LIVE_STREAM_MAX_EVENTS = 80

# R28.16: Phase event protocol — matches ARBY_PHASE: prefix from run_scan_real.py
PHASE_LINE_PREFIX = "ARBY_PHASE:"

# -- config introspection -------------------------------------------------


def read_config_meta(config_path: str) -> dict[str, Any]:
    """Return chain/run_kind from a YAML config without importing strategy code."""
    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}
    return {
        "chain": data.get("chain", "unknown"),
        "chain_id": data.get("chain_id"),
        "run_kind": data.get("run_kind", "NORMAL"),
        "blocker_classification": data.get("blocker_classification"),
        "blocker_reason": data.get("blocker_reason"),
    }


def is_primary_rolling_config(meta: dict[str, Any]) -> bool:
    return meta["run_kind"] == "NORMAL"


# -- child process -------------------------------------------------------


def run_gate_once(
    config: str,
    cycles: int,
    prune_keep: int,
    sleep_seconds: int,
    refresh_rolling: bool,
    timeout_seconds: int,
    line_prefix: str = "",
    extra_env: dict[str, str] | None = None,
    phase_callback: Any = None,
) -> tuple[int, Path | None]:
    """Run ci_m5_0_gate.py once; return (exit_code, runDir).

    phase_callback: if provided, called with dict for each ARBY_PHASE: line
    emitted by the child process (see strategy/jobs/run_scan_real.py).
    """
    cmd = [
        sys.executable,
        str(CI_GATE),
        "--online",
        "--config",
        config,
        "--cycles",
        str(cycles),
        "--prune-keep",
        str(prune_keep),
        "--sleep-seconds",
        str(sleep_seconds),
    ]
    if refresh_rolling:
        cmd += ["--refresh-rolling", "--refresh-rolling-strict"]

    # R28.11: Thread extra env vars to subprocess (e.g. ARBY_HOT_PAIRS_FILE)
    env = None
    if extra_env:
        import os as _os
        env = _os.environ.copy()
        env.update(extra_env)

    run_dir: Path | None = None
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    assert proc.stdout is not None

    try:
        start = time.monotonic()
        for line in proc.stdout:
            stripped = line.strip()
            # R28.16: Parse phase event lines from child process
            if stripped.startswith(PHASE_LINE_PREFIX) and phase_callback is not None:
                try:
                    phase_data = json.loads(stripped[len(PHASE_LINE_PREFIX):])
                    phase_callback(phase_data)
                except Exception:
                    pass  # Malformed phase line — ignore silently
            # R28.9: Prefix worker lines for log readability
            if line_prefix:
                sys.stdout.write(f"{line_prefix} {line}")
            else:
                sys.stdout.write(line)
            m = RUN_DIR_RE.match(stripped)
            if m:
                run_dir = Path(m.group(1).strip())
            if timeout_seconds > 0 and (time.monotonic() - start) > timeout_seconds:
                proc.kill()
                print(f"[TIMEOUT] Child killed after {timeout_seconds}s")
                break
        rc = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = 3
    except Exception:
        proc.kill()
        rc = 3

    return rc, run_dir


# -- run_summary extraction -----------------------------------------------


def extract_run_summary(run_dir: Path | None) -> dict[str, Any] | None:
    """Read the latest run_summary from a runDir."""
    if run_dir is None or not run_dir.exists():
        return None
    reports = run_dir / "reports"
    if not reports.exists():
        return None
    summaries = sorted(reports.glob("run_summary_*.json"))
    if not summaries:
        return None
    try:
        with open(summaries[-1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def extract_gate_result(run_dir: Path | None) -> dict[str, Any] | None:
    """Read gate_result.json from a runDir."""
    if run_dir is None or not run_dir.exists():
        return None
    path = run_dir / "reports" / "gate_result.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def extract_scan_stats(run_dir: Path | None) -> dict[str, Any] | None:
    """Read the latest scan_*.json and return its stats sub-dict.

    The scan JSON contains ``stats.discovery_runtime`` which is not present in
    run_summary.  Used by ``update_chain_stats`` to populate discovery_coverage.
    """
    if run_dir is None or not run_dir.exists():
        return None
    reports = run_dir / "reports"
    if not reports.exists():
        return None
    scans = sorted(reports.glob("scan_*.json"))
    if not scans:
        return None
    try:
        with open(scans[-1], encoding="utf-8") as f:
            data = json.load(f)
        return data.get("stats")
    except Exception:
        return None


def extract_truth_report(run_dir: Path | None) -> dict[str, Any] | None:
    """Read the latest truth_report from a runDir."""
    if run_dir is None or not run_dir.exists():
        return None
    reports = run_dir / "reports"
    if not reports.exists():
        return None
    truths = sorted(reports.glob("truth_report_*.json"))
    if not truths:
        return None
    try:
        with open(truths[-1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _validate_chain_id_match(run_dir: Path, expected_chain_id: int, chain_name: str) -> None:
    """Warn if any scan artifact in run_dir has a chain_id mismatch.

    This catches runDir collision bugs where two chains write into the same directory.
    """
    reports = run_dir / "reports"
    if not reports.exists():
        return
    for scan_file in reports.glob("scan_*.json"):
        try:
            with open(scan_file, encoding="utf-8") as f:
                data = json.load(f)
            actual = data.get("chain_id")
            if actual is not None and actual != expected_chain_id:
                print(
                    f"[CHAIN_MISMATCH] {run_dir.name}: expected chain_id={expected_chain_id} "
                    f"({chain_name}) but scan artifact has chain_id={actual}"
                )
        except Exception:
            pass


def classify_run(exit_code: int, summary: dict[str, Any] | None) -> str:
    """Return PASS / NO_DATA / FAIL / INFRA_FAIL for a single run."""
    if summary is None:
        return "INFRA_FAIL"
    status = summary.get("status", "")
    if status == "PASS":
        return "PASS"
    if status == "NO_DATA":
        return "NO_DATA"
    return "FAIL"


# -- housekeeping ---------------------------------------------------------


def delete_if_empty_run_dir(run_dir: Path) -> bool:
    try:
        if run_dir.name and CI_M5_DIR_RE.match(run_dir.name):
            reports = run_dir / "reports"
            if not reports.exists():
                shutil.rmtree(run_dir)
                return True
    except Exception:
        return False
    return False


def prune_run_dirs(keep: int) -> None:
    subprocess.run(
        [sys.executable, "scripts/prune_run_dirs.py", "--keep", str(keep), "--yes"],
        check=False,
    )


# -- per-chain aggregation ------------------------------------------------


def new_chain_stats() -> dict[str, Any]:
    return {
        "config": "",
        "runs": 0,
        "infra_pass": 0,
        "pass": 0,
        "no_data": 0,
        "fail": 0,
        "infra_fail": 0,
        "included_signals_total": 0,
        "net_usdc_total": 0.0,
        "profitable_roundtrips_total": 0,
        "roundtrip_evaluated_total": 0,
        # R28.10: Profit realism tracking for chain state classification
        "real_quote_count_total": 0,
        "last_profit_realism_status": None,
        "best_roundtrip_net_bps": None,
        "_suspect_accounting_count": 0,  # R28.17: contaminated PnL events
        "best_measured_spread_gap_bps": None,
        "sweep_best_net_pnl_bps": None,
        "sweep_best_size_usd": None,
        "sweep_best_pair": None,
        "sweep_gap_to_zero_bps": None,
        "sweep_measured_gas_bps": None,
        "sweep_measured_fee_bps": None,
        "sweep_measured_slippage_bps": None,
        "sweep_measured_total_cost_bps": None,
        "last_run_timestamp": None,
        "last_run_dir": None,
        # Richer per-chain fields (last-run snapshot)
        "last_run_summary_status": None,
        "last_quality_status": None,
        "last_chain_quality_level": None,
        "last_profit_truth_available": None,
        "run_kind": None,
        "last_cross_dex_pairs_count": None,
        "last_quality_reasons": [],
        "accepted_fail": False,
        # R19: Blocker classification from config
        "blocker_classification": None,
        "blocker_reason": None,
        # R12: Frontier ranking metrics (robust selection)
        "_sweep_gap_values": [],  # for median computation
        "runs_with_sweep": 0,
        # R21: Per-chain drift tracking
        "_drift_rejection_rates": [],
        "_drift_median_bps_values": [],
        "drift_excluded_total": 0,
        "drift_pairs_with_data_total": 0,
        # R22: Worst drift pair (latest snapshot)
        "drift_worst_pair": None,
        "drift_worst_pair_bps": None,
        # R28.9: Phase timers for dashboard performance visibility
        "last_phase_timers_ms": None,
        # R28.11: Pair-level live snapshot for dashboard/operator view
        "last_current_block": None,
        "last_top_spread_signals": [],
        # R28.11: Pair history — last N snapshots for delta tracking
        "_pair_history": [],  # list of {block, signals} dicts, max 5
        # R28.11: Cache freshness from discovery_runtime
        "last_pools_from_cache": None,
        "last_pools_from_rpc": None,
        "last_rpc_calls": None,
        # R28.11: Suppression counters from truth_report stats
        "last_suppression": None,
        # R28.11: Hot loop tracking
        "_run_counter": 0,
        "last_scan_mode": None,  # "full" or "hot"
        "hot_requote_count": 0,
        "full_sweep_count": 0,
        # R28.13: Micro-requote stats (in-process per-pair re-quotes)
        "micro_requote_count": 0,
        "micro_requote_quotes": 0,
    }


def update_chain_stats(
    stats: dict[str, Any],
    exit_code: int,
    run_dir: Path | None,
    summary: dict[str, Any] | None,
    gate_result: dict[str, Any] | None = None,
    scan_stats: dict[str, Any] | None = None,
    truth_report: dict[str, Any] | None = None,
) -> None:
    stats["runs"] += 1
    cls = classify_run(exit_code, summary)
    stats[cls.lower()] = stats.get(cls.lower(), 0) + 1
    if exit_code == 0:
        stats["infra_pass"] += 1

    if summary:
        metrics = summary.get("metrics", {})
        stats["included_signals_total"] += metrics.get("included_signals_count", 0)
        stats["net_usdc_total"] += float(metrics.get("total_net_usdc", 0) or 0)
        rt = metrics.get("roundtrip", {}) or summary.get("roundtrip_summary", {})
        stats["profitable_roundtrips_total"] += int(rt.get("profitable_count", 0) or 0)
        stats["roundtrip_evaluated_total"] = stats.get("roundtrip_evaluated_total", 0) + int(rt.get("evaluated_count", 0) or 0)
        # R28.10: Accumulate real_quote_count and snapshot profit_realism_status
        stats["real_quote_count_total"] += int(rt.get("real_quote_count", 0) or 0)
        prs = metrics.get("profit_realism_status")
        if prs:
            stats["last_profit_realism_status"] = prs
        run_best = rt.get("best_net_pnl_bps")
        if run_best is not None:
            # R28.17: Guard against accumulating contaminated PnL values
            if SANE_ROUNDTRIP_PNL_BPS_MIN <= run_best <= SANE_ROUNDTRIP_PNL_BPS_MAX:
                prev = stats.get("best_roundtrip_net_bps")
                stats["best_roundtrip_net_bps"] = run_best if prev is None else max(prev, run_best)
            else:
                print(
                    f"[WARN] SUSPECT_ACCOUNTING: best_net_pnl_bps={run_best:.2f} outside sane range "
                    f"[{SANE_ROUNDTRIP_PNL_BPS_MIN}, {SANE_ROUNDTRIP_PNL_BPS_MAX}], skipping"
                )
                stats["_suspect_accounting_count"] = stats.get("_suspect_accounting_count", 0) + 1
        run_gap = rt.get("best_measured_spread_gap_bps")
        if run_gap is not None:
            prev_gap = stats.get("best_measured_spread_gap_bps")
            stats["best_measured_spread_gap_bps"] = run_gap if prev_gap is None else max(prev_gap, run_gap)
        sweep = rt.get("dynamic_sweep", {})
        sweep_pnl = sweep.get("best_net_pnl_bps") or sweep.get("sweep_best_net_pnl_bps")
        if sweep_pnl is not None:
            # R12: collect gap for median computation
            gap = sweep.get("gap_to_zero_bps")
            if gap is not None:
                stats["_sweep_gap_values"].append(gap)
                stats["runs_with_sweep"] = stats.get("runs_with_sweep", 0) + 1
            prev_sweep = stats.get("sweep_best_net_pnl_bps")
            if prev_sweep is None or sweep_pnl > prev_sweep:
                stats["sweep_best_net_pnl_bps"] = sweep_pnl
                stats["sweep_best_size_usd"] = sweep.get("best_size_usd") or sweep.get("sweep_best_size_usd")
                stats["sweep_best_pair"] = sweep.get("best_pair") or sweep.get("frontier_pair")
                stats["sweep_gap_to_zero_bps"] = gap
                stats["sweep_measured_gas_bps"] = sweep.get("measured_gas_bps") or sweep.get("best_gas_bps")
                stats["sweep_measured_fee_bps"] = sweep.get("measured_fee_bps") or sweep.get("best_fee_bps")
                stats["sweep_measured_slippage_bps"] = sweep.get("measured_slippage_bps") or sweep.get("best_slippage_bps")
                stats["sweep_measured_total_cost_bps"] = sweep.get("measured_total_cost_bps") or sweep.get("best_total_cost_bps")
        ctx = summary.get("run_context", {})
        stats["last_run_timestamp"] = ctx.get("run_timestamp", stats["last_run_timestamp"])
        # Richer snapshot fields
        stats["last_run_summary_status"] = summary.get("status")
        stats["last_quality_status"] = summary.get("quality_status")
        stats["last_chain_quality_level"] = metrics.get("chain_quality_level")
        stats["last_profit_truth_available"] = metrics.get("profit_truth_available")
        stats["run_kind"] = summary.get("run_kind", stats["run_kind"])
        # R28.9: Capture quality_reasons for gate PASS + run_summary FAIL disambiguation
        stats["last_quality_reasons"] = summary.get("quality_reasons", [])

        # R21: Per-chain drift tracking from run_summary
        drift = metrics.get("drift_summary", {})
        if drift:
            dr = drift.get("drift_rejection_rate")
            if dr is not None:
                stats["_drift_rejection_rates"].append(dr)
            med_bps = drift.get("signal_drift_median_bps") or drift.get("notional_drift_bps")
            if med_bps is not None:
                stats["_drift_median_bps_values"].append(med_bps)
            stats["drift_excluded_total"] += drift.get("drift_excluded_count", 0)
            stats["drift_pairs_with_data_total"] += drift.get("pairs_with_drift_data", 0)
            # R22: Worst drift pair snapshot (always latest)
            ppds = drift.get("per_pair_drift_summary", [])
            if ppds:
                stats["drift_worst_pair"] = ppds[0].get("pair")
                stats["drift_worst_pair_bps"] = ppds[0].get("notional_drift_median_bps")

    if gate_result:
        stats["last_cross_dex_pairs_count"] = gate_result.get("cross_dex_pairs_count")

    if run_dir:
        stats["last_run_dir"] = str(run_dir.name)

    # R24→R25: Discovery runtime coverage from scan_*.json stats (not run_summary)
    if scan_stats:
        dr = scan_stats.get("discovery_runtime")
        if dr and dr.get("pairs_evaluated", 0) > 0:
            stats["last_discovery_runtime"] = {
                "pairs_evaluated": dr.get("pairs_evaluated", 0),
                "pairs_resolved": dr.get("pairs_resolved", 0),
                "cross_dex_pairs_count": dr.get("cross_dex_pairs_count", 0),
                "pairs_skipped_no_tokens": dr.get("pairs_skipped_no_tokens", 0),
                "pairs_skipped_no_pool": dr.get("pairs_skipped_no_pool", 0),
                "pairs_skipped_single_dex": dr.get("pairs_skipped_single_dex", 0),
                "pairs_skipped_excluded": dr.get("pairs_skipped_excluded", 0),
            }
            # R28.11: Cache freshness from discovery_runtime
            stats["last_pools_from_cache"] = dr.get("pools_from_cache")
            stats["last_pools_from_rpc"] = dr.get("pools_from_rpc")
            stats["last_rpc_calls"] = dr.get("rpc_calls")
        # R28.9: Propagate phase_timers_ms for dashboard performance visibility
        pt = scan_stats.get("phase_timers_ms")
        if pt:
            stats["last_phase_timers_ms"] = pt

    # R28.11: Suppression counters from truth_report stats
    if truth_report:
        tr_stats = truth_report.get("stats") or {}
        drift_sum = truth_report.get("drift_summary") or {}
        dr_rt = (scan_stats or {}).get("discovery_runtime") or {}
        suppression = {
            "single_dex": dr_rt.get("pairs_skipped_single_dex", 0),
            "no_pool": tr_stats.get("pool_missing_count", 0),
            "excluded": dr_rt.get("pairs_skipped_excluded", 0),
            "price_sanity_failed": tr_stats.get("price_sanity_failed", 0),
            "notional_drift_excluded": drift_sum.get("drift_excluded_count", 0),
            "quarantined": tr_stats.get("quarantined_count", 0),
        }
        if any(v for v in suppression.values()):
            stats["last_suppression"] = suppression
        # R28.20: Propagate reject histogram from truth_report for long_scan RCA
        rh = truth_report.get("reject_histogram")
        if rh:
            stats["last_reject_histogram"] = rh

    if truth_report:
        stats["last_current_block"] = truth_report.get("current_block")
        top_signals = []
        for sig in (truth_report.get("spread_signals") or [])[:5]:
            top_signals.append({
                "pair": sig.get("pair"),
                "buy_dex": sig.get("buy_dex"),
                "sell_dex": sig.get("sell_dex"),
                "spread_bps": sig.get("spread_bps"),
                "effective_slippage_bps": sig.get("effective_slippage_bps"),
                "spread_minus_required_bps": sig.get("spread_minus_required_bps"),
            })
        stats["last_top_spread_signals"] = top_signals

        # R28.11: Pair history — keep last 5 snapshots for run-to-run delta
        if top_signals or stats["last_current_block"] is not None:
            history = stats["_pair_history"]
            history.append({
                "block": stats["last_current_block"],
                "signals": top_signals,
            })
            # Keep only last 5 entries
            if len(history) > 5:
                stats["_pair_history"] = history[-5:]


# -- guardrails -----------------------------------------------------------


def check_guardrails(per_chain: dict[str, dict[str, Any]]) -> list[str]:
    """Return list of warning strings for suspicious patterns."""
    warnings: list[str] = []
    total_runs = sum(s["runs"] for s in per_chain.values())
    total_pass = sum(s["pass"] for s in per_chain.values())
    total_fail = sum(s["fail"] for s in per_chain.values())
    total_no_data = sum(s["no_data"] for s in per_chain.values())

    if total_runs >= 5 and total_fail == 0 and total_no_data == 0:
        warnings.append(
            "ALL_POSITIVE: Every run PASS, zero FAIL/NO_DATA -- "
            "verify against Roadmap.md Truth Engine expectation"
        )

    for chain, s in per_chain.items():
        if s["runs"] >= 3 and s["pass"] > 0 and s["fail"] == 0 and s["no_data"] == 0:
            warnings.append(
                f"CHAIN_ALL_POSITIVE [{chain}]: {s['runs']} runs all PASS -- "
                "check if data quality is real"
            )
        if s["runs"] >= 3 and s["infra_fail"] > s["runs"] * 0.5:
            warnings.append(
                f"CHAIN_INFRA_UNSTABLE [{chain}]: >{50}% runs had infra failures"
            )

        # R28.11: Narrow probe path stability warning
        # If a chain has identical top signals across multiple runs, its apparent
        # stability may be an artifact of a narrow static probe universe rather
        # than genuine market quiescence.
        hist = s.get("_pair_history", [])
        if len(hist) >= 3:
            pairs_sets = [frozenset(sig.get("pair", "") for sig in h.get("signals", [])) for h in hist[-3:]]
            if all(ps == pairs_sets[0] for ps in pairs_sets) and len(pairs_sets[0]) > 0:
                warnings.append(
                    f"STATIC_PROBE_PATH [{chain}]: same top pairs across last {len(hist[-3:])} runs — "
                    "apparent stability may reflect narrow probe config, not market health"
                )

        # R28.11: Single 0-fee route dominance warning
        top_sigs = s.get("last_top_spread_signals", [])
        if top_sigs and all(
            (sig.get("spread_bps") or 0) == 0 and (sig.get("spread_minus_required_bps") or 0) == 0
            for sig in top_sigs
        ):
            warnings.append(
                f"ZERO_FEE_DOMINANCE [{chain}]: all top signals have 0 bps spread — "
                "likely single structural 0-fee route (e.g. lynex_v3); not market edge"
            )

    return warnings


# -- chain profit state (R28.10, R28.17) -----------------------------------

# R28.17: Sane bounds for roundtrip PnL — values outside this range indicate
# accounting contamination (mixed-source quotes, decimal mismatch, garbage pools).
SANE_ROUNDTRIP_PNL_BPS_MAX = 500  # aligned with SUSPECT_ROUNDTRIP_OUTLIER_BPS
SANE_ROUNDTRIP_PNL_BPS_MIN = -500


def _roundtrip_accounting_is_sane(stats: dict[str, Any]) -> bool:
    """R28.17: Guard against contaminated roundtrip accounting.

    Returns False if best_roundtrip_net_bps is outside sane bounds,
    or if suspect accounting events were recorded during accumulation.
    """
    best = stats.get("best_roundtrip_net_bps")
    if best is not None and not (SANE_ROUNDTRIP_PNL_BPS_MIN <= best <= SANE_ROUNDTRIP_PNL_BPS_MAX):
        return False
    if stats.get("_suspect_accounting_count", 0) > 0:
        return False
    return True


def classify_chain_profit_state(stats: dict[str, Any]) -> str:
    """R28.10/R28.17: Derive chain profit state from accumulated per-chain metrics.

    States (ordered by strength):
      CONFIRMED_POSITIVE_CONTROL - profitable RT with repeated real quotes AND sane accounting
      THIN_POSITIVE              - profitable RT exists but evidence thin or accounting suspect
      PRIMARY_BLOCKER            - RT evaluated with real quotes but none profitable
      SUSPECT_ACCOUNTING         - profitable RT reported but accounting is outside sane bounds
      CANDIDATE                  - runs exist but no roundtrip evaluation yet
      PROBE_ONLY                 - no runs or no meaningful data
    """
    profitable = stats.get("profitable_roundtrips_total", 0)
    evaluated = stats.get("roundtrip_evaluated_total", 0)
    rq_total = stats.get("real_quote_count_total", 0)
    runs = stats.get("runs", 0)
    sane = _roundtrip_accounting_is_sane(stats)
    # R28.18: Strict promotion guard — block CONFIRMED when evidence is diagnostic-only or quality FAIL
    last_prs = stats.get("last_profit_realism_status")
    last_qs = stats.get("last_quality_status")

    if profitable > 0 and not sane:
        return "SUSPECT_ACCOUNTING"
    if profitable > 0 and rq_total >= 2:
        if last_prs == "ONE_LEG_ONLY_DIAGNOSTIC" or last_qs == "FAIL_QUALITY":
            return "THIN_POSITIVE"
        return "CONFIRMED_POSITIVE_CONTROL"
    if profitable > 0:
        return "THIN_POSITIVE"
    if evaluated > 0 and rq_total > 0:
        return "PRIMARY_BLOCKER"
    if runs > 0:
        return "CANDIDATE"
    return "PROBE_ONLY"


# -- summary output -------------------------------------------------------


def _compute_median(values: list[float]) -> float | None:
    """Compute median of a list of floats."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def build_summary(
    per_chain: dict[str, dict[str, Any]],
    wall_seconds: float,
    warnings: list[str],
) -> dict[str, Any]:
    pass_chains = [c for c, s in per_chain.items() if s["runs"] > 0 and s["fail"] == 0 and s["infra_fail"] == 0 and s["pass"] > 0]
    fail_chains = [c for c, s in per_chain.items() if s["fail"] > 0 or s["infra_fail"] > 0]
    probe_only_chains = [c for c, s in per_chain.items() if s["runs"] > 0 and s["pass"] == 0 and s["fail"] == 0]
    accepted_fail_chains = [c for c in fail_chains if per_chain[c].get("accepted_fail")]
    unexpected_fail_chains = [c for c in fail_chains if not per_chain[c].get("accepted_fail")]

    # R12: Compute cross-chain gap percentile context
    all_gap_values = []
    total_sweep_runs = 0
    for s in per_chain.values():
        all_gap_values.extend(s.get("_sweep_gap_values", []))
        total_sweep_runs += s.get("runs_with_sweep", 0)
    gap_best = min(all_gap_values) if all_gap_values else None
    gap_median = _compute_median(all_gap_values)

    # R26: run_context with run_timestamp for SHA-free provenance policy
    now_utc = datetime.now(timezone.utc)
    run_ts = now_utc.isoformat().replace("+00:00", "Z")

    # R28.10: Classify chain profit state for each chain
    for chain, s in per_chain.items():
        s["chain_profit_state"] = classify_chain_profit_state(s)

    summary = {
        "schema": "start:long_scan_summary:v1.13",  # R28.17: truth-quality discipline + 3-tier signal classification
        "generated_at": run_ts,
        "run_context": {
            "run_timestamp": run_ts,
            "code_identity": f"ts:{run_ts}",
            "code_sha": None,
            "evidence_sha": None,
        },
        "wall_seconds": round(wall_seconds, 1),
        "total_runs": sum(s["runs"] for s in per_chain.values()),
        "total_pass": sum(s["pass"] for s in per_chain.values()),
        "total_no_data": sum(s["no_data"] for s in per_chain.values()),
        "total_fail": sum(s["fail"] for s in per_chain.values()),
        "total_infra_fail": sum(s["infra_fail"] for s in per_chain.values()),
        "total_included_signals": sum(s["included_signals_total"] for s in per_chain.values()),
        "total_net_usdc": round(sum(s["net_usdc_total"] for s in per_chain.values()), 4),
        "total_profitable_roundtrips": sum(s["profitable_roundtrips_total"] for s in per_chain.values()),
        "total_roundtrip_evaluated": sum(s.get("roundtrip_evaluated_total", 0) for s in per_chain.values()),
        "best_roundtrip_net_bps": max(
            (s["best_roundtrip_net_bps"] for s in per_chain.values() if s.get("best_roundtrip_net_bps") is not None),
            default=None,
        ),
        "best_measured_spread_gap_bps": max(
            (s["best_measured_spread_gap_bps"] for s in per_chain.values() if s.get("best_measured_spread_gap_bps") is not None),
            default=None,
        ),
        "sweep_best_net_pnl_bps": max(
            (s["sweep_best_net_pnl_bps"] for s in per_chain.values() if s.get("sweep_best_net_pnl_bps") is not None),
            default=None,
        ),
        "sweep_best_size_usd": next(
            (
                s["sweep_best_size_usd"]
                for s in sorted(per_chain.values(), key=lambda x: x.get("sweep_best_net_pnl_bps") or -9999, reverse=True)
                if s.get("sweep_best_size_usd") is not None
            ),
            None,
        ),
        # R12: Gap percentile context for frontier analysis
        "gap_percentile_context": {
            "best_gap_to_zero_bps": round(gap_best, 4) if gap_best is not None else None,
            "median_gap_to_zero_bps": round(gap_median, 4) if gap_median is not None else None,
            "runs_with_sweep": total_sweep_runs,
            "sweep_values_count": len(all_gap_values),
        },
        "pass_chains": pass_chains,
        "fail_chains": fail_chains,
        "accepted_fail_chains": accepted_fail_chains,
        "unexpected_fail_chains": unexpected_fail_chains,
        "probe_only_chains": probe_only_chains,
        "per_chain": per_chain,
        "warnings": warnings,
        "frontier_ranking": _compute_frontier_ranking(per_chain),
        # R21: Top-level per-chain drift summary (extracted from per_chain stats)
        "per_chain_drift_summary": _compute_per_chain_drift_summary(per_chain),
        # R21: Explicit discovery vs truth-probe universe split
        "universe_split": _compute_universe_split(per_chain, pass_chains, fail_chains),
        # R28.10: Strict KPI separation — signals vs executable vs profitable vs truth
        "kpi_separation": _compute_kpi_separation(per_chain),
        # R28.10: Profit truth summary — chain_profit_state rollup
        "profit_truth_summary": _compute_profit_truth_summary(per_chain),
        # R28.9: Live batch state for dashboard visibility
        "batch_state": {
            "chains_total": len(per_chain),
            "chains_with_runs": sum(1 for s in per_chain.values() if s["runs"] > 0),
            "last_completed_chain": next(
                (c for c in reversed(list(per_chain)) if per_chain[c]["runs"] > 0),
                None,
            ),
            "last_summary_write": run_ts,
        },
        # R28.11: Hot loop metrics — full sweep vs hot re-quote cycle counts
        "hot_loop": {
            "full_sweep_interval": FULL_SWEEP_INTERVAL,
            "total_full_sweeps": sum(s.get("full_sweep_count", 0) for s in per_chain.values()),
            "total_hot_requotes": sum(s.get("hot_requote_count", 0) for s in per_chain.values()),
            "per_chain_mode": {
                c: {
                    "last_scan_mode": s.get("last_scan_mode"),
                    "full_sweeps": s.get("full_sweep_count", 0),
                    "hot_requotes": s.get("hot_requote_count", 0),
                }
                for c, s in per_chain.items()
            },
        },
        # R28.12: Truth path alignment — makes static-probe exceptions visible
        "truth_path_alignment": None,  # filled below
        # R28.14: Benchmark chain — strongest ALIGNED chain by merit
        "benchmark_chain": None,  # filled below
    }
    _tpa, _bench = _compute_truth_path_alignment(per_chain)
    summary["truth_path_alignment"] = _tpa
    summary["benchmark_chain"] = _bench
    return summary


def _compute_truth_path_alignment(per_chain: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], str | None]:
    """R28.14: Compute truth path alignment for all chains.

    Shows BOTH profit truth AND operational quality in one view, so the
    operator never sees a misleading ``POSITIVE + fail_chain`` without
    explanation.

    alignment values:
      ALIGNED        — profit proven + quality healthy (no fails)
      POSITIVE       — profitable roundtrips exist but quality has issues
      BLOCKED        — roundtrips evaluated with real quotes, none profitable
      NOT_PROVEN     — no real quote data or no runs yet
    """
    result: dict[str, Any] = {}
    for chain, s in per_chain.items():
        profit_state = s.get("chain_profit_state", "UNKNOWN")
        has_real_quotes = (s.get("real_quote_count_total", 0) or 0) > 0
        has_profitable_rt = (s.get("profitable_roundtrips_total", 0) or 0) > 0
        run_kind = "NORMAL" if s.get("config", "").endswith("real_minimal.yaml") else "COVERAGE"
        truth_mode = s.get("last_truth_mode", s.get("last_quality_level"))

        # R28.13: Operational quality — surface fail/pass alongside profit truth
        run_status = s.get("last_run_summary_status")
        quality_status = s.get("last_quality_status")
        fail_count = s.get("fail", 0) + s.get("infra_fail", 0)
        total_runs = s.get("runs", 0)
        quality_healthy = fail_count == 0 and total_runs > 0

        alignment = "ALIGNED"
        if profit_state == "PRIMARY_BLOCKER":
            alignment = "BLOCKED"
        elif profit_state == "CANDIDATE" or not has_real_quotes:
            alignment = "NOT_PROVEN"
        elif has_profitable_rt:
            # R28.13: Distinguish ALIGNED (profit + quality) from POSITIVE (profit only)
            alignment = "ALIGNED" if quality_healthy else "POSITIVE"

        result[chain] = {
            "run_kind": run_kind,
            "profit_state": profit_state,
            "has_real_quotes": has_real_quotes,
            "has_profitable_rt": has_profitable_rt,
            "alignment": alignment,
            "truth_mode": truth_mode,
            # R28.13: Operational quality context (Step 2 — no hidden contradictions)
            "run_status": run_status,
            "quality_status": quality_status,
            "quality_healthy": quality_healthy,
            "real_quote_count": s.get("real_quote_count_total", 0),
            "profitable_roundtrips": s.get("profitable_roundtrips_total", 0),
            "best_net_pnl_bps": s.get("best_roundtrip_net_bps"),
            "gap_to_zero_bps": s.get("sweep_gap_to_zero_bps"),
        }

    # R28.14: Identify benchmark chain — strongest ALIGNED chain by merit
    # Primary chain remains contractual (arbitrum_one for rolling), but the
    # benchmark is whoever currently holds the best truth standard.
    aligned_chains = [
        (ch, info) for ch, info in result.items()
        if info["alignment"] == "ALIGNED"
    ]
    benchmark_chain = None
    if aligned_chains:
        # Sort by profitable_roundtrips desc, then gap_to_zero_bps asc (lower is better)
        aligned_chains.sort(
            key=lambda x: (
                -(x[1].get("profitable_roundtrips") or 0),
                x[1].get("gap_to_zero_bps") if x[1].get("gap_to_zero_bps") is not None else 9999,
            )
        )
        benchmark_chain = aligned_chains[0][0]

    # R28.14: Unified truth standard fields per chain
    for ch, info in result.items():
        info["truth_standard_met"] = (
            info["alignment"] in ("ALIGNED", "POSITIVE")
            and info["has_real_quotes"]
            and (info.get("profitable_roundtrips") or 0) > 0
        )
        info["is_benchmark"] = ch == benchmark_chain

    return result, benchmark_chain


def _compute_per_chain_drift_summary(per_chain: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """R21: Build top-level per-chain drift summary from accumulated per-chain stats."""
    result = {}
    for chain, s in per_chain.items():
        drift_rates = s.get("_drift_rejection_rates", [])
        drift_bps_vals = s.get("_drift_median_bps_values", [])
        drift_rate_med = _compute_median(drift_rates)
        drift_bps_med = _compute_median(drift_bps_vals)
        result[chain] = {
            "drift_excluded_total": s.get("drift_excluded_total", 0),
            "drift_rejection_rate_median": round(drift_rate_med, 4) if drift_rate_med is not None else None,
            "notional_drift_median_bps": round(drift_bps_med, 1) if drift_bps_med is not None else None,
            "drift_pairs_with_data_total": s.get("drift_pairs_with_data_total", 0),
            "runs_sampled": len(drift_rates),
            # R22: Worst drift pair snapshot (from latest run)
            "drift_worst_pair": s.get("drift_worst_pair"),
            "drift_worst_pair_bps": s.get("drift_worst_pair_bps"),
        }
    return result


def _compute_universe_split(
    per_chain: dict[str, dict[str, Any]],
    pass_chains: list[str],
    fail_chains: list[str],
) -> dict[str, Any]:
    """R21: Compute explicit discovery vs truth-probe universe split.

    Discovery chains: all chains in scan rotation (COVERAGE + NORMAL).
    Truth-probe chains: chains with run_kind=NORMAL that update rolling artifacts.
    Monitoring-only: accepted_fail chains kept for ecosystem monitoring.
    """
    discovery = []
    truth_probe = []
    monitoring_only = []
    for chain, s in per_chain.items():
        rk = s.get("run_kind")
        if s.get("accepted_fail", False):
            monitoring_only.append(chain)
        elif rk == "NORMAL":
            truth_probe.append(chain)
        else:
            discovery.append(chain)
    return {
        "discovery_chains": sorted(discovery),
        "truth_probe_chains": sorted(truth_probe),
        "monitoring_only_chains": sorted(monitoring_only),
        "total_chains": len(per_chain),
    }


def _compute_kpi_separation(per_chain: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """R28.10/R28.17: Three-tier signal classification per chain.

    Tiers (strictly ordered):
      diagnostic_signals       — raw spread signals (one-leg detection, may be mixed-source/noise)
      real_quote_signals       — roundtrips evaluated with real DEX quotes (real_quote_count > 0)
      executable_profitable    — profitable roundtrips with sane accounting AND real quotes
    """
    per_chain_kpi = {}
    totals = {"diagnostic_signals": 0, "real_quote_signals": 0, "executable_profitable": 0}
    for chain, s in per_chain.items():
        diagnostic = s.get("included_signals_total", 0)
        rq = s.get("real_quote_count_total", 0)
        profitable_rt = s.get("profitable_roundtrips_total", 0)
        sane = _roundtrip_accounting_is_sane(s)
        # real_quote_signals: roundtrips that used real quotes (regardless of profitability)
        real_quote_sig = rq
        # executable_profitable: profitable AND sane AND real-quote backed
        exec_profitable = profitable_rt if (sane and rq > 0) else 0
        per_chain_kpi[chain] = {
            "diagnostic_signals": diagnostic,
            "real_quote_signals": real_quote_sig,
            "executable_profitable": exec_profitable,
            "accounting_sane": sane,
            "real_quote_count": rq,
        }
        totals["diagnostic_signals"] += diagnostic
        totals["real_quote_signals"] += real_quote_sig
        totals["executable_profitable"] += exec_profitable
    return {"totals": totals, "per_chain": per_chain_kpi}


def _compute_profit_truth_summary(per_chain: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """R28.10/R28.17: Summarize chain profit state across all chains.

    Groups chains by their profit state for operator visibility.
    Includes SUSPECT_ACCOUNTING group for contaminated chains.
    """
    groups: dict[str, list[str]] = {}
    for chain, s in per_chain.items():
        state = s.get("chain_profit_state", "PROBE_ONLY")
        groups.setdefault(state, []).append(chain)

    # Promotion eligibility: only CONFIRMED_POSITIVE_CONTROL chains are promotion-ready
    # THIN_POSITIVE needs more evidence (real_quote_count >= 2)
    promotion_eligible = sorted(groups.get("CONFIRMED_POSITIVE_CONTROL", []))
    primary_blockers = sorted(groups.get("PRIMARY_BLOCKER", []))
    thin_positive = sorted(groups.get("THIN_POSITIVE", []))
    suspect_accounting = sorted(groups.get("SUSPECT_ACCOUNTING", []))

    return {
        "chain_states": {state: sorted(chains) for state, chains in groups.items()},
        "promotion_eligible": promotion_eligible,
        "primary_blockers": primary_blockers,
        "thin_positive_needs_evidence": thin_positive,
        "suspect_accounting": suspect_accounting,
    }


def _compute_frontier_ranking(per_chain: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank chains by composite frontier score (R12→R22: robust multi-metric selection).

    Sort order (ascending tuple):
      1. accepted_fail (False < True — non-accepted first)
      2. median_gap_to_zero_bps (lower = more consistent near-breakeven)
      3. gap_to_zero_bps (best - lower = closer tail-case)
      4. drift_rejection_rate_median (R22: lower drift = more reliable signals)
      5. -runs_with_sweep (more data = higher confidence)
      6. -included_signals_total (more signals = better coverage)
      7. -cross_dex_pairs_count (more venues = more opportunity)

    This ensures top-2 candidate selection is robust, not based on one lucky run.
    gap_to_zero_bps is a WARN / frontier KPI only, NOT a hard pass/fail gate.
    """
    ranked = []
    for chain, s in per_chain.items():
        gap = s.get("sweep_gap_to_zero_bps")
        pnl = s.get("sweep_best_net_pnl_bps")
        signals = s.get("included_signals_total", 0)
        xdex = s.get("last_cross_dex_pairs_count") or 0
        is_af = s.get("accepted_fail", False)
        runs_sweep = s.get("runs_with_sweep", 0)
        gap_values = s.get("_sweep_gap_values", [])
        median_gap = _compute_median(gap_values)
        if pnl is None and signals == 0:
            continue
        # R21: Per-chain drift aggregates
        drift_rates = s.get("_drift_rejection_rates", [])
        drift_bps_vals = s.get("_drift_median_bps_values", [])
        drift_rate_median = _compute_median(drift_rates)
        drift_bps_median = _compute_median(drift_bps_vals)
        # R26: Derive triage status from chain metrics
        chain_status = s.get("last_run_summary_status")
        chain_quality = s.get("last_chain_quality_level")
        blocker_cls = s.get("blocker_classification")
        blocker_rsn = s.get("blocker_reason")
        # route_health: ratio of pass runs to total runs (None if no runs)
        total_runs = s.get("runs", 0)
        pass_runs = s.get("pass", 0)
        route_health = round(pass_runs / total_runs, 4) if total_runs > 0 else None

        ranked.append({
            "chain": chain,
            "gap_to_zero_bps": gap,
            "median_gap_to_zero_bps": round(median_gap, 4) if median_gap is not None else None,
            "runs_with_sweep": runs_sweep,
            "sweep_best_net_pnl_bps": pnl,
            "sweep_best_size_usd": s.get("sweep_best_size_usd"),
            "frontier_pair": s.get("sweep_best_pair"),
            "measured_gas_bps": s.get("sweep_measured_gas_bps"),
            "measured_fee_bps": s.get("sweep_measured_fee_bps"),
            "measured_slippage_bps": s.get("sweep_measured_slippage_bps"),
            "measured_total_cost_bps": s.get("sweep_measured_total_cost_bps"),
            "included_signals_total": signals,
            "cross_dex_pairs_count": xdex,
            "accepted_fail": is_af,
            "frontier_ready": gap is not None and gap < 30 and not is_af,
            # R21: Per-chain drift summary in frontier ranking
            "drift_rejection_rate_median": round(drift_rate_median, 4) if drift_rate_median is not None else None,
            "notional_drift_median_bps": round(drift_bps_median, 1) if drift_bps_median is not None else None,
            "drift_excluded_total": s.get("drift_excluded_total", 0),
            "drift_pairs_with_data_total": s.get("drift_pairs_with_data_total", 0),
            # R22: Worst drift pair for operator analysis
            "drift_worst_pair": s.get("drift_worst_pair"),
            "drift_worst_pair_bps": s.get("drift_worst_pair_bps"),
            # R24: Discovery runtime coverage (latest snapshot)
            "discovery_coverage": s.get("last_discovery_runtime"),
            # R26: Triage fields for promotion decisions
            "status": chain_status,
            "route_health": route_health,
            "chain_quality_level": chain_quality,
            "blocker_classification": blocker_cls,
            "blocker_reason": blocker_rsn,
            # R28.10: Chain profit state and promotion eligibility
            "chain_profit_state": s.get("chain_profit_state"),
            "promotion_eligible": s.get("chain_profit_state") == "CONFIRMED_POSITIVE_CONTROL",
            # R28.13: Truth KPIs surfaced in frontier ranking (Step 5)
            "real_quote_count": s.get("real_quote_count_total", 0),
            "profitable_roundtrips": s.get("profitable_roundtrips_total", 0),
            "best_net_pnl_bps": s.get("best_roundtrip_net_bps"),
        })
    ranked.sort(key=lambda x: (
        x.get("accepted_fail", False),
        x.get("median_gap_to_zero_bps") if x.get("median_gap_to_zero_bps") is not None else 9999,
        x.get("gap_to_zero_bps") if x.get("gap_to_zero_bps") is not None else 9999,
        # R22: drift as secondary factor — lower drift = more reliable signal
        x.get("drift_rejection_rate_median") if x.get("drift_rejection_rate_median") is not None else 9999,
        -(x.get("runs_with_sweep", 0)),
        -(x.get("included_signals_total", 0)),
        -(x.get("cross_dex_pairs_count", 0)),
    ))
    # Annotate with rank, truth-probe target, and candidate score
    truth_probe_count = 0
    total_ranked = len(ranked)
    for i, entry in enumerate(ranked):
        entry["frontier_rank"] = i + 1
        # candidate_score: higher is better (inverse of rank normalized to 0-100)
        entry["candidate_score"] = round(100.0 * (total_ranked - i) / max(total_ranked, 1), 2)
        if not entry.get("accepted_fail", False) and truth_probe_count < 2:
            entry["target_for_truth_probe"] = True
            truth_probe_count += 1
        else:
            entry["target_for_truth_probe"] = False
    return ranked


def print_summary(summary: dict[str, Any]) -> None:
    print("\n" + "=" * 70)
    print("MULTI-CHAIN LONG SCAN SUMMARY")
    print("=" * 70)
    print(f"Wall time:      {summary['wall_seconds']:.0f}s")
    print(
        f"Total runs:     {summary['total_runs']}  "
        f"(PASS={summary['total_pass']}  NO_DATA={summary['total_no_data']}  "
        f"FAIL={summary['total_fail']}  INFRA_FAIL={summary['total_infra_fail']})"
    )
    print(f"Signals total:  {summary['total_included_signals']}")
    print(f"Net USDC total: ${summary['total_net_usdc']:.4f}")
    best_bps = summary.get('best_roundtrip_net_bps')
    best_str = f"{best_bps:+.2f} bps" if best_bps is not None else "n/a"
    gap_bps = summary.get('best_measured_spread_gap_bps')
    gap_str = f"{gap_bps:+.2f} bps" if gap_bps is not None else "n/a"
    print(f"Profitable RTs: {summary.get('total_profitable_roundtrips', 0)}  (evaluated: {summary.get('total_roundtrip_evaluated', 0)}, best: {best_str})")
    print(f"Spread gap:     {gap_str}  (measured, target: >=0)")
    sw_bps = summary.get('sweep_best_net_pnl_bps')
    sw_size = summary.get('sweep_best_size_usd')
    if sw_bps is not None:
        print(f"Sweep best:     {sw_bps:+.2f} bps @ ${sw_size}")

    pass_c = summary.get("pass_chains", [])
    fail_c = summary.get("fail_chains", [])
    accepted_c = summary.get("accepted_fail_chains", [])
    unexpected_c = summary.get("unexpected_fail_chains", [])
    probe_c = summary.get("probe_only_chains", [])
    if pass_c:
        print(f"Pass chains:    {', '.join(pass_c)}")
    if unexpected_c:
        print(f"Fail chains:    {', '.join(unexpected_c)}")
    if accepted_c:
        print(f"Accepted fail:  {', '.join(accepted_c)}")
    if probe_c:
        print(f"Probe-only:     {', '.join(probe_c)}")

    print("\n--- Per-chain breakdown ---")
    for chain, s in summary["per_chain"].items():
        print(
            f"  {chain:16s}  runs={s['runs']}  "
            f"PASS={s['pass']}  NO_DATA={s['no_data']}  FAIL={s['fail']}  "
            f"INFRA_FAIL={s['infra_fail']}  signals={s['included_signals_total']}  "
            f"net_usdc=${s['net_usdc_total']:.4f}"
        )
        quality = s.get("last_quality_status") or "-"
        level = s.get("last_chain_quality_level") or "-"
        truth = s.get("last_profit_truth_available")
        truth_s = str(truth) if truth is not None else "-"
        xdex = s.get("last_cross_dex_pairs_count")
        xdex_s = str(xdex) if xdex is not None else "-"
        profit_state = s.get("chain_profit_state") or "-"
        rq = s.get("real_quote_count_total", 0)
        print(
            f"  {'':16s}  quality={quality}  level={level}  "
            f"truth={truth_s}  cross_dex={xdex_s}"
        )
        print(
            f"  {'':16s}  profit_state={profit_state}  "
            f"real_quotes={rq}  profitable_rt={s.get('profitable_roundtrips_total', 0)}"
        )

    if summary["warnings"]:
        print("\n--- WARNINGS ---")
        for w in summary["warnings"]:
            print(f"  [!] {w}")

    # R28.10: Profit truth summary
    pts = summary.get("profit_truth_summary", {})
    chain_states = pts.get("chain_states", {})
    if chain_states:
        print("\n--- Profit Truth Summary (R28.10) ---")
        for state, chains in sorted(chain_states.items()):
            print(f"  {state}: {', '.join(chains)}")
        promo = pts.get("promotion_eligible", [])
        if promo:
            print(f"  PROMOTION-ELIGIBLE: {', '.join(promo)}")
        blockers = pts.get("primary_blockers", [])
        if blockers:
            print(f"  PRIMARY-BLOCKERS:   {', '.join(blockers)}")
        suspect = pts.get("suspect_accounting", [])
        if suspect:
            print(f"  SUSPECT-ACCOUNTING: {', '.join(suspect)}")

    ranking = summary.get("frontier_ranking", [])
    if ranking:
        print("\n--- FRONTIER RANKING (R12: median + best + runs) ---")
        for i, r in enumerate(ranking):
            gap = r.get("gap_to_zero_bps")
            median_gap = r.get("median_gap_to_zero_bps")
            gap_s = f"{gap:.1f}" if gap is not None else "n/a"
            median_s = f"{median_gap:.1f}" if median_gap is not None else "n/a"
            pnl = r.get("sweep_best_net_pnl_bps") or 0
            runs_sw = r.get("runs_with_sweep", 0)
            sigs = r.get("included_signals_total", 0)
            xdex = r.get("cross_dex_pairs_count", 0)
            is_af = r.get("accepted_fail", False)
            ready = "READY" if r.get("frontier_ready") else "AF" if is_af else "-"
            probe = "PROBE" if r.get("target_for_truth_probe") else ""
            print(
                f"  #{i+1} {r['chain']:16s}  "
                f"median={median_s:>6s}  best={gap_s:>6s} bps  "
                f"pnl={pnl:+.1f} bps  runs={runs_sw}  "
                f"sig={sigs}  xdex={xdex}  {ready}  {probe}"
            )

    print("=" * 70)


def write_summary_file(summary: dict[str, Any], path: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    tmp.replace(out)
    print(f"Summary written to {out}")


# -- R28.13 Step 7: Per-pair micro-quote (in-process, no child) -----------


def _micro_requote_hot_pairs(
    pair_hot_queue: Any,
    config_meta: dict[str, dict[str, Any]],
    per_chain: dict[str, dict[str, Any]],
    stats_lock: threading.Lock,
) -> int:
    """Drain hot pairs and re-quote them in-process via collect_quotes.

    Returns the number of pairs successfully re-quoted.  This runs between
    Phase 1 (primary) and Phase 2 (coverage) to give dirty pairs an
    immediate update without waiting for the next full chain-run.
    """
    if not pair_hot_queue or pair_hot_queue.pending_count() == 0:
        return 0

    batch = pair_hot_queue.drain(max_items=30)
    if not batch:
        return 0

    # Group by chain: {chain: {pair_tags, block_number}}
    chain_groups: dict[str, dict[str, Any]] = {}
    for chain, tag, block in batch:
        g = chain_groups.setdefault(chain, {"pair_tags": set(), "block": 0})
        g["pair_tags"].add(tag)
        g["block"] = max(g["block"], block)

    total_requoted = 0

    for chain, group in chain_groups.items():
        pair_tags = group["pair_tags"]
        block = group["block"]

        # Get full pair dicts from PairHotQueue cache
        pair_dicts = pair_hot_queue.get_pair_dicts(chain, pair_tags)
        if not pair_dicts:
            continue

        # Find config file path for this chain
        chain_cfg_path = per_chain.get(chain, {}).get("config")
        if not chain_cfg_path:
            continue

        try:
            # Load full YAML config
            with open(chain_cfg_path, encoding="utf-8") as f:
                full_config = yaml.safe_load(f) or {}

            # Reconstruct PairConfig objects
            from config.pairs import PairConfig
            pair_configs = [PairConfig.from_dict(d) for d in pair_dicts]

            # In-process quote collection (no child process)
            from strategy.quotes import collect_quotes
            quotes, rejects, counts = collect_quotes(
                full_config,
                block,
                rpc_latency=0,
                pairs_list=pair_configs,
            )

            n_ok = counts.get("quotes_fetched", 0)
            n_rej = len(rejects)
            total_requoted += n_ok

            print(
                f"  [MICRO] {chain}: {len(pair_configs)} pairs @ block {block} → "
                f"{n_ok} quotes, {n_rej} rejected"
            )

            # Update per_chain stats for observability
            with stats_lock:
                cs = per_chain.get(chain, {})
                cs["micro_requote_count"] = cs.get("micro_requote_count", 0) + 1
                cs["micro_requote_quotes"] = cs.get("micro_requote_quotes", 0) + n_ok

        except Exception as e:
            print(f"  [MICRO] {chain}: ERROR {e}")

    return total_requoted


def write_hot_loop_snapshot(
    per_chain: dict[str, dict[str, Any]],
    dirty_tracker: Any,
    wall_start: float,
    summary_file: str = "",
    pair_hot_queue: Any = None,
    live_events: list[dict[str, Any]] | None = None,
    active_runs: dict[str, dict[str, Any]] | None = None,
    is_test_session: bool = False,
) -> None:
    """Write lightweight hot_loop_latest.json after each hot re-quote batch.

    R28.13: Schema v1.2 — added is_test_session marker for rolling protection.
    R28.17: is_test_session=True marks snapshot as test/diagnostic, not operational.
    """
    import time as _time
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot: dict[str, Any] = {
        "schema": "start:hot_loop_snapshot:v1.2",
        "generated_at": run_ts,
        "is_test_session": is_test_session,  # R28.17: rolling protection marker
        # R28.13 Step 4: run_context provenance (same shape as long_scan)
        "run_context": {
            "run_timestamp": run_ts,
            "code_identity": f"ts:{run_ts}",
            "code_sha": None,
            "evidence_sha": None,
        },
        "wall_seconds": round(_time.monotonic() - wall_start, 1),
        "full_sweep_interval": FULL_SWEEP_INTERVAL,
        "total_full_sweeps": sum(s.get("full_sweep_count", 0) for s in per_chain.values()),
        "total_hot_requotes": sum(s.get("hot_requote_count", 0) for s in per_chain.values()),
        "total_micro_requotes": sum(s.get("micro_requote_count", 0) for s in per_chain.values()),
        "total_runs": sum(s.get("runs", 0) for s in per_chain.values()),
        # R28.13 Step 3: Link to active long-scan session artifact
        "session_summary_file": summary_file or None,
        "per_chain": {},
    }
    for c, s in per_chain.items():
        entry: dict[str, Any] = {
            "last_scan_mode": s.get("last_scan_mode"),
            "full_sweeps": s.get("full_sweep_count", 0),
            "hot_requotes": s.get("hot_requote_count", 0),
            "runs": s.get("runs", 0),
            "pass": s.get("pass", 0),
            "fail": s.get("fail", 0) + s.get("infra_fail", 0),
            "last_current_block": s.get("last_current_block"),
            # R28.13 Step 5: Truth KPIs in hot snapshot (fast-refresh surface)
            "chain_profit_state": s.get("chain_profit_state"),
            "real_quote_count": s.get("real_quote_count_total", 0),
            "profitable_roundtrips": s.get("profitable_roundtrips_total", 0),
            "best_net_pnl_bps": s.get("best_roundtrip_net_bps"),
            "gap_to_zero_bps": s.get("sweep_gap_to_zero_bps"),
            # R28.13 Step 7: Micro-requote stats
            "micro_requotes": s.get("micro_requote_count", 0),
            "micro_requote_quotes": s.get("micro_requote_quotes", 0),
        }
        # Include latest top signals for live pair visibility
        top_sigs = s.get("last_top_spread_signals", [])
        if top_sigs:
            entry["top_signals"] = top_sigs[:5]
        snapshot["per_chain"][c] = entry
    # Dirty-set status
    if dirty_tracker:
        try:
            snapshot["dirty_set"] = dirty_tracker.status()
        except Exception:
            pass

    # R28.13 Step 7: Per-pair hot queue status
    if pair_hot_queue:
        try:
            snapshot["pair_hot_queue"] = pair_hot_queue.status()
        except Exception:
            pass

    pq_pending = 0
    if pair_hot_queue:
        try:
            pq_pending = pair_hot_queue.pending_count()
        except Exception:
            pass

    snapshot["live_stream"] = _serialize_live_stream(active_runs, live_events, pq_pending)

    HOT_LOOP_LATEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = HOT_LOOP_LATEST.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, default=str)
    # Atomic replace with Windows PermissionError resilience:
    # If the dashboard (or another reader) has the file open, Path.replace()
    # can fail on Windows.  Retry once after a short pause, then fall back to
    # a non-atomic overwrite so the scanner loop is never blocked.
    try:
        tmp.replace(HOT_LOOP_LATEST)
    except PermissionError:
        import time as _t2
        _t2.sleep(0.05)
        try:
            tmp.replace(HOT_LOOP_LATEST)
        except PermissionError:
            # Non-atomic fallback: write directly (reader may see partial)
            try:
                with open(HOT_LOOP_LATEST, "w", encoding="utf-8") as f2:
                    json.dump(snapshot, f2, indent=2, default=str)
                tmp.unlink(missing_ok=True)
            except Exception:
                pass  # Snapshot is best-effort; never block the scan loop


def _serialize_live_stream(
    active_runs: dict[str, dict[str, Any]] | None,
    live_events: list[dict[str, Any]] | None,
    pair_hot_queue_pending: int = 0,
) -> dict[str, Any]:
    """Build bounded live stream payload for dashboard fast-refresh."""
    now = time.monotonic()
    active_list: list[dict[str, Any]] = []
    for chain, item in sorted((active_runs or {}).items()):
        entry = {k: v for k, v in item.items() if not k.startswith("_")}
        started = item.get("_started_monotonic")
        if started is not None:
            entry["elapsed_seconds"] = round(max(0.0, now - float(started)), 1)
        active_list.append(entry)
    events = list(live_events or [])
    return {
        "active_count": len(active_list),
        "active_runs": active_list,
        "recent_events": list(reversed(events[-20:])),
        "pair_hot_queue_pending": pair_hot_queue_pending,
    }


# -- main -----------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Multi-chain time-bounded online scan orchestrator"
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--config",
        help="Single config file (legacy mode, equivalent to --config-list with one entry)",
    )
    g.add_argument(
        "--config-list",
        help="Comma-separated list of config files for round-robin scanning",
    )
    ap.add_argument("--hours", type=float, default=0, help="Time limit in hours (takes precedence over --minutes)")
    ap.add_argument("--minutes", type=int, default=120, help="Time limit in minutes (ignored if --hours set)")
    ap.add_argument("--max-runs", type=int, default=0, help="0 = unlimited within time window")
    ap.add_argument("--sleep-seconds", type=int, default=1)
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--prune-keep", type=int, default=200)
    ap.add_argument(
        "--child-timeout",
        type=int,
        default=600,
        help="Kill child process after this many seconds (0=no timeout)",
    )
    ap.add_argument(
        "--summary-file",
        default="data/runs/_rolling/long_scan_latest.json",
        help="Path to overwrite with session summary JSON (canonical rolling artifact)",
    )
    ap.add_argument(
        "--max-fail-chains",
        type=int,
        default=-1,
        help="Max chains allowed to have failures. -1=permissive (exit 0 if any PASS), "
             "0=strict (all must PASS)",
    )
    ap.add_argument(
        "--accepted-fail-chains",
        default="",
        help="Comma-separated chain names whose failures are expected/accepted "
             "(e.g. 'scroll'). These do not count toward --max-fail-chains.",
    )
    ap.add_argument(
        "--coverage-workers",
        type=int,
        default=2,
        help="Max parallel COVERAGE chain workers (default: 2). "
             "Primary NORMAL chains always run sequentially first.",
    )
    ap.add_argument(
        "--no-dashboard",
        action="store_true",
        default=False,
        help="Disable the dashboard server (dashboard is launched by default)",
    )
    ap.add_argument(
        "--dashboard",
        action="store_true",
        default=False,
        help="(deprecated, now default-on) Kept for backward compatibility",
    )
    ap.add_argument(
        "--dashboard-port",
        type=int,
        default=8099,
        help="Port for the dashboard server (default: 8099)",
    )
    ap.add_argument(
        "--keep-dashboard",
        action="store_true",
        default=False,
        help="Keep dashboard server running after scan completes (default: terminate with scan)",
    )
    return ap.parse_args(argv)


def resolve_configs(args: argparse.Namespace) -> list[str]:
    if args.config:
        return [args.config]
    return [c.strip() for c in args.config_list.split(",") if c.strip()]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configs = resolve_configs(args)
    if not configs:
        print("ERROR: No config files specified")
        return 1

    # Co-launch dashboard server (default-on; use --no-dashboard to disable)
    dashboard_proc: subprocess.Popen | None = None
    if not args.no_dashboard:
        dashboard_proc = subprocess.Popen(
            [sys.executable, "-m", "monitoring.dashboard_server", "--port", str(args.dashboard_port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"Dashboard launched: http://127.0.0.1:{args.dashboard_port}")

    try:
        return _run_scan_loop(args, configs)
    finally:
        if dashboard_proc is not None:
            if args.keep_dashboard:
                print(f"Dashboard server kept alive (PID {dashboard_proc.pid}): http://127.0.0.1:{args.dashboard_port}")
            else:
                dashboard_proc.terminate()
                dashboard_proc.wait(timeout=5)
                print("Dashboard server stopped.")


def _warn_missing_chains(config_meta: dict[str, dict[str, Any]]) -> None:
    """R24→R25: Hard-fail if any chain from chains.yaml is not represented in config-list.

    Prevents silent coverage gaps where a chain is defined but has no config in the scan.
    """
    chains_yaml = Path("config") / "chains.yaml"
    if not chains_yaml.exists():
        return
    try:
        with open(chains_yaml, encoding="utf-8") as f:
            all_chains = set(yaml.safe_load(f) or {})
    except Exception:
        return
    config_chains = {meta["chain"] for meta in config_meta.values()}
    missing = sorted(all_chains - config_chains)
    if missing:
        print(f"  FATAL: chains.yaml defines {sorted(all_chains)} but config-list covers only {sorted(config_chains)}")
        print(f"  FATAL: missing chains: {missing}")
        print(f"  Add configs for missing chains or remove them from chains.yaml.")
        sys.exit(1)


def _run_scan_loop(args: argparse.Namespace, configs: list[str]) -> int:

    # Pre-read config metadata
    config_meta: dict[str, dict[str, Any]] = {}
    for cfg in configs:
        meta = read_config_meta(cfg)
        config_meta[cfg] = meta
        rolling = "YES" if is_primary_rolling_config(meta) else "no"
        print(f"  [{meta['chain']:16s}] {cfg}  run_kind={meta['run_kind']}  rolling={rolling}")

    # R24: Check config-list coverage against chains.yaml
    _warn_missing_chains(config_meta)

    # R28.5: Separate primary (NORMAL) and coverage configs
    primary_configs = [cfg for cfg in configs if is_primary_rolling_config(config_meta[cfg])]
    coverage_configs = [cfg for cfg in configs if not is_primary_rolling_config(config_meta[cfg])]
    coverage_workers = max(1, args.coverage_workers)
    print(f"  Primary configs: {len(primary_configs)}  Coverage configs: {len(coverage_configs)}  workers={coverage_workers}")

    # Time budget
    if args.hours > 0:
        budget_seconds = args.hours * 3600
    else:
        budget_seconds = max(1, args.minutes) * 60
    deadline = time.monotonic() + budget_seconds

    # Accepted-fail chain set
    accepted_fail_set = {
        c.strip() for c in args.accepted_fail_chains.split(",") if c.strip()
    }

    # Per-chain stats keyed by chain name
    per_chain: dict[str, dict[str, Any]] = {}
    for cfg in configs:
        chain = config_meta[cfg]["chain"]
        if chain not in per_chain:
            per_chain[chain] = new_chain_stats()
            per_chain[chain]["config"] = cfg
            per_chain[chain]["accepted_fail"] = chain in accepted_fail_set
            per_chain[chain]["blocker_classification"] = config_meta[cfg].get("blocker_classification")
            per_chain[chain]["blocker_reason"] = config_meta[cfg].get("blocker_reason")

    total_runs = 0
    empty_deleted = 0
    wall_start = time.monotonic()

    # R28.11: WebSocket dirty-set tracker — only re-scan chains with new blocks
    dirty_tracker: Any = None
    try:
        from strategy.infra import DirtySetTracker
        chains_yaml = Path("config") / "chains.yaml"
        _chain_ws: dict[str, str | None] = {}
        if chains_yaml.exists():
            with open(chains_yaml, encoding="utf-8") as _cyf:
                _cy = yaml.safe_load(_cyf) or {}
            for _cn, _cd in _cy.items():
                ws_eps = _cd.get("ws_endpoints") or []
                _chain_ws[_cn] = ws_eps[0] if ws_eps else None
        dirty_tracker = DirtySetTracker()
        for chain in per_chain:
            dirty_tracker.start_watching(chain, _chain_ws.get(chain))
        print(f"  DirtySet: watching {len(per_chain)} chains ({sum(1 for v in _chain_ws.values() if v)} have WSS)")
    except Exception as _ds_err:
        print(f"  DirtySet: disabled ({_ds_err})")
        dirty_tracker = None

    # R28.13 Step 7: Per-pair hot queue — load cached pairs for immediate re-quote
    pair_hot_queue: Any = None
    try:
        from strategy.infra import PairHotQueue
        pair_hot_queue = PairHotQueue()
        for chain in per_chain:
            hp_file = HOT_PAIRS_CACHE_DIR / f"hot_pairs_{chain}.json"
            if hp_file.is_file():
                with open(hp_file, encoding="utf-8") as _hpf:
                    hp_data = json.load(_hpf)
                pair_hot_queue.load_pairs_for_chain(chain, hp_data.get("pairs", []))
        pq_status = pair_hot_queue.status()
        print(f"  PairHotQueue: {pq_status['chains_loaded']} chains, {pq_status['total_pairs_loaded']} pairs loaded")
    except Exception as _pq_err:
        print(f"  PairHotQueue: disabled ({_pq_err})")
        pair_hot_queue = None

    # R28.5: Thread-safe lock for per_chain stats and stdout
    _stats_lock = threading.Lock()
    _live_lock = threading.Lock()
    _hot_snapshot_lock = threading.Lock()
    _live_events: deque[dict[str, Any]] = deque(maxlen=LIVE_STREAM_MAX_EVENTS)
    _active_runs: dict[str, dict[str, Any]] = {}

    def _append_live_event(
        event: str,
        *,
        chain: str | None = None,
        message: str | None = None,
        **extra: Any,
    ) -> None:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event": event,
        }
        if chain:
            entry["chain"] = chain
        if message:
            entry["message"] = message
        for key, value in extra.items():
            if value is not None:
                entry[key] = value
        with _live_lock:
            _live_events.append(entry)

    def _set_active_run(
        chain: str,
        *,
        config: str,
        run_kind: str,
        scan_mode: str,
        is_coverage: bool,
        rolling: bool,
        block_number: int | None = None,
    ) -> None:
        with _live_lock:
            _active_runs[chain] = {
                "chain": chain,
                "config": config,
                "run_kind": run_kind,
                "scan_mode": scan_mode,
                "is_coverage": is_coverage,
                "rolling": rolling,
                "block_number": block_number,
                "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "_started_monotonic": time.monotonic(),
            }

    def _clear_active_run(chain: str) -> None:
        with _live_lock:
            _active_runs.pop(chain, None)

    # R28.17: Detect test-like session to protect rolling artifacts
    _is_test_session = os.environ.get("ARBY_OFFLINE", "") == "1"

    def _write_hot_snapshot() -> None:
        with _live_lock:
            live_events = list(_live_events)
            active_runs = {k: dict(v) for k, v in _active_runs.items()}
        with _hot_snapshot_lock:
            write_hot_loop_snapshot(
                per_chain,
                dirty_tracker,
                wall_start,
                args.summary_file,
                pair_hot_queue,
                live_events=live_events,
                active_runs=active_runs,
                is_test_session=_is_test_session,
            )

    _append_live_event(
        "session_started",
        message="Multi-chain scan session started",
        config_count=len(configs),
        coverage_workers=args.coverage_workers,
        full_sweep_interval=FULL_SWEEP_INTERVAL,
    )
    _write_hot_snapshot()

    def _run_one_chain(cfg: str, is_coverage: bool = False) -> tuple[int, Path | None, str, str]:
        """Run a single chain scan. Thread-safe for parallel coverage workers."""
        meta = config_meta[cfg]
        chain = meta["chain"]
        expected_chain_id = meta.get("chain_id")
        refresh = is_primary_rolling_config(meta)
        # R28.9: Prefix coverage worker output for log readability
        prefix = f"[{chain}]" if is_coverage else ""

        # R28.11: Hot loop — decide scan mode (full sweep vs hot re-quote)
        extra_env: dict[str, str] | None = None
        scan_mode = "full"
        with _stats_lock:
            chain_stats = per_chain[chain]
            run_count = chain_stats["_run_counter"]
            chain_stats["_run_counter"] = run_count + 1

        # Hot re-quote: skip discovery on non-full-sweep cycles if cache exists
        if run_count > 0 and run_count % FULL_SWEEP_INTERVAL != 0:
            hot_file = HOT_PAIRS_CACHE_DIR / f"hot_pairs_{chain}.json"
            if hot_file.is_file():
                extra_env = {"ARBY_HOT_PAIRS_FILE": str(hot_file)}
                scan_mode = "hot"

        # R28.12: Pass WS-observed block number to child so it skips getBlockNumber RPC
        if dirty_tracker:
            evt = dirty_tracker.drain_event(chain)
            if evt and evt.get("block_number"):
                extra_env = extra_env or {}
                extra_env["ARBY_WS_BLOCK_NUMBER"] = str(evt["block_number"])
                # R28.13 Step 7: Enqueue hot pairs for this block
                if pair_hot_queue:
                    pair_hot_queue.enqueue_chain(chain, evt["block_number"])

        block_number = None
        if extra_env:
            try:
                block_number = int(extra_env.get("ARBY_WS_BLOCK_NUMBER")) if extra_env.get("ARBY_WS_BLOCK_NUMBER") else None
            except Exception:
                block_number = None

        _set_active_run(
            chain,
            config=cfg,
            run_kind=meta["run_kind"],
            scan_mode=scan_mode,
            is_coverage=is_coverage,
            rolling=refresh,
            block_number=block_number,
        )
        _append_live_event(
            "scan_started",
            chain=chain,
            message=f"{scan_mode.upper()} scan started",
            config=cfg,
            run_kind=meta["run_kind"],
            scan_mode=scan_mode,
            is_coverage=is_coverage,
            rolling=refresh,
            block_number=block_number,
        )
        _write_hot_snapshot()

        try:
            # R28.16: Phase callback — pipe child phase events into live stream
            def _on_phase(phase_data: dict) -> None:
                evt = phase_data.get("event", "phase_unknown")
                _append_live_event(
                    f"phase:{evt}",
                    chain=chain,
                    scan_mode=scan_mode,
                    message=f"{evt.replace('_', ' ').title()}",
                    **{k: v for k, v in phase_data.items() if k != "event" and k != "chain"},
                )
                _write_hot_snapshot()

            rc, run_dir = run_gate_once(
                cfg, args.cycles, args.prune_keep, args.sleep_seconds,
                refresh_rolling=refresh,
                timeout_seconds=args.child_timeout,
                line_prefix=prefix,
                extra_env=extra_env,
                phase_callback=_on_phase,
            )

            summary = extract_run_summary(run_dir)
            gate_res = extract_gate_result(run_dir)
            scan_st = extract_scan_stats(run_dir)
            truth = extract_truth_report(run_dir)

            # R28.6: Validate scan artifact chain_id matches config chain
            # Prevents corrupted summary from runDir collisions
            if run_dir and expected_chain_id is not None:
                _validate_chain_id_match(run_dir, expected_chain_id, chain)

            cls = classify_run(rc, summary)

            with _stats_lock:
                update_chain_stats(per_chain[chain], rc, run_dir, summary, gate_res, scan_st, truth)
                # R28.11: Track scan mode for observability
                per_chain[chain]["last_scan_mode"] = scan_mode
                if scan_mode == "hot":
                    per_chain[chain]["hot_requote_count"] += 1
                else:
                    per_chain[chain]["full_sweep_count"] += 1
                if run_dir and run_dir.exists():
                    if delete_if_empty_run_dir(run_dir):
                        pass  # cleaned up

            rt = (summary or {}).get("metrics", {}).get("roundtrip", {}) or (summary or {}).get("roundtrip_summary", {})
            _clear_active_run(chain)
            _append_live_event(
                "scan_finished",
                chain=chain,
                message=f"{scan_mode.upper()} scan finished: {cls}",
                config=cfg,
                run_kind=meta["run_kind"],
                scan_mode=scan_mode,
                is_coverage=is_coverage,
                rolling=refresh,
                result=cls,
                exit_code=rc,
                run_dir=run_dir.name if run_dir else None,
                signals=(summary or {}).get("metrics", {}).get("included_signals_count"),
                real_quote_count=rt.get("real_quote_count"),
                profitable_roundtrips=rt.get("profitable_count"),
                profit_realism_status=(summary or {}).get("metrics", {}).get("profit_realism_status"),
            )
            _write_hot_snapshot()

            return rc, run_dir, chain, cls
        except Exception as exc:
            _clear_active_run(chain)
            _append_live_event(
                "scan_error",
                chain=chain,
                message=f"{scan_mode.upper()} scan errored",
                config=cfg,
                run_kind=meta["run_kind"],
                scan_mode=scan_mode,
                is_coverage=is_coverage,
                rolling=refresh,
                error=str(exc),
            )
            _write_hot_snapshot()
            raise

    print(f"\nStarting multi-chain scan: {len(configs)} configs, budget={budget_seconds:.0f}s")

    # R28.5: Batched round — primary sequential, then coverage parallel
    while time.monotonic() < deadline:
        # Phase 1: Run primary (NORMAL) configs sequentially (isolated, rolling-safe)
        # R28.12: Use pending_chains() for priority ordering (earliest-dirty first)
        if dirty_tracker:
            _pending = set(dirty_tracker.pending_chains())
            _ordered_primary = sorted(
                primary_configs,
                key=lambda c: (config_meta[c]["chain"] not in _pending, 0),
            )
        else:
            _ordered_primary = primary_configs

        for cfg in _ordered_primary:
            if time.monotonic() >= deadline:
                break
            chain = config_meta[cfg]["chain"]

            # R28.11: Skip chain if no new block since last scan (dirty-set gate)
            if dirty_tracker and not dirty_tracker.is_dirty(chain):
                continue

            total_runs += 1
            _sm = per_chain.get(chain, {}).get("last_scan_mode", "full")
            print(f"\n{'-'*60}")
            print(f"[run {total_runs}] chain={chain}  config={cfg}  rolling=YES  mode={_sm}  (PRIMARY)")

            rc, run_dir, chain_name, cls = _run_one_chain(cfg)
            _sm = per_chain.get(chain, {}).get("last_scan_mode", "full")
            print(f"[run {total_runs}] result={cls}  exit_code={rc}  mode={_sm}  run_dir={run_dir.name if run_dir else 'N/A'}")

            # R28.11: Mark chain clean after scan (wait for next block)
            if dirty_tracker:
                dirty_tracker.mark_clean(chain)

            # Live update summary for dashboard
            interim_wall = time.monotonic() - wall_start
            interim_warnings = check_guardrails(per_chain)
            interim_summary = build_summary(per_chain, interim_wall, interim_warnings)
            write_summary_file(interim_summary, args.summary_file)

            # R28.12: Write lightweight hot snapshot for fast dashboard refresh
            _write_hot_snapshot()

        # R28.13 Step 7: Per-pair micro-quote — drain dirty pairs, re-quote in-process
        if pair_hot_queue and pair_hot_queue.pending_count() > 0 and time.monotonic() < deadline:
            pending_pairs = pair_hot_queue.pending_count()
            _append_live_event(
                "micro_requote_started",
                message="In-process micro re-quote batch started",
                pending_pairs=pending_pairs,
            )
            _write_hot_snapshot()
            total_micro_quotes = _micro_requote_hot_pairs(pair_hot_queue, config_meta, per_chain, _stats_lock)
            _append_live_event(
                "micro_requote_finished",
                message="In-process micro re-quote batch finished",
                pending_pairs=pending_pairs,
                quoted_pairs=total_micro_quotes,
            )
            _write_hot_snapshot()

        if time.monotonic() >= deadline:
            break

        # Phase 2: Run coverage configs in bounded parallel pool
        if coverage_configs:
            # R28.12: Use pending_chains() for priority filtering
            if dirty_tracker:
                _pending_cov = set(dirty_tracker.pending_chains())
                batch_cfgs = [
                    cfg for cfg in coverage_configs
                    if time.monotonic() < deadline
                    and config_meta[cfg]["chain"] in _pending_cov
                ]
            else:
                batch_cfgs = [
                    cfg for cfg in coverage_configs
                    if time.monotonic() < deadline
                ]
            if batch_cfgs:
                print(f"\n{'-'*60}")
                print(f"[COVERAGE BATCH] {len(batch_cfgs)} chains, workers={coverage_workers}")
                _append_live_event(
                    "coverage_batch_started",
                    message="Coverage batch started",
                    chains=[config_meta[c]["chain"] for c in batch_cfgs],
                    workers=coverage_workers,
                )

                with ThreadPoolExecutor(max_workers=coverage_workers) as pool:
                    futures = {pool.submit(_run_one_chain, cfg, True): cfg for cfg in batch_cfgs}
                    _write_hot_snapshot()
                    for future in as_completed(futures):
                        cfg = futures[future]
                        total_runs += 1
                        try:
                            rc, run_dir, chain_name, cls = future.result()
                            print(f"[run {total_runs}] chain={chain_name}  result={cls}  exit_code={rc}  run_dir={run_dir.name if run_dir else 'N/A'}  (COVERAGE)")
                            # R28.11: Mark chain clean after coverage scan
                            if dirty_tracker:
                                dirty_tracker.mark_clean(chain_name)
                        except Exception as e:
                            print(f"[run {total_runs}] COVERAGE_ERROR: {cfg}: {e}")

                        # R28.9: Write summary after each coverage future for live dashboard
                        interim_wall = time.monotonic() - wall_start
                        interim_warnings = check_guardrails(per_chain)
                        interim_summary = build_summary(per_chain, interim_wall, interim_warnings)
                        write_summary_file(interim_summary, args.summary_file)
                        _write_hot_snapshot()

                # R28.12: Hot loop snapshot after coverage batch
                _append_live_event(
                    "coverage_batch_finished",
                    message="Coverage batch finished",
                    chains=[config_meta[c]["chain"] for c in batch_cfgs],
                    workers=coverage_workers,
                )
                _write_hot_snapshot()

        if total_runs % max(len(configs), 3) == 0:
            prune_run_dirs(args.prune_keep)

        if args.max_runs > 0 and total_runs >= args.max_runs:
            break
        if time.monotonic() >= deadline:
            break

        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    # Final report
    # R28.11: Stop dirty-set watcher threads
    if dirty_tracker:
        dirty_tracker.stop()

    wall_seconds = time.monotonic() - wall_start
    warnings = check_guardrails(per_chain)
    summary_obj = build_summary(per_chain, wall_seconds, warnings)
    print_summary(summary_obj)

    write_summary_file(summary_obj, args.summary_file)
    _append_live_event(
        "session_finished",
        message="Multi-chain scan session finished",
        total_runs=summary_obj.get("total_runs"),
        total_signals=summary_obj.get("total_included_signals"),
        total_profitable_roundtrips=summary_obj.get("total_profitable_roundtrips"),
        wall_seconds=summary_obj.get("wall_seconds"),
    )
    _write_hot_snapshot()

    # Exit semantics — accepted-fail chains don't count toward limit
    unexpected_fail_count = len(summary_obj.get("unexpected_fail_chains", []))
    has_any_pass = summary_obj["total_pass"] > 0

    if args.max_fail_chains >= 0:
        # Strict mode: exit 1 if too many unexpected chains failed
        if unexpected_fail_count > args.max_fail_chains:
            print(f"EXIT 1: {unexpected_fail_count} unexpected fail chain(s) > --max-fail-chains={args.max_fail_chains}")
            return 1
        if not has_any_pass:
            print("EXIT 1: no PASS runs at all")
            return 1
        return 0
    else:
        # Permissive (default): exit 0 if any PASS
        return 0 if has_any_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
