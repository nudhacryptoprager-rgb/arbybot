"""M8 -> M9 runtime truth admission gate.

Hard operational gate that refuses a cross-artifact runtime bundle when:

* the M8 sniper artifact is a stub / partial document (schema invalid,
  placeholder pool address such as ``0xabc``, minimal content, missing
  ``m8_health`` / ``recent_events_by_dex``);
* any M8 -> M9 input artifact is missing, has no parseable timestamp, or is
  stale past its threshold;
* artifacts come from mixed runtime windows (no single ``run_timestamp``
  window), i.e. pairwise ``generated_at_utc`` deltas exceed the window
  budget.

Blockers produced by this gate are classified ``CODE_ARTIFACT_CONTRACT`` —
they are evidence-integrity defects, never a market-window blocker.  A
market verdict is only admissible when ``truth_status == "PASS"``.

This gate is additive: it never weakens the per-layer acceptance gates
(``m8_2_acceptance_report.py``, ``m8_3_acceptance_report.py``,
``m9_lane_acceptance_report.py``).  It exists so that a stub sniper artifact
or a stitched mixed-provenance bundle cannot silently flow downstream and be
described later as a fresh, quote-ready state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from monitoring.sniper_artifacts import (
    M9_SNIPER_BLOCKER,
    assess_sniper_artifact_for_m9,
)

__all__ = [
    "BLOCKER_CLASS_CODE_ARTIFACT_CONTRACT",
    "STALE_SECONDS",
    "WINDOW_MISMATCH_SECONDS",
    "evaluate_runtime_truth_gate",
]

# Blocker classification for every blocker emitted by this gate.
BLOCKER_CLASS_CODE_ARTIFACT_CONTRACT = "CODE_ARTIFACT_CONTRACT"

# Per-artifact staleness ceilings (seconds), keyed by input artifact.
# Mirrors the conservative thresholds of the M9 lane freshness gate:
# the sniper is the hottest upstream input; the rest refresh on the order
# of tens of minutes to hours.
STALE_SECONDS: Dict[str, int] = {
    "sniper": 30 * 60,        # 30 min
    "anchor": 6 * 3600,       # M8.1 stable-anchor diagnostics
    "hints": 6 * 3600,        # M8.2 external pool hints
    "expansion": 6 * 3600,    # M8.2 cross-DEX expansion
    "m8_3": 6 * 3600,         # M8.3 token metadata registry
    "bridge": 6 * 3600,       # M9 bridge inventory
}

# Artifacts further apart than this do not count as one runtime window.
WINDOW_MISMATCH_SECONDS: int = 30 * 60

# Canonical ``generated_at_utc`` extraction per artifact key.
def _artifact_timestamp(key: str, doc: Optional[Dict[str, Any]]) -> Optional[str]:
    if not doc:
        return None
    ts = doc.get("generated_at_utc")
    if ts:
        return str(ts)
    if key == "bridge":
        bsm = doc.get("bridge_source_metrics") or {}
        if bsm.get("sniper_generated_at_utc"):
            return None  # bridge itself must carry its own timestamp
    return None


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def evaluate_runtime_truth_gate(
    *,
    sniper: Optional[Dict[str, Any]],
    anchor: Optional[Dict[str, Any]] = None,
    hints: Optional[Dict[str, Any]] = None,
    expansion: Optional[Dict[str, Any]] = None,
    m8_3_registry: Optional[Dict[str, Any]] = None,
    bridge: Optional[Dict[str, Any]] = None,
    window_seconds: int = WINDOW_MISMATCH_SECONDS,
    stale_seconds: Optional[Dict[str, int]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Evaluate one M8 -> M9 runtime bundle for evidence integrity.

    Returns a verdict dict:

    * ``truth_status``: ``"PASS"`` | ``"BLOCKED"``
    * ``blocker_class``: ``None`` when PASS, else ``CODE_ARTIFACT_CONTRACT``
    * ``blockers``: sorted unique blocker codes
    * ``sniper_assessment``: full ``assess_sniper_artifact_for_m9`` result
    * ``per_artifact``: per-input freshness rows
    """
    thresholds = dict(STALE_SECONDS)
    if stale_seconds:
        thresholds.update(stale_seconds)
    now_dt = now or datetime.now(tz=timezone.utc)

    docs: Dict[str, Optional[Dict[str, Any]]] = {
        "sniper": sniper,
        "anchor": anchor,
        "hints": hints,
        "expansion": expansion,
        "m8_3": m8_3_registry,
        "bridge": bridge,
    }

    blockers: List[str] = []

    # --- 1. Sniper stub / schema truth (0xabc, partial content, schema) ---
    sniper_assessment = assess_sniper_artifact_for_m9(sniper)
    if not sniper_assessment.get("operational"):
        blockers.extend(sniper_assessment.get("blockers") or [M9_SNIPER_BLOCKER])

    # --- 2. Presence + timestamp + staleness for every input --------------
    per_artifact: Dict[str, Dict[str, Any]] = {}
    parsed: Dict[str, datetime] = {}
    for key, doc in docs.items():
        entry: Dict[str, Any] = {"present": doc is not None}
        if doc is None:
            entry["status"] = "MISSING"
            blockers.append(f"{key.upper()}_ARTIFACT_MISSING")
            per_artifact[key] = entry
            continue
        ts_str = _artifact_timestamp(key, doc)
        entry["generated_at_utc"] = ts_str
        ts_dt = _parse_ts(ts_str)
        if ts_dt is None:
            entry["status"] = "MISSING_TIMESTAMP"
            blockers.append(f"{key.upper()}_TIMESTAMP_MISSING")
            per_artifact[key] = entry
            continue
        age_s = (now_dt - ts_dt).total_seconds()
        entry["age_seconds"] = round(age_s, 1)
        threshold = thresholds.get(key)
        entry["stale_threshold_seconds"] = threshold
        if threshold is not None and age_s > threshold:
            entry["status"] = "STALE"
            blockers.append(f"{key.upper()}_STALE")
        else:
            entry["status"] = "FRESH"
        parsed[key] = ts_dt
        per_artifact[key] = entry

    # --- 3. Single run_timestamp window ------------------------------------
    keys_present = sorted(parsed.keys())
    max_delta = 0.0
    for i in range(len(keys_present)):
        for j in range(i + 1, len(keys_present)):
            delta = abs(
                (parsed[keys_present[i]] - parsed[keys_present[j]]).total_seconds()
            )
            if delta > max_delta:
                max_delta = delta
    if len(keys_present) >= 2 and max_delta > window_seconds:
        blockers.append("MIXED_RUNTIME_WINDOW")

    blockers = sorted(set(blockers))
    truth_status = "PASS" if not blockers else "BLOCKED"
    return {
        "schema_version": "m8_m9_runtime_truth_gate.1",
        "truth_status": truth_status,
        "blocker_class": (
            None if truth_status == "PASS" else BLOCKER_CLASS_CODE_ARTIFACT_CONTRACT
        ),
        "blockers": blockers,
        "sniper_assessment": sniper_assessment,
        "per_artifact": per_artifact,
        "window_seconds": window_seconds,
        "window_max_delta_seconds": round(max_delta, 1),
        "stale_thresholds_seconds": thresholds,
        "evaluated_at_utc": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "semantics": (
            "BLOCKED means the evidence bundle failed stub/schema/freshness/"
            "window integrity (CODE_ARTIFACT_CONTRACT); it is never a market "
            "verdict. Market claims are admissible only after PASS."
        ),
    }
