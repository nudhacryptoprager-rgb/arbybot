"""Remove curve_stable pools from quarantine (now properly indexed in adapter_metadata.yaml)."""
import json
import datetime

QUARANTINE_FILE = "data/quarantine/m9_pool_depth_quarantine.json"

CURVE_ADDRS = {
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
}

q = json.load(open(QUARANTINE_FILE))
before = len(q["quarantined_pools"])
q["quarantined_pools"] = [
    p for p in q["quarantined_pools"]
    if p["pool_address"].lower() not in CURVE_ADDRS
]
removed = before - len(q["quarantined_pools"])
q["total_quarantined"] = len(q["quarantined_pools"])
q["last_updated"] = datetime.datetime.utcnow().isoformat() + "Z"
json.dump(q, open(QUARANTINE_FILE, "w"), indent=2)
print(f"Removed {removed} curve_stable pools from quarantine. Total now: {q['total_quarantined']}")
