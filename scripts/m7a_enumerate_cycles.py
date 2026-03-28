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
    CycleScore,
    LegQuote,
    SizeSweepPoint,
    SizeSweepResult,
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


def _calculate_starting_amount(token: str, decimals: int, target_usd: float = 100.0) -> int:
    """Calculate starting amount for triangular cycle.

    Reuses canonical DEFAULT_TOKEN_USD_PRICES from strategy.quotes
    as single source of truth to avoid drift.
    """
    from strategy.quotes import DEFAULT_TOKEN_USD_PRICES
    # Lookup with case-insensitive fallback
    price = DEFAULT_TOKEN_USD_PRICES.get(token)
    if price is None:
        price = DEFAULT_TOKEN_USD_PRICES.get(token.upper())
    if price is None:
        for k, v in DEFAULT_TOKEN_USD_PRICES.items():
            if k.upper() == token.upper():
                price = v
                break
    if price is None:
        price = 1.0
    amount_tokens = target_usd / price
    return int(amount_tokens * (10 ** decimals))


# ---------------------------------------------------------------------------
# Blocker analysis — machine-readable RCA for M7.A feasibility verdict
# ---------------------------------------------------------------------------

# Blocker tag constants
BLOCKER_GROSS_NEGATIVE_CORE = "GROSS_NEGATIVE_CORE"
BLOCKER_GAS_DOMINANT_SMALL = "GAS_DOMINANT_SMALL"
BLOCKER_SLIPPAGE_DOMINANT_LARGE = "SLIPPAGE_DOMINANT_LARGE"
BLOCKER_THIRD_LEG_FEE_BINDING = "THIRD_LEG_FEE_BINDING"
BLOCKER_SINGLE_TRIPLE_CONCENTRATION = "SINGLE_TRIPLE_CONCENTRATION"
BLOCKER_QUOTE_FAILURE_BREADTH_LIMIT = "QUOTE_FAILURE_BREADTH_LIMIT"


def classify_blocker_tags(
    score: CycleScore,
    sweep: Optional[SizeSweepResult] = None,
) -> List[str]:
    """Classify a single cycle's dominant blockers.

    Returns a list of blocker tag strings from the canonical set.
    """
    tags: List[str] = []

    # GROSS_NEGATIVE_CORE: gross_bps < 0 before any costs
    if score.gross_bps < 0:
        tags.append(BLOCKER_GROSS_NEGATIVE_CORE)

    # THIRD_LEG_FEE_BINDING: third leg adds >= 5 bps fee overhead
    if score.fee_leg3_bps >= 5.0:
        tags.append(BLOCKER_THIRD_LEG_FEE_BINDING)

    # Size-dependent tags require sweep data
    if sweep is not None and sweep.size_curve:
        quoted_points = [p for p in sweep.size_curve if p.quoted]
        if len(quoted_points) >= 2:
            smallest = quoted_points[0]
            largest = quoted_points[-1]
            best_pt = min(quoted_points, key=lambda p: abs(p.final_net_bps - sweep.best_net_bps))

            # GAS_DOMINANT_SMALL: smallest size net is >5x worse than best
            if best_pt.final_net_bps != 0 and smallest.final_net_bps != 0:
                if smallest.final_net_bps < best_pt.final_net_bps * 5:
                    tags.append(BLOCKER_GAS_DOMINANT_SMALL)

            # SLIPPAGE_DOMINANT_LARGE: largest size net is >3x worse than best
            if best_pt.final_net_bps != 0 and largest.final_net_bps != 0:
                if largest.final_net_bps < best_pt.final_net_bps * 3:
                    tags.append(BLOCKER_SLIPPAGE_DOMINANT_LARGE)

    return tags


