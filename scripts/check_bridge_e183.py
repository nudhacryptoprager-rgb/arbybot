#!/usr/bin/env python3
"""Check m7_cold_hot_bridge.json for E1.83 factory enrichment."""
import json, time
from pathlib import Path

ROLLING = Path("data/runs/_rolling")

p = ROLLING / "m7_cold_hot_bridge.json"
if not p.exists():
    print("m7_cold_hot_bridge.json: NOT FOUND")
    raise SystemExit(0)

age = time.time() - p.stat().st_mtime
d = json.loads(p.read_text(encoding="utf-8"))
ppm_raw = d.get("pair_pool_matrix") or {}
# May be {pairs: {...}, summary: ..., matrix_timestamp_utc: ...}
if isinstance(ppm_raw, dict) and "pairs" in ppm_raw:
    pairs_raw = ppm_raw["pairs"]
elif isinstance(ppm_raw, dict):
    pairs_raw = list(ppm_raw.values())
else:
    pairs_raw = ppm_raw if isinstance(ppm_raw, list) else []

# Normalise to dict keyed by canonical_pair
if isinstance(pairs_raw, list):
    ppm = {}
    for item in pairs_raw:
        if isinstance(item, dict):
            key = item.get("canonical_pair") or item.get("pair") or item.get("symbol", "?")
            ppm[key] = item
else:
    ppm = pairs_raw  # already dict

ts = str(d.get("timestamp", "?"))[:19]
# E1.83 fix #4: bridge field is `cold_executable` (live schema), not legacy `ce_candidates`.
status = d.get("bridge_generation_status") or d.get("bridge_status", "?")
ce = d.get("cold_executable") or d.get("ce_candidates") or []
fac_loaded = bool(d.get("factory_truth_loaded", False))
fac_age = d.get("factory_truth_age_s")
fac_enriched = d.get("factory_enriched_pairs", 0)

print(f"m7_cold_hot_bridge.json  age={age:.0f}s  ts={ts}  status={status}  CE={len(ce)}  PPM_pairs={len(ppm)}")
print(f"  factory_truth_loaded={fac_loaded}  factory_truth_age_s={fac_age}  factory_enriched_pairs={fac_enriched}")
print(f"  micro_candidate_count={d.get('micro_candidate_count')}  micro_net_usd={d.get('micro_net_usd')}")

enriched = [(k, v) for k, v in ppm.items() if isinstance(v, dict) and (v.get("factory_dex_count") or 0) > 0]
print(f"factory_enriched={len(enriched)}/{len(ppm)}")
if enriched:
    print(f"  {'Pair':<22} {'fac_pool':>8} {'fac_dex':>7} {'ref_only':>8}")
    for k, v in sorted(enriched, key=lambda x: -x[1].get("factory_dex_count", 0)):
        fp = v.get("factory_pool_count", 0)
        fd = v.get("factory_dex_count", 0)
        ro = v.get("reference_only", "?")
        guard = " <- STEP8" if (fd > 0 and fd < 2 and fp < 2) else ""
        print(f"  {k:<22} {fp:>8} {fd:>7} {ro!s:>8}{guard}")
else:
    print("  (no pairs with factory_dex_count > 0 — factory truth NOT loaded in this bridge session)")
    # Show a sample from PPM to understand structure
    sample = list(ppm.items())[:3]
    for k, v in sample:
        if isinstance(v, dict):
            print(f"  sample {k}: keys={list(v.keys())[:8]}")

if ce:
    print(f"\nCE candidates (top 8):")
    print(f"  {'Pair':<22} {'net_bps':>8} {'sz_usd':>10} {'profit$':>8} {'fac_dex':>7} {'fac_pool':>8} {'pool':>14}")
    for c in ce[:8]:
        pair = c.get("pair") or c.get("actual_pair", "?")
        bps = c.get("net_bps") or c.get("spread_bps", 0) or 0
        sz = c.get("amount_in_optimal_usd") or c.get("size_usd_estimate") or c.get("size_usd") or 0
        prof = c.get("expected_profit_usd") or 0
        pa = (c.get("pool_address") or "")[:12]
        pe = ppm.get(pair, {}) if isinstance(ppm.get(pair), dict) else {}
        fd = pe.get("factory_dex_count", "—")
        fp = pe.get("factory_pool_count", "—")
        guard = " <- STEP8" if (isinstance(fd, int) and fd > 0 and fd < 2 and isinstance(fp, int) and fp < 2) else ""
        print(f"  {pair:<22} {float(bps):>8.2f} {float(sz):>10.4f} {float(prof):>8.4f} {fd!s:>7} {fp!s:>8} {pa:>14}{guard}")
else:
    print("\nCE list: empty")
