#!/usr/bin/env python3
"""
M7.A — Static enumeration of triangular cycles from verified pool cache.

Builds a PoolGraph from the pool_resolver_cache (offline, no RPC),
applies the M7.A narrow universe filter, enumerates 3-hop cycles,
scores by fee structure (diagnostic prefilter), and outputs a summary.

This is the first runtime evidence for M7 triangular feasibility.

Usage:
    python scripts/m7a_enumerate_cycles.py
    python scripts/m7a_enumerate_cycles.py --output data/tmp/m7a_cycles.json
    python scripts/m7a_enumerate_cycles.py --chain arbitrum_one --max-cycles 5000
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure repository root is on sys.path so `python scripts/m7a_enumerate_cycles.py` works
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Project imports
from config import get_all_token_addresses, load_core_tokens, load_dexes
from discovery.index_factories import get_dex_adapter_type
from engine.triangular_graph import (
    M7A_DEXES_ARBITRUM_ONE,
    M7A_STABLE_ADAPTERS,
    M7A_TOKENS_ARBITRUM_ONE,
    PoolEdge,
    PoolGraph,
    filter_graph_to_m7a_universe,
)
from engine.triangular_cycles import (
    filter_viable_fee_structures,
    find_3hop_cycles,
    rank_cycles_by_net,
    score_cycle_fees_only,
)

logger = logging.getLogger("scripts.m7a_enumerate_cycles")


def _load_pool_resolver_cache(chain: str) -> Dict[str, str]:
    """Load pool_resolver_cache_{chain}.json from data/cache/."""
    cache_path = Path(f"data/cache/pool_resolver_cache_{chain}.json")
    if not cache_path.exists():
        logger.error("Pool resolver cache not found: %s", cache_path)
        return {}
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("pools", {})


def _build_address_to_symbol(chain: str) -> Dict[str, str]:
    """Build lowercase-address -> symbol mapping from core_tokens.yaml."""
    addr_map = get_all_token_addresses(chain)
    return {addr.lower(): symbol for symbol, addr in addr_map.items()}


def build_graph_from_resolver_cache(chain: str) -> PoolGraph:
    """Build a PoolGraph from the pool_resolver_cache.

    Each cache entry is:
      key: "{chain}:{dex}:{addr_token0_lower}:{addr_token1_lower}:{fee}"
      value: pool_address or "__NULL__"
    """
    pools_cache = _load_pool_resolver_cache(chain)
    addr_to_sym = _build_address_to_symbol(chain)
    tokens_config = load_core_tokens().get(chain, {})

    graph = PoolGraph(chain=chain)
    skipped_null = 0
    skipped_unknown_token = 0

    for cache_key, pool_address in pools_cache.items():
        if pool_address == "__NULL__":
            skipped_null += 1
            continue

        parts = cache_key.split(":")
        if len(parts) != 5:
            continue
        c_chain, c_dex, c_addr0, c_addr1, c_fee_str = parts
        if c_chain != chain:
            continue

        sym0 = addr_to_sym.get(c_addr0.lower())
        sym1 = addr_to_sym.get(c_addr1.lower())
        if not sym0 or not sym1:
            skipped_unknown_token += 1
            continue

        fee: Optional[int] = None
        try:
            fee = int(c_fee_str)
        except ValueError:
            pass  # V2 or non-numeric

        adapter_type = get_dex_adapter_type(chain, c_dex) or c_dex

        # Get decimals from core_tokens config
        dec0 = tokens_config.get(sym0, {}).get("decimals", 18) if isinstance(tokens_config.get(sym0), dict) else 18
        dec1 = tokens_config.get(sym1, {}).get("decimals", 18) if isinstance(tokens_config.get(sym1), dict) else 18

        edge = PoolEdge(
            token_in=sym0,
            token_out=sym1,
            pool_address=pool_address,
            dex=c_dex,
            adapter_type=adapter_type,
            fee=fee,
            chain=chain,
            decimals_in=dec0,
            decimals_out=dec1,
        )
        graph.add_pool(edge)

    logger.info(
        "Built graph from resolver cache: chain=%s nodes=%d edges=%d "
        "(skipped_null=%d, skipped_unknown_token=%d)",
        chain, graph.node_count, graph.edge_count,
        skipped_null, skipped_unknown_token,
    )
    return graph


def _fee_distribution(cycles: list) -> Dict[str, int]:
    """Compute fee structure distribution across cycles."""
    counter: Counter = Counter()
    for c in cycles:
        fees = sorted([c.leg1.fee, c.leg2.fee, c.leg3.fee],
                      key=lambda f: f if f is not None else -1)
        label = "/".join(str(f) if f is not None else "v2" for f in fees)
        counter[label] += 1
    return dict(counter.most_common())


def _dex_distribution(cycles: list) -> Dict[str, int]:
    """Compute DEX usage distribution across cycle legs."""
    counter: Counter = Counter()
    for c in cycles:
        for leg in c.legs():
            counter[leg.dex] += 1
    return dict(counter.most_common())


def _multi_dex_breakdown(cycles: list) -> Dict[str, int]:
    """Count how many distinct DEXes each cycle uses."""
    counter: Counter = Counter()
    for c in cycles:
        n_dexes = len({c.leg1.dex, c.leg2.dex, c.leg3.dex})
        counter[f"{n_dexes}_dex"] += 1
    return dict(counter.most_common())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="M7.A: Enumerate triangular cycles from verified pool cache",
    )
    parser.add_argument("--chain", default="arbitrum_one", help="Chain key")
    parser.add_argument("--max-cycles", type=int, default=10_000, help="Max cycles to enumerate")
    parser.add_argument("--output", default=None, help="Output JSON path (default: stdout summary)")
    parser.add_argument("--max-fee-bps", type=float, default=100.0,
                        help="Max total fee bps for viable filter")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    chain = args.chain

    # 1. Build full graph from resolver cache
    full_graph = build_graph_from_resolver_cache(chain)
    if full_graph.edge_count == 0:
        logger.error("No edges in graph — check pool_resolver_cache_%s.json", chain)
        return 1

    # 2. Apply M7.A universe filter
    m7a_graph = filter_graph_to_m7a_universe(full_graph)

    # 3. Enumerate cycles
    cycles = find_3hop_cycles(m7a_graph, max_cycles=args.max_cycles)

    # 4. Filter by fee viability
    viable = filter_viable_fee_structures(cycles, max_total_fee_bps=args.max_fee_bps)

    # 5. Score by fee structure (diagnostic prefilter)
    scores = [score_cycle_fees_only(c) for c in viable]
    ranked = rank_cycles_by_net(scores)

    # 6. Build summary
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary: Dict[str, Any] = {
        "m7a_enumeration": True,
        "timestamp": ts,
        "chain": chain,
        "full_graph": full_graph.to_summary(),
        "m7a_graph": m7a_graph.to_summary(),
        "m7a_universe": {
            "tokens": sorted(M7A_TOKENS_ARBITRUM_ONE),
            "dexes": sorted(M7A_DEXES_ARBITRUM_ONE),
            "stable_adapters": sorted(M7A_STABLE_ADAPTERS),
        },
        "cycles": {
            "total_found": len(cycles),
            "viable_after_fee_filter": len(viable),
            "max_fee_bps_threshold": args.max_fee_bps,
        },
        "fee_distribution": _fee_distribution(viable),
        "dex_distribution": _dex_distribution(viable),
        "multi_dex_breakdown": _multi_dex_breakdown(viable),
        "top_10_by_lowest_cost": [s.to_dict() for s in ranked[:10]],
    }

    if ranked:
        summary["best_fee_cost_bps"] = round(ranked[0].final_net_bps, 4)
        summary["worst_fee_cost_bps"] = round(ranked[-1].final_net_bps, 4)
        summary["median_fee_cost_bps"] = round(
            ranked[len(ranked) // 2].final_net_bps, 4
        )

    # 7. Output
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        logger.info("Written to %s", out_path)
    else:
        # Print human-readable summary to stdout
        print(f"\n=== M7.A Triangular Cycle Enumeration ({chain}) ===")
        print(f"Full graph: {full_graph.node_count} tokens, {full_graph.edge_count} edges")
        print(f"M7.A graph: {m7a_graph.node_count} tokens, {m7a_graph.edge_count} edges")
        print(f"Cycles found: {len(cycles)} total, {len(viable)} viable (fee <= {args.max_fee_bps} bps)")
        if ranked:
            print(f"Best fee cost: {ranked[0].final_net_bps:.1f} bps")
            print(f"Median fee cost: {ranked[len(ranked)//2].final_net_bps:.1f} bps")
            print(f"\nTop 5 lowest-cost cycles:")
            for i, s in enumerate(ranked[:5], 1):
                print(f"  {i}. {s.cycle.route_display} "
                      f"[fee={s.total_fee_bps:.0f}bps, net={s.final_net_bps:.1f}bps] "
                      f"dexes={','.join(set(l.dex for l in s.cycle.legs()))}")
        print(f"\nFee structure distribution: {summary['fee_distribution']}")
        print(f"DEX leg distribution: {summary['dex_distribution']}")
        print(f"Multi-DEX breakdown: {summary['multi_dex_breakdown']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
