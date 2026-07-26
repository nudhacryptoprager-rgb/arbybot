"""Route-level depth probe contract for M9 inventories."""
from __future__ import annotations

from typing import Any, Dict, Optional

DEPTH_CONTRACT_KEYS = (
    "effective_depth_usd",
    "usable_depth_usd",
    "depth_probe_status",
    "depth_method",
    "depth_source",
    "depth_block_number",
    "depth_confidence",
    "depth_error_code",
)

_PROBE_ERROR_TO_CODE = {
    "NO_QUOTER": "UNSUPPORTED",
    "NO_ANCHOR_FOR_DEPTH": "NO_ANCHOR_PRICE",
    "V2_RESERVES_FAILED": "NO_LIQUIDITY",
    "V2_ZERO_RESERVES": "NO_LIQUIDITY",
    "ZERO_AMOUNT_IN": "NO_LIQUIDITY",
    "QUOTE_REVERT": "REVERT",
    "QUOTE_FAIL": "REVERT",
    "V4_DEPTH_UNSUPPORTED": "UNSUPPORTED",
    "MISSING_TOKEN_ADDR": "UNSUPPORTED",
    "UNKNOWN_TOKEN": "UNSUPPORTED",
}


def depth_error_code_from_probe(
    *,
    probe_error: Optional[str],
    depth_probe_status: Optional[str],
    effective_depth_usd: Optional[float],
) -> Optional[str]:
    if effective_depth_usd is not None:
        return None
    if probe_error:
        upper = str(probe_error).upper()
        for prefix, code in _PROBE_ERROR_TO_CODE.items():
            if upper.startswith(prefix) or prefix in upper:
                return code
        return "PROBE_FAIL"
    status = str(depth_probe_status or "").upper()
    if status in {"DEPTH_PROBE_TOO_THIN", "DEPTH_PROBE_UNKNOWN"}:
        return "NO_LIQUIDITY"
    if status == "DEPTH_PROBE_ANALYTICAL_SUSPECT":
        return "UNSUPPORTED"
    return None


def normalize_route_depth_contract(
    route: Dict[str, Any],
    *,
    block_number: Optional[int] = None,
    depth_source: Optional[str] = None,
    depth_confidence: Optional[str] = None,
) -> None:
    """Ensure canonical depth fields exist on a bridge route row."""
    for key in DEPTH_CONTRACT_KEYS:
        route.setdefault(key, None)

    if depth_source is not None:
        route["depth_source"] = depth_source
    elif route.get("depth_price_source"):
        route["depth_source"] = str(route["depth_price_source"])
    elif route.get("depth_method"):
        route["depth_source"] = str(route["depth_method"])

    if block_number is not None:
        route["depth_block_number"] = int(block_number)
    elif route.get("depth_block_number") is None and route.get("block_number") is not None:
        route["depth_block_number"] = route.get("block_number")

    if depth_confidence is not None:
        route["depth_confidence"] = depth_confidence
    elif route.get("depth_confidence") is None:
        status = str(route.get("depth_probe_status") or "")
        if status == "MEASURED_CAPACITY":
            route["depth_confidence"] = "measured"
        elif status in {"LOWER_BOUND_AT_MAX", "LOWER_BOUND_AT_MAX_PROBE"}:
            route["depth_confidence"] = "lower_bound"
        elif route.get("effective_depth_usd") is not None:
            route["depth_confidence"] = "inferred"

    depth = route.get("effective_depth_usd")
    if route.get("usable_depth_usd") is None and depth is not None:
        try:
            route["usable_depth_usd"] = round(float(depth), 2)
        except (TypeError, ValueError):
            pass

    route["depth_error_code"] = depth_error_code_from_probe(
        probe_error=route.get("depth_probe_error") or route.get("probe_error"),
        depth_probe_status=route.get("depth_probe_status"),
        effective_depth_usd=route.get("effective_depth_usd"),
    )


