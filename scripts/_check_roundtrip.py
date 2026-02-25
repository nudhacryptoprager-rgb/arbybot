#!/usr/bin/env python
"""Check recent scan reports for roundtrip data."""
import json
import glob

files = glob.glob('data/runs/*/reports/scan_*.json')
found = []
for f in files:
    try:
        d = json.load(open(f))
        rt = d.get('roundtrip', {})
        if rt and rt.get('enabled'):
            found.append({
                'file': f, 
                'eval_count': rt.get('evaluated_count', 0),
                'profitable': rt.get('profitable_count', 0),
                'best_net_bps': rt.get('best_net_pnl_bps'),
            })
    except:
        pass

# Show last 10 with roundtrip enabled
print("Recent runs with roundtrip enabled:")
for r in found[-10:]:
    print(f"  {r['file']}: eval={r['eval_count']}, profitable={r['profitable']}, best_bps={r['best_net_bps']}")

# Also show LP filter stats from latest
try:
    latest_files = sorted(files)[-5:]
    for f in latest_files:
        d = json.load(open(f))
        lp = d.get('roundtrip_lp_filter', {})
        if lp:
            print(f"\nLP filter ({f}):")
            print(f"  candidates_considered: {lp.get('candidates_considered')}")
            print(f"  lp_viable_count: {lp.get('lp_viable_count')}")
            print(f"  passed_to_roundtrip: {lp.get('passed_to_roundtrip')}")
except:
    pass
