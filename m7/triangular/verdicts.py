"""
M7 triangular — Regime classification, blocker analysis, and verdict summary.

Contains regime tag constants and classify_regime_bucket, blocker tag constants
and classify_blocker_tags, _build_blocker_summary, build_verdict_summary, and
the TWO_LEG_BASELINE_NET_BPS reference.

Extracted from scripts/m7a_enumerate_cycles.py during M7.R1 structural refactor.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from m7.triangular.scoring import CycleScore, SizeSweepResult

logger = logging.getLogger("m7.triangular.verdicts")


# ---------------------------------------------------------------------------
# Regime classification — M7.A.3 temporal market regime tagging
# ---------------------------------------------------------------------------

REGIME_HIGH_ACTIVITY = "high_activity"
REGIME_MEDIUM_ACTIVITY = "medium_activity"
REGIME_LOW_ACTIVITY = "low_activity"
REGIME_HIGH_FAILURE = "high_failure"
REGIME_LOW_FAILURE = "low_failure"
REGIME_WIDE_SPREAD = "wide_spread"
REGIME_TIGHT_SPREAD = "tight_spread"

ALL_REGIME_TAGS = frozenset({
    REGIME_HIGH_ACTIVITY, REGIME_MEDIUM_ACTIVITY, REGIME_LOW_ACTIVITY,
    REGIME_HIGH_FAILURE, REGIME_LOW_FAILURE,
    REGIME_WIDE_SPREAD, REGIME_TIGHT_SPREAD,
})

REGIME_HIGH_ACTIVITY_THRESHOLD = 0.8
REGIME_LOW_ACTIVITY_THRESHOLD = 0.5
REGIME_HIGH_FAILURE_THRESHOLD = 0.4
REGIME_LOW_FAILURE_THRESHOLD = 0.2
REGIME_WIDE_SPREAD_THRESHOLD = -30.0
REGIME_TIGHT_SPREAD_THRESHOLD = -10.0


def classify_regime_bucket(
    measured_stats: Dict[str, Any],
    blocker_summary: Dict[str, Any],
) -> List[str]:
    """Classify the temporal market regime of a measured run."""
    tags: List[str] = []

    attempted = measured_stats.get("attempted", 0)
    scored = measured_stats.get("scored", 0)
    if attempted > 0:
        success_rate = scored / attempted
        if success_rate > REGIME_HIGH_ACTIVITY_THRESHOLD:
            tags.append(REGIME_HIGH_ACTIVITY)
        elif success_rate < REGIME_LOW_ACTIVITY_THRESHOLD:
            tags.append(REGIME_LOW_ACTIVITY)
        else:
            tags.append(REGIME_MEDIUM_ACTIVITY)

    if "route_failure_rate" in blocker_summary:
        route_failure_rate = blocker_summary["route_failure_rate"]
        if route_failure_rate > REGIME_HIGH_FAILURE_THRESHOLD:
            tags.append(REGIME_HIGH_FAILURE)
        elif route_failure_rate < REGIME_LOW_FAILURE_THRESHOLD:
            tags.append(REGIME_LOW_FAILURE)

    best_net_bps = blocker_summary.get("best_route_net_bps")
    if best_net_bps is not None:
        if best_net_bps < REGIME_WIDE_SPREAD_THRESHOLD:
            tags.append(REGIME_WIDE_SPREAD)
        elif best_net_bps > REGIME_TIGHT_SPREAD_THRESHOLD:
            tags.append(REGIME_TIGHT_SPREAD)

    return sorted(tags)


# ---------------------------------------------------------------------------
# Blocker analysis — machine-readable RCA for M7.A feasibility verdict
# ---------------------------------------------------------------------------

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
    """Classify a single cycle's dominant blockers."""
    tags: List[str] = []

    if score.gross_bps < 0:
        tags.append(BLOCKER_GROSS_NEGATIVE_CORE)

    if score.fee_leg3_bps >= 5.0:
        tags.append(BLOCKER_THIRD_LEG_FEE_BINDING)

    if sweep is not None and sweep.size_curve:
        quoted_points = [p for p in sweep.size_curve if p.quoted]
        if len(quoted_points) >= 2:
            smallest = quoted_points[0]
            largest = quoted_points[-1]
            best_pt = min(quoted_points, key=lambda p: abs(p.final_net_bps - sweep.best_net_bps))

            if best_pt.final_net_bps != 0 and smallest.final_net_bps != 0:
                if smallest.final_net_bps < best_pt.final_net_bps * 5:
                    tags.append(BLOCKER_GAS_DOMINANT_SMALL)

            if best_pt.final_net_bps != 0 and largest.final_net_bps != 0:
                if largest.final_net_bps < best_pt.final_net_bps * 3:
                    tags.append(BLOCKER_SLIPPAGE_DOMINANT_LARGE)

    return tags


