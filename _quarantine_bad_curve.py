"""Add 5 reverting curve_stable pools to quarantine."""
import json, datetime

bad_pools = [
    "0x35c6c59277f8fa9ae98dea29b0546d79957acdd8",  # USDC_WETH - revert both selectors
    "0x385540fda649a114ffeb943fd73ae82ce7908da3",  # USDbC_crvUSD - revert both selectors
    "0xb9c79bd5e5561bdcc281e2b530cefbbebc9976ac",  # USDC_crvUSD - revert both selectors
    "0xf8474c80dfe3af4794eac64672137ad390aabb0a",  # USDC_crvUSD - revert both selectors
    "0x3a38e9b0b5cb034de01d5298fc2ed2d793c0c36f",  # USDC_USDbC - revert both selectors
]

with open("data/quarantine/m9_pool_depth_quarantine.json") as f:
    q = json.load(f)

existing = {p["pool_address"] for p in q["quarantined_pools"]}
added = 0
for addr in bad_pools:
    if addr not in existing:
        q["quarantined_pools"].append({
            "pool_address": addr,
            "reason": "CURVE_GET_DY_REVERT",
            "added_at": datetime.datetime.utcnow().isoformat() + "Z",
            "adapter_type": "curve_stable",
        })
        added += 1

q["total_quarantined"] = len(q["quarantined_pools"])
q["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"

with open("data/quarantine/m9_pool_depth_quarantine.json", "w") as f:
    json.dump(q, f, indent=2)

total = q["total_quarantined"]
print(f"Added {added} pools. Total now: {total}")
