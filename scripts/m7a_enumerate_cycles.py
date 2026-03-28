#!/usr/bin/env python3
"""
M7.A — Enumeration of triangular cycles from verified pool sources.

Supports two graph sources:
  --source cache    (default) Build from pool_resolver_cache (offline, no RPC)
  --source runtime  Build from live RuntimePair via discovery.runtime (requires RPC)

Supports two scoring modes:
  --score fees      (default) Diagnostic fee-structure-only scoring (no RPC quotes)
  --score measured  Live per-leg quoting via adapter RPC, fed into score_cycle_measured()

Usage:
    python scripts/m7a_enumerate_cycles.py
    python scripts/m7a_enumerate_cycles.py --source runtime --score measured --output data/tmp/m7a_cycles.json
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
from typing import Any, Dict, List, Optional, Tuple

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
    build_graph_from_runtime_pairs,
    filter_graph_to_m7a_universe,
)
from engine.triangular_cycles import (
    LegQuote,
    TriangularCycle,
    filter_viable_fee_structures,
    find_3hop_cycles,
    leg_quote_from_rpc_result,
    rank_cycles_by_net,
    score_cycle_fees_only,
    score_cycle_measured,
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


def build_graph_from_live_runtime(chain: str) -> PoolGraph:
    """Build a PoolGraph from live RuntimePair via discovery.runtime.

    This is the end-to-end verified runtime path: intent.txt -> pool_resolver
    -> factory.getPool() -> RuntimePair -> PoolGraph.

    Uses all M7.A-eligible DEXes and the full intent universe.
    """
    from discovery.runtime import resolve_runtime_pairs

    dexes = sorted(M7A_DEXES_ARBITRUM_ONE)
    pairs, stats = resolve_runtime_pairs(
        chain=chain,
        dexes=dexes,
        max_pairs=100,
        require_cross_dex=False,
    )
    logger.info(
        "Runtime discovery: %d pairs, %d pools (rpc_calls=%d, cache=%d)",
        stats.pairs_resolved, stats.pools_resolved,
        stats.rpc_calls, stats.pools_from_cache,
    )
    return build_graph_from_runtime_pairs(chain, pairs)


# ---------------------------------------------------------------------------
# Live per-leg quoting (reuses existing RPC readers, no new quote format)
# ---------------------------------------------------------------------------

def _quote_single_leg(
    edge: PoolEdge,
    amount_in_wei: int,
    rpc_url: str,
    block_number: int,
    dex_configs: Dict[str, Any],
    token_addresses: Dict[str, str],
) -> Optional[LegQuote]:
    """Quote a single leg via the appropriate adapter RPC reader.

    Dispatches to read_quoter_v2 / read_algebra_quoter / read_ve33_amount_out
    based on edge.adapter_type. Returns LegQuote or None on failure.
    """
    from strategy.quote_rpc import read_quoter_v2
    from strategy.quote_adapters import read_algebra_quoter, read_ve33_amount_out

    token_in_addr = token_addresses.get(edge.token_in, "")
    token_out_addr = token_addresses.get(edge.token_out, "")
    if not token_in_addr or not token_out_addr:
        logger.debug("Missing address for %s or %s", edge.token_in, edge.token_out)
        return None

    adapter = edge.adapter_type
    rpc_result: Optional[Dict[str, Any]] = None
    source = adapter

    if adapter in ("uniswap_v3",):
        dex_cfg = dex_configs.get(edge.dex)
        quoter_addr = dex_cfg.get_quoter_address() if dex_cfg else None
        if not quoter_addr:
            logger.debug("No quoter for %s", edge.dex)
            return None
        rpc_result = read_quoter_v2(
            quoter_addr, token_in_addr, token_out_addr,
            amount_in_wei, edge.fee or 3000, rpc_url, block_number,
        )
        source = "quoter_v2"

    elif adapter in ("algebra",):
        dex_cfg = dex_configs.get(edge.dex)
        quoter_addr = dex_cfg.get_quoter_address() if dex_cfg else None
        if not quoter_addr:
            logger.debug("No quoter for %s", edge.dex)
            return None
        rpc_result = read_algebra_quoter(
            quoter_addr, token_in_addr, token_out_addr,
            amount_in_wei, rpc_url, block_number,
        )
        source = "algebra_quoter"

    elif adapter in ("uniswap_v2", "ve33"):
        amount_out = read_ve33_amount_out(
            edge.pool_address, token_in_addr, amount_in_wei,
            rpc_url, block_number,
        )
        if amount_out is not None and amount_out > 0:
            rpc_result = {
                "amount_out": amount_out,
                "gas_estimate": 80_000,
                "ticks_crossed": None,
                "sqrt_price_after": None,
            }
        source = "ve33_getAmountOut"

    else:
        logger.debug("Unsupported adapter_type=%s for %s", adapter, edge.edge_key)
        return None

    # Handle rate-limit sentinel from read_quoter_v2
    if rpc_result is not None and rpc_result.get("_rate_limited"):
        logger.warning("Rate limited on %s", edge.edge_key)
        return None

    return leg_quote_from_rpc_result(
        rpc_result,
        amount_in_wei=amount_in_wei,
        fee_tier=edge.fee,
        block_number=block_number,
        quote_source=source,
    )


def quote_cycle_3legs(
    cycle: TriangularCycle,
    starting_amount_wei: int,
    rpc_url: str,
    block_number: int,
    dex_configs: Dict[str, Any],
    token_addresses: Dict[str, str],
) -> Tuple[Optional[LegQuote], Optional[LegQuote], Optional[LegQuote]]:
    """Quote all 3 legs of a cycle sequentially, chaining amounts.

    leg1.amount_out -> leg2.amount_in -> leg3.amount_in.
    Returns (q1, q2, q3). Any None means that leg (and downstream) failed.
    """
    q1 = _quote_single_leg(
        cycle.leg1, starting_amount_wei, rpc_url, block_number,
        dex_configs, token_addresses,
    )
    if q1 is None:
        return None, None, None

    q2 = _quote_single_leg(
        cycle.leg2, q1.amount_out_wei, rpc_url, block_number,
        dex_configs, token_addresses,
    )
    if q2 is None:
        return q1, None, None

    q3 = _quote_single_leg(
        cycle.leg3, q2.amount_out_wei, rpc_url, block_number,
        dex_configs, token_addresses,
    )
    return q1, q2, q3


def _get_current_block(rpc_url: str) -> Optional[int]:
    """Get current block number from RPC."""
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        return w3.eth.block_number
    except Exception as e:
        logger.error("Failed to get block number: %s", e)
        return None


def _calculate_starting_amount(token: str, decimals: int) -> int:
    """Calculate starting amount for triangular cycle (100 USD notional)."""
    # Rough USD sizing matching strategy/quotes.py DEFAULT_TOKEN_USD_PRICES
    usd_prices = {"WETH": 2000.0, "USDC": 1.0, "USDT": 1.0, "DAI": 1.0,
                  "WBTC": 60000.0, "ARB": 0.5, "LINK": 15.0, "PENDLE": 3.0}
    price = usd_prices.get(token, 1.0)
    target_usd = 100.0
    amount_tokens = target_usd / price
    return int(amount_tokens * (10 ** decimals))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="M7.A: Enumerate triangular cycles from verified pool cache",
    )
    parser.add_argument("--chain", default="arbitrum_one", help="Chain key")
    parser.add_argument("--source", choices=["cache", "runtime"], default="cache",
                        help="Graph source: cache (offline) or runtime (live RPC)")
    parser.add_argument("--score", choices=["fees", "measured"], default="fees",
                        help="Scoring mode: fees (diagnostic) or measured (live RPC quotes)")
    parser.add_argument("--max-cycles", type=int, default=10_000, help="Max cycles to enumerate")
    parser.add_argument("--max-scored", type=int, default=200,
                        help="Max cycles to score in measured mode (RPC budget)")
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
    score_mode = args.score

    # 1. Build full graph from chosen source
    if args.source == "runtime":
        full_graph = build_graph_from_live_runtime(chain)
        graph_source = "runtime"
    else:
        full_graph = build_graph_from_resolver_cache(chain)
        graph_source = "cache"

    if full_graph.edge_count == 0:
        logger.error("No edges in graph — check %s source for %s", graph_source, chain)
        return 1

    # 2. Apply M7.A universe filter
    m7a_graph = filter_graph_to_m7a_universe(full_graph)

    # 3. Enumerate cycles
    cycles = find_3hop_cycles(m7a_graph, max_cycles=args.max_cycles)
    max_cycles_hit = len(cycles) >= args.max_cycles

    # 4. Filter by fee viability
    viable = filter_viable_fee_structures(cycles, max_total_fee_bps=args.max_fee_bps)

    # 5. Score
    if score_mode == "measured":
        scores, ranked, measured_stats = _score_measured(
            viable, chain, args.max_scored,
        )
    else:
        scores = [score_cycle_fees_only(c) for c in viable]
        ranked = rank_cycles_by_net(scores)
        measured_stats = None

    # 6. Build summary
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary: Dict[str, Any] = {
        "m7a_enumeration": True,
        "timestamp": ts,
        "chain": chain,
        "graph_source": graph_source,
        "score_mode": score_mode,
        "full_graph": full_graph.to_summary(),
        "m7a_graph": m7a_graph.to_summary(),
        "m7a_universe": {
            "tokens": sorted(M7A_TOKENS_ARBITRUM_ONE),
            "dexes": sorted(M7A_DEXES_ARBITRUM_ONE),
            "stable_adapters": sorted(M7A_STABLE_ADAPTERS),
        },
        "cycles": {
            "total_found": len(cycles),
            "max_cycles_cap": args.max_cycles,
            "max_cycles_hit": max_cycles_hit,
            "cycles_lower_bound": max_cycles_hit,
            "viable_after_fee_filter": len(viable),
            "max_fee_bps_threshold": args.max_fee_bps,
        },
        "fee_distribution": _fee_distribution(viable),
        "dex_distribution": _dex_distribution(viable),
        "multi_dex_breakdown": _multi_dex_breakdown(viable),
        "top_10_by_lowest_cost": [s.to_dict() for s in ranked[:10]],
    }

    if measured_stats:
        summary["measured"] = measured_stats

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
        print(f"\n=== M7.A Triangular Cycle Enumeration ({chain}, source={graph_source}, score={score_mode}) ===")
        print(f"Full graph: {full_graph.node_count} tokens, {full_graph.edge_count} edges")
        print(f"M7.A graph: {m7a_graph.node_count} tokens, {m7a_graph.edge_count} edges")
        cap_note = f" (CAP HIT — lower bound, not full count)" if max_cycles_hit else ""
        print(f"Cycles found: {len(cycles)} total{cap_note}, {len(viable)} viable (fee <= {args.max_fee_bps} bps)")
        if measured_stats:
            print(f"Measured: {measured_stats['scored']}/{measured_stats['attempted']} quoted, "
                  f"block={measured_stats.get('block_number', 'N/A')}")
            same_state = measured_stats.get("same_state_distribution", {})
            if same_state:
                print(f"Same-state: {same_state}")
        if ranked:
            print(f"Best net: {ranked[0].final_net_bps:.1f} bps [{ranked[0].provenance_summary}]")
            print(f"Median net: {ranked[len(ranked)//2].final_net_bps:.1f} bps")
            print(f"\nTop 5 cycles:")
            for i, s in enumerate(ranked[:5], 1):
                print(f"  {i}. {s.cycle.route_display} "
                      f"[gross={s.gross_bps:.1f}, gas={s.gas_bps:.1f}, net={s.final_net_bps:.1f}bps] "
                      f"same_state={s.same_state_class} "
                      f"dexes={','.join(set(l.dex for l in s.cycle.legs()))}")
        print(f"\nFee structure distribution: {summary['fee_distribution']}")
        print(f"DEX leg distribution: {summary['dex_distribution']}")
        print(f"Multi-DEX breakdown: {summary['multi_dex_breakdown']}")

    return 0


def _score_measured(
    viable: List[TriangularCycle],
    chain: str,
    max_scored: int,
) -> Tuple[list, list, Dict[str, Any]]:
    """Score viable cycles with live RPC quotes.

    Returns (all_scores, ranked_scores, measured_stats_dict).
    """
    from collections import Counter as _Counter
    from core.rpc_urls import get_rpc_url
    from dex.registry import load_dex_configs

    rpc_url = get_rpc_url(chain)
    if not rpc_url:
        logger.error("No RPC URL for %s — cannot do measured scoring", chain)
        scores = [score_cycle_fees_only(c) for c in viable]
        return scores, rank_cycles_by_net(scores), {"error": "no_rpc_url"}

    block_number = _get_current_block(rpc_url)
    if block_number is None:
        logger.error("Cannot get block number — falling back to fee-only scoring")
        scores = [score_cycle_fees_only(c) for c in viable]
        return scores, rank_cycles_by_net(scores), {"error": "no_block"}

    dex_configs = load_dex_configs(chain)
    token_addresses = get_all_token_addresses(chain)

    # Pre-sort by fee-only ranking so we quote the most promising first
    fee_scores = [score_cycle_fees_only(c) for c in viable]
    fee_ranked = rank_cycles_by_net(fee_scores)
    to_quote = [s.cycle for s in fee_ranked[:max_scored]]

    logger.info("Measured scoring: %d cycles, block=%d, rpc=%s",
                len(to_quote), block_number, rpc_url[:50])

    scores = []
    quote_attempted = 0
    quote_success = 0
    quote_failed = 0
    same_state_counter: _Counter = _Counter()

    for cycle in to_quote:
        quote_attempted += 1
        starting_amount = _calculate_starting_amount(
            cycle.leg1.token_in, cycle.leg1.decimals_in,
        )
        q1, q2, q3 = quote_cycle_3legs(
            cycle, starting_amount, rpc_url, block_number,
            dex_configs, token_addresses,
        )
        if q1 is None or q2 is None or q3 is None:
            quote_failed += 1
            # Still score what we can — use fee-only as fallback for failed quotes
            scores.append(score_cycle_fees_only(cycle))
            continue

        quote_success += 1
        s = score_cycle_measured(cycle, q1, q2, q3)
        scores.append(s)
        same_state_counter[s.same_state_class] += 1

    ranked = rank_cycles_by_net(scores)

    # Compute measured-specific stats
    measured_count = sum(1 for s in scores if s.provenance_summary == "measured")
    promoted_count = sum(1 for s in scores if s.is_promoted())
    best_measured = None
    for s in ranked:
        if s.provenance_summary == "measured":
            best_measured = round(s.final_net_bps, 4)
            break

    stats: Dict[str, Any] = {
        "block_number": block_number,
        "attempted": quote_attempted,
        "scored": quote_success,
        "failed": quote_failed,
        "measured_count": measured_count,
        "promoted_count": promoted_count,
        "best_measured_net_bps": best_measured,
        "same_state_distribution": dict(same_state_counter),
    }

    logger.info(
        "Measured scoring complete: %d/%d quoted, %d promoted, best_net=%s bps, "
        "same_state=%s",
        quote_success, quote_attempted, promoted_count, best_measured,
        dict(same_state_counter),
    )

    return scores, ranked, stats


if __name__ == "__main__":
    sys.exit(main())