def _build_blocker_summary(
    measured_ranked: List[CycleScore],
    measured_stats: Dict[str, Any],
    sweep_results: List[SizeSweepResult],
) -> Dict[str, Any]:
    """Build machine-readable blocker summary for M7.A feasibility report.

    Required metrics (per reviewer spec):
     - best_route_gross_bps, best_route_gas_bps, best_route_total_fee_bps
     - best_route_best_size_usd
     - small_size_gas_domination, large_size_slippage_domination
     - same_state_proven_rate, route_failure_rate
     - token_triple_concentration
     - top_blockers (dominant blocker tags)
    """
    if not measured_ranked:
        return {"error": "no_measured_routes"}

    best = measured_ranked[0]

    # Core decomposition of best route
    best_route_gross_bps = round(best.gross_bps, 4)
    best_route_gas_bps = round(best.gas_bps, 4)
    best_route_total_fee_bps = round(best.total_fee_bps, 4)
    best_route_net_bps = round(best.final_net_bps, 4)

    # Best size from sweep (if available), else from scored_size_usd
    best_route_best_size_usd = best.scored_size_usd
    best_sweep: Optional[SizeSweepResult] = None
    if sweep_results:
        best_sweep = sweep_results[0]
        best_route_best_size_usd = best_sweep.best_size_usd

    # Size-dependent domination metrics (from sweep of best route)
    small_size_gas_domination = False
    large_size_slippage_domination = False
    small_size_worst_bps: Optional[float] = None
    large_size_worst_bps: Optional[float] = None

    if best_sweep and best_sweep.size_curve:
        quoted = [p for p in best_sweep.size_curve if p.quoted]
        if len(quoted) >= 3:
            smallest = quoted[0]
            largest = quoted[-1]
            small_size_worst_bps = round(smallest.final_net_bps, 4)
            large_size_worst_bps = round(largest.final_net_bps, 4)
            # Gas dominates small sizes: smallest >5x worse than best
            if best_sweep.best_net_bps != 0:
                small_size_gas_domination = (
                    smallest.final_net_bps < best_sweep.best_net_bps * 5
                )
                large_size_slippage_domination = (
                    largest.final_net_bps < best_sweep.best_net_bps * 3
                )

    # Same-state proven rate
    same_dist = measured_stats.get("same_state_distribution", {})
    total_scored = measured_stats.get("scored", 0)
    proven_count = same_dist.get("same_state_proven", 0)
    same_state_proven_rate = round(proven_count / total_scored, 4) if total_scored > 0 else 0.0

    # Route failure rate (quote failures / attempted)
    attempted = measured_stats.get("attempted", 0)
    failed = measured_stats.get("failed", 0)
    route_failure_rate = round(failed / attempted, 4) if attempted > 0 else 0.0

    # Token triple concentration
    token_triples: Counter = Counter()
    for s in measured_ranked:
        triple = tuple(sorted(s.cycle.tokens))
        token_triples[triple] += 1
    total_routes = len(measured_ranked)
    most_common_triple, most_common_count = token_triples.most_common(1)[0]
    token_triple_concentration = round(most_common_count / total_routes, 4)
    dominant_triple = list(most_common_triple)

    # Classify blocker tags with separated semantics:
    # per_cycle_blocker_counts: tags counted per-cycle (out of cycles_analyzed)
    # global_blockers_present: tags that are global observations (present/absent)
    per_cycle_tags: Counter = Counter()
    global_blockers: List[str] = []

    # Global blocker: single-triple concentration
    if token_triple_concentration >= 0.9:
        global_blockers.append(BLOCKER_SINGLE_TRIPLE_CONCENTRATION)

    # Global blocker: quote failure breadth limit
    if route_failure_rate >= 0.25:
        global_blockers.append(BLOCKER_QUOTE_FAILURE_BREADTH_LIMIT)

    # Per-cycle tags (from top 10 or all measured)
    cycles_for_tags = measured_ranked[:10]
    sweep_lookup: Dict[str, SizeSweepResult] = {}
    for sr in sweep_results:
        sweep_lookup[sr.cycle.cycle_key] = sr

    for s in cycles_for_tags:
        sw = sweep_lookup.get(s.cycle.cycle_key)
        tags = classify_blocker_tags(s, sw)
        for t in tags:
            per_cycle_tags[t] += 1

    # top_blockers: unified ordered list (per-cycle by frequency, then globals)
    top_blockers = [tag for tag, _ in per_cycle_tags.most_common()]
    for g in global_blockers:
        if g not in top_blockers:
            top_blockers.append(g)

    return {
        "best_route_gross_bps": best_route_gross_bps,
        "best_route_gas_bps": best_route_gas_bps,
        "best_route_total_fee_bps": best_route_total_fee_bps,
        "best_route_net_bps": best_route_net_bps,
        "best_route_best_size_usd": best_route_best_size_usd,
        "small_size_gas_domination": small_size_gas_domination,
        "small_size_worst_bps": small_size_worst_bps,
        "large_size_slippage_domination": large_size_slippage_domination,
        "large_size_worst_bps": large_size_worst_bps,
        "same_state_proven_rate": same_state_proven_rate,
        "route_failure_rate": route_failure_rate,
        "token_triple_concentration": token_triple_concentration,
        "dominant_triple": dominant_triple,
        "top_blockers": top_blockers,
        "per_cycle_blocker_counts": dict(per_cycle_tags.most_common()),
        "global_blockers_present": global_blockers,
        "cycles_analyzed": len(cycles_for_tags),
    }


