#!/usr/bin/env python3
"""Script to identify unresolvable pairs and missing tokens."""

import sys
import os

# Add project root to path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discovery.index_factories import count_discovery_candidates
from discovery.intent_loader import get_intent_universe
from discovery.verify import get_token_registry


def main():
    chain = "arbitrum_one"
    universe = get_intent_universe()
    registry = get_token_registry()
    pairs = universe.get_pairs_for_chain(chain)

    missing = []
    for pair in pairs:
        addr_a = registry.get_address(chain, pair.token_a)
        addr_b = registry.get_address(chain, pair.token_b)
        if not addr_a or not addr_b:
            missing_tokens = []
            if not addr_a:
                missing_tokens.append(pair.token_a)
            if not addr_b:
                missing_tokens.append(pair.token_b)
            missing.append({
                "pair": f"{pair.token_a}/{pair.token_b}",
                "missing": missing_tokens,
            })

    print(f"Unresolvable pairs ({len(missing)}):")
    for m in missing:
        print(f"  {m['pair']}: missing {m['missing']}")

    all_missing = set()
    for m in missing:
        for t in m["missing"]:
            all_missing.add(t)
    print(f"\nMissing tokens: {sorted(all_missing)}")


if __name__ == "__main__":
    main()