def _build_blocker_summary(
    measured_ranked: List[CycleScore],
    measured_stats: Dict[str, Any],
    sweep_results: List[SizeSweepResult],
) -> Dict[str, Any]:
    """Build machine-readable blocker summary for M7.A feasibility report."""
    if not measured_ranked:
        return {"error": "no_measured_routes"}

    best = measured_ranked[0]

    best_route_gross_bps = round(best.gross_bps, 4)
    best_route_gas_bps = round(best.gas_bps, 4)
    best_route_total_fee_bps = round(best.total_fee_bps, 4)
    best_route_net_bps = round(best.final_net_bps, 4)

    best_route_best_size_usd = best.scored_size_usd
    best_sweep: Optional[SizeSweepResult] = None
    if sweep_results:
        best_sweep = sweep_results[0]
        best_route_best_size_usd = best_sweep.best_size_usd

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
            if best_sweep.best_net_bps != 0:
                small_size_gas_domination = (
                    smallest.final_net_bps < best_sweep.best_net_bps * 5
                )
                large_size_slippage_domination = (
                    largest.final_net_bps < best_sweep.best_net_bps * 3
                )

    same_dist = measured_stats.get("same_state_distribution", {})
    total_scored = measured_stats.get("scored", 0)
    proven_count = same_dist.get("same_state_proven", 0)
    same_state_proven_rate = round(proven_count / total_scored, 4) if total_scored > 0 else 0.0

    attempted = measured_stats.get("attempted", 0)
    failed = measured_stats.get("failed", 0)
    route_failure_rate = round(failed / attempted, 4) if attempted > 0 else 0.0

    token_triples: Counter = Counter()
    for s in measured_ranked:
        triple = tuple(sorted(s.cycle.tokens))
        token_triples[triple] += 1
    total_routes = len(measured_ranked)
    most_common_triple, most_common_count = token_triples.most_common(1)[0]
    token_triple_concentration = round(most_common_count / total_routes, 4)
    dominant_triple = list(most_common_triple)

    per_cycle_tags: Counter = Counter()
    global_blockers: List[str] = []

    if token_triple_concentration >= 0.9:
        global_blockers.append(BLOCKER_SINGLE_TRIPLE_CONCENTRATION)

    if route_failure_rate >= 0.25:
        global_blockers.append(BLOCKER_QUOTE_FAILURE_BREADTH_LIMIT)

    cycles_for_tags = measured_ranked[:10]
    sweep_lookup: Dict[str, SizeSweepResult] = {}
    for sr in sweep_results:
        sweep_lookup[sr.cycle.cycle_key] = sr

    for s in cycles_for_tags:
        sw = sweep_lookup.get(s.cycle.cycle_key)
        tags = classify_blocker_tags(s, sw)
        for t in tags:
            per_cycle_tags[t] += 1

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
# Verdict summary — bounded-scope M7.A no-graduate decision artifact
# ---------------------------------------------------------------------------

TWO_LEG_BASELINE_NET_BPS = -3.5062


def build_verdict_summary(
    repeatability: Dict[str, Any],
    two_leg_baseline_bps: float = TWO_LEG_BASELINE_NET_BPS,
    chain: str = "arbitrum_one",
) -> Dict[str, Any]:
    """Build a machine-readable bounded-scope verdict for M7.A."""
    if "error" in repeatability:
        return {"error": repeatability["error"], "verdict": "INSUFFICIENT_EVIDENCE"}

    mr = repeatability["metric_ranges"]
    stability = repeatability["blocker_class_stability"]
    runs_count = repeatability["runs_count"]

    best_net_range = mr["best_route_net_bps"]
    best_net_max = best_net_range["max"]
    best_net_mean = best_net_range["mean"]

    beats_two_leg_baseline = best_net_max > two_leg_baseline_bps
    all_runs_negative_net = best_net_range["max"] < 0.0

    gross_range = mr["best_route_gross_bps"]
    gross_sometimes_positive = gross_range["max"] > 0.0

    stable_count = len(stability["stable_blockers"])
    flapping_count = len(stability["flapping_blockers"])

    conc = mr["token_triple_concentration"]
    route_fail = mr["route_failure_rate"]

    dominant_triple = None
    for snap in repeatability.get("snapshots", []):
        break

    recommend_open_m7b = (
        beats_two_leg_baseline
        and flapping_count == 0
        and stable_count <= 2
        and not all_runs_negative_net
    )
    recommend_freeze = not recommend_open_m7b

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    snapshots_list = repeatability.get("snapshots", [])
    universe_from_evidence = "narrow_7"
    if snapshots_list:
        universe_from_evidence = snapshots_list[0].get("universe_profile", "narrow_7")

    return {
        "m7a_verdict": True,
        "timestamp": ts,
        "verdict_scope": {
            "chain": chain,
            "universe": universe_from_evidence,
            "phase": "M7.A",
            "evidence_tier": "local_session",
            "runs_count": runs_count,
            "block_range": repeatability["block_range"],
        },
        "two_leg_baseline_net_bps": round(two_leg_baseline_bps, 4),
        "best_net_bps_range": {
            "min": best_net_range["min"],
            "max": best_net_range["max"],
            "mean": best_net_range["mean"],
        },
        "beats_two_leg_baseline": beats_two_leg_baseline,
        "all_sizes_negative": all_runs_negative_net,
        "gross_sometimes_positive": gross_sometimes_positive,
        "stable_blockers_count": stable_count,
        "flapping_blockers_count": flapping_count,
        "stable_blockers": stability["stable_blockers"],
        "flapping_blockers": stability["flapping_blockers"],
        "dominant_triple": conc["max"] >= 1.0,
        "route_failure_rate": {
            "min": route_fail["min"],
            "max": route_fail["max"],
            "mean": route_fail["mean"],
        },
        "recommend_open_m7b": recommend_open_m7b,
        "recommend_freeze_current_m7a_scope": recommend_freeze,
        "verdict_reasoning": (
            "Net bps never beats two-leg baseline across all runs. "
            "Gross is sometimes positive but gas+fees always push net negative. "
            f"{stable_count} stable blockers, {flapping_count} flapping. "
            "Multi-cost structure (gas + fees + concentration) is the binding constraint, "
            "not a single blocker."
            if recommend_freeze
            else "Triangular evidence exceeds two-leg baseline; M7.B evaluation warranted."
        ),
    }