# ---------------------------------------------------------------------------
# Blocker repeatability — temporal stability of blocker classes across blocks
# ---------------------------------------------------------------------------

def build_blocker_repeatability(
    artifact_paths: List[str],
) -> Dict[str, Any]:
    """Aggregate multiple blocker summaries into a temporal repeatability report.

    Each artifact must be a JSON file produced by m7a_enumerate_cycles.py
    with a blocker_summary block.

    Returns a machine-readable repeatability summary with:
    - per-run blocker snapshots (block, key metrics, blocker tags)
    - blocker class stability across runs (which tags are stable vs flapping)
    - metric ranges (min/max/mean for key bps values)
    """
    snapshots: List[Dict[str, Any]] = []

    for path_str in artifact_paths:
        path = Path(path_str)
        if not path.exists():
            logger.warning("Artifact not found: %s", path)
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        bs = data.get("blocker_summary")
        if not bs or "error" in bs:
            logger.warning("No valid blocker_summary in %s", path)
            continue
        block = data.get("measured", {}).get("block_number")
        snapshots.append({
            "artifact": path.name,
            "block": block,
            "best_route_gross_bps": bs["best_route_gross_bps"],
            "best_route_gas_bps": bs["best_route_gas_bps"],
            "best_route_total_fee_bps": bs["best_route_total_fee_bps"],
            "best_route_net_bps": bs["best_route_net_bps"],
            "best_route_best_size_usd": bs["best_route_best_size_usd"],
            "route_failure_rate": bs["route_failure_rate"],
            "token_triple_concentration": bs["token_triple_concentration"],
            "top_blockers": bs["top_blockers"],
            "per_cycle_blocker_counts": bs.get("per_cycle_blocker_counts", {}),
            "global_blockers_present": bs.get("global_blockers_present", []),
        })

    if not snapshots:
        return {"error": "no_valid_artifacts", "artifacts_checked": len(artifact_paths)}

    # Metric ranges
    def _range(key: str) -> Dict[str, float]:
        vals = [s[key] for s in snapshots if s[key] is not None]
        if not vals:
            return {"min": 0.0, "max": 0.0, "mean": 0.0}
        return {
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "mean": round(sum(vals) / len(vals), 4),
        }

    # Blocker tag stability: a tag is "stable" if present in ALL runs
    all_tags_seen: Counter = Counter()
    for s in snapshots:
        for tag in s["top_blockers"]:
            all_tags_seen[tag] += 1

    n_runs = len(snapshots)
    stable_blockers = [tag for tag, count in all_tags_seen.items() if count == n_runs]
    flapping_blockers = [tag for tag, count in all_tags_seen.items() if 0 < count < n_runs]

    # Per-cycle tag stability (using per_cycle_blocker_counts)
    per_cycle_tag_ranges: Dict[str, Dict[str, Any]] = {}
    all_per_cycle_tags = set()
    for s in snapshots:
        for tag in s.get("per_cycle_blocker_counts", {}):
            all_per_cycle_tags.add(tag)
    for tag in sorted(all_per_cycle_tags):
        counts = [s.get("per_cycle_blocker_counts", {}).get(tag, 0) for s in snapshots]
        per_cycle_tag_ranges[tag] = {
            "min": min(counts),
            "max": max(counts),
            "present_in_runs": sum(1 for c in counts if c > 0),
        }

    # Global blocker stability
    all_global_tags = set()
    for s in snapshots:
        for tag in s.get("global_blockers_present", []):
            all_global_tags.add(tag)
    global_tag_stability: Dict[str, int] = {}
    for tag in sorted(all_global_tags):
        global_tag_stability[tag] = sum(
            1 for s in snapshots if tag in s.get("global_blockers_present", [])
        )

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "blocker_repeatability": True,
        "timestamp": ts,
        "runs_count": n_runs,
        "block_range": {
            "min": min(s["block"] for s in snapshots if s["block"]),
            "max": max(s["block"] for s in snapshots if s["block"]),
        },
        "metric_ranges": {
            "best_route_gross_bps": _range("best_route_gross_bps"),
            "best_route_gas_bps": _range("best_route_gas_bps"),
            "best_route_total_fee_bps": _range("best_route_total_fee_bps"),
            "best_route_net_bps": _range("best_route_net_bps"),
            "best_route_best_size_usd": _range("best_route_best_size_usd"),
            "route_failure_rate": _range("route_failure_rate"),
            "token_triple_concentration": _range("token_triple_concentration"),
        },
        "blocker_class_stability": {
            "stable_blockers": sorted(stable_blockers),
            "flapping_blockers": sorted(flapping_blockers),
            "all_observed": sorted(all_tags_seen.keys()),
        },
        "per_cycle_tag_ranges": per_cycle_tag_ranges,
        "global_blocker_stability": global_tag_stability,
        "snapshots": snapshots,
    }


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
    parser.add_argument("--sweep-top", type=int, default=0,
                        help="Sweep canonical size ladder on top N measured cycles (0=disabled)")
    parser.add_argument("--repeatability", nargs="+", default=None,
                        help="Aggregate blocker summaries from multiple artifact JSONs. "
                             "Outputs repeatability report instead of running enumeration.")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Repeatability mode: aggregate existing artifacts
    if args.repeatability:
        result = build_blocker_repeatability(args.repeatability)
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            logger.info("Repeatability report written to %s", out_path)
        else:
            print(json.dumps(result, indent=2))
        return 0 if "error" not in result else 1

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
        measured_scores, fallback_scores, measured_ranked, measured_stats = _score_measured(
            viable, chain, args.max_scored,
        )
        # In measured mode, the canonical ranking is measured-only
        ranked = measured_ranked

        # 5b. Optional bounded size sweep on top measured candidates
        sweep_results: List[SizeSweepResult] = []
        if args.sweep_top > 0 and measured_ranked:
            from engine.roundtrip import CANONICAL_SWEEP_SIZES_USD
            from core.rpc_urls import get_rpc_url
            from dex.registry import load_dex_configs

            sweep_n = min(args.sweep_top, len(measured_ranked))
            rpc_url = get_rpc_url(chain)
            block_number = measured_stats.get("block_number") if measured_stats else None
            if rpc_url and block_number:
                dex_configs = load_dex_configs(chain)
                token_addresses = get_all_token_addresses(chain)
                logger.info(
                    "Size sweep: %d cycles x %d sizes, block=%d",
                    sweep_n, len(CANONICAL_SWEEP_SIZES_USD), block_number,
                )
                for s in measured_ranked[:sweep_n]:
                    result = _sweep_cycle_sizes(
                        s.cycle, CANONICAL_SWEEP_SIZES_USD,
                        rpc_url, block_number, dex_configs, token_addresses,
                    )
                    if result is not None:
                        sweep_results.append(result)
                logger.info(
                    "Size sweep complete: %d/%d swept",
                    len(sweep_results), sweep_n,
                )
    else:
        scores = [score_cycle_fees_only(c) for c in viable]
        ranked = rank_cycles_by_net(scores)
        measured_stats = None
        measured_scores = []
        fallback_scores = []
        sweep_results = []

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
    }

    if score_mode == "measured":
        # Measured mode: ranked list is measured-only; fallbacks are separate
        summary["top_10_by_net"] = [s.to_dict() for s in measured_ranked[:10]]
        if measured_ranked:
            summary["best_net_bps"] = round(measured_ranked[0].final_net_bps, 4)
            summary["worst_net_bps"] = round(measured_ranked[-1].final_net_bps, 4)
            summary["median_net_bps"] = round(
                measured_ranked[len(measured_ranked) // 2].final_net_bps, 4
            )
        summary["measured"] = measured_stats
        if fallback_scores:
            fallback_ranked = rank_cycles_by_net(fallback_scores)
            summary["diagnostic_fee_only_fallbacks"] = [
                s.to_dict() for s in fallback_ranked[:10]
            ]
        if sweep_results:
            summary["size_sweep"] = {
                "sweep_top": args.sweep_top,
                "cycles_swept": len(sweep_results),
                "results": [r.to_dict() for r in sweep_results],
            }
        # Blocker summary: machine-readable RCA for feasibility verdict
        if measured_ranked and measured_stats:
            summary["blocker_summary"] = _build_blocker_summary(
                measured_ranked, measured_stats, sweep_results,
            )
    else:
        # Fee-only mode: use fee-cost naming for clarity
        summary["top_10_by_lowest_cost"] = [s.to_dict() for s in ranked[:10]]
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
            print(f"Measured-only ranked: {measured_stats['measured_ranked_count']}, "
                  f"fallback (diagnostic): {measured_stats['diagnostic_fallback_count']}")
            same_state = measured_stats.get("same_state_distribution", {})
            if same_state:
                print(f"Same-state: {same_state}")
        if ranked:
            label = "measured" if score_mode == "measured" else "fee-only"
            print(f"Best net ({label}): {ranked[0].final_net_bps:.1f} bps [{ranked[0].provenance_summary}]")
            print(f"Median net ({label}): {ranked[len(ranked)//2].final_net_bps:.1f} bps")
            print(f"\nTop 5 cycles ({label}):")
            for i, s in enumerate(ranked[:5], 1):
                print(f"  {i}. {s.cycle.route_display} "
                      f"[gross={s.gross_bps:.1f}, gas={s.gas_bps:.1f}, net={s.final_net_bps:.1f}bps] "
                      f"same_state={s.same_state_class} "
                      f"dexes={','.join(set(l.dex for l in s.cycle.legs()))}")
        print(f"\nFee structure distribution: {summary['fee_distribution']}")
        print(f"DEX leg distribution: {summary['dex_distribution']}")
        print(f"Multi-DEX breakdown: {summary['multi_dex_breakdown']}")

    return 0


def _sweep_cycle_sizes(
    cycle: TriangularCycle,
    sizes_usd: List[float],
    rpc_url: str,
    block_number: int,
    dex_configs: Dict[str, Any],
    token_addresses: Dict[str, str],
) -> Optional[SizeSweepResult]:
    """Sweep a single cycle over the canonical size ladder.

    Quotes all 3 legs at each notional in sizes_usd, scores each,
    and returns the size curve with the best notional identified.
    Returns None if no size point could be quoted.
    """
    curve: List[SizeSweepPoint] = []
    best_score: Optional[CycleScore] = None
    best_net: float = float("-inf")
    best_size: float = 0.0
    quoted_count = 0

    for size_usd in sizes_usd:
        amt_wei = _calculate_starting_amount(
            cycle.leg1.token_in, cycle.leg1.decimals_in, target_usd=size_usd,
        )
        if amt_wei <= 0:
            curve.append(SizeSweepPoint(size_usd=size_usd, final_net_bps=0.0, quoted=False))
            continue

        q1, q2, q3 = quote_cycle_3legs(
            cycle, amt_wei, rpc_url, block_number, dex_configs, token_addresses,
        )
        if q1 is None or q2 is None or q3 is None:
            curve.append(SizeSweepPoint(size_usd=size_usd, final_net_bps=0.0, quoted=False))
            continue

        s = score_cycle_measured(cycle, q1, q2, q3)
        quoted_count += 1
        curve.append(SizeSweepPoint(
            size_usd=s.scored_size_usd,
            final_net_bps=s.final_net_bps,
            quoted=True,
        ))

        if s.final_net_bps > best_net:
            best_net = s.final_net_bps
            best_size = s.scored_size_usd
            best_score = s

    if best_score is None:
        return None

    return SizeSweepResult(
        cycle=cycle,
        best_size_usd=best_size,
        best_net_bps=best_net,
        best_score=best_score,
        size_curve=curve,
        sizes_attempted=len(sizes_usd),
        sizes_quoted=quoted_count,
    )


def _score_measured(
    viable: List[TriangularCycle],
    chain: str,
    max_scored: int,
) -> Tuple[list, list, list, Dict[str, Any]]:
    """Score viable cycles with live RPC quotes.

    Measured scores and fee-only fallback scores are kept separate.
    Returns (measured_scores, fallback_scores, measured_ranked, measured_stats_dict).
    """
    from collections import Counter as _Counter
    from core.rpc_urls import get_rpc_url
    from dex.registry import load_dex_configs

    rpc_url = get_rpc_url(chain)
    if not rpc_url:
        logger.error("No RPC URL for %s — cannot do measured scoring", chain)
        scores = [score_cycle_fees_only(c) for c in viable]
        return [], scores, [], {"error": "no_rpc_url"}

    block_number = _get_current_block(rpc_url)
    if block_number is None:
        logger.error("Cannot get block number — falling back to fee-only scoring")
        scores = [score_cycle_fees_only(c) for c in viable]
        return [], scores, [], {"error": "no_block"}

    dex_configs = load_dex_configs(chain)
    token_addresses = get_all_token_addresses(chain)

    # Pre-sort by fee-only ranking so we quote the most promising first
    fee_scores = [score_cycle_fees_only(c) for c in viable]
    fee_ranked = rank_cycles_by_net(fee_scores)
    to_quote = [s.cycle for s in fee_ranked[:max_scored]]

    logger.info("Measured scoring: %d cycles, block=%d, rpc=%s",
                len(to_quote), block_number, rpc_url[:50])

    measured_scores = []
    fallback_scores = []
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
            fallback_scores.append(score_cycle_fees_only(cycle))
            continue

        quote_success += 1
        s = score_cycle_measured(cycle, q1, q2, q3)
        measured_scores.append(s)
        same_state_counter[s.same_state_class] += 1

    measured_ranked = rank_cycles_by_net(measured_scores)

    promoted_count = sum(1 for s in measured_scores if s.is_promoted())
    best_measured = None
    if measured_ranked:
        best_measured = round(measured_ranked[0].final_net_bps, 4)

    stats: Dict[str, Any] = {
        "block_number": block_number,
        "attempted": quote_attempted,
        "scored": quote_success,
        "failed": quote_failed,
        "measured_ranked_count": len(measured_ranked),
        "diagnostic_fallback_count": len(fallback_scores),
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

    return measured_scores, fallback_scores, measured_ranked, stats


if __name__ == "__main__":
    sys.exit(main())
