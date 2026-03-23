#!/usr/bin/env python3
# PATH: scripts/generate_intent.py
"""
Generate intent.txt from tiered token metadata in core_tokens.yaml.

v3.3.0: Quality-ranked pair selection (R39d).

Instead of blindly pairing every token with WETH/USDC, this script reads
per-token tier metadata (productive_default, accounting_sensitive, volatility_tier,
liquidity_tier, cross_dex_expected) and selects pairs by tier:

  PRODUCTIVE: volatile + liquid + multi-DEX tokens → default scanning universe
  EXPLORATORY: lower-tier but still interesting tokens → opt-in only
  DIAGNOSTIC: stable/stable, LST/LRT, near-stable → calibration class

Pair rules (per tier):
  1. Every productive token paired with WETH + USDC (anchor quote tokens)
  2. WETH/WBTC + WBTC/USDC where both productive
  3. Chain-native wrapper pairs (WMNT/USDC, WMNT/USDT on mantle)
  4. WETH/USDC anchor always included (price reference)
  5. Stablecoins and LST tokens excluded from productive by default

Usage:
    py -3.11 scripts/generate_intent.py                      # Preview productive (dry-run)
    py -3.11 scripts/generate_intent.py --write               # Overwrite intent.txt
    py -3.11 scripts/generate_intent.py --tier all            # Show all tiers
    py -3.11 scripts/generate_intent.py --tier exploratory    # Show exploratory only
    py -3.11 scripts/generate_intent.py --diff                # Show diff vs current

Exit codes: 0=OK, 1=ERROR
"""

import argparse
import difflib
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
CORE_TOKENS_PATH = PROJECT_ROOT / "config" / "core_tokens.yaml"
INTENT_PATH = PROJECT_ROOT / "config" / "intent.txt"

# ──────────────────────────────────────────────────────────────
# Tier classification
# ──────────────────────────────────────────────────────────────

# Infrastructure tokens — never directly paired (used as quote/anchor only)
INFRA_TOKENS = {s.lower() for s in ["USDC", "USDC_E", "USDT", "DAI", "FRAX", "LUSD", "USDE", "mUSD"]}

# Platform-native wrapped tokens that act as WETH equivalents
WETH_EQUIVALENTS = {"WETH", "WMNT"}

# Tokens that are accounting-sensitive (LST/LRT) — detected from yaml metadata
# Fallback set for tokens without metadata
KNOWN_LST = {s.lower() for s in [
    "wstETH", "WSTETH", "rETH", "RETH", "ezETH", "weETH", "STONE",
    "cbETH", "mETH", "cmETH",
]}


