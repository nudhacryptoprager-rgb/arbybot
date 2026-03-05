#!/usr/bin/env python3
"""
Temporary script to extract evidence-based anchor prices from runDir.
"""

import json
from pathlib import Path
from collections import defaultdict
import statistics

RUN_DIR = Path("data/runs/ci_m5_gate_20260305_105825/reports")

def main():
    # Load reject_histogram
    rh_files = list(RUN_DIR.glob("reject_histogram_*.json"))
    if not rh_files:
        print("ERROR: No reject_histogram found")
        return
    
    with open(rh_files[0]) as f:
        rh = json.load(f)
    
    rejects = rh.get("rejects", [])
    
    # Extract PRICE_SANITY_FAILED by pair
    pair_prices = defaultdict(list)
    for r in rejects:
        if r.get("reason") != "PRICE_SANITY_FAILED":
            continue
        pair = r.get("pair", "")
        price_str = r.get("price_exact")
        anchor_str = r.get("anchor_price")
        if price_str:
            try:
                price = float(price_str)
                pair_prices[pair].append({"price": price, "anchor": anchor_str})
            except:
                pass
    
    print("PRICE_SANITY_FAILED evidence by pair:")
    print("=" * 70)
    for pair, samples in sorted(pair_prices.items()):
        prices = [s["price"] for s in samples]
        median = statistics.median(prices)
        anchor = samples[0]["anchor"]  # same anchor for all
        print(f"  {pair}: n={len(samples)}, median={median:.10f}, current_anchor={anchor}")
    
    # Also load scan for PASS quotes
    scan_files = list(RUN_DIR.glob("scan_*.json"))
    if not scan_files:
        print("\nERROR: No scan found")
        return
    
    with open(scan_files[0]) as f:
        scan = json.load(f)
    
    quotes = scan.get("quotes_sample", [])
    print()
    print("PASS quotes from scan (baseline):")
    print("=" * 70)
    pass_pair_prices = defaultdict(list)
    for q in quotes:
        token_in = q.get("token_in", "")
        token_out = q.get("token_out", "")
        pair = f"{token_in}/{token_out}"
        price_str = q.get("price_exact")
        if price_str:
            try:
                pass_pair_prices[pair].append(float(price_str))
            except:
                pass
    
    for pair, prices in sorted(pass_pair_prices.items()):
        median = statistics.median(prices)
        print(f"  {pair}: n={len(prices)}, median={median:.10f}")
    
    # Compute USD reference from WETH/USDC
    weth_usdc_prices = pass_pair_prices.get("WETH/USDC", [])
    if weth_usdc_prices:
        weth_usd = statistics.median(weth_usdc_prices)
        print()
        print("=" * 70)
        print(f"WETH/USDC baseline: {weth_usd:.2f}")
        print()
        print("Derived USD prices from evidence:")
        print("=" * 70)
        
        # Derive other token USD prices
        for pair, prices in sorted(pass_pair_prices.items()):
            median = statistics.median(prices)
            tokens = pair.split("/")
            if len(tokens) == 2:
                t_in, t_out = tokens
                if t_out == "USDC":
                    # Direct USD price
                    print(f"  {t_in}: ${median:.4f}")
                elif t_out == "WETH":
                    # Derive from WETH
                    token_usd = median * weth_usd
                    print(f"  {t_in}: ${token_usd:.4f} (via {median:.8f} * WETH)")
                elif t_in == "WETH":
                    # Inverse
                    if median > 0:
                        token_usd = weth_usd / median
                        print(f"  {t_out}: ${token_usd:.4f} (via WETH / {median:.4f})")

if __name__ == "__main__":
    main()
