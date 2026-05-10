"""E1.76 — Depth-aware profit ladder, MAV estimate, lag score.

Pure functions consumed by the cold scanner and dashboard to rank
candidates by *executable* depth and *correlated price divergence*
rather than naive bps.

Concepts
--------

``expected_profit_usd_at_depth``
    For a fixed ladder of probe sizes (default ``[10, 25, 50, 100, 250,
    500]`` USD), compute net USD profit from a depth curve produced by
    the simulator.  The depth curve is a list of ``{size_usd, net_bps,
    expected_profit_usd}`` dicts already produced by
    ``scoring_parallel``.  We *interpolate* between adjacent rungs so a
    soak with sparse rungs still resolves meaningful values.

``MAV_estimate_usd``  (Maximal Arbitrage Value)
    Following Uniswap-style price-divergence research: ``MAV ≈ price
    divergence × executable liquidity`` capped by gas / cost.  Here we
    approximate it as ``min(profit_at_depth) over the executable
    depths`` — i.e. the largest profit *that can actually clear*, not
    the speculative bps × notional.

``lag_score``
    Heuristic 0-100 score combining seconds-since-last-swap and
    volume-imbalance between paired pools.  High score means stale
    pricing and high probability of an arbitrage edge persisting.

All functions return primitives or simple dicts; never raise on bad
input.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

__all__ = [
    "DEFAULT_DEPTH_LADDER_USD",
    "expected_profit_at_depth",
    "mav_estimate_usd",
    "lag_score",
    "build_depth_ladder",
]


# Conventional probe rungs for the cold scanner.  The user/GPT directive
# explicitly calls out $10 / $25 / $50 / $100 / $250 / $500.
DEFAULT_DEPTH_LADDER_USD: Sequence[float] = (10.0, 25.0, 50.0, 100.0, 250.0, 500.0)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return f


def _normalize_curve(depth_curve: Iterable[Dict[str, Any]]) -> List[Dict[str, float]]:
    out: List[Dict[str, float]] = []
    for r in depth_curve or []:
        if not isinstance(r, dict):
            continue
        size = _safe_float(r.get("size_usd"))
        if size <= 0:
            continue
        out.append(
            {
                "size_usd": size,
                "net_bps": _safe_float(r.get("net_bps")),
                "profit_usd": _safe_float(
                    r.get("expected_profit_usd")
                    if "expected_profit_usd" in r
                    else r.get("profit_usd")
                ),
            }
        )
    out.sort(key=lambda x: x["size_usd"])
    return out


def expected_profit_at_depth(
    depth_curve: Iterable[Dict[str, Any]],
    target_usd: float,
) -> float:
    """Profit (USD) at ``target_usd`` size, linearly interpolated.

    Returns 0.0 when the curve is empty or the target is below the
    smallest rung.  Above the largest rung, conservatively returns the
    profit at the largest rung *clamped at zero* (no extrapolation —
    real pools degrade non-linearly past the simulated max).
    """
    curve = _normalize_curve(depth_curve)
    if not curve:
        return 0.0
    target = _safe_float(target_usd)
    if target <= 0:
        return 0.0
    # below smallest rung
    if target < curve[0]["size_usd"]:
        return 0.0
    # above largest rung: do not extrapolate optimistically
    if target >= curve[-1]["size_usd"]:
        return max(0.0, curve[-1]["profit_usd"]) if target == curve[-1]["size_usd"] \
            else max(0.0, curve[-1]["profit_usd"])
    # linear interpolation between bracketing rungs
    for i in range(len(curve) - 1):
        lo, hi = curve[i], curve[i + 1]
        if lo["size_usd"] <= target <= hi["size_usd"]:
            span = hi["size_usd"] - lo["size_usd"]
            if span <= 0:
                return lo["profit_usd"]
            t = (target - lo["size_usd"]) / span
            return lo["profit_usd"] + t * (hi["profit_usd"] - lo["profit_usd"])
    return 0.0


def build_depth_ladder(
    depth_curve: Iterable[Dict[str, Any]],
    rungs_usd: Sequence[float] = DEFAULT_DEPTH_LADDER_USD,
) -> List[Dict[str, float]]:
    """Project a (possibly sparse) depth curve onto canonical rungs.

    Returns a list ordered by rung size with
    ``{"size_usd", "expected_profit_usd"}`` entries, suitable for the
    dashboard heatmap.
    """
    return [
        {
            "size_usd": float(r),
            "expected_profit_usd": round(
                float(expected_profit_at_depth(depth_curve, r)), 6
            ),
        }
        for r in rungs_usd
    ]


def mav_estimate_usd(
    depth_curve: Iterable[Dict[str, Any]],
    rungs_usd: Sequence[float] = DEFAULT_DEPTH_LADDER_USD,
) -> Dict[str, float]:
    """Maximal Arbitrage Value estimate.

    We define MAV here as the *peak* expected_profit_usd over the
    canonical rungs — i.e. the largest dollar profit that is actually
    executable on the simulated curve.  The corresponding rung is
    returned as ``best_size_usd``.  This sidesteps the well-known
    "infinite spread × tiny depth" trap of bps-only ranking.
    """
    curve_norm = _normalize_curve(depth_curve)
    if not curve_norm:
        return {"mav_usd": 0.0, "best_size_usd": 0.0}
    ladder = build_depth_ladder(depth_curve, rungs_usd)
    if not ladder:
        return {"mav_usd": 0.0, "best_size_usd": 0.0}
    best = max(ladder, key=lambda x: x["expected_profit_usd"])
    return {
        "mav_usd": round(max(0.0, float(best["expected_profit_usd"])), 6),
        "best_size_usd": float(best["size_usd"]),
    }


def lag_score(
    *,
    seconds_since_last_swap: Optional[float] = None,
    volume_imbalance_ratio: Optional[float] = None,
    price_divergence_bps: Optional[float] = None,
) -> float:
    """Heuristic 0-100 staleness/divergence score.

    Components (each 0..1, then averaged and scaled):
      * ``stale``            : ``min(seconds_since_last_swap / 300, 1)``
      * ``imbalance``        : ``min(volume_imbalance_ratio, 1)``
      * ``divergence``       : ``min(abs(price_divergence_bps) / 100, 1)``

    Missing components are skipped (mean of available ones).  Returns
    0.0 when no inputs are usable.
    """
    parts: List[float] = []
    if seconds_since_last_swap is not None:
        s = _safe_float(seconds_since_last_swap)
        parts.append(min(max(s, 0.0) / 300.0, 1.0))
    if volume_imbalance_ratio is not None:
        v = _safe_float(volume_imbalance_ratio)
        parts.append(min(max(v, 0.0), 1.0))
    if price_divergence_bps is not None:
        d = abs(_safe_float(price_divergence_bps))
        parts.append(min(d / 100.0, 1.0))
    if not parts:
        return 0.0
    return round(100.0 * sum(parts) / len(parts), 3)
