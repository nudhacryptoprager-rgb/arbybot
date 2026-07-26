#!/usr/bin/env python3
"""Per-layer M8->M8.1->M8.2->M9 bridge acceptance report from rolling artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from m8.discovery.fresh_direct_queue import build_fresh_direct_queue_snapshot
from monitoring.sniper_artifacts import (  # noqa: E402
    M9_SNIPER_BLOCKER,
    assess_sniper_artifact_for_m9,
)

# ---------------------------------------------------------------------------
# Freshness / provenance gate (Patch 3)
#
# Cross-artifact freshness contract: M8.2, M8.3, bridge, shadow and capacity
# artifacts must come from a single coherent runtime window before any M9
# claim can be accepted. Mixed runtime windows are an explicit blocker even
# when individual upstream gates pass.
#
# Staleness thresholds are conservative ceilings keyed on the same artifact
# ``generated_at_utc`` already published by upstream scripts. Defaults are
# intentionally generous (production runtime windows in this project refresh
# on the order of tens of minutes to hours): the goal is to catch *mixed*
# provenance and gross staleness, not to enforce a tight SLA here.
# ---------------------------------------------------------------------------
FRESHNESS_STALE_SECONDS = {
    "m8_2": 6 * 3600,     # 6h
    "m8_3": 6 * 3600,     # 6h
    "bridge": 6 * 3600,   # 6h
    "shadow": 24 * 3600,  # 1d (shadow runs are bounded sessions)
    "capacity": 24 * 3600,
    "sniper": 30 * 60,    # 30m (sniper is the hottest upstream input)
}

# Allow artifacts to be up to this far apart in wall-clock time and still
# count as one runtime window. Guards against stitching unrelated runs.
FRESHNESS_MISMATCH_SECONDS = 30 * 60  # 30 min

# When session_id binding is exact across bridge/shadow/capacity, allow a wider
# wall-clock spread before declaring MIXED_RUNTIME_WINDOW.
SESSION_ALIGNED_MISMATCH_SECONDS = 90 * 60  # 90 min

# Pipeline latency SLO: final sniper artifact -> first shadow econ quote.
# Separate from SESSION_ALIGNED_MISMATCH_SECONDS (session TTL compensation).
SNIPER_TO_SHADOW_QUOTE_SLO_SECONDS = 45 * 60  # 45 min

FRESHNESS_BLOCKER_BY_KEY = {
    "m8_2": "M8_2_STALE",
    "m8_3": "M8_3_STALE",
    "bridge": "BRIDGE_STALE",
    "shadow": "SHADOW_STALE",
    "capacity": "CAPACITY_STALE",
    "sniper": "M8_SNIPER_STALE",
}


def _parse_iso_ts(ts: Optional[str]) -> Optional[Any]:
    """Parse an ISO-8601 timestamp (with optional trailing Z) into a
    timezone-aware datetime. Returns None on missing/unparseable input."""
    if not ts:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _now_utc() -> Any:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc)


def _artifact_timestamps(
    *,
    sniper: Optional[Dict[str, Any]],
    bridge: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
    m8_2_report: Optional[Dict[str, Any]],
    m8_3_registry: Optional[Dict[str, Any]],
    capacity_metrics: Optional[Dict[str, Any]],
) -> Dict[str, Optional[str]]:
    """Collect the canonical ``generated_at_utc`` (or equivalent) timestamp
    from each cross-artifact input. Missing inputs yield None (explicit
    blocker downstream, not a silent pass)."""
    bsm = (bridge or {}).get("bridge_source_metrics") or {}
    return {
        "sniper": (
            bsm.get("sniper_generated_at_utc")
            or (sniper or {}).get("generated_at_utc")
        ),
        "m8_2": (
            (m8_2_report or {}).get("generated_at_utc")
            or (m8_2_report or {}).get("provenance", {}).get("generated_at_utc")
        ),
        "m8_3": (m8_3_registry or {}).get("generated_at_utc"),
        "bridge": (bridge or {}).get("generated_at_utc"),
        "shadow": (
            (shadow or {}).get("generated_at_utc")
            or (shadow or {}).get("run_timestamp")
        ),
        "capacity": (
            (capacity_metrics or {}).get("generated_at_utc")
            or (capacity_metrics or {}).get("run_timestamp")
        ),
    }


def _session_id_from_artifact(doc: Optional[Dict[str, Any]]) -> Optional[str]:
    if not doc:
        return None
    sid = doc.get("session_id")
    if sid:
        return str(sid)
    rc = doc.get("run_context")
    if isinstance(rc, dict) and rc.get("session_id"):
        return str(rc["session_id"])
    uc = doc.get("universe_contract")
    if isinstance(uc, dict) and uc.get("session_id"):
        return str(uc["session_id"])
    depth = doc.get("depth_enrichment") or {}
    if isinstance(depth, dict) and depth.get("depth_enrichment_session_id"):
        return str(depth["depth_enrichment_session_id"])
    return None


def _session_binding_gate(
    *,
    sniper: Optional[Dict[str, Any]],
    bridge: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
    capacity_metrics: Optional[Dict[str, Any]],
    m8_2_report: Optional[Dict[str, Any]] = None,
    m8_3_registry: Optional[Dict[str, Any]] = None,
    skip_shadow: bool = False,
) -> Dict[str, Any]:
    """Require exact session_id alignment across M9 execution artifacts."""
    entries: Dict[str, Optional[Dict[str, Any]]] = {
        "bridge": bridge,
        "capacity": capacity_metrics,
        "shadow": None if skip_shadow else shadow,
        "sniper": sniper,
        "m8_2": m8_2_report,
        "m8_3": m8_3_registry,
    }
    per_artifact = {
        key: sid
        for key, doc in entries.items()
        if doc is not None
        for sid in [_session_id_from_artifact(doc)]
        if sid
    }
    blockers: List[str] = []
    shared_session: Optional[str] = None
    core_keys = ("bridge", "capacity") if skip_shadow else ("bridge", "capacity", "shadow")
    core_present = {k: per_artifact[k] for k in core_keys if k in per_artifact}
    if len(core_present) >= 2:
        distinct = set(core_present.values())
        if len(distinct) > 1:
            blockers.append("SESSION_ID_MISMATCH")
        else:
            shared_session = next(iter(distinct))
    core_with_docs = [k for k in core_keys if entries.get(k)]
    if core_with_docs and 0 < len(core_present) < len(core_with_docs):
        blockers.append("SESSION_ID_INCOMPLETE")
    return {
        "session_id": shared_session,
        "blockers": sorted(set(blockers)),
        "per_artifact": per_artifact,
        "missing_session_on": [
            k for k in core_with_docs if k not in per_artifact
        ],
    }


def _fresh_direct_cohort_counters(
    bridge: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
    bsm: Dict[str, Any],
) -> Dict[str, Any]:
    """First-class M8 fresh-direct cohort counters (admission + mirror recall)."""
    routes = [
        r
        for r in ((bridge or {}).get("active_routes") or [])
        if str(r.get("source") or "") == "m8_sniper"
    ]
    tokens: set[str] = set()
    pools: set[str] = set()
    mirrors = 0
    for route in routes:
        pool = str(route.get("pool_address") or "").lower()
        if pool:
            pools.add(pool)
        for key in ("token0", "token1"):
            tok = str(route.get(key) or "").lower()
            if tok:
                tokens.add(tok)
        if route.get("mirror_of") or route.get("verified_mirror"):
            mirrors += 1
    return {
        "tokens": len(tokens),
        "pools": len(pools),
        "routes": len(routes),
        "mirrors": mirrors,
        "cycles_found": int(
            (shadow or {}).get("m8_direct_cycles_found")
            or (shadow or {}).get("cycles_with_direct_sniper_pool")
            or 0
        ),
        "cycles_quoteable": int((shadow or {}).get("m8_direct_cycles_quoteable") or 0),
        "m8_direct_routes_in_bridge": bsm.get("m8_direct_routes_in_bridge"),
        "derived_m8_routes": max(
            0,
            int(bsm.get("graph_ready_from_m8") or 0)
            - int(bsm.get("m8_direct_routes_in_bridge") or 0),
        ),
        "configured_seed_routes": bsm.get("graph_ready_from_expansion"),
    }


def _sniper_to_shadow_quote_slo_gate(
    *,
    sniper: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
    skip_shadow: bool = False,
) -> Dict[str, Any]:
    """Pipeline latency SLO: final sniper artifact -> first shadow econ quote."""
    blockers: List[str] = []
    if skip_shadow or shadow is None or sniper is None:
        return {
            "slo_status": "SKIPPED",
            "blockers": blockers,
            "slo_budget_seconds": SNIPER_TO_SHADOW_QUOTE_SLO_SECONDS,
        }
    scan_scope = (shadow or {}).get("scan_scope") or {}
    quoted_ids = list(scan_scope.get("shadow_quoted_cycle_ids") or [])
    econ_attempts = int(
        ((shadow or {}).get("quote_size_truth") or {}).get("econ_rpc_quote_attempts") or 0
    )
    sniper_ts = _parse_iso_ts(sniper.get("generated_at_utc"))
    first_attempt_ts = _parse_iso_ts(scan_scope.get("first_econ_rpc_attempt_at_utc"))
    first_quote_ts = _parse_iso_ts(
        scan_scope.get("first_successful_econ_quote_at_utc")
        or scan_scope.get("first_shadow_quote_at_utc")
    )
    latency_s: Optional[float] = None
    slo_status = "PASS"

    if econ_attempts == 0:
        blockers.append("SNIPER_TO_SHADOW_QUOTE_NOT_MEASURED")
        slo_status = "NOT_MEASURED"
    elif sniper_ts is not None and first_attempt_ts is not None:
        latency_s = (first_attempt_ts - sniper_ts).total_seconds()
        if latency_s > SNIPER_TO_SHADOW_QUOTE_SLO_SECONDS:
            blockers.append("SNIPER_TO_SHADOW_QUOTE_SLO_EXCEEDED")
            slo_status = "BLOCKED"
    elif sniper_ts is not None and first_quote_ts is not None:
        latency_s = (first_quote_ts - sniper_ts).total_seconds()
        if latency_s > SNIPER_TO_SHADOW_QUOTE_SLO_SECONDS:
            blockers.append("SNIPER_TO_SHADOW_QUOTE_SLO_EXCEEDED")
            slo_status = "BLOCKED"
    elif quoted_ids:
        blockers.append("SNIPER_TO_SHADOW_QUOTE_SLO_UNMEASURED")
        slo_status = "BLOCKED"
    elif econ_attempts > 0:
        blockers.append("SNIPER_TO_SHADOW_QUOTE_SLO_UNMEASURED")
        slo_status = "BLOCKED"

    if blockers and slo_status == "PASS":
        slo_status = "BLOCKED"

    return {
        "slo_status": slo_status,
        "blockers": sorted(set(blockers)),
        "slo_budget_seconds": SNIPER_TO_SHADOW_QUOTE_SLO_SECONDS,
        "latency_seconds": round(latency_s, 1) if latency_s is not None else None,
        "econ_rpc_quote_attempts": econ_attempts,
        "sniper_generated_at_utc": sniper.get("generated_at_utc"),
        "first_econ_rpc_attempt_at_utc": scan_scope.get("first_econ_rpc_attempt_at_utc"),
        "first_successful_econ_quote_at_utc": scan_scope.get(
            "first_successful_econ_quote_at_utc"
        ),
        "first_shadow_quote_at_utc": scan_scope.get("first_shadow_quote_at_utc"),
    }


def _freshness_gate(
    *,
    sniper: Optional[Dict[str, Any]],
    bridge: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
    m8_2_report: Optional[Dict[str, Any]],
    m8_3_registry: Optional[Dict[str, Any]],
    capacity_metrics: Optional[Dict[str, Any]],
    now: Optional[Any] = None,
    skip_shadow: bool = False,
) -> Dict[str, Any]:
    """Cross-artifact freshness/provenance gate (Patch 3).

    Verdicts:
      * ``PASS`` - every available artifact carries a parseable timestamp,
        none are stale, and all pairwise deltas are within
        ``FRESHNESS_MISMATCH_SECONDS``.
      * ``BLOCKED`` - at least one artifact is stale, missing a timestamp, or
        artifacts come from clearly different runtime windows.

    The gate is additive: it never weakens existing upstream gates. When
    blocked, callers MUST surface the returned blockers to upstream_blockers
    so ``goal_status`` stays ``BLOCKED``.
    """
    ts_raw = _artifact_timestamps(
        sniper=sniper,
        bridge=bridge,
        shadow=shadow,
        m8_2_report=m8_2_report,
        m8_3_registry=m8_3_registry,
        capacity_metrics=capacity_metrics,
    )
    if skip_shadow:
        for key in ("shadow", "capacity"):
            ts_raw.pop(key, None)
    parsed = {k: _parse_iso_ts(v) for k, v in ts_raw.items()}
    now_dt = now or _now_utc()

    blockers: List[str] = []
    session_binding = _session_binding_gate(
        sniper=sniper,
        bridge=bridge,
        shadow=shadow,
        capacity_metrics=capacity_metrics,
        m8_2_report=m8_2_report,
        m8_3_registry=m8_3_registry,
        skip_shadow=skip_shadow,
    )
    blockers.extend(session_binding["blockers"])
    per_artifact: Dict[str, Dict[str, Any]] = {}
    for key, ts_str in ts_raw.items():
        ts_dt = parsed.get(key)
        entry: Dict[str, Any] = {"generated_at_utc": ts_str}
        if ts_dt is None:
            entry["status"] = "MISSING_TIMESTAMP"
            entry["blocker"] = f"{key.upper()}_TIMESTAMP_MISSING"
            blockers.append(f"{key.upper()}_TIMESTAMP_MISSING")
            per_artifact[key] = entry
            continue
        age_s = (now_dt - ts_dt).total_seconds()
        entry["age_seconds"] = round(age_s, 1)
        threshold = FRESHNESS_STALE_SECONDS.get(key)
        entry["stale_threshold_seconds"] = threshold
        if threshold is not None and age_s > threshold:
            entry["status"] = "STALE"
            entry["blocker"] = FRESHNESS_BLOCKER_BY_KEY.get(key, f"{key.upper()}_STALE")
            blockers.append(entry["blocker"])
        else:
            entry["status"] = "FRESH"
            entry["blocker"] = None
        per_artifact[key] = entry

    # Mixed runtime window: pairwise deltas among present timestamps must all
    # be within FRESHNESS_MISMATCH_SECONDS.
    present = {k: v for k, v in parsed.items() if v is not None}
    if len(present) >= 2:
        max_delta = 0.0
        keys_present = list(present.keys())
        for i in range(len(keys_present)):
            for j in range(i + 1, len(keys_present)):
                delta = abs(
                    (present[keys_present[i]] - present[keys_present[j]]).total_seconds()
                )
                if delta > max_delta:
                    max_delta = delta
        if max_delta > (
            SESSION_ALIGNED_MISMATCH_SECONDS
            if session_binding.get("session_id")
            and "SESSION_ID_MISMATCH" not in blockers
            else FRESHNESS_MISMATCH_SECONDS
        ):
            blockers.append("MIXED_RUNTIME_WINDOW")

    return {
        "freshness_status": "PASS" if not blockers else "BLOCKED",
        "blockers": sorted(set(blockers)),
        "thresholds_seconds": dict(FRESHNESS_STALE_SECONDS),
        "mismatch_threshold_seconds": FRESHNESS_MISMATCH_SECONDS,
        "session_aligned_mismatch_threshold_seconds": SESSION_ALIGNED_MISMATCH_SECONDS,
        "session_binding": session_binding,
        "per_artifact": per_artifact,
    }


_DEFAULT_PATHS = {
    "sniper": REPO_ROOT / "data/runs/_rolling/new_pool_sniper_latest.json",
    "anchor": REPO_ROOT / "data/runs/_rolling/m8_1_stable_anchor_latest.json",
    "expansion": REPO_ROOT / "data/runs/_rolling/m8_cross_dex_expansion_latest.json",
    "bridge": REPO_ROOT / "data/tmp/m9_bridge_inventory_graph_handoff_latest.json",
    "shadow": REPO_ROOT / "data/tmp/m9_graph_handoff_quote_validation_10m.json",
    "rca": REPO_ROOT / "data/tmp/m9_quote_lane_rca_graph_handoff_latest.json",
}


def _load(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _dex_coverage(
    bridge: Optional[Dict[str, Any]],
    expansion: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    active = (bridge or {}).get("active_routes") or []
    configured = set()
    bsm = (bridge or {}).get("bridge_source_metrics") or {}
    for dex in bsm.get("expansion_dex_ids_checked") or []:
        configured.add(str(dex))
    for r in active:
        if r.get("dex_id"):
            configured.add(str(r["dex_id"]))

    indexed = Counter()
    exp_metrics = (expansion or {}).get("metrics") or {}
    for dex, count in (exp_metrics.get("pools_found_by_dex") or {}).items():
        indexed[str(dex)] = int(count or 0)

    verified = Counter()
    for dex, count in (bsm.get("expansion_quoteable_by_dex") or {}).items():
        verified[str(dex)] = int(count or 0)

    bridge_active = Counter(str(r.get("dex_id") or "unknown") for r in active)
    cross_mechanic = Counter(
        str(r.get("dex_id") or "unknown")
        for r in active
        if r.get("cross_mechanic")
    )

    cycles_by_family = dict((shadow or {}).get("cycles_by_adapter_family") or {})
    return {
        "configured_dex_ids": sorted(configured),
        "indexed_pools_by_dex": dict(indexed),
        "verified_quoteable_by_dex": dict(verified),
        "bridge_active_routes_by_dex": dict(bridge_active),
        "cross_mechanic_routes_by_dex": dict(cross_mechanic),
        "cycles_by_adapter_family": cycles_by_family,
    }


def _cross_mechanic_topology(
    bridge: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    active = (bridge or {}).get("active_routes") or []
    cm_routes = [r for r in active if r.get("cross_mechanic")]
    cm_pools = {
        str(r.get("pool_address", "")).lower()
        for r in cm_routes
        if r.get("pool_address")
    }
    cm_tokens = Counter(
        str(r.get("focus_token_symbol") or r.get("token1") or r.get("token0") or "?")
        for r in cm_routes
    )
    connector_tokens = Counter(
        str(r.get("connector_token") or "")
        for r in cm_routes
        if r.get("connector_token")
    )

    shadow_summary = {
        "cycles_found": (shadow or {}).get("cycles_found"),
        "cycles_quoteable": (shadow or {}).get("cycles_quoteable"),
        "cross_mechanic_cycles": (shadow or {}).get("cross_mechanic_cycles"),
    }
    bsm = (shadow or {}).get("bridge_source_metrics") or {}
    if bsm.get("cross_mechanic_cycles") is not None:
        shadow_summary["cross_mechanic_cycles"] = bsm.get("cross_mechanic_cycles")
    if bsm.get("expected_cross_mechanic_cycles") is not None:
        shadow_summary["expected_cross_mechanic_cycles"] = bsm.get(
            "expected_cross_mechanic_cycles"
        )

    top_cycles = (shadow or {}).get("top_cycles") or []
    cm_touched = 0
    for cyc in top_cycles:
        for leg in cyc.get("legs") or []:
            if (leg.get("pool_address") or "").lower() in cm_pools:
                cm_touched += 1
                break

    hints: List[str] = []
    if cm_routes and int(shadow_summary.get("cross_mechanic_cycles") or 0) == 0:
        if cm_touched == 0:
            hints.append("cross_mechanic_pools_not_in_sampled_cycles")
        if len(connector_tokens) < 2:
            hints.append("connector_token_diversity_low")
        leaf_only = sum(
            1 for r in cm_routes
            if not r.get("connector_token") and r.get("expansion_route_kind") == "token_presence"
        )
        if leaf_only == len(cm_routes):
            hints.append("cross_mechanic_routes_may_be_leaf_only")

    return {
        "cross_mechanic_route_count": len(cm_routes),
        "cross_mechanic_unique_pools": len(cm_pools),
        "focus_token_histogram": dict(cm_tokens.most_common(12)),
        "connector_token_histogram": dict(connector_tokens.most_common(12)),
        "shadow_cycle_summary": shadow_summary,
        "cross_mechanic_in_top_cycles_sample": cm_touched,
        "diagnostic_hints": hints,
    }


def _shadow_bridge_stale_or_mismatch(
    bridge: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
) -> bool:
    """True when shadow artifact is older than bridge or route counts diverge."""
    if not bridge or not shadow:
        return False
    bridge_ts = bridge.get("generated_at_utc")
    shadow_ts = shadow.get("generated_at_utc") or shadow.get("run_timestamp")
    if bridge_ts and shadow_ts:
        try:
            from datetime import datetime

            def _parse(ts: str) -> datetime:
                return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))

            if _parse(str(shadow_ts)) < _parse(str(bridge_ts)):
                return True
        except Exception:
            pass
    bridge_active = len((bridge or {}).get("active_routes") or [])
    shadow_active = shadow.get("bridge_active_routes_at_run")
    if shadow_active is None:
        shadow_active = shadow.get("active_routes_at_run")
    if shadow_active is not None and int(shadow_active) != bridge_active:
        return True
    shadow_inv = str(shadow.get("inventory_path") or "")
    if shadow_inv and not shadow_inv.endswith("graph_handoff_latest.json"):
        pass  # path alone is weak signal
    return False


def _economics_profile_context_for_report(
    *,
    shadow: Optional[Dict[str, Any]],
    capacity_metrics: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    import os

    from m9.graph_arb.size_truth import economics_profile_context

    profile_name = (
        (shadow or {}).get("active_economics_profile")
        or (shadow or {}).get("economics_profile")
        or ((shadow or {}).get("economics_profile_context") or {}).get(
            "active_economics_profile"
        )
        or (capacity_metrics or {}).get("active_economics_profile")
        or os.environ.get("ARBY_M9_ECONOMICS_PROFILE")
        or "production_conservative"
    )
    return economics_profile_context(profile_name=profile_name, shadow=shadow)


def _m9_economics_blockers(
    *,
    shadow: Optional[Dict[str, Any]],
    rca: Optional[Dict[str, Any]],
    shadow_cycles_found: int,
    shadow_cycles_quoteable: int,
    shadow_cycles_with_m8: int,
    quote_liveness: Optional[Dict[str, Any]] = None,
    bridge: Optional[Dict[str, Any]] = None,
    capacity_metrics: Optional[Dict[str, Any]] = None,
    economics_profile: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """M9-only blockers: graph/cycle/quote/economics (not M8.2 hint/mirror quality)."""
    blockers: List[str] = []
    eprof = economics_profile or {}
    profile_role = str(eprof.get("role") or "production")
    active_profile = str(eprof.get("active_economics_profile") or "production_conservative")
    shadow_qsr = float((shadow or {}).get("qsr") or 0.0)
    qsr_econ = (shadow or {}).get("qsr_econ")
    depth_known = (shadow or {}).get("depth_aware_known_rate")
    cycles_positive = int((shadow or {}).get("cycles_positive_gross") or 0)
    qst = (shadow or {}).get("quote_size_truth") or {}
    econ_rpc = int(qst.get("econ_rpc_quote_attempts") or 0)
    econ_gate = qst.get("econ_gate_attempts")

    if shadow_cycles_found > 0 and shadow_cycles_quoteable == 0:
        blockers.append("NO_QUOTEABLE_CYCLES")
    if _shadow_bridge_stale_or_mismatch(bridge, shadow):
        blockers.append("SHADOW_BRIDGE_STALE_OR_MISMATCH")
    econ_gate_int = int(econ_gate or 0)
    admission_before_quote = (
        shadow_cycles_found > 0
        and shadow_cycles_quoteable == 0
        and int(econ_rpc or 0) == 0
        and econ_gate_int > 0
    )
    if admission_before_quote:
        blockers.append("CODE_OR_POLICY_ADMISSION_BLOCKED_BEFORE_ECONOMIC_QUOTE")
    if (
        shadow_cycles_found > 0
        and cycles_positive == 0
        and profile_role != "diagnostic"
        and int(econ_rpc or 0) > 0
    ):
        if (
            active_profile == "base_realistic"
            and str(eprof.get("profit_claim_mode") or "") == "runtime_conditional"
        ):
            blockers.append("BASE_REALISTIC_RUNTIME_PROOF_PENDING")
        else:
            blockers.append("NO_POSITIVE_GROSS")
    if shadow_cycles_found > 0 and shadow_cycles_quoteable == 0 and float(shadow_qsr or 0) > 0:
        blockers.append("DISCOVERY_QSR_NOT_QUOTE_HEALTH")
    if shadow_cycles_found > 0 and float(shadow_qsr or 0) == 0.0:
        blockers.append("QSR_ZERO")
    if shadow_cycles_found > 0 and econ_rpc == 0 and qst:
        blockers.append("ECON_RPC_QUOTES_ZERO")
    if shadow_cycles_found > 0 and qsr_econ is not None and float(qsr_econ) == 0.0 and int(econ_rpc or 0) > 0:
        blockers.append("QSR_ECON_ZERO")
    if shadow_cycles_found > 0 and int(econ_gate or 0) > 0 and int(econ_rpc or 0) == 0:
        blockers.append("ECON_RPC_QUOTE_NOT_ATTEMPTED")
        if active_profile == "base_realistic":
            blockers.append("BASE_REALISTIC_ADMISSION_OR_CAPACITY_GATE")
    econ_blocker = str((shadow or {}).get("economics_blocker_class") or "")
    if econ_blocker in {
        "MARKET_NO_POSITIVE_GROSS",
        "DEPTH_ADMISSION_BLOCKED_BEFORE_ECONOMIC_QUOTE",
    } and int(econ_rpc or 0) == 0:
        blockers = [
            b
            for b in blockers
            if b not in {"NO_POSITIVE_GROSS", "QSR_ECON_ZERO"}
        ]
        if "CODE_OR_POLICY_ADMISSION_BLOCKED_BEFORE_ECONOMIC_QUOTE" not in blockers:
            blockers.append("CODE_OR_POLICY_ADMISSION_BLOCKED_BEFORE_ECONOMIC_QUOTE")
    if shadow_cycles_found > 0 and depth_known is not None and float(depth_known) == 0.0:
        blockers.append("DEPTH_UNKNOWN")

    rca_summary = (rca or {}).get("summary") or {}
    shadow_rca = (shadow or {}).get("quote_lane_rca") or {}
    stable_outliers = int(
        rca_summary.get("stable_value_ratio_outlier_legs")
        or shadow_rca.get("stable_value_ratio_outlier_legs")
        or 0
    )
    econ_metrics = (shadow or {}).get("economics_metrics") or {}
    toxic_rate = econ_metrics.get("toxic_route_rate")
    toxic_denominator = int(econ_metrics.get("toxic_route_denominator") or 0)
    if toxic_rate is None:
        toxic_rate = rca_summary.get("toxic_route_rate")
    reject_hist = (shadow or {}).get("cycle_reject_histogram") or {}
    continuity_count = int(
        reject_hist.get("AMOUNT_CONTINUITY_VIOLATION", 0)
        + reject_hist.get("INSTRUMENTATION_BLOCKED__AMOUNT_CONTINUITY", 0)
    )
    instrumentation_count = int(econ_metrics.get("instrumentation_blocked_count") or 0)
    if continuity_count > 0 or instrumentation_count > 0:
        blockers.append("CONTINUITY_INSTRUMENTATION_NOT_CLEAN")
    if shadow_cycles_quoteable > 0 and toxic_rate is not None and toxic_denominator > 0:
        if float(toxic_rate) >= 1.0:
            blockers.append("VALUE_RATIO_RCA_NOT_CLEAN")
        elif float(toxic_rate) >= 0.9 and stable_outliers > 0:
            blockers.append("VALUE_RATIO_RCA_NOT_CLEAN")
    elif shadow_cycles_quoteable > 0 and toxic_rate is not None and toxic_denominator == 0:
        pass  # all quoteable cycles are instrumentation — not a market-toxic verdict
    elif shadow_cycles_quoteable > 0 and stable_outliers > 0:
        blockers.append("VALUE_RATIO_RCA_NOT_CLEAN")

    ql = quote_liveness or {}
    disc_by_len = ql.get("discovery_cycles_by_length") or (
        (shadow or {}).get("discovery_cycles_by_length") or {}
    )
    quote_by_len = ql.get("cycles_quoteable_by_length") or (
        (shadow or {}).get("cycles_quoteable_by_length") or {}
    )
    if int(disc_by_len.get("4") or 0) > 0 and int(quote_by_len.get("4") or 0) == 0:
        blockers.append("FOUR_LEG_PRODUCTIVE_COVERAGE_ZERO")

    top_reject = str(
        rca_summary.get("top_reject")
        or rca_summary.get("dominant_reject")
        or ""
    ).upper()
    by_reject = (rca or {}).get("by_reject_reason") or {}
    if "QUOTE_REVERT" in top_reject or int(by_reject.get("QUOTE_REVERT") or 0) > 0:
        if shadow_cycles_found > 0 and shadow_cycles_quoteable == 0:
            blockers.append("QUOTE_REVERT")

    phantom_count = int(
        ((shadow or {}).get("phantom_quote_diagnostics") or {}).get("phantom_count")
        or ((shadow or {}).get("cycle_reject_histogram") or {}).get(
            "PHANTOM_QUOTE_BPS_OVERFLOW", 0
        )
        or 0
    )
    if phantom_count > 0:
        blockers.append("PHANTOM_QUOTE_PRESENT")

    bsm = (bridge or {}).get("bridge_source_metrics") or {}
    missing_lanes = list(bsm.get("missing_distinct_pricing_lanes") or [])
    productive_curve = int(bsm.get("productive_curve_quoteable_routes") or 0)
    if "curve" in missing_lanes or productive_curve == 0:
        blockers.append("CURVE_PRODUCTIVE_LANE_INCOMPLETE")

    decimals_unknown = int(bsm.get("routes_decimals_unknown") or 0)
    m8_3_authority = bool(bsm.get("m8_3_authority_applied"))
    if decimals_unknown > 50 and not m8_3_authority:
        blockers.append("DECIMALS_ENRICHMENT_REQUIRED")
    elif decimals_unknown == 0 and m8_3_authority:
        pass  # M8.3 authority satisfied; never surface stale decimals blocker
    depth_known = bsm.get("depth_known_rate")
    if depth_known is not None and float(depth_known) < 0.5:
        blockers.append("DEPTH_ENRICHMENT_REQUIRED")

    cm_found = int(
        (shadow or {}).get("cross_mechanic_cycles_found")
        or (shadow or {}).get("cross_mechanic_cycles")
        or 0
    )
    cm_quoteable = int((shadow or {}).get("cross_mechanic_cycles_quoteable") or 0)
    if shadow_cycles_found > 0 and shadow_cycles_with_m8 == 0:
        blockers.append("CYCLES_WITH_M8_POOL_ZERO")
    if cm_found == 0 and shadow_cycles_found > 0:
        blockers.append("NO_CROSS_MECHANIC_CYCLES_IN_GRAPH")
    elif cm_quoteable == 0 and cm_found > 0:
        blockers.append("NO_CROSS_MECHANIC_CYCLES_QUOTEABLE")

    cap = capacity_metrics or {}
    cycles_total_cap = int(cap.get("cycles_total") or 0)
    cycles_at_prod = int(
        cap.get("cycles_at_production_floor")
        or cap.get("cycles_at_econ_floor")
        or 0
    )
    near_econ = int(cap.get("near_econ_cycles_count") or 0)
    if cycles_total_cap > 0 and cycles_at_prod == 0:
        blockers.append("NO_ECON_CAPACITY_CYCLES_AT_PRODUCTION_FLOOR")
        blockers.append("NO_ECON_CAPACITY_CYCLES")
    if near_econ > 0 and cycles_at_prod == 0:
        blockers.append("NEAR_ECON_CAPACITY_ONLY")

    scan_scope = (shadow or {}).get("scan_scope") or {}
    cap_ids = list(scan_scope.get("capacity_valid_cycle_ids") or [])
    quoted_ids = list(scan_scope.get("shadow_quoted_cycle_ids") or [])
    if cycles_at_prod > 0 and cap_ids and not quoted_ids:
        blockers.append("CAPACITY_VALID_CYCLES_NOT_QUOTED_IN_SHADOW")
    if int(scan_scope.get("session_quarantine_filtered_count") or 0) > 0:
        if not quoted_ids:
            blockers.append("SESSION_POOL_QUARANTINE_BLOCKED_QUOTES")
    if int(scan_scope.get("capacity_contract_missing_count") or 0) > 0:
        blockers.append("CAPACITY_CONTRACT_MISSING_IN_SHADOW")
    shadow_lane_mode = str(scan_scope.get("shadow_lane_mode") or "")
    if shadow_lane_mode == "broad_graph_diagnostic":
        blockers.append("BROAD_GRAPH_DIAGNOSTIC_NOT_LONG_TAIL_ECONOMICS")
    bsm = (bridge or {}).get("bridge_source_metrics") or {}
    # Step 6 (P0): only honour fresh_ready when the bridge carries a session_id
    # (provenance binding). A stale bridge without session must not flip the
    # lane to long_tail_target while acceptance reads the current bridge.
    bridge_session = (
        (bridge or {}).get("session_id")
        or bsm.get("session_id")
        or ((bridge or {}).get("run_context") or {}).get("pipeline_session_id")
    )
    fresh_ready = int(
        bsm.get("fresh_long_tail_quote_ready_tokens")
        or (bridge or {}).get("fresh_long_tail_quote_ready_tokens")
        or 0
    )
    if not bridge_session:
        # No session binding → treat as not fresh to avoid contradictory verdicts.
        fresh_ready = 0
    if shadow_lane_mode == "long_tail_target" and fresh_ready <= 0:
        blockers.append("FRESH_LONG_TAIL_QUOTE_READY_ZERO")

    return sorted(set(blockers))


def _quote_liveness_metrics(shadow: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Split quote liveness vs economics metrics; explain qsr_liveness drift."""
    if not shadow:
        return {}
    cycles_quoteable = int(shadow.get("cycles_quoteable") or 0)
    cycles_positive_gross = int(shadow.get("cycles_positive_gross") or 0)
    shadow_cycles_found = int(shadow.get("cycles_found") or 0)
    qsr = shadow.get("qsr")
    qsr_liveness = shadow.get("qsr_liveness")
    qsr_econ = shadow.get("qsr_econ")
    qst = shadow.get("quote_size_truth") or {}
    econ_quote_attempt_rate = shadow.get("econ_quote_attempt_rate")
    econ_quote_success_rate = shadow.get("econ_quote_success_rate")
    econ_metrics = (shadow or {}).get("economics_metrics") or {}
    discovery_qsr = shadow.get("discovery_qsr", qsr)
    depth_admission_rate = shadow.get("depth_admission_rate")
    rpc_quote_attempt_rate = shadow.get("rpc_quote_attempt_rate")
    rpc_quote_success_rate = shadow.get("rpc_quote_success_rate")

    if cycles_quoteable == 0:
        quote_liveness_status = "NOT_PROVEN"
    elif cycles_positive_gross > 0:
        quote_liveness_status = "PROVEN_WITH_POSITIVE_GROSS"
    elif float(qsr or 0) >= 0.99:
        quote_liveness_status = "PROVEN"
    else:
        quote_liveness_status = "PARTIAL"

    notes: List[str] = []
    consistent = True
    if cycles_quoteable > 0 and float(qsr or 0) > 0:
        if qsr_liveness is not None and float(qsr_liveness or 0) == 0.0:
            consistent = False
            notes.append(
                "cycles_quoteable>0 and qsr>0 but qsr_liveness=0: "
                "qsr_liveness counts only size_usd<=5 USD (liveness ladder); "
                "dynamic sizing may select larger sizes (e.g. 25 USD) excluded "
                "from the liveness subset - do not claim qsr_liveness without "
                "checking quote_size_truth.liveness_quote_attempts."
            )
    if cycles_quoteable == 0 and qsr_econ is not None and float(qsr_econ or 0) > 0:
        notes.append(
            "qsr_econ>0 with cycles_quoteable=0: leg-level econ RPC subset only; "
            "use econ_quote_success_rate for cycle-level economics proof."
        )
    if cycles_quoteable > 0 and qsr_econ is not None and float(qsr_econ or 0) == 0.0:
        notes.append(
            "qsr_econ=0 while cycles_quoteable>0: no economics-sized quotes "
            "(size_usd >= economic floor) succeeded - economics NOT_PROVEN."
        )
    econ_gate = qst.get("econ_gate_attempts")
    econ_rpc = qst.get("econ_rpc_quote_attempts")
    if shadow_cycles_found > 0 and econ_gate is not None and int(econ_gate) > 0:
        if econ_rpc is not None and int(econ_rpc) == 0:
            notes.append(
                "econ_gate_attempts>0 but econ_rpc_quote_attempts=0: sizing/depth "
                "gate blocked all economics RPC quotes (not a market QSR success)."
            )

    return {
        "quote_liveness_status": quote_liveness_status,
        "cycles_quoteable": cycles_quoteable,
        "cycles_positive_gross": cycles_positive_gross,
        "positive_gross_proven": cycles_positive_gross > 0,
        "qsr": qsr,
        "qsr_liveness": qsr_liveness,
        "qsr_econ": qsr_econ,
        "econ_quote_attempt_rate": econ_quote_attempt_rate,
        "econ_quote_success_rate": econ_quote_success_rate,
        "discovery_qsr": discovery_qsr,
        "depth_admission_rate": depth_admission_rate,
        "rpc_quote_attempt_rate": rpc_quote_attempt_rate,
        "rpc_quote_success_rate": rpc_quote_success_rate,
        "economics_status": (
            "NOT_PROVEN"
            if cycles_positive_gross == 0
            else "PARTIAL"
        ),
        "qsr_liveness_consistency": {"consistent": consistent, "notes": notes},
        "cycles_found_by_length": shadow.get("cycles_found_by_length") or {},
        "cycles_quoteable_by_length": shadow.get("cycles_quoteable_by_length") or {},
        "discovery_cycles_by_length": shadow.get("discovery_cycles_by_length") or {},
    }


