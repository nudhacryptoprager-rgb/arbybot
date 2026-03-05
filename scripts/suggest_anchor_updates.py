#!/usr/bin/env python3
"""
Suggest anchor price updates based on runDir evidence.

v3.2.25: Fixed to process full rejects list, separate PASS/FAIL samples,
add outlier filtering, and produce strict JSON with --json.

Reads scan_*.json and reject_histogram_*.json from a runDir,
computes robust median prices for pairs with PRICE_SANITY_FAILED,
and prints YAML snippets for updating tokens_anchor_price and tokens_usd_price.

Usage:
    py -3.11 scripts/suggest_anchor_updates.py --run-dir data/runs/ci_m5_gate_YYYYMMDD_HHMMSS

    # With reference WETH_USDC price for USD derivations
    py -3.11 scripts/suggest_anchor_updates.py --run-dir data/runs/ci_m5_gate_YYYYMMDD_HHMMSS --weth-usd 2100

    # JSON output (strict - no preamble, suitable for automation)
    py -3.11 scripts/suggest_anchor_updates.py --run-dir data/runs/ci_m5_gate_YYYYMMDD_HHMMSS --json
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple


class PriceEvidence(NamedTuple):
    """Price evidence with source tracking."""
    price: float
    source: str  # "PASS" or "FAIL"


def load_artifacts(run_dir: Path) -> tuple[dict, dict]:
    """Load scan and reject_histogram from runDir."""
    reports = run_dir / "reports"
    
    scan_files = sorted(reports.glob("scan_*.json"), key=lambda p: p.name, reverse=True)
    rh_files = sorted(reports.glob("reject_histogram_*.json"), key=lambda p: p.name, reverse=True)
    
    if not scan_files:
        raise FileNotFoundError(f"No scan_*.json in {reports}")
    if not rh_files:
        raise FileNotFoundError(f"No reject_histogram_*.json in {reports}")
    
    scan = json.load(open(scan_files[0], encoding='utf-8'))
    rh = json.load(open(rh_files[0], encoding='utf-8'))
    
    return scan, rh


def normalize_pair_key(token_in: str, token_out: str) -> str:
    """Normalize pair key for anchor lookup (e.g., WETH_USDC)."""
    return f"{token_in.upper()}_{token_out.upper()}"


def parse_pair_string(pair: str) -> tuple[str, str]:
    """Parse pair string like 'ARB/DAI' into ('ARB', 'DAI')."""
    if "/" in pair:
        parts = pair.split("/")
        return parts[0].strip().upper(), parts[1].strip().upper()
    elif "_" in pair:
        parts = pair.split("_")
        return parts[0].strip().upper(), parts[1].strip().upper()
    return pair.upper(), ""


def is_outlier(price: float, prices: list[float], max_deviation: float = 10.0) -> bool:
    """Check if price is an outlier (more than max_deviation * IQR from median)."""
    if len(prices) < 3:
        return False  # Not enough data for outlier detection
    
    median = statistics.median(prices)
    if median == 0:
        return True  # Zero median is suspicious
    
    # Simple ratio-based check: reject if > 10x or < 0.1x from median
    ratio = price / median
    return ratio > max_deviation or ratio < (1.0 / max_deviation)


def extract_prices(scan: dict, rh: dict) -> dict[str, list[PriceEvidence]]:
    """
    Extract observed prices by pair from both PASS quotes and FAIL samples.
    
    v3.2.25: Processes full rejects list, not just price_sanity_samples.
    Tracks source (PASS/FAIL) separately for quality assessment.
    """
    pair_evidence: dict[str, list[PriceEvidence]] = defaultdict(list)
    
    # From PASS quotes (quotes_sample) - high quality
    for q in scan.get("quotes_sample", []):
        token_in = q.get("token_in")
        token_out = q.get("token_out")
        price_exact = q.get("price_exact")
        
        if token_in and token_out and price_exact:
            try:
                pair_key = normalize_pair_key(token_in, token_out)
                pair_evidence[pair_key].append(PriceEvidence(float(price_exact), "PASS"))
            except (ValueError, TypeError):
                pass
    
    # From full rejects list - filter for PRICE_SANITY_FAILED only
    for reject in rh.get("rejects", []):
        if reject.get("reason") != "PRICE_SANITY_FAILED":
            continue
        
        pair = reject.get("pair", "")
        price_exact = reject.get("price_exact")
        
        if pair and price_exact:
            try:
                t_in, t_out = parse_pair_string(pair)
                if t_in and t_out:
                    pair_key = normalize_pair_key(t_in, t_out)
                    pair_evidence[pair_key].append(PriceEvidence(float(price_exact), "FAIL"))
            except (ValueError, TypeError):
                pass
    
    # Also check legacy price_sanity_samples (fallback for older artifacts)
    for sample in rh.get("price_sanity_samples", []):
        pair = sample.get("pair")
        price_exact = sample.get("price_exact")
        
        if pair and price_exact:
            try:
                t_in, t_out = parse_pair_string(pair)
                if t_in and t_out:
                    pair_key = normalize_pair_key(t_in, t_out)
                    pair_evidence[pair_key].append(PriceEvidence(float(price_exact), "FAIL"))
            except (ValueError, TypeError):
                pass
    
    return dict(pair_evidence)


def compute_anchor_suggestions(
    pair_evidence: dict[str, list[PriceEvidence]],
    weth_usd: float = 2100.0
) -> tuple[dict[str, float], dict[str, float], dict[str, dict]]:
    """
    Compute suggested anchor prices and USD prices.
    
    v3.2.25: Uses outlier filtering and prefers PASS quotes over FAIL.
    
    Returns:
        (anchors, usd_prices, statistics)
    """
    anchors: dict[str, float] = {}
    usd_prices: dict[str, float] = {}
    stats: dict[str, dict] = {}
    
    for pair_key, evidence_list in pair_evidence.items():
        if not evidence_list:
            continue
        
        # Separate PASS and FAIL
        pass_prices = [e.price for e in evidence_list if e.source == "PASS"]
        fail_prices = [e.price for e in evidence_list if e.source == "FAIL"]
        
        # Prefer PASS quotes if available, otherwise use FAIL (they have actual market prices)
        if pass_prices:
            prices = pass_prices
            primary_source = "PASS"
        else:
            prices = fail_prices
            primary_source = "FAIL"
        
        # Apply outlier filtering if we have enough samples
        if len(prices) >= 3:
            median = statistics.median(prices)
            filtered = [p for p in prices if not is_outlier(p, prices)]
            if filtered:
                prices = filtered
        
        if not prices:
            continue
        
        median_price = statistics.median(prices)
        anchors[pair_key] = median_price
        
        stats[pair_key] = {
            "median": median_price,
            "n_pass": len(pass_prices),
            "n_fail": len(fail_prices),
            "primary_source": primary_source,
            "min": min(prices),
            "max": max(prices),
        }
    
    # Extract WETH_USDC baseline from PASS quotes preferably
    weth_usdc_ev = pair_evidence.get("WETH_USDC", [])
    pass_weth_usdc = [e.price for e in weth_usdc_ev if e.source == "PASS"]
    if pass_weth_usdc:
        weth_usd = statistics.median(pass_weth_usdc)
    elif "WETH_USDC" in anchors:
        weth_usd = anchors["WETH_USDC"]
    
    usd_prices["WETH"] = weth_usd
    
    # Fixed USD prices for stablecoins
    for stable in ["USDC", "USDT", "DAI", "LUSD", "USDE"]:
        usd_prices[stable] = 1.0
    
    # Derive USD prices from anchors
    for pair_key, median_price in anchors.items():
        parts = pair_key.split("_")
        if len(parts) != 2:
            continue
        token_in, token_out = parts
        
        # If denominated in USDC/USDT/DAI, price_exact IS the USD price
        if token_out in ["USDC", "USDT", "DAI"]:
            usd_prices[token_in] = median_price
        
        # If denominated in WETH, derive USD price
        elif token_out == "WETH" and weth_usd > 0:
            usd_prices[token_in] = median_price * weth_usd
        
        # If WETH is token_in (e.g., WETH_ARB), derive inverse
        elif token_in == "WETH" and median_price > 0:
            derived_usd = weth_usd / median_price
            if token_out not in usd_prices:
                usd_prices[token_out] = derived_usd
    
    return anchors, usd_prices, stats


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
                        help="Reference WETH/USD price (default: 2100, auto-detected if WETH_USDC PASS quotes exist)")
    parser.add_argument("--json", action="store_true", help="Output as strict JSON (no preamble, suitable for automation)")
    args = parser.parse_args()
    
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        if args.json:
            print(json.dumps({"error": f"Run dir not found: {run_dir}"}))
        else:
            print(f"ERROR: Run dir not found: {run_dir}", file=sys.stderr)
        return 1
    
    try:
        scan, rh = load_artifacts(run_dir)
    except FileNotFoundError as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    
    # Extract prices with source tracking
    pair_evidence = extract_prices(scan, rh)
    
    if not pair_evidence:
        if args.json:
            print(json.dumps({"error": "No prices found in artifacts"}))
        else:
            print("WARNING: No prices found in artifacts", file=sys.stderr)
        return 1
    
    # Compute suggestions with outlier filtering
    anchors, usd_prices, stats = compute_anchor_suggestions(pair_evidence, args.weth_usd)
    
    if args.json:
        # v3.2.25: Strict JSON output - no preamble, no comments
        result = {
            "anchors": anchors,
            "usd_prices": usd_prices,
            "statistics": stats,
            "source_run_dir": str(run_dir),
            "weth_usd_baseline": usd_prices.get("WETH", args.weth_usd),
        }
        print(json.dumps(result, indent=2))
    else:
        # Human-readable output with context
        print(f"# Found prices for {len(pair_evidence)} pairs from {run_dir.name}")
        print(f"# Evidence: PASS quotes_sample + FAIL PRICE_SANITY_FAILED rejects")
        print(f"# WETH/USDC baseline: {usd_prices.get('WETH', args.weth_usd):.2f}")
        print()
        
        # Print per-pair statistics
        print("# === OBSERVED PRICES BY PAIR ===")
        for pair in sorted(stats.keys()):
            s = stats[pair]
            print(f"# {pair}: median={s['median']:.8f}, range=[{s['min']:.8f}, {s['max']:.8f}], "
                  f"n_pass={s['n_pass']}, n_fail={s['n_fail']}, source={s['primary_source']}")
        print()
        
        # Print YAML snippets
        print(format_yaml_snippet(anchors, usd_prices))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
