"""M9 Graph-Arb live monitoring dashboard.

Reads the rolling artifact every N seconds and prints a compact summary of
gates, funnel, infra-telemetry, and provider-router health.

Usage:
    py -3.11 tools/m9_dashboard.py             # default: refresh every 30s
    py -3.11 tools/m9_dashboard.py 15          # refresh every 15s
    py -3.11 tools/m9_dashboard.py --once      # single snapshot and exit
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROLLING = Path("data/runs/_rolling/m9_graph_latest.json")

# ─────────────────────── helpers ────────────────────────────────────────────

_PASS = "PASS ✅"
_FAIL = "FAIL ❌"
_WARN = "WARN ⚠️"


def _gate(val: float, threshold: float, ge: bool = True) -> str:
    ok = (val >= threshold) if ge else (val < threshold)
    mark = _PASS if ok else _FAIL
    return f"{val:.4f}  {mark}"


def _bar(ratio: float, width: int = 30) -> str:
    filled = int(ratio * width)
    return "[" + "█" * filled + "░" * (width - filled) + f"]  {ratio*100:.1f}%"


# ─────────────────────── display ────────────────────────────────────────────

def display(path: Path) -> None:  # noqa: C901
    try:
        art = json.loads(path.read_bytes())
    except FileNotFoundError:
        print(f"  [artifact not found: {path}]")
        return
    except json.JSONDecodeError as exc:
        print(f"  [malformed JSON: {exc}]")
        return

    ts          = art.get("run_timestamp", "?")
    elapsed     = art.get("elapsed_s", 0.0)
    duration    = art.get("duration_fulfilled", False)
    sweeps      = art.get("sweeps_completed", 0)
    cycles      = art.get("cycles_found", 0)
    quoteable   = art.get("cycles_quoteable", 0)
    pos_gross   = art.get("cycles_positive_gross", 0)
    qsr_val     = art.get("qsr", 0.0)

    rg          = art.get("runtime_gates", {})

    # runtime_gates values may be raw floats (legacy) or {value, threshold, pass} dicts
    def _rg_val(key: str, fallback: float = 0.0) -> float:
        v = rg.get(key, fallback)
        return v["value"] if isinstance(v, dict) else float(v)

    def _rg_pass(key: str) -> bool:
        v = rg.get(key)
        if isinstance(v, dict):
            return bool(v.get("pass", False))
        return False

    mc_sr       = _rg_val("multicall_success_rate")
    dc          = _rg_val("data_completeness")
    unverified  = int(_rg_val("unverified_active_routes", -1))
    qsr_gate    = _rg_val("qsr")
    qrr         = _rg_val("quote_revert_rate")
    all_pass    = rg.get("all_pass", False)

    it          = art.get("infra_telemetry", {})
    h429        = it.get("http_429_count", 0)
    raw429      = it.get("raw_http_429_count", 0)
    mc429       = it.get("multicall_429_count", 0)
    dyn_en      = it.get("dynamic_size_enabled", False)
    dyn_cnt     = it.get("dynamic_size_selected_count", 0)
    dyn_rate    = it.get("dynamic_size_selection_rate", 0.0)
    sizes_src   = it.get("sizes_usd_source", "?")
    calls       = it.get("actual_http_calls", 0)
    prequote_sk = it.get("prequote_cycles_skipped", 0)
    pq_ratio    = it.get("prequote_skip_ratio", 0.0)

    pr_snap     = it.get("provider_router_snapshot")

    mc_stats    = art.get("multicall_stats") or {}
    mc_att      = mc_stats.get("attempted", 0)
    mc_ok       = mc_stats.get("success", 0)
    mc_retry    = mc_stats.get("retry_count", 0)
    mc_split    = mc_stats.get("subchunk_splits", 0)

    rh          = art.get("cycle_reject_histogram") or {}
    top_opps    = art.get("top_opportunities") or []

    W = 64
    line = "─" * W
    thick = "═" * W

    now_str = datetime.now().strftime("%H:%M:%S")
    status  = f"  ALL_PASS={all_pass}"
    print(f"\n{thick}")
    print(f"  M9 Dashboard  [{now_str}]  run={ts}")
    print(f"  elapsed={elapsed:.0f}s  duration_fulfilled={duration}{status}")
    print(thick)

    # ── Funnel ───────────────────────────────────────────────────────────
    print(f"\n  FUNNEL  (sweeps={sweeps})")
    print(f"  {line}")
    total_batched = prequote_sk + cycles
    print(f"  batched_for_prequote: {total_batched:>6}")
    prequote_rate = min(1.0, prequote_sk / max(1, total_batched))
    print(f"  prequote_skipped    : {prequote_sk:>6}  {_bar(prequote_rate)}  ratio={pq_ratio:.3f}")
    passed_prequote = cycles  # cycles_found are those that passed prequote
    print(f"  cycles_found (pass) : {passed_prequote:>6}")
    q_rate = min(1.0, quoteable / max(1, passed_prequote))
    print(f"  cycles_quoteable    : {quoteable:>6}  {_bar(q_rate)}")
    pos_rate = min(1.0, pos_gross / max(1, quoteable))
    print(f"  cycles_pos_gross    : {pos_gross:>6}  {_bar(pos_rate)}")
    if top_opps:
        best = top_opps[0]
        best_net = best.get("net_bps", best.get("gross_bps", 0))
        print(f"  best_net_bps        : {best_net:.2f} bps")

    # ── Runtime Gates ────────────────────────────────────────────────────
    print(f"\n  RUNTIME GATES  (all_pass={all_pass})")
    print(f"  {line}")
    print(f"  multicall_success   : {_gate(mc_sr, 0.90)}")
    print(f"  data_completeness   : {_gate(dc, 0.98)}")
    print(f"  qsr                 : {_gate(qsr_gate, 0.80)}")
    print(f"  quote_revert_rate   : {_gate(qrr, 0.05, ge=False)}")
    uvr_mark = _PASS if unverified == 0 else _FAIL
    print(f"  unverified_routes   : {unverified}  {uvr_mark}")

    # ── Infra / 429 ──────────────────────────────────────────────────────
    print(f"\n  INFRA  (http_calls={calls})")
    print(f"  {line}")
    print(f"  http_429 (artifact) : {h429}")
    print(f"  raw_http_429        : {raw429}")
    print(f"  multicall_429       : {mc429}")
    if mc_att:
        print(f"  multicall_stats     : attempted={mc_att} success={mc_ok} "
              f"retry={mc_retry} splits={mc_split}")

    # ── Dynamic Sizes ────────────────────────────────────────────────────
    print(f"\n  DYNAMIC SIZES  enabled={dyn_en}  src={sizes_src}")
    print(f"  {line}")
    print(f"  selected_count      : {dyn_cnt}")
    print(f"  selection_rate      : {_bar(dyn_rate)}")

    # ── Provider Router Snapshot ─────────────────────────────────────────
    if pr_snap:
        print(f"\n  PROVIDER ROUTER")
        print(f"  {line}")
        print(f"  failed_over         : {pr_snap.get('is_failed_over', '?')}")
        for name, pinfo in (pr_snap.get("providers") or {}).items():
            recent = pinfo.get("recent_429", 0)
            total  = pinfo.get("attempts_total", 0)
            t429   = pinfo.get("http_429_total", 0)
            p50    = pinfo.get("latency_p50_s")
            p90    = pinfo.get("latency_p90_s")
            lat_str = ""
            if p50 is not None:
                lat_str = f"  p50={p50*1000:.0f}ms p90={p90*1000:.0f}ms" if p90 else f"  p50={p50*1000:.0f}ms"
            print(f"  {name:<12}: recent_429={recent} total_att={total} total_429={t429}{lat_str}")

    # ── Reject Histogram ─────────────────────────────────────────────────
    if rh:
        total_rh = sum(rh.values())
        print(f"\n  REJECT HISTOGRAM  (total={total_rh})")
        print(f"  {line}")
        for reason, cnt in sorted(rh.items(), key=lambda x: -x[1])[:6]:
            pct = cnt / max(1, total_rh) * 100
            print(f"  {reason:<30}: {cnt:>5}  ({pct:.1f}%)")

    print(f"\n{thick}\n")


# ─────────────────────── main ────────────────────────────────────────────────

def main() -> None:
    args   = sys.argv[1:]
    once   = "--once" in args
    args   = [a for a in args if a != "--once"]
    period = int(args[0]) if args else 30

    if once:
        display(ROLLING)
        return

    print(f"M9 Monitor — reading {ROLLING} every {period}s  (Ctrl+C to stop)")
    while True:
        display(ROLLING)
        try:
            time.sleep(period)
        except KeyboardInterrupt:
            print("\nMonitor stopped.")
            break


if __name__ == "__main__":
    main()
