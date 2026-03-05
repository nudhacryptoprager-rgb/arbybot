#!/usr/bin/env python3
"""
Suggest anchor price updates based on runDir evidence.

Reads scan_*.json and reject_histogram_*.json from a runDir,
computes robust median prices for pairs with PRICE_SANITY_FAILED,
and prints YAML snippets for updating tokens_anchor_price and tokens_usd_price.

Usage:
    py -3.11 scripts/suggest_anchor_updates.py --run-dir data/runs/ci_m5_gate_YYYYMMDD_HHMMSS

    # With reference WETH_USDC price for USD derivations
    py -3.11 scripts/suggest_anchor_updates.py --run-dir data/runs/ci_m5_gate_YYYYMMDD_HHMMSS --weth-usd 2100
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def load_artifacts(run_dir: Path) -> tuple[dict, dict]:
    """Load scan and reject_histogram from runDir."""
    reports = run_dir / "reports"
    
    scan_files = list(reports.glob("scan_*.json"))
    rh_files = list(reports.glob("reject_histogram_*.json"))
    
    if not scan_files:
        raise FileNotFoundError(f"No scan_*.json in {reports}")
    if not rh_files:
        raise FileNotFoundError(f"No reject_histogram_*.json in {reports}")
    
    scan = json.load(open(scan_files[0]))
    rh = json.load(open(rh_files[0]))
    
    return scan, rh


def normalize_pair_key(token_in: str, token_out: str) -> str:
    """Normalize pair key for anchor lookup (e.g., WETH_USDC)."""
    return f"{token_in}_{token_out}"


def extract_prices(scan: dict, rh: dict) -> dict[str, list[float]]:
    """Extract observed prices by pair from both PASS quotes and FAIL samples."""
    pair_prices: dict[str, list[float]] = defaultdict(list)
    
    # From PASS quotes (quotes_sample)
    for q in scan.get("quotes_sample", []):
        token_in = q.get("token_in")
        token_out = q.get("token_out")
        price_exact = q.get("price_exact")
        
        if token_in and token_out and price_exact:
            try:
                pair_key = normalize_pair_key(token_in, token_out)
                pair_prices[pair_key].append(float(price_exact))
            except (ValueError, TypeError):
                pass
    
    # From PRICE_SANITY_FAILED samples
    for sample in rh.get("price_sanity_samples", []):
        pair = sample.get("pair")
        price_exact = sample.get("price_exact")
        
        if pair and price_exact:
            try:
                # Parse pair "ARB/DAI" -> "ARB_DAI"
                if "/" in pair:
                    parts = pair.split("/")
                    pair_key = normalize_pair_key(parts[0], parts[1])
                else:
                    pair_key = pair
                pair_prices[pair_key].append(float(price_exact))
            except (ValueError, TypeError):
                pass
    
    # From sample_rejects (broader reject samples)
    for sample in rh.get("sample_rejects", []):
        pair = sample.get("pair")
        price = sample.get("price_exact") or sample.get("implied_price")
        
        if pair and price:
            try:
                if "/" in pair:
                    parts = pair.split("/")
                    pair_key = normalize_pair_key(parts[0], parts[1])
                else:
                    pair_key = pair
                pair_prices[pair_key].append(float(price))
            except (ValueError, TypeError):
                pass
    
    return dict(pair_prices)


def compute_anchor_suggestions(
    pair_prices: dict[str, list[float]],
    weth_usd: float = 2100.0
) -> tuple[dict[str, float], dict[str, float]]:
    """Compute suggested anchor prices and USD prices."""
    
    anchors: dict[str, float] = {}
    usd_prices: dict[str, float] = {}
    
    # First, compute WETH_USDC from evidence if available
    if "WETH_USDC" in pair_prices:
        anchors["WETH_USDC"] = statistics.median(pair_prices["WETH_USDC"])
        weth_usd = anchors["WETH_USDC"]
        usd_prices["WETH"] = weth_usd
    else:
        usd_prices["WETH"] = weth_usd
    
    # Fixed USD prices for stablecoins
    for stable in ["USDC", "USDT", "DAI", "LUSD", "USDE"]:
        usd_prices[stable] = 1.0
    
    for pair_key, prices in pair_prices.items():
        if not prices:
            continue
        
        median_price = statistics.median(prices)
        anchors[pair_key] = median_price
        
        # Try to derive USD prices for tokens
        parts = pair_key.split("_")
        if len(parts) == 2:
            token_in, token_out = parts
            
            # If denominated in USDC/USDT/DAI, price_exact IS the USD price
            if token_out in ["USDC", "USDT", "DAI"]:
                usd_prices[token_in] = median_price
            
            # If denominated in WETH, derive USD price
            elif token_out == "WETH" and weth_usd > 0:
                usd_prices[token_in] = median_price * weth_usd
    
    return anchors, usd_prices


def format_yaml_snippet(anchors: dict[str, float], usd_prices: dict[str, float]) -> str:
    """Format anchors and USD prices as YAML snippets."""
    lines = []
    
    lines.append("# tokens_anchor_price (suggested updates from evidence)")
    lines.append("tokens_anchor_price:")
    for key in sorted(anchors.keys()):
        val = anchors[key]
        # Format with appropriate precision
        if val >= 100:
            lines.append(f"  {key}: {val:.1f}")
        elif val >= 1:
            lines.append(f"  {key}: {val:.4f}")
        elif val >= 0.001:
            lines.append(f"  {key}: {val:.6f}")
        else:
            lines.append(f"  {key}: {val:.10f}")
    
    lines.append("")
    lines.append("# tokens_usd_price (derived from anchors)")
    lines.append("tokens_usd_price:")
    for key in sorted(usd_prices.keys()):
        val = usd_prices[key]
        if val >= 1:
            lines.append(f"  {key}: {val:.2f}")
        else:
            lines.append(f"  {key}: {val:.6f}")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Suggest anchor price updates from runDir evidence")
    parser.add_argument("--run-dir", required=True, help="Path to runDir")
    parser.add_argument("--weth-usd", type=float, default=2100.0, 
                        help="Reference WETH/USD price (default: 2100)")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of YAML")
    args = parser.parse_args()
    
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"ERROR: Run dir not found: {run_dir}", file=sys.stderr)
        return 1
    
    try:
        scan, rh = load_artifacts(run_dir)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    
    # Extract prices
    pair_prices = extract_prices(scan, rh)
    
    if not pair_prices:
        print("WARNING: No prices found in artifacts", file=sys.stderr)
        return 1
    
    print(f"# Found prices for {len(pair_prices)} pairs from {run_dir.name}")
    print(f"# Evidence: quotes_sample + price_sanity_samples")
    print()
    
    # Compute suggestions
    anchors, usd_prices = compute_anchor_suggestions(pair_prices, args.weth_usd)
    
    if args.json:
        result = {
            "anchors": anchors,
            "usd_prices": usd_prices,
            "source_run_dir": str(run_dir),
        }
        print(json.dumps(result, indent=2))
    else:
        # Print per-pair statistics first
        print("# === OBSERVED PRICES BY PAIR ===")
        for pair in sorted(pair_prices.keys()):
            prices = pair_prices[pair]
            med = statistics.median(prices)
            mn = min(prices)
            mx = max(prices)
            print(f"# {pair}: median={med:.8f}, range=[{mn:.8f}, {mx:.8f}], n={len(prices)}")
        print()
        
        # Print YAML snippets
        print(format_yaml_snippet(anchors, usd_prices))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
