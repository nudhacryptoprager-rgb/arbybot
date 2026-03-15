#!/usr/bin/env python3
# PATH: scripts/generate_intent.py
"""
Generate intent.txt from verified token inventory + pair rules.

Reads config/core_tokens.yaml and generates trading pairs per chain
using deterministic pair rules:
  1. Every token paired with WETH (the universal quote)
  2. Every token paired with USDC (triangular closing)
  3. WETH/USDC anchor per chain (price reference)
  4. Stablecoin cross-pairs (USDC/USDT)
  5. LST pairs with WETH (wstETH, rETH, etc.)

Filters:
  - Only tokens with verified addresses in core_tokens.yaml
  - Skip self-pairs (e.g., WETH/WETH)
  - Skip USDC_E paired with USDC (too close)

Usage:
    py -3.11 scripts/generate_intent.py                      # Preview (dry-run)
    py -3.11 scripts/generate_intent.py --write               # Overwrite intent.txt
    py -3.11 scripts/generate_intent.py --diff                # Show diff vs current

Exit codes: 0=OK, 1=ERROR
"""

import argparse
import difflib
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
CORE_TOKENS_PATH = PROJECT_ROOT / "config" / "core_tokens.yaml"
INTENT_PATH = PROJECT_ROOT / "config" / "intent.txt"

# ──────────────────────────────────────────────────────────────
# Pair rules
# ──────────────────────────────────────────────────────────────

# Universal quote tokens (every non-quote token gets paired with these)
QUOTE_TOKENS = {"WETH", "USDC"}

# Stablecoin cross-pairs (always generated if both exist)
STABLE_PAIRS = [("USDC", "USDT"), ("USDC", "DAI")]

# Platform-native wrapped tokens that act as WETH equivalents
WETH_EQUIVALENTS = {"WETH", "WMNT"}  # WMNT is Mantle's native wrapper

# LST/LRT tokens — pair with WETH only (not USDC, too illiquid)
LST_TOKENS = {s.lower() for s in ["wstETH", "rETH", "ezETH", "weETH", "STONE", "cbETH", "mETH", "cmETH"]}

# Tokens to skip in USDC pairing (redundant or too close)
SKIP_USDC_PAIR = {s.lower() for s in ["USDC_E", "USDT", "DAI", "USDC", "WETH", "FRAX", "LUSD", "USDE"]}

# Tokens to skip in WETH pairing (not meaningful)
SKIP_WETH_PAIR = {s.lower() for s in ["WETH", "WMNT", "USDC", "USDC_E", "USDT", "DAI", "mUSD"]}

# Chain-specific native token pairs (pair with WETH and USDC)
CHAIN_NATIVE = {
    "arbitrum_one": "ARB",
    "base": "AERO",
    "linea": None,       # No native governance token with liquidity
    "scroll": "SCR",
    "mantle": "WMNT",
    "zksync": "ZK",
}


def load_core_tokens() -> dict:
    """Load core_tokens.yaml: chain -> {symbol: {...}}."""
    with open(CORE_TOKENS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def generate_pairs_for_chain(chain: str, tokens: dict) -> list[str]:
    """
    Generate intent pairs for a single chain.

    Returns list of 'chain:TOKENA/TOKENB' strings.
    """
    # Deduplicate tokens by lowercase (prefer the original-case version)
    seen_lower: dict[str, str] = {}
    for sym in tokens:
        low = sym.lower()
        if low not in seen_lower:
            seen_lower[low] = sym
    symbols = set(seen_lower.values())
    pairs = set()

    # 1. Anchor: WETH/USDC (or WMNT/USDC for mantle)
    if "WETH" in symbols and "USDC" in symbols:
        pairs.add(("WETH", "USDC"))
    if "WMNT" in symbols and "USDC" in symbols:
        pairs.add(("WMNT", "USDC"))
    if "WMNT" in symbols and "USDT" in symbols:
        pairs.add(("WMNT", "USDT"))
    if "WMNT" in symbols and "WETH" in symbols:
        pairs.add(("WETH", "WMNT"))

    # 2. Stablecoin cross-pairs
    for a, b in STABLE_PAIRS:
        if a in symbols and b in symbols:
            pairs.add((a, b))

    # 3. Every non-infrastructure token paired with WETH
    for sym in sorted(symbols):
        if sym.lower() not in SKIP_WETH_PAIR:
            if "WETH" in symbols:
                pairs.add(("WETH" if "WETH" > sym else sym, sym if "WETH" > sym else "WETH"))

    # 4. Every non-stable, non-infra token paired with USDC (triangular closing)
    for sym in sorted(symbols):
        if sym.lower() not in SKIP_USDC_PAIR and sym.lower() not in LST_TOKENS:
            if "USDC" in symbols:
                pairs.add((sym, "USDC"))

    # 5. LST/LRT tokens with WETH (and also USDC for closing)
    for sym in sorted(symbols):
        if sym.lower() in LST_TOKENS and "WETH" in symbols:
            pairs.add((sym, "WETH"))
        if sym.lower() in LST_TOKENS and "USDC" in symbols:
            pairs.add((sym, "USDC"))

    # 6. WETH/WBTC if both exist
    if "WETH" in symbols and "WBTC" in symbols:
        pairs.add(("WETH", "WBTC"))
    if "WBTC" in symbols and "USDC" in symbols:
        pairs.add(("WBTC", "USDC"))

    # Normalize: always BASE/QUOTE with alphabetical or WETH-first ordering
    result = []
    for a, b in sorted(pairs):
        result.append(f"{chain}:{a}/{b}")

    return result


def generate_intent() -> str:
    """Generate full intent.txt content from core_tokens.yaml."""
    data = load_core_tokens()

    lines = [
        "# intent.txt — Generated trading universe",
        "# Source: config/core_tokens.yaml (verified token inventory)",
        "# Generated by: scripts/generate_intent.py",
        "# Format: <chain_key>:<BASE>/<QUOTE>",
        "#",
        "# Rules:",
        "#   - Every verified token paired with WETH and USDC",
        "#   - Stablecoin cross-pairs (USDC/USDT, USDC/DAI)",
        "#   - LST tokens paired with WETH + USDC",
        "#   - WETH/WBTC + WBTC/USDC where available",
        "#   - Only tokens with verified addresses in core_tokens.yaml",
        "",
    ]

    chain_order = ["arbitrum_one", "base", "linea", "scroll", "mantle", "zksync"]

    for chain in chain_order:
        tokens = data.get(chain, {})
        if not tokens:
            continue

        pairs = generate_pairs_for_chain(chain, tokens)
        if not pairs:
            continue

        lines.append(f"# {'=' * 60}")
        lines.append(f"# {chain.upper().replace('_', ' ')} ({len(pairs)} pairs, {len(tokens)} tokens)")
        lines.append(f"# {'=' * 60}")
        lines.append("")
        for pair_str in pairs:
            lines.append(pair_str)
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate intent.txt from core_tokens.yaml")
    parser.add_argument("--write", action="store_true", help="Overwrite config/intent.txt")
    parser.add_argument("--diff", action="store_true", help="Show diff vs current intent.txt")
    args = parser.parse_args()

    generated = generate_intent()

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
        print(f"Wrote {len(lines)} pairs to {INTENT_PATH}")
        return

    # Default: dry-run preview
    print(generated)
    lines = [l for l in generated.split("\n") if l and not l.startswith("#")]
    print(f"\n# Total: {len(lines)} pairs (dry-run, use --write to apply)")


if __name__ == "__main__":
    main()
