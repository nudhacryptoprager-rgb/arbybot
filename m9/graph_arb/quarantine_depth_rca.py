"""RCA for quarantined / toxic depth routes — false-positive vs genuinely thin."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from m9.graph_arb.depth_telemetry import classify_depth_reject_class

# Routes probed via distinct_depth_probe often cap effective_depth at ~$10 with
# artificial 95%+ impact — not the same as on-chain dead pools.
_FALLBACK_DEPTH_USD_MAX = 12.0
_FALSE_POSITIVE_IMPACT_MIN = 0.85


def _is_quarantine_candidate(route: Dict[str, Any]) -> bool:
    if route.get("quarantined") is True:
        return True
    if route.get("pool_quality_state") == "QUARANTINED":
        return True
    if route.get("productive_admission_block_reason") == "quarantined":
        return True
    reason = str(route.get("depth_reject_reason") or "").upper()
    return reason in ("TOXIC_PRICE_IMPACT", "QUARANTINED")


def is_false_positive_toxic_depth(route: Dict[str, Any]) -> bool:
    """Probe-band toxicity that should not hard-quarantine productive admission."""
    bucket = classify_quarantine_route(route)
    return bucket in (
        "false_positive_depth_cap_band",
        "false_positive_distinct_probe_toxicity",
    )


def classify_quarantine_route(route: Dict[str, Any]) -> str:
    """Return RCA bucket for a quarantined or toxic-depth route."""
    reason = str(route.get("depth_reject_reason") or "").upper()
    reject_class = route.get("depth_reject_class") or classify_depth_reject_class(reason)
    probe_src = str(route.get("depth_probe_source") or "")
    impact = route.get("price_impact_at_100usd")
    depth = route.get("effective_depth_usd")
    try:
        impact_f = float(impact) if impact is not None else None
    except (TypeError, ValueError):
        impact_f = None
    try:
        depth_f = float(depth) if depth is not None else None
    except (TypeError, ValueError):
        depth_f = None

    if reject_class == "analytical_suspect":
        return "analytical_suspect_depth"
    if reason == "LOW_EFFECTIVE_DEPTH" or reject_class == "low_capacity":
        return "genuinely_low_capacity"
    if route.get("depth_probe_error") or route.get("depth_probe_status") == "DEPTH_PROBE_UNKNOWN":
        return "adapter_probe_failed"

    if reason == "TOXIC_PRICE_IMPACT":
        fallback_band = (
            depth_f is not None
            and 9.5 <= depth_f <= _FALLBACK_DEPTH_USD_MAX
            and impact_f is not None
            and impact_f >= _FALSE_POSITIVE_IMPACT_MIN
        )
        if fallback_band and (
            probe_src == "distinct_depth_probe"
            or route.get("distinct_depth_probe") is True
            or route.get("depth_status") == "FALLBACK_CAPPED"
        ):
            return "false_positive_distinct_probe_toxicity"
        if fallback_band:
            return "false_positive_depth_cap_band"
        if depth_f is not None and depth_f <= 25.0 and impact_f is not None and impact_f >= 0.5:
            return "genuinely_thin_or_toxic"
        return "toxicity_unclassified"

    qreason = str(route.get("quarantine_reason") or "")
    if qreason:
        return f"structural_{qreason.lower()}"
    return "unclassified"


def run_quarantine_depth_rca(
    *,
    active_routes: List[Dict[str, Any]],
    quarantined_routes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Summarize quarantine/toxic depth RCA for bridge inventory routes."""
    active_candidates = [r for r in active_routes if _is_quarantine_candidate(r)]
    structural = list(quarantined_routes or [])

    by_bucket: Counter[str] = Counter()
    samples: Dict[str, List[Dict[str, Any]]] = {}
    route_rows: List[Dict[str, Any]] = []

    for route in active_candidates:
        bucket = classify_quarantine_route(route)
        by_bucket[bucket] += 1
        row = {
            "route_id": route.get("route_id"),
            "dex_id": route.get("dex_id"),
            "pool_address": route.get("pool_address"),
            "depth_reject_reason": route.get("depth_reject_reason"),
            "depth_reject_class": route.get("depth_reject_class")
            or classify_depth_reject_class(route.get("depth_reject_reason")),
            "effective_depth_usd": route.get("effective_depth_usd"),
            "price_impact_at_100usd": route.get("price_impact_at_100usd"),
            "depth_probe_source": route.get("depth_probe_source"),
            "rca_bucket": bucket,
        }
        route_rows.append(row)
        if len(samples.get(bucket, [])) < 5:
            samples.setdefault(bucket, []).append(row)

    structural_by_reason: Counter[str] = Counter(
        str(r.get("quarantine_reason") or "UNKNOWN") for r in structural
    )

    false_positive = int(by_bucket.get("false_positive_distinct_probe_toxicity", 0)) + int(
        by_bucket.get("false_positive_depth_cap_band", 0)
    )
    genuine_thin = int(by_bucket.get("genuinely_thin_or_toxic", 0)) + int(
        by_bucket.get("genuinely_low_capacity", 0)
    )
    probe_failed = int(by_bucket.get("adapter_probe_failed", 0))

    if false_positive > genuine_thin:
        primary_verdict = "DEPTH_TOXICITY_FALSE_POSITIVE_DOMINANT"
        operator_note = (
            "Most active quarantines are distinct_depth_probe fallback (~$10 cap, "
            ">85% impact) — treat as probe artifact, not dead-pool market verdict."
        )
    elif genuine_thin > 0:
        primary_verdict = "GENUINELY_THIN_POOLS_DOMINANT"
        operator_note = "Quarantines reflect measured thin/toxic liquidity."
    else:
        primary_verdict = "QUARANTINE_MIXED_OR_UNCLASSIFIED"
        operator_note = "Review per-bucket histogram."

    return {
        "active_quarantine_candidates": len(active_candidates),
        "structural_quarantined_routes": len(structural),
        "by_rca_bucket": dict(sorted(by_bucket.items())),
        "structural_quarantine_reason_histogram": dict(
            sorted(structural_by_reason.items())
        ),
        "false_positive_distinct_probe_count": false_positive,
        "genuinely_thin_or_toxic_count": genuine_thin,
        "adapter_probe_failed_count": probe_failed,
        "primary_verdict": primary_verdict,
        "operator_note": operator_note,
        "samples_by_bucket": samples,
        "route_rows": route_rows,
    }