# ---------------------------------------------------------------------------
# Cycle-level economic capacity verdict (Step 2 P0)
# ---------------------------------------------------------------------------
# This section decouples two universes that were previously conflated:
#
# * ``topology_admitted`` — a route may participate in graph build and
#   topology diagnostics even when its raw depth is far below the economics
#   floor.  This keeps topology diagnostics meaningful and prevents the graph
#   from collapsing to zero whenever the long-tail universe is thin.
#
# * ``economics_ready`` — a cycle's bottleneck usable capacity
#   (``min(edge_depth * family_fraction)``) must meet the active economics
#   floor before any RPC quote is dispatched.  This is the *execution* universe.
#
# The split fixes the root cause of ``ECON_RPC_QUOTE_NOT_ATTEMPTED`` observed
# in session ``2026-07-26T13:04:06Z``: the graph admitted routes at a ~$50
# topology threshold while the quoter required an effective ~$1,200–$9,000 raw
# depth (depending on family fraction), so 2182/2468 attempts died at
# ``DEPTH_BELOW_ECONOMICS_FLOOR`` without a single RPC call.

from dataclasses import dataclass, field  # noqa: E402
from typing import Iterable, List, Tuple  # noqa: E402

from m9.graph_arb.adapter_families import route_family  # noqa: E402
from m9.graph_arb.models import GraphCycle, GraphEdge  # noqa: E402
from m9.graph_arb.per_dex_sizing import depth_fraction_for_family  # noqa: E402

REASON_READY = "ready"
REASON_UNKNOWN_DEPTH = "unknown_depth"
REASON_BELOW_FLOOR = "below_economics_floor"
REASON_EMPTY_CYCLE = "empty_cycle"


@dataclass(frozen=True)
class CycleCapacityVerdict:
    """Pure verdict for one cycle against one economics floor."""

    cycle_id: str
    ready: bool
    reason: str
    bottleneck_route_id: Optional[str]
    bottleneck_dex_id: Optional[str]
    bottleneck_adapter_type: Optional[str]
    raw_depth_usd: Optional[float]
    family_fraction: Optional[float]
    usable_capacity_usd: Optional[float]
    required_depth_usd: Optional[float]
    economics_floor_usd: float
    length: int
    leg_verdicts: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "ready": self.ready,
            "reason": self.reason,
            "bottleneck_route_id": self.bottleneck_route_id,
            "bottleneck_dex_id": self.bottleneck_dex_id,
            "bottleneck_adapter_type": self.bottleneck_adapter_type,
            "raw_depth_usd": self.raw_depth_usd,
            "family_fraction": self.family_fraction,
            "usable_capacity_usd": self.usable_capacity_usd,
            "required_depth_usd": self.required_depth_usd,
            "economics_floor_usd": self.economics_floor_usd,
            "length": self.length,
            "leg_verdicts": list(self.leg_verdicts),
        }


def required_route_depth_usd(
    economics_floor_usd: float,
    family: str,
    *,
    depth_probe_status: Optional[str] = None,
) -> float:
    """Raw route depth required so one leg can absorb ``economics_floor_usd``."""
    floor = float(economics_floor_usd)
    if floor <= 0:
        return 0.0
    frac = float(depth_fraction_for_family(family, depth_probe_status=depth_probe_status))
    if frac <= 0:
        from m9.graph_arb.per_dex_sizing import _DEFAULT_DEPTH_FRACTION

        frac = float(_DEFAULT_DEPTH_FRACTION)
    return round(floor / frac, 4)


def _edge_verdict(edge: GraphEdge, economics_floor_usd: float) -> Dict[str, Any]:
    family = route_family(
        {"dex_id": edge.dex_id, "adapter_type": edge.adapter_type}
    )
    frac = float(
        depth_fraction_for_family(
            family, depth_probe_status=getattr(edge, "depth_probe_status", None)
        )
    )
    raw = edge.effective_depth_usd
    raw_f = float(raw) if isinstance(raw, (int, float)) else None
    usable = round(raw_f * frac, 4) if raw_f is not None and raw_f > 0 else None
    required = required_route_depth_usd(
        economics_floor_usd, family, depth_probe_status=getattr(edge, "depth_probe_status", None)
    )
    if raw_f is None:
        reason = REASON_UNKNOWN_DEPTH
    elif usable is None or usable < float(economics_floor_usd):
        reason = REASON_BELOW_FLOOR
    else:
        reason = REASON_READY
    return {
        "route_id": edge.route_id,
        "dex_id": edge.dex_id,
        "adapter_type": edge.adapter_type,
        "family": family,
        "raw_depth_usd": raw_f,
        "family_fraction": round(frac, 4),
        "usable_capacity_usd": usable,
        "required_depth_usd": required,
        "reason": reason,
    }


