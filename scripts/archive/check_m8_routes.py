"""Debug helper: show M8 sniper routes and M9 pool coverage."""
import json

inv = json.load(open("data/runs/_rolling/m9_bridge_inventory_latest.json", encoding="utf-8"))
m8_routes = [r for r in inv.get("active_routes", []) if r.get("source") == "m8_sniper"]
print("=== M8 Sniper Routes in Bridge Inventory ===")
for r in m8_routes:
    t0 = r.get("token0_addr", "")[:10]
    t1 = r.get("token1_addr", "")[:10]
    pool = r.get("pool_address", "")[:16]
    dex = r.get("dex_id", "")
    depth = r.get("effective_depth_usd")
    print(f"  {dex:20s}  t0={t0}  t1={t1}  pool={pool}  depth={depth}")

# Now check what the M9 artifact top_pools look like
a = json.load(open("data/runs/_rolling/m9_graph_latest.json", encoding="utf-8"))
pool_cov = a.get("pool_coverage") or []
m8_pool_addrs = {r.get("pool_address", "").lower() for r in m8_routes}
print()
print("=== M9 Pool Coverage (M8 pool hits) ===")
hits = [p for p in pool_cov if p.get("pool_address", "").lower() in m8_pool_addrs]
if hits:
    for p in hits:
        print(f"  {p.get('pool_address', '')}  dex={p.get('dex_id')}  cycle_count={p.get('cycle_count')}")
else:
    print("  NONE — M8 pools not found in M9 pool_coverage")
    print(f"  (total pool_coverage entries: {len(pool_cov)})")
    if pool_cov:
        print("  Sample from pool_coverage:", list(pool_cov[0].keys()))
