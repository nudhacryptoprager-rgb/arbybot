#!/usr/bin/env python3
"""Check bridge artifacts for E1.83 factory truth integration."""
import json, time
from pathlib import Path
ROLLING = Path("data/runs/_rolling")

for fname in ["m7_orderflow_latest.json", "m7_cold_hot_bridge.json"]:
    p = ROLLING / fname
    if not p.exists():
        print(f"{fname}: NOT FOUND")
        continue
    age = time.time() - p.stat().st_mtime
    d = json.loads(p.read_text(encoding="utf-8"))
    ts = str(d.get("timestamp","?"))[:19]
    ppm = d.get("pair_pool_matrix") or {}
    ce = d.get("ce_candidates") or d.get("candidates") or []
    status = d.get("bridge_status","?")
    enriched = [(k,v) for k,v in ppm.items() if (v.get("factory_dex_count") or 0) > 0]
    print(f"{fname} (age={age:.0f}s):  ts={ts}  status={status}  CE={len(ce)}  PPM={len(ppm)}  factory_enriched={len(enriched)}")
    if enriched:
        print("  factory enriched pairs:")
        for k, v in sorted(enriched, key=lambda x: -x[1].get("factory_dex_count",0))[:8]:
            fp = v.get("factory_pool_count", 0)
            fd = v.get("factory_dex_count", 0)
            ro = v.get("reference_only", "?")
            print(f"    {k}: factory_pool_count={fp}  factory_dex_count={fd}  reference_only={ro}")
    if ce:
        print("  CE candidates:")
        for c in ce[:8]:
            pair = c.get("pair","?")
            bps = c.get("spread_bps", 0)
            sz = c.get("size_usd_estimate") or c.get("size_usd") or 0
            ppm_e = ppm.get(pair, {})
            fd = ppm_e.get("factory_dex_count","—")
            fp = ppm_e.get("factory_pool_count","—")
            ro = ppm_e.get("reference_only","—")
            guard = " <- STEP8_BLOCK" if (isinstance(fd,int) and fd > 0 and fd < 2 and isinstance(fp,int) and fp < 2) else ""
            print(f"    {pair}: bps={bps:.1f} sz=${sz:.4f}  fac_dex={fd}  fac_pool={fp}  ref_only={ro}{guard}")
    print()