def evaluate_cycle_economic_capacity(
    cycle: GraphCycle,
    economics_floor_usd: float,
) -> CycleCapacityVerdict:
    """Evaluate one cycle against the active economics floor."""
    floor = float(economics_floor_usd)
    edges = list(cycle.edges)
    if not edges:
        return CycleCapacityVerdict(
            cycle_id=cycle.cycle_id,
            ready=False,
            reason=REASON_EMPTY_CYCLE,
            bottleneck_route_id=None,
            bottleneck_dex_id=None,
            bottleneck_adapter_type=None,
            raw_depth_usd=None,
            family_fraction=None,
            usable_capacity_usd=None,
            required_depth_usd=None,
            economics_floor_usd=floor,
            length=cycle.length,
            leg_verdicts=(),
        )

    leg_verdicts = tuple(_edge_verdict(e, floor) for e in edges)

    def _usable_key(v: Dict[str, Any]) -> float:
        u = v.get("usable_capacity_usd")
        return float(u) if isinstance(u, (int, float)) else -1.0

    bottleneck = min(leg_verdicts, key=_usable_key)
    any_unknown = any(v["reason"] == REASON_UNKNOWN_DEPTH for v in leg_verdicts)
    any_below = any(v["reason"] == REASON_BELOW_FLOOR for v in leg_verdicts)
    if any_unknown:
        reason = REASON_UNKNOWN_DEPTH
    elif any_below:
        reason = REASON_BELOW_FLOOR
    else:
        reason = REASON_READY

    return CycleCapacityVerdict(
        cycle_id=cycle.cycle_id,
        ready=(reason == REASON_READY),
        reason=reason,
        bottleneck_route_id=bottleneck["route_id"],
        bottleneck_dex_id=bottleneck["dex_id"],
        bottleneck_adapter_type=bottleneck["adapter_type"],
        raw_depth_usd=bottleneck["raw_depth_usd"],
        family_fraction=bottleneck["family_fraction"],
        usable_capacity_usd=bottleneck["usable_capacity_usd"],
        required_depth_usd=bottleneck["required_depth_usd"],
        economics_floor_usd=floor,
        length=cycle.length,
        leg_verdicts=leg_verdicts,
    )


def evaluate_cycles_economic_capacity(
    cycles: Iterable[GraphCycle],
    economics_floor_usd: float,
) -> List[CycleCapacityVerdict]:
    return [evaluate_cycle_economic_capacity(c, economics_floor_usd) for c in cycles]


def cycle_contract_hash(verdict: CycleCapacityVerdict) -> str:
    """Stable hash of the verdict's capacity-relevant fields (all legs)."""
    import hashlib

    def _hash_field(value: Any) -> str:
        if value is None:
            return "<none>"
        return str(value)

    leg_parts = []
    for lv in sorted(
        verdict.leg_verdicts,
        key=lambda x: str(x.get("route_id") or ""),
    ):
        leg_parts.append(
            "|".join(
                _hash_field(lv.get(k))
                for k in (
                    "route_id",
                    "dex_id",
                    "adapter_type",
                    "family",
                    "raw_depth_usd",
                    "family_fraction",
                    "usable_capacity_usd",
                    "required_depth_usd",
                    "reason",
                )
            )
        )
    payload = "|".join(
        [
            _hash_field(verdict.cycle_id),
            _hash_field(verdict.ready),
            _hash_field(verdict.reason),
            _hash_field(verdict.bottleneck_route_id),
            _hash_field(verdict.raw_depth_usd),
            _hash_field(verdict.family_fraction),
            _hash_field(verdict.usable_capacity_usd),
            _hash_field(verdict.required_depth_usd),
            _hash_field(verdict.economics_floor_usd),
        ]
        + leg_parts
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
