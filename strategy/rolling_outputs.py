"""
strategy/rolling_outputs.py - Rolling output writers and console summary.

Extracted from start.py (R33). Handles writing long_scan_latest.json,
hot_loop_latest.json, console summary printing, and micro-requote logic.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

HOT_LOOP_LATEST = Path("data") / "runs" / "_rolling" / "hot_loop_latest.json"
FULL_SWEEP_INTERVAL = 5
LIVE_STREAM_MAX_EVENTS = 80


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


def _micro_requote_hot_pairs(
    pair_hot_queue: Any,
    config_meta: dict[str, dict[str, Any]],
    per_chain: dict[str, dict[str, Any]],
    stats_lock: threading.Lock,
) -> int:
    """Drain hot pairs and re-quote them in-process via collect_quotes.

    Returns the number of pairs successfully re-quoted.
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
    output_path: Path | None = None,
) -> None:
    """Write lightweight hot_loop_latest.json after each hot re-quote batch."""
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot: dict[str, Any] = {
        "schema": "start:hot_loop_snapshot:v1.3",
        "generated_at": run_ts,
        "is_test_session": is_test_session,
        "run_context": {
            "run_timestamp": run_ts,
            "code_identity": f"ts:{run_ts}",
            "code_sha": None,
            "evidence_sha": None,
        },
        "wall_seconds": round(time.monotonic() - wall_start, 1),
        "full_sweep_interval": FULL_SWEEP_INTERVAL,
        "total_full_sweeps": sum(s.get("full_sweep_count", 0) for s in per_chain.values()),
        "total_hot_requotes": sum(s.get("hot_requote_count", 0) for s in per_chain.values()),
        "total_micro_requotes": sum(s.get("micro_requote_count", 0) for s in per_chain.values()),
        "total_runs": sum(s.get("runs", 0) for s in per_chain.values()),
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
            "chain_profit_state": s.get("chain_profit_state"),
            "real_quote_count": s.get("real_quote_count_total", 0),
            "profitable_roundtrips": s.get("profitable_roundtrips_total", 0),
            "best_net_pnl_bps": s.get("best_roundtrip_net_bps"),
            "gap_to_zero_bps": s.get("sweep_gap_to_zero_bps"),
            "micro_requotes": s.get("micro_requote_count", 0),
            "micro_requote_quotes": s.get("micro_requote_quotes", 0),
            "last_full_refresh_utc": s.get("last_full_refresh_utc"),
            "last_hot_requote_utc": s.get("last_hot_requote_utc"),
            "pools_from_cache": s.get("last_pools_from_cache"),
            "pools_from_rpc": s.get("last_pools_from_rpc"),
        }
        # Include latest top signals for live pair visibility
        top_sigs = s.get("last_top_spread_signals", [])
        if top_sigs:
            entry["top_signals"] = top_sigs[:5]
        live_candidates = s.get("last_live_candidates", [])
        if live_candidates:
            entry["live_candidates"] = live_candidates[:5]
        snapshot["per_chain"][c] = entry
    # Dirty-set status
    if dirty_tracker:
        try:
            snapshot["dirty_set"] = dirty_tracker.status()
        except Exception:
            pass

    # Per-pair hot queue status
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

    snapshot["live_stream"] = _serialize_live_stream(
        active_runs, live_events, pq_pending, per_chain=per_chain
    )

    # R34: When is_test_session=True and no explicit output_path, skip writing
    # to the canonical rolling file to prevent test runs from overwriting
    # production hot_loop_latest.json.
    if is_test_session and output_path is None:
        return

    # Use output_path if provided, else default to HOT_LOOP_LATEST
    target_path = output_path if output_path is not None else HOT_LOOP_LATEST
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = target_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, default=str)
    # Atomic replace with Windows PermissionError resilience
    try:
        tmp.replace(target_path)
    except PermissionError:
        import time as _t2
        _t2.sleep(0.05)
        try:
            tmp.replace(target_path)
        except PermissionError:
            try:
                with open(target_path, "w", encoding="utf-8") as f2:
                    json.dump(snapshot, f2, indent=2, default=str)
                tmp.unlink(missing_ok=True)
            except Exception:
                pass  # Snapshot is best-effort; never block the scan loop


def _serialize_live_stream(
    active_runs: dict[str, dict[str, Any]] | None,
    live_events: list[dict[str, Any]] | None,
    pair_hot_queue_pending: int = 0,
    per_chain: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build bounded live stream payload for dashboard fast-refresh."""
    now = time.monotonic()
    active_list: list[dict[str, Any]] = []
    verified_pairs: list[dict[str, Any]] = []
    diagnostic_pairs: list[dict[str, Any]] = []
    for chain, item in sorted((active_runs or {}).items()):
        entry = {k: v for k, v in item.items() if not k.startswith("_")}
        started = item.get("_started_monotonic")
        if started is not None:
            entry["elapsed_seconds"] = round(max(0.0, now - float(started)), 1)
        active_list.append(entry)
        for pair in (entry.get("verified_pairs") or [])[:5]:
            row = dict(pair)
            row.setdefault("network", chain)
            if row.get("is_actionable"):
                verified_pairs.append(row)
            else:
                diagnostic_pairs.append(row)

    # R34: Also collect from per_chain["last_live_candidates"] — this survives
    # after _clear_active_run() has cleared active_runs for the chain.
    if per_chain:
        seen_keys: set[str] = set()
        for chain, stats in sorted(per_chain.items()):
            for pair in (stats.get("last_live_candidates") or [])[:5]:
                key = f"{chain}:{pair.get('pair')}:{pair.get('route')}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                row = dict(pair)
                row.setdefault("network", chain)
                if row.get("is_actionable"):
                    verified_pairs.append(row)
                else:
                    diagnostic_pairs.append(row)

    events = list(live_events or [])
    return {
        "active_count": len(active_list),
        "active_runs": active_list,
        "recent_events": list(reversed(events[-20:])),
        "pair_hot_queue_pending": pair_hot_queue_pending,
        "verified_pairs": verified_pairs[:20],
        "diagnostic_pairs": diagnostic_pairs[:20],
    }
