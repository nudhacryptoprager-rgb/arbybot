import json

d = json.load(open("data/runs/_rolling/m7_hot_rollup_latest.json"))
s = d.get("session", {})

print("=== SESSION ===")
for k in ["session_id", "session_started_at", "session_windows_seen",
          "session_events_seen_total", "session_bridge_pool_hit_total",
          "session_fast_path_scored_total", "session_ws_connected_windows",
          "session_ws_failed_windows", "session_ws_failed_429_windows"]:
    print(f"  {k}: {s.get(k)}")

print("\n=== CUMULATIVE ===")
for k in ["fast_path_scored_total", "fast_path_positive_total",
          "profit_guard_passed_total", "sim_attempted_total",
          "sim_passed_total", "submit_ready_total", "windows_seen"]:
    print(f"  {k}: {d.get(k)}")

print(f"\n  last_updated: {d.get('last_updated')}")
print(f"  sim_backend: {d.get('simulation_backend')}")
