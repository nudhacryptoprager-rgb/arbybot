# PATH: strategy/roundtrip_selection.py
"""
Roundtrip candidate selection — filters and ranks opportunities for roundtrip evaluation.

Extracted from run_scan_real.py (R28.28) to isolate candidate selection policy
from scan orchestration. All policy gates live here so they can be tested and
overridden independently.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger("roundtrip_selection")

# Policy constant: minimum spread-minus-required for roundtrip consideration.
# Candidates below this threshold are too far from viability to warrant RPC calls.
# Configurable via config key "roundtrip_min_margin_bps".
DEFAULT_MIN_SPREAD_MINUS_THRESHOLD = -5.0  # bps


def lp_fee_viable(opp: dict) -> bool:
    """Check if gross spread covers roundtrip LP fees.

    LP fee per leg = fee_tier / 100 (e.g., 500 -> 5 bps).
    Roundtrip LP cost = buy_fee/100 + sell_fee/100.
    """
    try:
        lp_bps = (opp.get("buy_fee", 0) + opp.get("sell_fee", 0)) / 100
        return float(opp.get("gross_spread_bps", 0)) > lp_bps
    except Exception:
        return True  # Allow on error (conservative)


def is_cross_dex(opp: dict) -> bool:
    """Check if opportunity is cross-DEX (buy_dex != sell_dex)."""
    return opp.get("buy_dex") != opp.get("sell_dex")


def roundtrip_eligible(opp: dict) -> bool:
    """Combined eligibility: cross-DEX, LP-fee viable, not diagnostic-only.

    R28.21: Exclude diagnostic-only signals from roundtrip evaluation.
    """
    if opp.get("is_diagnostic_only", False):
        return False
    return is_cross_dex(opp) and lp_fee_viable(opp)


def margin_viable(opp: dict, threshold: float = DEFAULT_MIN_SPREAD_MINUS_THRESHOLD) -> bool:
    """Check if candidate has viable economics margin.

    Only candidates with spread_minus_required_bps > threshold get evaluated.
    This prevents wasting roundtrip evals on clearly non-viable candidates.
    """
    margin = opp.get("spread_minus_required_bps", -999)
    return margin > threshold


def best_per_pair(opps: List[dict], max_candidates: int = 10) -> List[dict]:
    """Select best opportunity per pair by spread_minus_required_bps.

    Instead of taking top-N overall (which often clusters on one pair),
    select best candidate per unique pair for better coverage.
    """
    pairs_best: Dict[str, dict] = {}
    for o in opps[:max_candidates]:
        pair = o.get("pair", "unknown")
        curr_margin = o.get("spread_minus_required_bps", -999)
        best_margin = pairs_best[pair].get("spread_minus_required_bps", -999) if pair in pairs_best else -999
        if pair not in pairs_best or curr_margin > best_margin:
            pairs_best[pair] = o
    return sorted(pairs_best.values(), key=lambda x: x.get("spread_minus_required_bps", -999), reverse=True)


def select_roundtrip_candidates(
    opps_list: List[dict],
    rt_max_candidates: int = 50,
    rt_top_n: int = 10,
    min_margin_bps: float = DEFAULT_MIN_SPREAD_MINUS_THRESHOLD,
) -> tuple:
    """Run the full candidate selection pipeline and return (eligible_opps, filter_stats).

    Pipeline:
    1. best_per_pair — deduplicate by pair (keep best margin)
    2. roundtrip_eligible — cross-DEX + LP-fee viable + not diagnostic
    3. margin_viable — spread_minus_required_bps > threshold
    4. Cap to rt_top_n

    Returns:
        (eligible_opps, filter_stats_dict)
    """
    per_pair = best_per_pair(opps_list, max_candidates=rt_max_candidates)

    eligible_and_rt = [o for o in per_pair if roundtrip_eligible(o)]
    eligible_all = [o for o in eligible_and_rt if margin_viable(o, min_margin_bps)]
    eligible_opps = eligible_all[:rt_top_n]

    margin_filtered_count = len(eligible_and_rt) - len(eligible_all)

    filter_stats = {
        "candidates_considered": min(rt_max_candidates, len(opps_list)),
        "cross_dex_count": len([o for o in opps_list[:rt_max_candidates] if is_cross_dex(o)]),
        "lp_viable_count": len([o for o in opps_list[:rt_max_candidates] if lp_fee_viable(o)]),
        "unique_pairs_considered": len(per_pair),
        "margin_filtered_count": margin_filtered_count,
        "passed_to_roundtrip": len(eligible_opps),
    }
    return eligible_opps, filter_stats
