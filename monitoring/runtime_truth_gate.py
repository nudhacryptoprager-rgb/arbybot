"""M8 -> M9 runtime truth admission gate.

Hard operational gate that refuses a cross-artifact runtime bundle when:

* the M8 sniper artifact is a stub / partial document (schema invalid,
  placeholder pool address such as ``0xabc``, minimal content, missing
  ``m8_health`` / ``recent_events_by_dex``);
* any M8 -> M9 input artifact is missing, has no parseable timestamp, or is
  stale past its threshold;
* artifacts come from mixed runtime windows (no single ``run_timestamp``
  window), i.e. pairwise ``run_timestamp`` deltas exceed the window budget;
* artifacts declare different ``run_context.session_id`` values (when
  session_ids are present on at least two inputs).

Provenance contract (SHA-free, v2.x). The canonical provenance field is
``run_context.run_timestamp`` (ISO-8601). ``generated_at_utc`` is a
legacy fallback only and is reported separately.  When two or more
artifacts carry a non-empty ``run_context.session_id`` and they disagree,
the bundle is refused outright (SESSION_ID_MISMATCH) — temporal proximity
cannot compensate for an explicit session-id mismatch.  Conversely, when
all session-bearing artifacts share the same session_id, the temporal
window check is widened to ``session_window_seconds`` (default 90 minutes)
because a serial M8 -> M9 pipeline legitimately spans more than the
30-minute proximity threshold used for ad-hoc handoffs.

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
    "SESSION_WINDOW_SECONDS",
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
# Used when no common session_id binds the artifacts. Allow a 48-minute
# budget by default so consecutively-produced artifacts (one M8 sniper
# run, one M8.1 run right after, ...) still count as one bundle while a
# 2h gap still counts as a mixed window.
WINDOW_MISMATCH_SECONDS: int = 48 * 60

# When session_id is shared by all session-bearing inputs, widen the
# window: a serial M8 -> M8.1 -> M8.2 -> M8.3 -> bridge pipeline can
# legitimately run for 60-90 minutes end-to-end. 90 minutes is the
# conservative ceiling; longer pipelines should pass --window-seconds
# explicitly with the session_id still matching.
SESSION_WINDOW_SECONDS: int = 90 * 60


def _artifact_session_id(doc: Optional[Dict[str, Any]]) -> Optional[str]:
    """Canonical session_id extraction (run_context.session_id or
    top-level session_id)."""
    if not doc:
        return None
    rc = doc.get("run_context")
    if isinstance(rc, dict):
        sid = rc.get("session_id")
        if sid:
            return str(sid)
    sid = doc.get("session_id")
    return str(sid) if sid else None


# Canonical timestamp extraction per artifact key. Prefers
# ``run_context.run_timestamp`` (canonical provenance since v2.x) and
# falls back to ``generated_at_utc`` for older artifacts.
def _artifact_timestamp(key: str, doc: Optional[Dict[str, Any]]) -> Optional[str]:
    if not doc:
        return None
    rc = doc.get("run_context")
    if isinstance(rc, dict):
        rts = rc.get("run_timestamp")
        if rts:
            return str(rts)
    ts = doc.get("generated_at_utc")
    if ts:
        return str(ts)
    if key == "bridge":
        bsm = doc.get("bridge_source_metrics") or {}
        if bsm.get("sniper_generated_at_utc"):
            return None  # bridge itself must carry its own timestamp
    return None


def _artifact_timestamp_source(key: str, doc: Optional[Dict[str, Any]]) -> str:
    """Return which provenance field supplied the timestamp (for reporting)."""
    if not doc:
        return "none"
    rc = doc.get("run_context")
    if isinstance(rc, dict) and rc.get("run_timestamp"):
        return "run_context.run_timestamp"
    if doc.get("generated_at_utc"):
        return "generated_at_utc"
    return "none"


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
    session_window_seconds: int = SESSION_WINDOW_SECONDS,
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
    * ``session_id``: shared session_id if all session-bearing inputs agree,
      ``None`` otherwise
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
    sessions: Dict[str, str] = {}
    for key, doc in docs.items():
        entry: Dict[str, Any] = {"present": doc is not None}
        sid = _artifact_session_id(doc)
        if sid:
            entry["session_id"] = sid
            sessions[key] = sid
        if doc is None:
            entry["status"] = "MISSING"
            blockers.append(f"{key.upper()}_ARTIFACT_MISSING")
            per_artifact[key] = entry
            continue
        ts_str = _artifact_timestamp(key, doc)
        entry["generated_at_utc"] = ts_str
        entry["timestamp_source"] = _artifact_timestamp_source(key, doc)
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

    # --- 3. Session_id binding --------------------------------------------
    # If two or more artifacts carry a session_id, they must all agree.
    # Mismatch is a hard blocker regardless of temporal proximity.
    shared_session_id: Optional[str] = None
    distinct_sessions = set(sessions.values())
    if len(sessions) >= 2:
        if len(distinct_sessions) > 1:
            blockers.append("SESSION_ID_MISMATCH")
            shared_session_id = None
        else:
            # All session-bearing artifacts agree: use the shared id.
            shared_session_id = next(iter(distinct_sessions))
    elif len(sessions) == 1:
        shared_session_id = next(iter(distinct_sessions))

    # --- 4. Single run_timestamp window -----------------------------------
    # When a shared session_id binds the bundle, widen the temporal budget
    # to session_window_seconds — a serial M8 -> M8.1 -> M8.2 -> M8.3 ->
    # bridge pipeline legitimately spans more than the ad-hoc proximity
    # threshold. Without a shared session_id, fall back to the strict
    # window_seconds budget.
    effective_window = (
        session_window_seconds if shared_session_id else window_seconds
    )
    keys_present = sorted(parsed.keys())
    max_delta = 0.0
    for i in range(len(keys_present)):
        for j in range(i + 1, len(keys_present)):
            delta = abs(
                (parsed[keys_present[i]] - parsed[keys_present[j]]).total_seconds()
            )
            if delta > max_delta:
                max_delta = delta
    if len(keys_present) >= 2 and max_delta > effective_window:
        blockers.append("MIXED_RUNTIME_WINDOW")

    blockers = sorted(set(blockers))
    truth_status = "PASS" if not blockers else "BLOCKED"
    return {
        "schema_version": "m8_m9_runtime_truth_gate.2",
        "truth_status": truth_status,
        "blocker_class": (
            None if truth_status == "PASS" else BLOCKER_CLASS_CODE_ARTIFACT_CONTRACT
        ),
        "blockers": blockers,
        "sniper_assessment": sniper_assessment,
        "per_artifact": per_artifact,
        "session_id": shared_session_id,
        "session_ids_by_artifact": sessions,
        "window_seconds": effective_window,
        "window_max_delta_seconds": round(max_delta, 1),
        "stale_thresholds_seconds": thresholds,
        "evaluated_at_utc": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "semantics": (
            "BLOCKED means the evidence bundle failed stub/schema/freshness/"
            "window/session integrity (CODE_ARTIFACT_CONTRACT); it is never a "
            "market verdict. Market claims are admissible only after PASS. "
            "Provenance: run_context.run_timestamp is canonical; "
            "generated_at_utc is a legacy fallback only."
        ),
    }