def _build_operator_verdict(
    *,
    shadow: Optional[Dict[str, Any]],
    quote_liveness: Dict[str, Any],
    m8_2_report: Optional[Dict[str, Any]],
    bridge: Optional[Dict[str, Any]],
    m9_blockers: List[str],
    rca: Optional[Dict[str, Any]],
    sniper: Optional[Dict[str, Any]] = None,
    sniper_assessment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Operator-facing milestone verdicts; explicit economics-claim guard."""
    handoff_ready = bool((m8_2_report or {}).get("handoff_ready"))
    cycles_positive = int((shadow or {}).get("cycles_positive_gross") or 0)
    qsr_econ = (shadow or {}).get("qsr_econ")
    qsr_econ_zero = qsr_econ is not None and float(qsr_econ or 0) == 0.0
    quoteable_by_len = quote_liveness.get("cycles_quoteable_by_length") or {}
    four_leg = int(quoteable_by_len.get("4") or 0)
    three_leg = int(quoteable_by_len.get("3") or 0)

    if handoff_ready:
        m8_2_label = "M8_2_GRAPH_HANDOFF_REACHED"
    else:
        m8_2_label = "M8_2_GRAPH_HANDOFF_NOT_REACHED"

    ql_status = quote_liveness.get("quote_liveness_status") or "NOT_PROVEN"
    cycles_quoteable = int((shadow or {}).get("cycles_quoteable") or 0)
    shadow_qsr = float((shadow or {}).get("qsr") or 0.0)
    if cycles_quoteable > 0 and shadow_qsr >= 0.99:
        m9_quote_label = "M9_QUOTE_LIVENESS_PROVEN"
    elif ql_status == "PARTIAL":
        m9_quote_label = "M9_QUOTE_LIVENESS_PARTIAL"
    elif ql_status in ("PROVEN_WITH_POSITIVE_GROSS",):
        m9_quote_label = "M9_QUOTE_LIVENESS_PROVEN"
    else:
        m9_quote_label = "M9_QUOTE_LIVENESS_NOT_PROVEN"

    econ_status = quote_liveness.get("economics_status") or "NOT_PROVEN"
    rca = (shadow or {}).get("quote_lane_rca") or {}
    continuity_violations = int(rca.get("amount_continuity_violations") or 0)
    stable_outliers = int(rca.get("stable_value_ratio_outlier_legs") or 0)
    if (
        econ_status == "NOT_PROVEN"
        and cycles_quoteable > 0
        and (continuity_violations > 0 or stable_outliers > 0)
    ):
        m9_econ_label = "M9_ECONOMICS_BLOCKED_BY_AMOUNT_CONTINUITY_AND_VALUE_RATIO_RCA"
    elif (
        econ_status == "NOT_PROVEN"
        and cycles_quoteable > 0
        and "VALUE_RATIO_RCA_NOT_CLEAN" in m9_blockers
    ):
        m9_econ_label = "M9_ECONOMICS_BLOCKED_BY_VALUE_RATIO_AND_ADAPTER_RCA"
    elif econ_status == "NOT_PROVEN" and cycles_quoteable > 0 and cycles_positive == 0:
        m9_econ_label = "M9_ECONOMICS_NOT_PROVEN"
    elif econ_status == "NOT_PROVEN":
        m9_econ_label = "M9_ECONOMICS_NOT_PROVEN"
    else:
        m9_econ_label = f"M9_ECONOMICS_{econ_status}"

    economics_claim_allowed = (
        cycles_positive > 0
        and not qsr_econ_zero
        and int(
            ((shadow or {}).get("quote_size_truth") or {}).get("econ_rpc_quote_attempts")
            or 0
        )
        > 0
    )
    forbidden_claims: List[str] = []
    if cycles_positive == 0:
        forbidden_claims.append("profit_ready")
        forbidden_claims.append("positive_gross")
    if qsr_econ_zero or cycles_positive == 0:
        forbidden_claims.append("economics_proven")
        forbidden_claims.append("qsr_econ_pass")
    if four_leg == 0:
        forbidden_claims.append("4_leg_quoteability_proven")
    if not handoff_ready:
        forbidden_claims.append("m8_2_handoff_complete")

    bsm = (bridge or {}).get("bridge_source_metrics") or {}
    _sniper_assess = sniper_assessment or assess_sniper_artifact_for_m9(sniper)
    shadow_cycles_with_m8 = int((shadow or {}).get("cycles_with_m8_pool") or 0)
    fresh_m8_proven = (
        not bool(bsm.get("m8_stale"))
        and bool(_sniper_assess.get("operational"))
        and shadow_cycles_with_m8 > 0
    )
    fresh_m8_label = (
        "FRESH_M8_PARTICIPATION_PROVEN"
        if fresh_m8_proven
        else "FRESH_M8_PARTICIPATION_NOT_PROVEN"
    )

    layer_ownership: List[Dict[str, Any]] = [
        {
            "layer": "M8_sniper",
            "status": (
                "INVALID_OR_STUB"
                if not _sniper_assess.get("operational")
                else ("STALE" if bsm.get("m8_stale") else "ACTIVE")
            ),
            "blocker_owner": (
                M9_SNIPER_BLOCKER
                if not _sniper_assess.get("operational")
                else ("M8_ARTIFACT_STALE" if bsm.get("m8_stale") else None)
            ),
        },
        {
            "layer": "M8_1_anchor",
            "status": "UPSTREAM",
            "blocker_owner": None,
        },
        {
            "layer": "M8_2_handoff",
            "status": "REACHED" if handoff_ready else "NOT_REACHED",
            "blocker_owner": None if handoff_ready else "M8_2",
        },
        {
            "layer": "M9_topology",
            "status": "REACHED" if int((shadow or {}).get("cycles_found") or 0) > 0 else "BLOCKED",
            "blocker_owner": None,
        },
        {
            "layer": "M9_quote",
            "status": ql_status,
            "blocker_owner": (
                "M9_quote"
                if ql_status == "NOT_PROVEN"
                else ("M9_adapter" if four_leg == 0 and three_leg > 0 else None)
            ),
        },
        {
            "layer": "M9_economics",
            "status": econ_status,
            "blocker_owner": "M9_economics" if cycles_positive == 0 else None,
        },
    ]

    if not handoff_ready:
        forbidden_claims.append("m8_2_handoff_complete")
    if not fresh_m8_proven:
        forbidden_claims.append("fresh_m8_participation")

    primary_blocker = None
    if not _sniper_assess.get("operational"):
        primary_blocker = M9_SNIPER_BLOCKER
    elif not handoff_ready:
        primary_blocker = "M8_2_handoff"
    elif four_leg == 0 and three_leg == 0:
        primary_blocker = "M9_topology_or_quarantine"
    elif four_leg == 0:
        primary_blocker = "M9_4_leg_quote"
    elif cycles_positive == 0:
        primary_blocker = "M9_economics"
    elif m9_blockers:
        primary_blocker = m9_blockers[0]

    return {
        "M8_2_HANDOFF": "REACHED" if handoff_ready else "NOT_REACHED",
        "M9_QUOTE_LIVENESS": m9_quote_label,
        "M9_ECONOMICS": m9_econ_label,
        "verdict_labels": [m8_2_label, m9_quote_label, m9_econ_label, fresh_m8_label],
        "M9_FRESH_M8_PARTICIPATION": fresh_m8_label,
        "m8_sniper_artifact_operational": _sniper_assess.get("operational"),
        "m8_sniper_artifact_blockers": _sniper_assess.get("blockers") or [],
        "economics_claim_allowed": economics_claim_allowed,
        "forbidden_claims": forbidden_claims,
        "layer_ownership": layer_ownership,
        "primary_blocker_owner": primary_blocker,
        "qsr_semantics": {
            "qsr": "all quote attempts success rate",
            "qsr_liveness": "subset size_usd<=5 only; may be 0 when dynamic sizing uses larger sizes",
            "qsr_econ": "economics-sized quotes only; 0 means economics NOT_PROVEN",
        },
        "rca_economics_status": (rca or {}).get("economics_status"),
    }


def build_acceptance_report(
    *,
    sniper: Optional[Dict[str, Any]],
    anchor: Optional[Dict[str, Any]],
    expansion: Optional[Dict[str, Any]],
    bridge: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
    rca: Optional[Dict[str, Any]],
    m8_2_report: Optional[Dict[str, Any]] = None,
    capacity_metrics: Optional[Dict[str, Any]] = None,
    m8_3_registry_path: Optional[str] = None,
    skip_shadow: bool = False,
) -> Dict[str, Any]:
    sniper_metrics = (sniper or {}).get("metrics") or {}
    anchor_metrics = (anchor or {}).get("metrics") or {}
    exp_metrics = (expansion or {}).get("metrics") or {}
    exp_summary = (expansion or {}).get("summary") or {}
    bsm = (bridge or {}).get("bridge_source_metrics") or {}

    sniper_assessment = assess_sniper_artifact_for_m9(sniper)

    shadow_cycles_found = int((shadow or {}).get("cycles_found") or 0)
    shadow_cycles_quoteable = int((shadow or {}).get("cycles_quoteable") or 0)
    shadow_cycles_with_m8 = int((shadow or {}).get("cycles_with_m8_pool") or 0)
    cm_found = int(
        (shadow or {}).get("cross_mechanic_cycles_found")
        or (shadow or {}).get("cross_mechanic_cycles")
        or 0
    )
    cm_quoteable = int((shadow or {}).get("cross_mechanic_cycles_quoteable") or 0)

    funnel_layers = [
        {
            "layer": "M8_sniper",
            "input": sniper_metrics.get("snipe_candidates_total")
            or len((sniper or {}).get("recent_events") or []),
            "status": (sniper or {}).get("status"),
            "rpc_errors": sniper_metrics.get("rpc_errors"),
        },
        {
            "layer": "M8_bridge_input",
            "m8_new_pools_input": bsm.get("m8_new_pools_input"),
            "token_verified": bsm.get("token_verified_count"),
            "anchor_connected": bsm.get("anchor_connected_count"),
            "cross_dex_seen": bsm.get("cross_dex_seen_count"),
            "multi_venue_quoteable": bsm.get("m8_multi_venue_quoteable_count"),
            "graph_ready_from_m8": bsm.get("graph_ready_from_m8"),
            "m8_funnel_reject_histogram": bsm.get("m8_funnel_reject_histogram"),
        },
        {
            "layer": "M8_1_anchor",
            "passes": anchor_metrics.get("stable_anchor_passes_total"),
            "qsr": anchor_metrics.get("qsr"),
            "status": (anchor or {}).get("status"),
        },
        {
            "layer": "M8_2_expansion",
            "routes_admitted": exp_summary.get("routes_admitted_count")
            or exp_metrics.get("routes_admitted"),
            "routes_admitted_count": exp_summary.get("routes_admitted_count"),
            "connector_routes_count": exp_summary.get("connector_routes_count"),
            "subgraph_ready_tokens": exp_summary.get("subgraph_ready_tokens"),
            "graph_topology_ready_tokens": exp_summary.get(
                "graph_topology_ready_tokens"
            ),
            "connector_graph_ready_tokens": exp_summary.get(
                "connector_graph_ready_tokens"
            ),
            "mirror_quote_ready_tokens": exp_summary.get("mirror_quote_ready_tokens"),
            "handoff_ready": exp_summary.get("handoff_ready"),
            "verified_second_pool_count": exp_summary.get(
                "verified_second_pool_count"
            ),
            "multi_venue_tokens": exp_summary.get("multi_venue_tokens")
            or exp_metrics.get("multi_venue_tokens"),
            "hint_tokens_matched": exp_summary.get("hint_tokens_matched"),
            "external_hints_enabled": exp_summary.get("external_hints_enabled"),
            "m8_tokens_in": exp_summary.get("m8_tokens_in"),
        },
        {
            "layer": "M8_fresh_direct_cohort",
            **_fresh_direct_cohort_counters(bridge, shadow, bsm),
            **build_fresh_direct_queue_snapshot(bridge=bridge, shadow=shadow),
        },
        {
            "layer": "M8_cohorts",
            "fresh_direct_sniper_routes": bsm.get("m8_direct_routes_in_bridge"),
            "derived_m8_routes": max(
                0,
                int(bsm.get("graph_ready_from_m8") or 0)
                - int(bsm.get("m8_direct_routes_in_bridge") or 0),
            ),
            "configured_seed_routes": bsm.get("graph_ready_from_expansion"),
            "m8_context_token_count": bsm.get("m8_context_token_count"),
            "external_hint_matches": bsm.get("external_hint_matches"),
            "specialized_index_matches": bsm.get("specialized_index_matches"),
            "m8_direct_cycles_found": (shadow or {}).get("m8_direct_cycles_found")
            or (shadow or {}).get("cycles_with_direct_sniper_pool"),
            "m8_direct_cycles_quoteable": (shadow or {}).get("m8_direct_cycles_quoteable"),
        },
        {
            "layer": "M9_bridge",
            "graph_ready_total": bsm.get("graph_ready_total"),
            "graph_ready_from_expansion": bsm.get("graph_ready_from_expansion"),
            "active_routes": len((bridge or {}).get("active_routes") or []),
            "canonical_routes_count": bsm.get("canonical_routes_count"),
            "exploration_routes_count": bsm.get("routes_rejected_not_m8_derived")
            or len((bridge or {}).get("exploration_routes") or []),
            "m8_provenance_enforced": bsm.get("m8_provenance_enforced"),
            "cross_mechanic_routes": sum(
                1
                for r in (bridge or {}).get("active_routes") or []
                if r.get("cross_mechanic")
            ),
            "canonical_cross_mechanic_routes": sum(
                1
                for r in (bridge or {}).get("active_routes") or []
                if r.get("cross_mechanic")
            ),
            "exploration_cross_mechanic_routes": sum(
                1
                for r in (bridge or {}).get("exploration_routes") or []
                if r.get("cross_mechanic")
            ),
            "active_factory_verified_routes": bsm.get("active_factory_verified_routes"),
            "routes_decimals_unknown": bsm.get("routes_decimals_unknown"),
            "m8_3_authority_applied": bsm.get("m8_3_authority_applied"),
            "route_capacity_histogram": bsm.get("route_capacity_histogram"),
        },
        {
            "layer": "M9_shadow",
            "cycles_found": (shadow or {}).get("cycles_found"),
            "cycles_quoteable": (shadow or {}).get("cycles_quoteable"),
            "cycles_positive_gross": (shadow or {}).get("cycles_positive_gross"),
            "qsr": (shadow or {}).get("qsr"),
            "qsr_liveness": (shadow or {}).get("qsr_liveness"),
            "qsr_econ": (shadow or {}).get("qsr_econ"),
            "econ_quote_attempt_rate": (shadow or {}).get("econ_quote_attempt_rate"),
            "econ_quote_success_rate": (shadow or {}).get("econ_quote_success_rate"),
            "cross_mechanic_cycles": (shadow or {}).get("cross_mechanic_cycles"),
            "cross_mechanic_cycles_found": (
                (shadow or {}).get("cross_mechanic_cycles_found")
                or (shadow or {}).get("cross_mechanic_cycles")
            ),
            "cross_mechanic_cycles_quoteable": int(
                (shadow or {}).get("cross_mechanic_cycles_quoteable") or 0
            ),
            "cycles_with_m8_pool": (shadow or {}).get("cycles_with_m8_pool"),
            "cycles_with_direct_sniper_pool": (shadow or {}).get(
                "cycles_with_direct_sniper_pool"
            ),
            "cycles_with_m8_derived_pool": (shadow or {}).get(
                "cycles_with_m8_derived_pool"
            ),
            "m8_direct_cycles_found": (shadow or {}).get("m8_direct_cycles_found")
            or (shadow or {}).get("cycles_with_direct_sniper_pool"),
            "m8_direct_cycles_quoteable": (shadow or {}).get(
                "m8_direct_cycles_quoteable"
            ),
            "m8_pool_cycle_ratio": (
                round(shadow_cycles_with_m8 / shadow_cycles_found, 4)
                if shadow_cycles_found > 0
                else None
            ),
            "m8_cross_mechanic_quoteable_ratio": (
                round(cm_quoteable / cm_found, 4)
                if cm_found > 0
                else None
            ),
        },
        {
            "layer": "M8_freshness",
            "m8_stale": bsm.get("m8_stale"),
            "m8_sniper_artifact_operational": sniper_assessment.get("operational"),
            "m8_sniper_artifact_blockers": sniper_assessment.get("blockers"),
            "m8_direct_routes_in_bridge": bsm.get("m8_direct_routes_in_bridge"),
            "sniper_age_seconds": bsm.get("sniper_age_seconds"),
            "sniper_generated_at_utc": bsm.get("sniper_generated_at_utc"),
            "m8_stale_threshold_seconds": bsm.get("m8_stale_threshold_seconds"),
            "sniper_status": (sniper or {}).get("status"),
        },
    ]

    quote_liveness = _quote_liveness_metrics(shadow)
    economics_profile_ctx = _economics_profile_context_for_report(
        shadow=shadow,
        capacity_metrics=capacity_metrics,
    )

    m9_blockers = _m9_economics_blockers(
        shadow=shadow,
        rca=rca,
        shadow_cycles_found=shadow_cycles_found,
        shadow_cycles_quoteable=shadow_cycles_quoteable,
        shadow_cycles_with_m8=shadow_cycles_with_m8,
        quote_liveness=quote_liveness,
        bridge=bridge,
        capacity_metrics=capacity_metrics,
        economics_profile=economics_profile_ctx,
    )
    if shadow is not None and not sniper_assessment.get("operational"):
        m9_blockers = sorted(set([M9_SNIPER_BLOCKER] + m9_blockers))

    upstream_blockers: List[str] = []
    m8_2_upstream: Dict[str, Any] = {
        "goal_status": "NOT_EVALUATED",
        "blockers": [],
        "metrics": {},
        "handoff_lane": "none",
        "handoff_ready": False,
    }
    if m8_2_report is not None:
        handoff_lane = str(m8_2_report.get("handoff_lane") or "none")
        handoff_ready = bool(m8_2_report.get("handoff_ready"))
        m8_2_upstream = {
            "goal_status": m8_2_report.get("goal_status"),
            "blockers": list(m8_2_report.get("blockers") or []),
            "metrics": dict(m8_2_report.get("metrics") or {}),
            "provenance": dict(m8_2_report.get("provenance") or {}),
            "handoff_lane": handoff_lane,
            "handoff_ready": handoff_ready,
            "quality_blockers": list(m8_2_report.get("quality_blockers") or []),
        }
        if not handoff_ready:
            upstream_blockers.append("UPSTREAM_M8_2_NOT_READY")
        elif int(bsm.get("graph_ready_from_expansion") or 0) == 0:
            if bsm.get("expansion_artifact_stale"):
                upstream_blockers.append("EXPANSION_ARTIFACT_STALE")
            upstream_blockers.append("M9_BRIDGE_NOT_CONSUMING_M8_2_HANDOFF_EXPANSION")

    from m8.metadata.acceptance import evaluate_m8_3_acceptance, is_m8_3_ready
    from m8.metadata.registry import DEFAULT_REGISTRY_PATH, load_registry

    m8_3_registry = load_registry(
        m8_3_registry_path or str(REPO_ROOT / DEFAULT_REGISTRY_PATH)
    )
    m8_3_acceptance = evaluate_m8_3_acceptance(m8_3_registry, strict=True)
    m8_3_upstream = {
        "goal_status": m8_3_acceptance.get("goal_status"),
        "blockers": list(m8_3_acceptance.get("m8_3_blockers") or []),
        "gate_results": dict(m8_3_acceptance.get("gate_results") or {}),
        "registry_present": m8_3_registry is not None,
        "generated_at_utc": (m8_3_registry or {}).get("generated_at_utc"),
    }
    if not is_m8_3_ready(m8_3_acceptance):
        upstream_blockers.append("UPSTREAM_M8_3_NOT_READY")
    elif int(bsm.get("routes_decimals_unknown") or 0) == 0:
        m9_blockers = [b for b in m9_blockers if b != "DECIMALS_ENRICHMENT_REQUIRED"]

    # Cross-artifact freshness gate (Patch 3). Additive: never weakens
    # existing upstream gates. When blocked, the freshness blockers are
    # surfaced into upstream_blockers so goal_status stays BLOCKED.
    freshness_gate = _freshness_gate(
        sniper=sniper,
        bridge=bridge,
        shadow=shadow,
        m8_2_report=m8_2_report,
        m8_3_registry=m8_3_registry,
        capacity_metrics=capacity_metrics,
        skip_shadow=skip_shadow,
    )
    if freshness_gate["freshness_status"] == "BLOCKED":
        upstream_blockers.extend(freshness_gate["blockers"])

    pipeline_slo_gate = _sniper_to_shadow_quote_slo_gate(
        sniper=sniper,
        shadow=shadow,
        skip_shadow=skip_shadow,
    )
    if pipeline_slo_gate["slo_status"] in ("BLOCKED", "NOT_MEASURED"):
        upstream_blockers.extend(pipeline_slo_gate["blockers"])

    m9_quote_validation_blockers: List[str] = []
    if capacity_metrics and shadow is not None and not skip_shadow:
        cap_ids = set(capacity_metrics.get("capacity_valid_cycle_ids") or [])
        scan_scope = (shadow or {}).get("scan_scope") or {}
        selected_ids = set(scan_scope.get("shadow_selected_cycle_ids") or [])
        quoted_ids = set(scan_scope.get("shadow_quoted_cycle_ids") or [])
        if cap_ids and selected_ids and not quoted_ids:
            m9_quote_validation_blockers.append("CAPACITY_SELECTED_BUT_NOT_QUOTED")
        if cap_ids and quoted_ids and not (cap_ids & quoted_ids):
            m9_quote_validation_blockers.append("CAPACITY_VALID_NO_SHADOW_QUOTE_OVERLAP")
        cap_inv = str(
            ((capacity_metrics or {}).get("universe_contract") or {}).get("inventory_path")
            or (capacity_metrics or {}).get("effective_inventory_path")
            or ""
        ).strip()
        shadow_inv = str(
            ((shadow or {}).get("universe_contract") or {}).get("inventory_path")
            or (shadow or {}).get("effective_inventory_path")
            or ""
        ).strip()
        if cap_inv and shadow_inv and cap_inv != shadow_inv:
            m9_quote_validation_blockers.append("CAPACITY_EXECUTION_INVENTORY_MISMATCH")
    if m8_2_report and m8_2_report.get("handoff_ready") and shadow is not None:
        if shadow_cycles_found == 0:
            m9_quote_validation_blockers.append("UPSTREAM_OK_BUT_NO_CYCLES")
        elif shadow_cycles_quoteable == 0:
            m9_quote_validation_blockers.append("NO_QUOTEABLE_CYCLES")
        if int((shadow or {}).get("cycles_positive_gross") or 0) == 0 and shadow_cycles_found > 0:
            diag_status = (shadow or {}).get("diagnostic_lane_status")
            econ_rpc_attempts = int(
                ((shadow or {}).get("quote_size_truth") or {}).get("econ_rpc_quote_attempts")
                or 0
            )
            if diag_status == "DIAGNOSTIC_NO_POSITIVE_GROSS":
                m9_quote_validation_blockers.append("DIAGNOSTIC_NO_POSITIVE_GROSS")
            elif diag_status == "CODE_OR_POLICY_ADMISSION_BLOCKED_BEFORE_ECONOMIC_QUOTE":
                m9_quote_validation_blockers.append(
                    "CODE_OR_POLICY_ADMISSION_BLOCKED_BEFORE_ECONOMIC_QUOTE"
                )
            elif econ_rpc_attempts > 0:
                m9_quote_validation_blockers.append("NO_POSITIVE_GROSS")
    if rca:
        top = (rca.get("top_reject_reasons") or rca.get("reject_histogram") or {})
        if isinstance(top, dict):
            if int(top.get("QUOTE_REVERT") or top.get("quote_revert") or 0) > 0:
                m9_quote_validation_blockers.append("QUOTE_REVERT")
            if int(top.get("NO_DEPTH") or top.get("OVERSIZED_VS_DEPTH") or 0) > 0:
                m9_quote_validation_blockers.append("NO_DEPTH")

    bridge_upstream_warnings: List[str] = []
    if not sniper_assessment.get("operational"):
        bridge_upstream_warnings.append(M9_SNIPER_BLOCKER)
    if int(bsm.get("graph_ready_from_m8") or 0) == 0:
        bridge_upstream_warnings.append("M8_DIRECT_INGESTION_NOT_READY")
    if bsm.get("m8_stale") and int(bsm.get("graph_ready_from_m8") or 0) > 0:
        bridge_upstream_warnings.append("M8_ARTIFACT_STALE")

    m9_quote_validation_blockers = sorted(set(m9_quote_validation_blockers))
    all_release_blockers = sorted(
        set(upstream_blockers + m9_blockers + m9_quote_validation_blockers)
    )
    blockers = all_release_blockers
    all_m9_blockers = sorted(set(m9_blockers + m9_quote_validation_blockers))

    upstream_only_blockers = sorted(set(upstream_blockers))
    upstream_bundle_status = (
        "UPSTREAM_BUNDLE_VALIDATED"
        if not upstream_only_blockers
        else "BLOCKED"
    )
    if skip_shadow:
        m9_shadow_acceptance_status = "SKIPPED"
    elif shadow is None:
        m9_shadow_acceptance_status = "NOT_RUN"
    elif m9_blockers or m9_quote_validation_blockers:
        m9_shadow_acceptance_status = "BLOCKED"
    else:
        m9_shadow_acceptance_status = "M9_SHADOW_ACCEPTED"

    exploration_sample: List[Dict[str, Any]] = []
    for r in ((bridge or {}).get("exploration_routes") or [])[:20]:
        exploration_sample.append(
            {
                "origin_source": r.get("origin_source"),
                "dex_id": r.get("dex_id"),
                "source": r.get("source"),
                "pool_address": r.get("pool_address"),
                "why_not_m8_derived": r.get("origin_source") or "exploration",
            }
        )

    if skip_shadow:
        m9_goal = "NOT_EVALUATED"
    elif shadow is None and not all_m9_blockers:
        m9_goal = "NOT_EVALUATED"
    elif all_m9_blockers:
        m9_goal = "BLOCKED"
    else:
        m9_goal = "REACHED"

    if skip_shadow:
        goal_status = (
            "BLOCKED"
            if upstream_only_blockers
            else "UPSTREAM_BUNDLE_VALIDATED"
        )
    else:
        goal_status = "BLOCKED" if blockers else "REACHED"

    operator_verdict = _build_operator_verdict(
        shadow=shadow,
        quote_liveness=quote_liveness,
        m8_2_report=m8_2_report,
        bridge=bridge,
        m9_blockers=m9_blockers,
        rca=rca,
        sniper=sniper,
        sniper_assessment=sniper_assessment,
    )

    return {
        "schema_version": "m9_lane_acceptance_report.6",
        "m8_sniper_assessment": sniper_assessment,
        "funnel_layers": funnel_layers,
        "quote_liveness_metrics": quote_liveness,
        "operator_verdict": operator_verdict,
        "dex_coverage": _dex_coverage(bridge, expansion, shadow),
        "cross_mechanic_topology": _cross_mechanic_topology(bridge, shadow),
        "provenance": {
            "m8_tokens_in": bsm.get("m8_tokens_in"),
            "hint_tokens_matched": bsm.get("hint_tokens_matched"),
            "specialized_index_tokens_matched": bsm.get(
                "specialized_index_tokens_matched"
            ),
            "expansion_external_hints_enabled": exp_summary.get(
                "external_hints_enabled"
            ),
            "expansion_m8_tokens_in": exp_summary.get("m8_tokens_in"),
        },
        "exploration_routes_sample": exploration_sample,
        "quote_lane_rca_summary": (rca or {}).get("summary"),
        "capacity_cycle_metrics": capacity_metrics or {},
        "economics_profile_context": economics_profile_ctx,
        "quote_lane_top_rejects": (rca or {}).get("by_reject_reason"),
        "quote_lane_adapter_errors": (rca or {}).get("by_adapter_family_leg_errors"),
        "m8_2_upstream": m8_2_upstream,
        "m8_3_upstream": m8_3_upstream,
        "freshness_gate": freshness_gate,
        "pipeline_slo_gate": pipeline_slo_gate,
        "m9_blockers": m9_blockers,
        "m9_quote_validation_blockers": m9_quote_validation_blockers,
        "m9_economics_status": (
            quote_liveness.get("economics_status")
            if quote_liveness
            else (
                "NOT_EVALUATED_AFTER_GRAPH_HANDOFF"
                if m8_2_report and m8_2_report.get("handoff_ready")
                else "NOT_EVALUATED"
            )
        ),
        "upstream_blockers": upstream_blockers,
        "bridge_upstream_warnings": bridge_upstream_warnings,
        "blockers": blockers,
        "goal_status": goal_status,
        "m9_goal_status": m9_goal,
        "upstream_bundle_status": upstream_bundle_status,
        "m9_shadow_acceptance_status": m9_shadow_acceptance_status,
        "skip_shadow": bool(skip_shadow),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="M8->M9 per-layer acceptance report")
    ap.add_argument("--sniper", default=str(_DEFAULT_PATHS["sniper"]))
    ap.add_argument("--anchor", default=str(_DEFAULT_PATHS["anchor"]))
    ap.add_argument("--expansion", default=str(_DEFAULT_PATHS["expansion"]))
    ap.add_argument("--bridge", default=str(_DEFAULT_PATHS["bridge"]))
    ap.add_argument("--shadow", default=str(_DEFAULT_PATHS["shadow"]))
    ap.add_argument("--rca", default=str(_DEFAULT_PATHS["rca"]))
    ap.add_argument(
        "--m8-2-report",
        default=str(REPO_ROOT / "data/tmp/m8_2_acceptance_report_latest.json"),
        help="M8.2 acceptance report (mirror/subgraph/handoff gates)",
    )
    ap.add_argument(
        "--capacity",
        default=str(REPO_ROOT / "data/tmp/m9_capacity_cycle_diagnostic_latest.json"),
        help="Usable-capacity cycle diagnostic artifact",
    )
    ap.add_argument(
        "--m8-3-registry",
        default=str(REPO_ROOT / "data/runs/_rolling/m8_3_token_metadata_registry_latest.json"),
        help="M8.3 token metadata registry for upstream gate",
    )
    ap.add_argument(
        "--output",
        default=str(REPO_ROOT / "data/tmp/m9_lane_acceptance_report_latest.json"),
    )
    ap.add_argument(
        "--skip-shadow",
        action="store_true",
        default=False,
        help="Shadow lane was not run; evaluate upstream bundle only.",
    )
    args = ap.parse_args()

    m8_2_path = Path(args.m8_2_report)
    m8_2_report = _load(m8_2_path) if m8_2_path.exists() else None
    capacity_path = Path(args.capacity)
    capacity_metrics = _load(capacity_path) if capacity_path.exists() else None

    report = build_acceptance_report(
        sniper=_load(Path(args.sniper)),
        anchor=_load(Path(args.anchor)),
        expansion=_load(Path(args.expansion)),
        bridge=_load(Path(args.bridge)),
        shadow=None if args.skip_shadow else _load(Path(args.shadow)),
        rca=_load(Path(args.rca)),
        m8_2_report=m8_2_report,
        capacity_metrics=capacity_metrics,
        m8_3_registry_path=args.m8_3_registry,
        skip_shadow=bool(args.skip_shadow),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["funnel_layers"], indent=2))
    print("m8_2_upstream:", report["m8_2_upstream"].get("goal_status"))
    print("m8_3_upstream:", report["m8_3_upstream"].get("goal_status"))
    print("m9_blockers:", report["m9_blockers"])
    print("upstream_blockers:", report["upstream_blockers"])
    print("blockers:", report["blockers"])
    print("written:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