def load_core_tokens() -> dict:
    """Load core_tokens.yaml: chain -> {symbol: {...metadata}}."""
    with open(CORE_TOKENS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def classify_token(sym: str, meta: dict) -> str:
    """
    Classify a token into a tier based on its metadata.

    Returns: 'productive', 'exploratory', or 'diagnostic'
    """
    low = sym.lower()

    # Infrastructure (stables, near-stables) → always diagnostic
    if low in INFRA_TOKENS:
        return "diagnostic"

    # WETH equivalents → infrastructure, skip (handled as anchor)
    if sym in WETH_EQUIVALENTS:
        return "productive"  # Always included as anchor

    # Check metadata
    is_accounting_sensitive = meta.get("accounting_sensitive", low in KNOWN_LST)
    is_productive = meta.get("productive_default", False)

    if is_accounting_sensitive:
        return "diagnostic"

    if is_productive:
        return "productive"

    return "exploratory"


def generate_pairs_for_chain(
    chain: str,
    tokens: dict[str, dict],
    tier_filter: str = "productive",
) -> list[str]:
    """
    Generate intent pairs for a single chain using tiered selection.

    tier_filter:
      'productive'   -> only productive tokens (default intent.txt)
      'exploratory'  -> productive + exploratory
      'all'          -> all tiers (including diagnostic)
      'diagnostic'   -> only diagnostic pairs (LST, stables)
      'calibration'  -> productive + near-zero benchmark pairs (USDC/DAI, USDC/USDT, WETH/USDC, WBTC/USDC)
    """
    # Deduplicate tokens by lowercase (prefer the original-case version)
    seen_lower: dict[str, tuple[str, dict]] = {}
    for sym, meta in tokens.items():
        low = sym.lower()
        if low not in seen_lower:
            seen_lower[low] = (sym, meta or {})

    # Classify all tokens
    token_tiers: dict[str, str] = {}  # sym -> tier
    for low, (sym, meta) in seen_lower.items():
        token_tiers[sym] = classify_token(sym, meta)

    # Determine which tokens pass the tier filter
    tier_order = {"productive": 0, "exploratory": 1, "diagnostic": 2}
    if tier_filter == "productive":
        max_tier = 0
    elif tier_filter == "exploratory":
        max_tier = 1
    elif tier_filter == "all":
        max_tier = 2
    elif tier_filter == "diagnostic":
        # Special: only diagnostic
        eligible = {s for s, t in token_tiers.items() if t == "diagnostic"}
        return _generate_diagnostic_pairs(chain, eligible, set(token_tiers.keys()))
    elif tier_filter == "calibration":
        # Productive + calibration benchmark pairs
        max_tier = 0
    else:
        max_tier = 0

    eligible = {s for s, t in token_tiers.items() if tier_order.get(t, 2) <= max_tier}
    symbols = set(token_tiers.keys())  # all symbols for anchor detection

    pairs: set[tuple[str, str]] = set()

    # 1. Anchor: WETH/USDC (always)
    if "WETH" in symbols and "USDC" in symbols:
        pairs.add(("WETH", "USDC"))

    # Calibration benchmark pairs (near-zero reference)
    if tier_filter == "calibration":
        if "USDC" in symbols and "DAI" in symbols:
            pairs.add(("USDC", "DAI"))
        if "USDC" in symbols and "USDT" in symbols:
            pairs.add(("USDC", "USDT"))
        if "WBTC" in symbols and "USDC" in symbols:
            pairs.add(("WBTC", "USDC"))

    # 2. Chain-native wrapper pairs (mantle WMNT)
    if "WMNT" in eligible:
        if "USDC" in symbols:
            pairs.add(("WMNT", "USDC"))
        if "USDT" in symbols:
            pairs.add(("WMNT", "USDT"))
        if "WETH" in symbols:
            pairs.add(("WETH", "WMNT"))

    # 3. Every eligible non-infra token paired with WETH
    for sym in sorted(eligible):
        if sym in WETH_EQUIVALENTS:
            continue
        if sym.lower() in INFRA_TOKENS:
            continue
        if "WETH" in symbols:
            pairs.add(("WETH", sym) if "WETH" > sym else (sym, "WETH"))

    # 4. Every eligible non-infra, non-LST token paired with USDC
    for sym in sorted(eligible):
        if sym in WETH_EQUIVALENTS:
            continue
        if sym.lower() in INFRA_TOKENS:
            continue
        meta = seen_lower.get(sym.lower(), (sym, {}))[1]
        is_lst = meta.get("accounting_sensitive", sym.lower() in KNOWN_LST)
        if is_lst:
            continue
        if "USDC" in symbols:
            pairs.add((sym, "USDC"))

    # 5. WETH/WBTC + WBTC/USDC if both productive
    if "WBTC" in eligible:
        if "WETH" in symbols:
            pairs.add(("WETH", "WBTC"))
        if "USDC" in symbols:
            pairs.add(("WBTC", "USDC"))

    # Normalize and sort
    result = []
    for a, b in sorted(pairs):
        result.append(f"{chain}:{a}/{b}")

    return result


def _generate_diagnostic_pairs(
    chain: str,
    diagnostic_tokens: set[str],
    all_symbols: set[str],
) -> list[str]:
    """Generate diagnostic-only pairs (stable/stable, LST/WETH)."""
    pairs: set[tuple[str, str]] = set()

    for sym in sorted(diagnostic_tokens):
        low = sym.lower()
        # Stablecoin cross-pairs
        if low in INFRA_TOKENS:
            if low in ("usdt",) and "USDC" in all_symbols:
                pairs.add(("USDC", "USDT"))
            if low in ("dai",) and "USDC" in all_symbols:
                pairs.add(("USDC", "DAI"))
            continue
        # LST tokens → pair with WETH + USDC
        if low in KNOWN_LST or low in KNOWN_LST:
            if "WETH" in all_symbols:
                pairs.add((sym, "WETH"))
            if "USDC" in all_symbols:
                pairs.add((sym, "USDC"))

    result = []
    for a, b in sorted(pairs):
        result.append(f"{chain}:{a}/{b}")
    return result


def generate_intent(tier_filter: str = "productive") -> str:
    """Generate full intent.txt content from core_tokens.yaml with tiered selection."""
    data = load_core_tokens()

    tier_label = {
        "productive": "Productive contour (volatile + liquid + multi-DEX)",
        "exploratory": "Productive + Exploratory",
        "all": "All tiers (productive + exploratory + diagnostic)",
        "diagnostic": "Diagnostic only (stable/stable, LST/LRT)",
        "calibration": "Productive + calibration benchmarks (USDC/DAI, USDC/USDT, WETH/USDC, WBTC/USDC)",
    }.get(tier_filter, "Productive contour")

    lines = [
        "# intent.txt — Quality-ranked trading universe (v3.3.0)",
        "# Source: config/core_tokens.yaml (tiered token metadata)",
        "# Generated by: scripts/generate_intent.py",
        f"# Tier: {tier_label}",
        "# Format: <chain_key>:<BASE>/<QUOTE>",
        "#",
        "# Selection policy (R39d):",
        "#   - Productive: volatile + liquid + multi-DEX tokens (default)",
        "#   - Stable/stable, LST/LRT, thin long-tail excluded from productive",
        "#   - Use --tier exploratory or --tier all for expanded universe",
        "",
    ]

    chain_order = ["arbitrum_one", "base", "linea", "scroll", "mantle", "zksync"]

    for chain in chain_order:
        tokens = data.get(chain, {})
        if not tokens:
            continue

        pairs = generate_pairs_for_chain(chain, tokens, tier_filter)
        if not pairs:
            continue

        # Count productive tokens for header
        productive_count = sum(
            1 for s, m in tokens.items()
            if classify_token(s, m or {}) == "productive"
        )

        lines.append(f"# {'=' * 60}")
        lines.append(
            f"# {chain.upper().replace('_', ' ')} "
            f"({len(pairs)} pairs, {productive_count} productive tokens)"
        )
        lines.append(f"# {'=' * 60}")
        lines.append("")
        for pair_str in pairs:
            lines.append(pair_str)
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate intent.txt from core_tokens.yaml (tiered)")
    parser.add_argument("--write", action="store_true", help="Overwrite config/intent.txt")
    parser.add_argument("--diff", action="store_true", help="Show diff vs current intent.txt")
    parser.add_argument(
        "--tier",
        choices=["productive", "exploratory", "all", "diagnostic", "calibration"],
        default="productive",
        help="Which tier to generate (default: productive)",
    )
    args = parser.parse_args()

    generated = generate_intent(tier_filter=args.tier)

    if args.diff:
        current = INTENT_PATH.read_text(encoding="utf-8") if INTENT_PATH.exists() else ""
        diff = difflib.unified_diff(
            current.splitlines(keepends=True),
            generated.splitlines(keepends=True),
            fromfile="config/intent.txt (current)",
            tofile="config/intent.txt (generated)",
        )
        diff_text = "".join(diff)
        if diff_text:
            print(diff_text)
            print(f"\nDiff found. Use --write to apply.")
        else:
            print("No differences.")
        return

    if args.write:
        INTENT_PATH.write_text(generated, encoding="utf-8")
        lines = [l for l in generated.split("\n") if l and not l.startswith("#")]
        print(f"Wrote {len(lines)} pairs to {INTENT_PATH} (tier={args.tier})")
        return

    # Default: dry-run preview
    print(generated)
    lines = [l for l in generated.split("\n") if l and not l.startswith("#")]
    print(f"\n# Total: {len(lines)} pairs (tier={args.tier}, dry-run, use --write to apply)")


if __name__ == "__main__":
    main()
