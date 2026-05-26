"""Quick bridge rebuild + metrics check."""
from m9.graph_arb.bridge_builder import build_bridge_inventory

metrics = build_bridge_inventory(
    sniper_path="data/runs/_rolling/new_pool_sniper_latest.json",
    anchor_path="data/runs/_rolling/m8_1_stable_anchor_latest.json",
    base_inv_path="data/tmp/m9_depth_enriched_inventory.json",
    output_path="data/runs/_rolling/m9_bridge_inventory_latest.json",
)
print("=== Bridge rebuild result ===")
print("pending_adapter_count:", metrics.get("pending_adapter_count"))
print("unsupported_dex_count:", metrics.get("unsupported_dex_count"))
print("graph_ready_from_m8:", metrics.get("graph_ready_from_m8"))
print("graph_ready_total:", metrics.get("graph_ready_total"))
print("graph_edges_from_m8:", metrics.get("graph_edges_from_m8"))
print("m8_new_pools_input:", metrics.get("m8_new_pools_input"))
dcm = metrics.get("dex_coverage_matrix", {})
print("=== DEX Coverage Matrix ===")
for dex, d in sorted(dcm.items()):
    sup = d.get("adapter_supported")
    pend = d.get("adapter_pending")
    evts = d.get("event_count")
    print(f"  {dex:30s} events={evts}  supported={sup}  pending={pend}")
