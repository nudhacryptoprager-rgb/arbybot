"""Quick diagnostic: show depth info for curve_stable routes in bridge inventory."""
import json

with open("data/tmp/m9_depth_enriched_bridge.json") as f:
    inv = json.load(f)

curve_routes = [r for r in inv.get("active_routes", []) if r.get("adapter_type") == "curve_stable"]
print(f"curve_stable routes: {len(curve_routes)}")
print()
for r in curve_routes:
    print(
        f"{r['pair_id']:20s}  depth_ok={r.get('depth_probe_ok')}  "
        f"reject={r.get('depth_reject_reason')}  "
        f"eff_depth={r.get('effective_depth_usd')}"
    )
