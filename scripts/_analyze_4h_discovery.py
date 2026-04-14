"""
Analyze 4-hour DISCOVERY scan results by comparing current rolling metrics against baseline.
Mirrors _analyze_4h_scan.py but uses discovery-suffix artifacts.

Usage:
    python scripts/_analyze_4h_discovery.py
"""
import json
import os
import sys
from pathlib import Path

ROLLING = Path("data/runs/_rolling")
BASELINE = ROLLING / "_baseline_pre4h_discovery.json"
CURRENT = ROLLING / "m7_hot_rollup_latest_discovery.json"


def load(p: Path) -> dict:
    if not p.exists():
        print(f"ERROR: {p} not found")
        sys.exit(1)
    return json.load(open(p))


def delta(cur: dict, base: dict, key: str):
    c = cur.get(key)
    b = base.get(key)
    if c is None or b is None:
        return c, b, "N/A"
    d = c - b
    return c, b, d


def pct(part, whole):
    if not whole:
        return "0.0%"
    return f"{100 * part / whole:.1f}%"


def main():
    base = load(BASELINE)
    cur = load(CURRENT)

    base_ts = base.get("last_updated") or base.get("snapshot_run_timestamp", "?")
    cur_ts = cur.get("last_updated") or cur.get("snapshot_run_timestamp", "?")

    print("=" * 70)
    print("  4-HOUR DISCOVERY SCAN ANALYSIS — FULL PERIOD DELTAS")
    print("=" * 70)
    print(f"  Baseline timestamp:  {base_ts}")
    print(f"  Current timestamp:   {cur_ts}")
    print(f"  Baseline session:    {base.get('session_id', '?')}")
    print(f"  Current session:     {cur.get('session_id', '?')}")

    metrics = [
        ("events_seen_total", "WS Events Seen"),
        ("fast_score_attempted_total", "Fast Score Attempted"),
        ("fast_path_scored_total", "Scored"),
        ("fast_path_positive_total", "Positive Net"),
        ("profit_guard_passed_total", "Guard Passed"),
        ("sim_attempted_total", "Sim Attempted"),
        ("sim_passed_total", "Sim Passed"),
        ("submit_ready_total", "Submit Ready"),
        ("windows_seen", "Windows Seen"),
        ("windows_with_events", "Windows with Events"),
        ("windows_with_fast_scores", "Windows with Scores"),
        ("broad_fallback_events_total", "Broad Fallback Events"),
        ("bridge_pool_hit_total", "Bridge Pool Hits"),
        ("route_viable_total", "Route Viable"),
    ]

    print("\n--- PIPELINE FUNNEL (cumulative -> 4h delta) ---")
    print(f"  {'Metric':<35} {'Baseline':>10} {'Current':>10} {'D 4h':>10}")
    print(f"  {'-'*35} {'-'*10} {'-'*10} {'-'*10}")

    for key, label in metrics:
        c, b, d = delta(cur, base, key)
        print(f"  {label:<35} {str(b):>10} {str(c):>10} {str(d):>10}")

    dc = {k: (cur.get(k) or 0) - (base.get(k) or 0) for k, _ in metrics}
    events_d = dc["events_seen_total"]
    scored_d = dc["fast_path_scored_total"]
    pos_d = dc["fast_path_positive_total"]
    guard_d = dc["profit_guard_passed_total"]
    sim_a_d = dc["sim_attempted_total"]
    sim_p_d = dc["sim_passed_total"]
    sub_d = dc["submit_ready_total"]
    win_d = dc["windows_seen"]
    win_ev_d = dc["windows_with_events"]

    print("\n--- CONVERSION RATES (4h period only) ---")
    if events_d:
        print(f"  Events -> Scored:     {pct(scored_d, events_d)}")
        print(f"  Events -> Positive:   {pct(pos_d, events_d)}")
        print(f"  Events -> Guard:      {pct(guard_d, events_d)}")
    if scored_d:
        print(f"  Scored -> Positive:   {pct(pos_d, scored_d)}")
    if guard_d:
        print(f"  Guard -> Sim:         {pct(sim_a_d, guard_d)}")
    if sim_a_d:
        print(f"  Sim -> Passed:        {pct(sim_p_d, sim_a_d)}")
        print(f"  Sim -> Submit:        {pct(sub_d, sim_a_d)}")
    if win_d:
        print(f"  Window activity:     {pct(win_ev_d, win_d)} windows had events")
    print(f"  Events per window:   {events_d / max(win_d, 1):.2f}")

    print("\n--- SIMULATION ERROR HISTOGRAM ---")
    base_hist = base.get("simulation_error_histogram", {})
    cur_hist = cur.get("simulation_error_histogram", {})
    all_keys = sorted(set(list(base_hist.keys()) + list(cur_hist.keys())))
    if all_keys:
        print(f"  {'Error Type':<55} {'Base':>5} {'Curr':>5} {'D':>5}")
        for k in all_keys:
            bv = base_hist.get(k, 0)
            cv = cur_hist.get(k, 0)
            dv = cv - bv
            flag = " *NEW" if k not in base_hist else ""
            print(f"  {k[:55]:<55} {bv:>5} {cv:>5} {dv:>5}{flag}")
    else:
        print("  (empty)")

    print("\n--- SUBMIT BLOCKER HISTOGRAM ---")
    base_sbh = base.get("submit_blocker_histogram", {})
    cur_sbh = cur.get("submit_blocker_histogram", {})
    all_sb = sorted(set(list(base_sbh.keys()) + list(cur_sbh.keys())))
    for k in all_sb:
        bv = base_sbh.get(k, 0)
        cv = cur_sbh.get(k, 0)
        print(f"  {k}: {bv} -> {cv} (D {cv - bv})")
    if not all_sb:
        print("  (empty)")

    print("\n--- SESSION METRICS ---")
    for k in ["session_events_seen_total", "session_fast_path_scored_total",
              "session_bridge_pool_hit_total", "session_windows_seen",
              "session_ws_connected_windows", "session_ws_failed_429_windows"]:
        print(f"  {k}: {cur.get(k, 'N/A')}")

    # Compare production vs discovery
    prod_path = ROLLING / "m7_hot_rollup_latest.json"
    if prod_path.exists():
        prod = json.load(open(prod_path))
        print("\n--- PRODUCTION vs DISCOVERY COMPARISON ---")
        for key, label in [
            ("events_seen_total", "Events"),
            ("fast_path_positive_total", "Positive"),
            ("sim_attempted_total", "Sim Attempted"),
            ("sim_passed_total", "Sim Passed"),
            ("submit_ready_total", "Submit Ready"),
            ("windows_with_events", "Active Windows"),
        ]:
            pv = prod.get(key, 0)
            cv = cur.get(key, 0)
            print(f"  {label:<20} prod={pv:<10} disc={cv:<10}")

    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"  Total 4h events:     {events_d}")
    print(f"  Sim passed (4h):     {sim_p_d}")
    print(f"  Submit ready (4h):   {sub_d}")
    if sub_d > 0:
        print(f"  PAPER SIGNING WORKING: submit_ready > 0")
    new_errors = [k for k in cur_hist if k not in base_hist]
    if new_errors:
        print(f"  New sim error types: {len(new_errors)}")
        for e in new_errors:
            print(f"    -> {e}")
    tenderly_errors = [k for k in cur_hist if "403" in k or "tenderly" in k.lower()]
    if tenderly_errors:
        print(f"  WARNING: Tenderly errors still present (should be using Anvil)")
    elif base_hist and any("403" in k for k in base_hist):
        print(f"  Tenderly 403 errors RESOLVED (now using Anvil)")
    print("=" * 70)


if __name__ == "__main__":
    main()
