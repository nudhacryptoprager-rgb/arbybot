"""Quick snapshot of rolling metrics before a long scan."""
import json
import os

p = "data/runs/_rolling/hot_rollup_latest.json"
if os.path.exists(p):
    d = json.load(open(p))
    keys = [
        "ws_events_total", "scored_total", "positive_net_total",
        "profit_guard_passed_total", "sim_attempted_total",
        "sim_passed_total", "submit_ready_total",
        "scoring_windows_seen", "scoring_windows_empty",
    ]
    print("=== BASELINE SNAPSHOT (pre-4h scan) ===")
    for k in keys:
        print(f"  {k}: {d.get(k, 'N/A')}")
    hist = d.get("simulation_error_histogram", {})
    print(f"  sim_error_histogram: {json.dumps(hist, indent=2)}")
    # Save baseline copy
    out = "data/runs/_rolling/_baseline_pre4h.json"
    with open(out, "w") as f:
        json.dump(d, f, indent=2)
    print(f"\nBaseline saved to {out}")
else:
    print("No hot_rollup_latest.json found")
