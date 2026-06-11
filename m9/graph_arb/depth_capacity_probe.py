"""Iterative depth-capacity measurement (ladder + binary search helpers).

Replaces the old single-$100 probe ceiling with explicit ``depth_probe_status``
so fallback-capped depths are not mistaken for measured market capacity.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

PROBE_LADDER_USD: Tuple[float, ...] = (100.0, 500.0, 2500.0, 10_000.0, 50_000.0)

DEPTH_PROBE_MEASURED_CAPACITY = "MEASURED_CAPACITY"
DEPTH_PROBE_LOWER_BOUND_AT_MAX = "LOWER_BOUND_AT_MAX_PROBE"
DEPTH_PROBE_TOO_THIN = "TOO_THIN"
DEPTH_PROBE_UNKNOWN = "UNKNOWN"
DEPTH_PROBE_ANALYTICAL_SUSPECT = "ANALYTICAL_SUSPECT"

MAX_SANE_DEPTH_USD: float = 10_000_000.0
MIN_SANE_MEASURED_DEPTH_USD: float = 50.0

_IMPACT_THRESHOLD_LOW = 0.10
_IMPACT_THRESHOLD_TOXIC = 0.50
_FEE_DENOMINATOR_BPS = 10_000


def marginal_impact(
    ref_in: int,
    ref_out: int,
    probe_in: int,
    probe_out: int,
) -> Optional[float]:
    """Price-agnostic impact from two marginal quotes (clamped >= 0)."""
    if ref_in <= 0 or probe_in <= 0 or ref_out <= 0 or probe_out <= 0:
        return None
    rate_ref = ref_out / ref_in
    rate_probe = probe_out / probe_in
    if rate_ref <= 0:
        return None
    impact = 1.0 - (rate_probe / rate_ref)
    return max(impact, 0.0)


def capacity_usd_at_threshold(
    probe_size_usd: float,
    impact: float,
    *,
    impact_threshold_low: float = _IMPACT_THRESHOLD_LOW,
) -> float:
    """Interpolate USD capacity where impact would equal the low threshold."""
    if impact <= impact_threshold_low:
        return float(probe_size_usd)
    return float(probe_size_usd) * impact_threshold_low / max(impact, 1e-9)


def finalize_marginal_depth(
    impact: float,
    probe_size_usd: float,
    *,
    at_max_ladder_rung: bool = False,
    impact_threshold_low: float = _IMPACT_THRESHOLD_LOW,
    impact_threshold_toxic: float = _IMPACT_THRESHOLD_TOXIC,
) -> Dict[str, Any]:
    """Build depth fields from one ladder rung."""
    result: Dict[str, Any] = {
        "effective_depth_usd": None,
        "price_impact_at_100usd": round(impact, 6),
        "probe_ok": True,
        "probe_error": None,
        "depth_reject_reason": None,
        "depth_method": "marginal_anchor",
        "depth_probe_status": DEPTH_PROBE_UNKNOWN,
        "depth_probe_rung_usd": round(float(probe_size_usd), 2),
    }

    est = round(capacity_usd_at_threshold(probe_size_usd, impact, impact_threshold_low=impact_threshold_low), 2)

    if impact >= impact_threshold_toxic:
        result["depth_probe_status"] = DEPTH_PROBE_TOO_THIN
        result["depth_reject_reason"] = "TOXIC_PRICE_IMPACT"
        result["effective_depth_usd"] = est
    elif impact > impact_threshold_low:
        result["depth_probe_status"] = DEPTH_PROBE_MEASURED_CAPACITY
        result["depth_reject_reason"] = "LOW_EFFECTIVE_DEPTH"
        result["effective_depth_usd"] = est
    elif at_max_ladder_rung:
        result["depth_probe_status"] = DEPTH_PROBE_LOWER_BOUND_AT_MAX
        result["effective_depth_usd"] = round(float(probe_size_usd), 2)
    else:
        # Intermediate rung: pool absorbs this size; caller continues ladder.
        result["depth_probe_status"] = DEPTH_PROBE_LOWER_BOUND_AT_MAX
        result["effective_depth_usd"] = round(float(probe_size_usd), 2)

    return result


def merge_ladder_results(
    rung_results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Pick the best depth outcome from an ascending USD ladder walk."""
    if not rung_results:
        return {
            "effective_depth_usd": None,
            "price_impact_at_100usd": None,
            "probe_ok": False,
            "probe_error": "EMPTY_LADDER",
            "depth_reject_reason": None,
            "depth_method": "marginal_anchor_ladder",
            "depth_probe_status": DEPTH_PROBE_UNKNOWN,
        }

    measured = [
        r for r in rung_results
        if r.get("depth_probe_status") == DEPTH_PROBE_MEASURED_CAPACITY
    ]
    if measured:
        best = min(measured, key=lambda r: float(r.get("depth_probe_rung_usd") or 0))
        out = dict(best)
        out["depth_method"] = "marginal_anchor_ladder"
        out["depth_probe_ladder_usd"] = list(PROBE_LADDER_USD)
        return out

    last = rung_results[-1]
    out = dict(last)
    if out.get("depth_probe_status") != DEPTH_PROBE_TOO_THIN:
        out["depth_probe_status"] = DEPTH_PROBE_LOWER_BOUND_AT_MAX
        out["effective_depth_usd"] = max(
            float(out.get("effective_depth_usd") or 0),
            float(out.get("depth_probe_rung_usd") or PROBE_LADDER_USD[-1]),
        )
    out["depth_method"] = "marginal_anchor_ladder"
    out["depth_probe_ladder_usd"] = list(PROBE_LADDER_USD)
    return out


