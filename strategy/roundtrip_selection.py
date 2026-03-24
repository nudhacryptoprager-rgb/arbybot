# PATH: strategy/roundtrip_selection.py
"""
Roundtrip candidate selection — filters and ranks opportunities for roundtrip evaluation.

Extracted from run_scan_real.py (R28.28) to isolate candidate selection policy
from scan orchestration. All policy gates live here so they can be tested and
overridden independently.
"""

import logging
from typing import Any, Dict, List, Tuple

from core.constants import EXECUTABLE_QUOTE_SOURCES, get_pair_role

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


# R39n: Pair role priority for alpha-first ordering.
# Lower number = higher priority in roundtrip evaluation.
_ROLE_PRIORITY = {"alpha": 0, "unclassified": 1, "benchmark": 2, "calibration": 3}


def _pair_role_sort_key(opp: dict, chain: str) -> int:
    """Return numeric priority for alpha-first ordering (0=alpha, 3=calibration)."""
    pair = opp.get("pair", "")
    role = get_pair_role(chain, pair)
    return _ROLE_PRIORITY.get(role, 1)


def select_roundtrip_candidates(
    opps_list: List[dict],
    rt_max_candidates: int = 50,
    rt_top_n: int = 10,
    min_margin_bps: float = DEFAULT_MIN_SPREAD_MINUS_THRESHOLD,
    chain: str = "",
) -> tuple:
    """Run the full candidate selection pipeline and return (eligible_opps, filter_stats).

    Pipeline:
    1. best_per_pair — deduplicate by pair (keep best margin)
    2. roundtrip_eligible — cross-DEX + LP-fee viable + not diagnostic
    3. margin_viable — spread_minus_required_bps > threshold
    4. R39n: Sort alpha-first when chain is provided
    5. Cap to rt_top_n

    Returns:
        (eligible_opps, filter_stats_dict)
    """
    per_pair = best_per_pair(opps_list, max_candidates=rt_max_candidates)

    eligible_and_rt = [o for o in per_pair if roundtrip_eligible(o)]
    eligible_all = [o for o in eligible_and_rt if margin_viable(o, min_margin_bps)]

    # R39n: Alpha-first ordering — evaluate alpha pairs before benchmark/calibration.
    if chain:
        eligible_all.sort(key=lambda o: _pair_role_sort_key(o, chain))

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


def select_sweep_reprieve_candidates(
    opps_list: List[dict],
    max_candidates: int = 15,
) -> Tuple[List[dict], dict]:
    """Select candidates for sweep reprieve from reprievable rejected opps.

    When OE rejects all opportunities at the single probe size (e.g. $10), routes
    rejected by economics-based gates (NET_PROFIT_TOO_LOW, GAS_TOO_HIGH,
    SPREAD_TOO_LOW, NOTIONAL_DRIFT) with both legs executable (quoter_v2) deserve
    a wide-size frontier replay. This prevents single-size economics from being the
    final verdict without exploring the full sweep ladder.

    Criteria:
    - gate_passed == False
    - is_reprievable == True (R36), or reject_reason starts with NET_PROFIT_TOO_LOW (legacy)
    - Both legs are executable (in EXECUTABLE_QUOTE_SOURCES, not slot0)
    - Cross-DEX

    Returns:
        (sweep_reprieve_candidates, stats_dict)
    """
    reprieve = []
    for opp in opps_list:
        if opp.get("gate_passed", False):
            continue
        # R36: Use is_reprievable flag if present, fall back to string match for legacy
        if not opp.get("is_reprievable", False):
            reason = opp.get("reject_reason") or ""
            if not reason.startswith("NET_PROFIT_TOO_LOW"):
                continue
        # R39n: Accept any executable quote source (quoter_v2, ve33_getAmountOut, etc.)
        buy_src = opp.get("buy_quote_source", "slot0")
        sell_src = opp.get("sell_quote_source", "slot0")
        if buy_src not in EXECUTABLE_QUOTE_SOURCES or sell_src not in EXECUTABLE_QUOTE_SOURCES:
            continue
        if not is_cross_dex(opp):
            continue
        reprieve.append(opp)

    # Sort by gross spread (best first) and deduplicate by pair
    reprieve.sort(key=lambda o: float(o.get("gross_spread_bps", 0)), reverse=True)
    seen_pairs: Dict[str, bool] = {}
    deduped: List[dict] = []
    for opp in reprieve:
        pair = opp.get("pair", "unknown")
        if pair not in seen_pairs:
            seen_pairs[pair] = True
            deduped.append(opp)
        if len(deduped) >= max_candidates:
            break

    stats = {
        "net_profit_too_low_total": len(reprieve),
        "sweep_reprieve_selected": len(deduped),
    }
    return deduped, stats
