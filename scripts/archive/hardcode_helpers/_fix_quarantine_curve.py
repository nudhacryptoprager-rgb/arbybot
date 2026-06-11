"""One-shot script: add curve_stable routes to quarantine."""
import json
import datetime

QUARANTINE_FILE = "data/quarantine/m9_pool_depth_quarantine.json"

new_addrs = [
    "0x35c6c59277f8fa9ae98dea29b0546d79957acdd8",
    "0xd4e59bfd7bce4a5bc1ee12ea930c7495831d6aef",
    "0x602c281d739357ccd54479960b3196f27571e5da",
    "0x385540fda649a114ffeb943fd73ae82ce7908da3",
    "0xb9c79bd5e5561bdcc281e2b530cefbbebc9976ac",
    "0xf8474c80dfe3af4794eac64672137ad390aabb0a",
    "0x3a38e9b0b5cb034de01d5298fc2ed2d793c0c36f",
    "0x1ab35116c3fa0b2f507d8c8c3261d42683c1e31e",
    "0xbc3705b2bfd42d38e8fa2c8efdc3fdda645c3b2a",
    "0x60868043f1f63aaf6ed9499cb00f60b8b0d6b802",
    "0xee454138083b9b9714cac3c7cf12560248d76d6b",
    "0x3df1658e3e76d14ef3c4d410829ea7575bb83b9b",
]

q = json.load(open(QUARANTINE_FILE))
existing = {p["pool_address"].lower() for p in q.get("quarantined_pools", [])}
ts = datetime.datetime.utcnow().isoformat() + "Z"
added = 0
for addr in new_addrs:
    if addr.lower() not in existing:
        q["quarantined_pools"].append({
            "pool_address": addr,
            "reason": "curve_stable_no_probe",
            "dex_id": "curve_stable",
            "price_impact_at_100usd": None,
            "quarantined_at": ts,
            "threshold_used": None,
            "note": "curve_stable quoter may return ABI-revert data as phantom gain; exclude until get_dy indexing verified",
        })
        existing.add(addr.lower())
        added += 1

q["total_quarantined"] = len(q["quarantined_pools"])
q["last_updated"] = ts
json.dump(q, open(QUARANTINE_FILE, "w"), indent=2)
print(f"Added {added} curve_stable addresses. Total: {q['total_quarantined']}")