def binary_refine_capacity_usd(
    low_usd: float,
    high_usd: float,
    quote_at_usd: Callable[[float], Optional[Tuple[int, int]]],
    ref_in: int,
    ref_out: int,
    *,
    iterations: int = 6,
    impact_threshold_low: float = _IMPACT_THRESHOLD_LOW,
) -> float:
    """Binary search USD capacity between two ladder rungs (high has impact > threshold)."""
    lo, hi = float(low_usd), float(high_usd)
    best = capacity_usd_at_threshold(hi, impact_threshold_low + 0.01, impact_threshold_low=impact_threshold_low)
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        quoted = quote_at_usd(mid)
        if quoted is None:
            hi = mid
            continue
        probe_in, probe_out = quoted
        impact = marginal_impact(ref_in, ref_out, probe_in, probe_out)
        if impact is None:
            hi = mid
            continue
        if impact > impact_threshold_low:
            best = capacity_usd_at_threshold(mid, impact, impact_threshold_low=impact_threshold_low)
            hi = mid
        else:
            lo = mid
    return round(best, 2)


def v2_analytical_depth_usd(
    reserve_in_raw: int,
    dec_in: int,
    price_in_usd: float,
    *,
    fee_bps: int = 30,
    impact_threshold: float = _IMPACT_THRESHOLD_LOW,
) -> float:
    """CPMM analytical depth on the input side (reserves-based, no quote probe)."""
    if reserve_in_raw <= 0 or price_in_usd <= 0:
        return 0.0
    fee_mult = max(_FEE_DENOMINATOR_BPS - int(fee_bps), 1) / float(_FEE_DENOMINATOR_BPS)
    amt_raw = int(
        reserve_in_raw * impact_threshold / max(1.0 - impact_threshold, 0.01) * fee_mult
    )
    return round((amt_raw / (10 ** int(dec_in))) * float(price_in_usd), 2)


def v3_liquidity_depth_lower_bound_usd(
    liquidity_raw: int,
    sqrt_price_x96: int,
    dec_in: int,
    price_in_usd: float,
    *,
    impact_threshold: float = _IMPACT_THRESHOLD_LOW,
) -> Optional[float]:
    """Conservative CL depth lower bound from on-chain ``liquidity`` + ``sqrtPriceX96``."""
    if liquidity_raw <= 0 or sqrt_price_x96 <= 0 or price_in_usd <= 0:
        return None
    sqrt_ratio = float(sqrt_price_x96) / (2.0 ** 96)
    if sqrt_ratio <= 0:
        return None
    # token0 amount for a small sqrt-price move: delta_x ≈ L * t / sqrt(P)
    amt0 = (
        float(liquidity_raw)
        * impact_threshold
        / (sqrt_ratio * max(1.0 - impact_threshold, 0.01))
    )
    usd = (amt0 / (10 ** int(dec_in))) * float(price_in_usd)
    if usd <= 0:
        return None
    return round(usd, 2)


def mark_analytical_depth_suspect(result: Dict[str, Any]) -> Dict[str, Any]:
    """Flag outlier analytical depths; keep raw value for topology diagnostics."""
    out = dict(result)
    depth = out.get("effective_depth_usd")
    if depth is None:
        return out
    try:
        depth_f = float(depth)
    except (TypeError, ValueError):
        return out
    if depth_f > MAX_SANE_DEPTH_USD:
        out["depth_analytical_suspect_usd"] = round(depth_f, 2)
        out["depth_probe_status"] = DEPTH_PROBE_ANALYTICAL_SUSPECT
        out["depth_reject_reason"] = "ANALYTICAL_DEPTH_OUTLIER"
        out["effective_depth_usd"] = None
    return out


def merge_depth_with_analytical(
    probe_result: Dict[str, Any],
    analytical_usd: Optional[float],
    *,
    analytical_method: str,
) -> Dict[str, Any]:
    """Take max(probe, analytical) when analytical is available."""
    if not analytical_usd or analytical_usd <= 0:
        return mark_analytical_depth_suspect(probe_result)
    out = dict(probe_result)
    cur = float(out.get("effective_depth_usd") or 0)
    if analytical_usd > cur:
        out["effective_depth_usd"] = round(float(analytical_usd), 2)
        if out.get("depth_probe_status") in (DEPTH_PROBE_UNKNOWN, DEPTH_PROBE_LOWER_BOUND_AT_MAX):
            out["depth_probe_status"] = DEPTH_PROBE_MEASURED_CAPACITY
        out["depth_analytical_usd"] = round(float(analytical_usd), 2)
        out["depth_analytical_method"] = analytical_method
    return mark_analytical_depth_suspect(out)


def is_measured_depth_status(status: Optional[str]) -> bool:
    return status in (
        DEPTH_PROBE_MEASURED_CAPACITY,
        DEPTH_PROBE_LOWER_BOUND_AT_MAX,
    )
