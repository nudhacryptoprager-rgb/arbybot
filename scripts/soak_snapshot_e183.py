#!/usr/bin/env python3
"""Full E1.83 soak snapshot — bridge CE + factory truth + hot rollup."""
import json, time
from pathlib import Path

ROLLING = Path("data/runs/_rolling")

def load(fname):
    p = ROLLING / fname
    if not p.exists():
        return None, 0
    age = time.time() - p.stat().st_mtime
    return json.loads(p.read_text(encoding="utf-8")), age

print(f"\n{'='*72}")
print(f"E1.83 FULL SOAK SNAPSHOT  — {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
print(f"{'='*72}")

# ── Factory truth ─────────────────────────────────────────────
ft, ft_age = load("pool_family_truth.json")
if ft:
    pairs_ft = ft.get("pairs", {})
    print(f"\n[pool_family_truth]  age={ft_age:.0f}s  pair_count={ft.get('pair_count',0)}")
    print(f"  {'Pair':<18} {'pools':>5} {'dexes':>5}  step8_fires?")
    for k, v in sorted(pairs_ft.items(), key=lambda x: -x[1].get("pool_count",0)):
        pc = v.get("pool_count",0); dc = v.get("dex_count",0)
        guard = "YES" if (dc > 0 and dc < 2 and pc < 2) else "no"
        print(f"  {k:<18} {pc:>5} {dc:>5}  {guard}")
else:
    print("\n[pool_family_truth] MISSING")

# ── Bridge ─────────────────────────────────────────────────────
bd, bridge_age = load("m7_cold_hot_bridge.json")
if bd:
    ts = str(bd.get("timestamp","?"))[:19]
    bgen = bd.get("bridge_generation_status","?")
    ppm_raw = bd.get("pair_pool_matrix") or {}
    if isinstance(ppm_raw, dict) and "pairs" in ppm_raw:
        pairs_list = ppm_raw["pairs"]
    elif isinstance(ppm_raw, list):
        pairs_list = ppm_raw
    else:
        pairs_list = []
    # Build pair dict
    ppm = {}
    for item in pairs_list:
        if isinstance(item, dict):
            k = item.get("pair") or item.get("canonical_pair","?")
            ppm[k] = item
    ce = bd.get("ce_candidates") or []
    enriched = [(k,v) for k,v in ppm.items() if (v.get("factory_dex_count") or 0) > 0]
    n_ref_only = sum(1 for v in ppm.values() if v.get("reference_only"))
    print(f"\n[bridge]  age={bridge_age:.0f}s  ts={ts}  bridge_gen={bgen}")
    print(f"  PPM: {len(ppm)} pairs  factory_enriched={len(enriched)}  reference_only={n_ref_only}")
    
    if enriched:
        print(f"\n  Factory-enriched pairs (6 expected from BASE_TARGET_PAIRS):")
        print(f"  {'Pair':<22} {'fac_pool':>8} {'fac_dex':>7} {'scout':>5} {'gecko':>5} {'ref_only':>8}")
        for k, v in sorted(enriched, key=lambda x: -x[1].get("factory_dex_count",0)):
            fp = v.get("factory_pool_count",0); fd = v.get("factory_dex_count",0)
            scout = v.get("scout_pool_count", v.get("pool_count",0))
            gecko = v.get("gecko_pool_count",0)
            ro = v.get("reference_only","?")
            guard = " <- STEP8" if (fd > 0 and fd < 2 and fp < 2) else ""
            print(f"  {k:<22} {fp:>8} {fd:>7} {scout:>5} {gecko:>5} {ro!s:>8}{guard}")
    
    if ce:
        print(f"\n  CE candidates ({len(ce)}):")
        print(f"  {'Pair':<22} {'bps':>8} {'sz_usd':>10} {'fac_dex':>7} {'fac_pool':>8} {'ref_only':>8}")
        for c in ce[:10]:
            pair = c.get("pair","?")
            bps = c.get("spread_bps",0)
            sz = c.get("size_usd_estimate") or c.get("size_usd") or 0
            pe = ppm.get(pair) or {}
            fd = pe.get("factory_dex_count","—")
            fp = pe.get("factory_pool_count","—")
            ro = pe.get("reference_only","—")
            guard = " <- STEP8" if (isinstance(fd,int) and fd > 0 and fd < 2 and isinstance(fp,int) and fp < 2) else ""
            print(f"  {pair:<22} {bps:>8.1f} {sz:>10.4f} {fd!s:>7} {fp!s:>8} {ro!s:>8}{guard}")
    else:
        print(f"\n  CE list: empty")
else:
    print("\n[bridge] NOT FOUND")

# ── Hot rollup ─────────────────────────────────────────────────
def show_rollup(fname, label):
    d, age = load(fname)
    if not d:
        print(f"\n[{label}] NOT FOUND")
        return
    ts = str(d.get("timestamp","?"))[:19]
    ev = d.get("events_seen_total",d.get("session_events_seen","?"))
    sc = d.get("fast_path_scored_total","?")
    bh = d.get("bridge_pair_hits_total","?")
    sim_a = d.get("sim_attempted_total","?")
    sim_p = d.get("sim_passed_total","?")
    sub = d.get("submit_ready_total","?")
    ws429 = d.get("ws_429_total","?")
    sess = d.get("current_session_id","?")
    print(f"\n[{label}]  age={age:.0f}s  ts={ts}  sess={sess}")
    print(f"  events={ev}  scored={sc}  bridge_hits={bh}  sim_a={sim_a}  sim_p={sim_p}  submit={sub}  ws429={ws429}")

show_rollup("m7_hot_rollup_latest.json", "hot_prod")
show_rollup("m7_hot_rollup_latest_discovery.json", "hot_disc")
print()
