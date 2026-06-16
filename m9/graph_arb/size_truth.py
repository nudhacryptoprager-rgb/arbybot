"""Quote-size truth helpers: liveness vs economics ladders."""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

# Sizes at or below this USD notional are liveness probes only.
LIVENESS_MAX_SIZE_USD: float = 5.0

# Default target net bps for economic floor when config omits override.
_DEFAULT_TARGET_NET_BPS: float = 10.0


def economic_size_floor_usd(
    *,
    gas_usd: float = 0.05,
    l1_fee_usd: float = 0.01,
    slippage_bps: float = 5.0,
    target_net_bps: float = _DEFAULT_TARGET_NET_BPS,
    safety_factor: float = 1.5,
    min_floor_usd: float = 25.0,
) -> float:
    """Minimum notional so fixed gas/L1 is not dominant vs target net edge.

    Solves: (gas + l1) / size * 10_000 + slippage_bps <= target_net_bps (approx).
  """
    if target_net_bps <= slippage_bps:
        return max(min_floor_usd, 100.0)
    fixed = max(gas_usd + l1_fee_usd, 0.0)
    variable_budget_bps = target_net_bps - slippage_bps
    if variable_budget_bps <= 0:
        return max(min_floor_usd, 100.0)
    raw = fixed / (variable_budget_bps / 10_000.0) * safety_factor
    return round(max(min_floor_usd, raw), 2)


def split_liveness_econ_sizes(
    sizes_usd: Sequence[float],
    econ_floor_usd: float,
) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    """Partition a size ladder into liveness probes and economics sizes."""
    liveness = tuple(sorted({float(s) for s in sizes_usd if float(s) <= LIVENESS_MAX_SIZE_USD}))
    econ = tuple(sorted({float(s) for s in sizes_usd if float(s) >= econ_floor_usd}))
    return liveness, econ


def is_liveness_size(size_usd: float) -> bool:
    return float(size_usd) <= LIVENESS_MAX_SIZE_USD


def is_econ_size(size_usd: float, econ_floor_usd: float) -> bool:
    return float(size_usd) >= float(econ_floor_usd)


def quote_size_truth_metrics(
    cycle_results: Sequence[Any],
    *,
    econ_floor_usd: float,
    liveness_max_size_usd: float = LIVENESS_MAX_SIZE_USD,
) -> Dict[str, Any]:
    """Histograms for attempted/selected quote sizes vs economics floor."""
    from collections import Counter

    attempted: Counter[str] = Counter()
    selected: Counter[str] = Counter()
    below_econ = 0
    liveness_attempts = 0
    econ_attempts = 0
    for qr in cycle_results:
        sz = round(float(getattr(qr, "size_usd", 0.0) or 0.0), 4)
        key = str(sz)
        attempted[key] += 1
        if is_liveness_size(sz):
            liveness_attempts += 1
        if is_econ_size(sz, econ_floor_usd):
            econ_attempts += 1
        if sz < econ_floor_usd:
            below_econ += 1
        status = getattr(qr, "status", "")
        if status in ("POSITIVE_GROSS", "NEGATIVE_GROSS"):
            selected[key] += 1
    return {
        "liveness_max_size_usd": liveness_max_size_usd,
        "economic_size_floor_usd": econ_floor_usd,
        "econ_floor_usd": econ_floor_usd,
        "liveness_quote_attempts": liveness_attempts,
        "econ_quote_attempts": econ_attempts,
        "below_econ_quote_attempts": below_econ,
        "attempted_size_usd_histogram": dict(sorted(attempted.items(), key=lambda kv: float(kv[0]))),
        "selected_size_usd_histogram": dict(sorted(selected.items(), key=lambda kv: float(kv[0]))),
    }


def cost_profile_from_model(cost_model: Optional[Dict]) -> Dict[str, float]:
    if not cost_model:
        return {"gas_usd": 0.05, "l1_fee_usd": 0.01, "slippage_bps": 5.0}
    profile = (cost_model.get("profiles") or {}).get(
        cost_model.get("default_profile", "default"), {}
    )
    return {
        "gas_usd": float(profile.get("gas_usd", 0.05)),
        "l1_fee_usd": float(profile.get("l1_fee_usd", 0.01)),
        "slippage_bps": float(profile.get("slippage_bps", 5.0)),
    }
