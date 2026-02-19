#!/usr/bin/env python3
"""Temporary script to analyze scan results."""
import json
import glob
from decimal import Decimal
from collections import defaultdict

# Find latest scan
scans = glob.glob('data/runs/ci_m5_gate_20260219_201744/reports/scan_*.json')
if not scans:
    scans = glob.glob('data/runs/ci_m5_gate_*/reports/scan_*.json')
    scans.sort(reverse=True)

f = scans[0]
print(f"Reading: {f}")
d = json.load(open(f))

# Summary: pairs with quoter_v2 vs slot0
print('\n=== Quote Source Analysis ===')
pair_sources = defaultdict(lambda: {'quoter_v2': [], 'slot0': []})
for q in d['quotes']:
    pair = f"{q['token_in']}/{q['token_out']}"
    source = q.get('quote_source', 'unknown')
    dex = q['dex_id']
    pair_sources[pair][source].append(dex)

# Pairs with cross-DEX quoter_v2 coverage (the goal)
print('Cross-DEX pairs with quoter_v2:')
cross_dex_working = []
for pair, sources in sorted(pair_sources.items()):
    quoter_dexes = set(sources['quoter_v2'])
    slot0_dexes = set(sources['slot0'])
    if len(quoter_dexes) >= 2:
        print(f"  [OK] {pair}: quoter_v2={quoter_dexes}")
        cross_dex_working.append(pair)
    elif len(quoter_dexes) == 1 and len(slot0_dexes) >= 1:
        print(f"  [PARTIAL] {pair}: quoter_v2={quoter_dexes}, slot0={slot0_dexes}")
    elif len(slot0_dexes) >= 2:
        print(f"  [SLOT0_ONLY] {pair}: slot0={slot0_dexes} (not eligible for spread)")
    else:
        print(f"  [SINGLE_DEX] {pair}: all sources={quoter_dexes|slot0_dexes}")

print(f'\nCross-DEX pairs with working quoter_v2: {len(cross_dex_working)}')
print(sorted(cross_dex_working))

# Current unique_pairs in signals
print('\n=== Truth Report Analysis ===')
truth_files = glob.glob('data/runs/ci_m5_gate_20260219_201744/reports/truth_report_*.json')
if truth_files:
    tr = json.load(open(truth_files[0]))
    signals = tr.get('spread_signals', [])
    signal_pairs = set()
    for s in signals:
        pair = s.get('pair', f"{s.get('token_in')}/{s.get('token_out')}")
        signal_pairs.add(pair)
    print(f'Unique pairs in signals: {len(signal_pairs)}: {sorted(signal_pairs)}')
    print(f'\nM4 needs unique_pairs >= 10, current = {len(signal_pairs)}')
