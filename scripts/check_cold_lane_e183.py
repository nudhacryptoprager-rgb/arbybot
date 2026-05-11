#!/usr/bin/env python3
"""Check cold lane orderflow artifacts for E1.83 factory truth."""
import json, time
from pathlib import Path
ROLLING = Path("data/runs/_rolling")

for fname in ["m7_orderflow_latest.json", "m7_orderflow_latest_discovery.json",
              "m7_cold_hot_bridge.json"]:
    p = ROLLING / fname
    if not p.exists():
        print(f"{fname}: NOT FOUND")
        continue
    age = time.time() - p.stat().st_mtime
    d = json.loads(p.read_text(encoding="utf-8"))
    ts = str(d.get("timestamp","?"))[:19]
    bridge_gen = d.get("bridge_generation_status","?")
    fam = d.get("family_promotion_snapshot") or {}
    ppm_raw = d.get("pair_pool_matrix") or {}
    if isinstance(ppm_raw, dict) and "pairs" in ppm_raw:
        pairs = ppm_raw["pairs"]
    elif isinstance(ppm_raw, list):
        pairs = ppm_raw
    else:
        pairs = list(ppm_raw.values()) if isinstance(ppm_raw, dict) else []
    
    fam_active = fam.get("fam_active","?")
    print(f"\n{fname} (age={age:.0f}s):  ts={ts}  bridge_gen={bridge_gen}  fam_active={fam_active}  pairs={len(pairs)}")
    
    # Check factory enrichment in pairs
    enriched = 0
    missing_fdc = 0
    for item in pairs:
        if not isinstance(item, dict):
            continue
        fdc = item.get("factory_dex_count")
        if fdc is None:
            missing_fdc += 1
        elif fdc > 0:
            enriched += 1
    print(f"  factory_enriched={enriched}  missing_factory_dex_count={missing_fdc}")
    
    # Show first 3 pairs detail
    for item in pairs[:3]:
        if not isinstance(item, dict):
            continue
        name = item.get("pair") or item.get("canonical_pair","?")
        fpc = item.get("factory_pool_count","MISSING")
        fdc = item.get("factory_dex_count","MISSING")
        scout = item.get("scout_pool_count", item.get("pool_count","?"))
        gecko = item.get("gecko_pool_count","?")
        ro = item.get("reference_only","?")
        print(f"  {name}: factory_pool_count={fpc}  factory_dex_count={fdc}  scout={scout}  gecko={gecko}  ref_only={ro}")
