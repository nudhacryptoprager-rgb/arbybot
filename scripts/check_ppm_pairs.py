#!/usr/bin/env python3
"""Check KEYCAT/WETH in bridge PPM."""
import json
from pathlib import Path

d = json.loads(Path("data/runs/_rolling/m7_cold_hot_bridge.json").read_text(encoding="utf-8"))
ppm_raw = d.get("pair_pool_matrix", {})
if isinstance(ppm_raw, dict) and "pairs" in ppm_raw:
    pairs = ppm_raw["pairs"]
elif isinstance(ppm_raw, list):
    pairs = ppm_raw
else:
    pairs = []

print(f"Total PPM pairs: {len(pairs)}")
print("\nAll pairs in PPM:")
for item in pairs:
    if not isinstance(item, dict):
        continue
    name = item.get("pair") or item.get("canonical_pair","?")
    fdc = item.get("factory_dex_count", "MISSING")
    fpc = item.get("factory_pool_count", "MISSING")
    scout = item.get("scout_pool_count", item.get("pool_count","?"))
    ro = item.get("reference_only","?")
    marker = " <-- factory enriched" if (isinstance(fdc, int) and fdc > 0) else ""
    print(f"  {name:<25} fdc={fdc!s:<6} fpc={fpc!s:<4} scout={scout!s:<3} ro={ro}{marker}")
