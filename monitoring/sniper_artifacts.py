"""M8 Phase 1 — Sniper artifact writer.

Writes ``data/runs/_rolling/new_pool_sniper_latest.json`` atomically.

This is the canonical rolling artifact for M8.  It must be overwritten on
every update; never create per-run copies.

Schema contract:
  schema_family   = "m8_sniper"  (fixed; never change without schema_revision bump)
  schema_revision = non-empty string identifying the current schema generation
  generated_at_utc, source, freshness_s, status, reasons, metrics — all required.

Golden fixture: ``docs/artifacts/golden/new_pool_sniper_latest_golden.json``.
Schema-contract test: ``tests/unit/test_m8_sniper_artifacts.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.json_io import atomic_write_json

__all__ = [
    "SCHEMA_FAMILY",
    "SCHEMA_REVISION",
    "ROLLING_ARTIFACT_PATH",
    "REQUIRED_TOP_LEVEL_FIELDS",
    "M9_SNIPER_BLOCKER",
    "make_empty_sniper_state",
    "make_sniper_artifact",
    "write_sniper_artifact",
    "validate_sniper_artifact",
    "assess_sniper_artifact_for_m9",
]

# ---------------------------------------------------------------------------
# Schema constants — bump SCHEMA_REVISION on any breaking field change.
# ---------------------------------------------------------------------------

SCHEMA_FAMILY: str = "m8_sniper"
# phase2.0 — Phase 2 paper-only unlock: added ``expected_pnl_usd`` to phase2_decision.
# All Phase 2 fields stay None in Phase 1 artifacts; null-friendly additive change.
SCHEMA_REVISION: str = "phase2.0"

# Canonical rolling artifact path (relative to repo root).
ROLLING_ARTIFACT_PATH: Path = Path("data/runs/_rolling/new_pool_sniper_latest.json")

# All fields required at the top level of every artifact.
REQUIRED_TOP_LEVEL_FIELDS: frozenset[str] = frozenset({
    "schema_family",
    "schema_revision",
    "generated_at_utc",
    "source",
    "freshness_s",
    "status",
    "reasons",
    "metrics",
})

# Required keys inside "metrics".
REQUIRED_METRIC_KEYS: frozenset[str] = frozenset({
    "pool_creation_events_seen",
    "pool_creation_events_filtered_out",
    "honeypot_check_pass",
    "honeypot_check_fail",
    "snipe_candidates_total",
})

# Extended funnel keys written under ``metrics`` (additive contract).
EXTENDED_METRIC_KEYS: frozenset[str] = frozenset({
    "factory_error_rate_by_dex",
    "factory_last_success_ts",
    "factory_last_error_code",
    "dexes_degraded",
    "pending_registry_sync",
})

# Valid status values.
VALID_STATUSES: frozenset[str] = frozenset({
    "EMPTY",       # no events seen yet (listener not running or just started)
    "ACTIVE",      # listener running, receiving events
    "STALE",       # listener was running but freshness_s exceeded threshold
    "ERROR",       # listener encountered a fatal error
    "DEGRADED",    # listener ran but health gate failed (RPC/WS/self-test)
    "RPC_ERROR",   # HTTP-only mode, all RPC calls failed (e.g. provider range limit)
})


# ---------------------------------------------------------------------------
# State builder
# ---------------------------------------------------------------------------


def make_empty_sniper_state() -> Dict[str, Any]:
    """Return a minimal metrics state with all counters zeroed."""
    return {
        "pool_creation_events_seen": 0,
        "pool_creation_events_filtered_out": 0,
        "honeypot_check_pass": 0,
        "honeypot_check_fail": 0,
        "snipe_candidates_total": 0,
        # Guaranteed present so artifact always has this field visible.
        # Populated by FunnelTracker.snapshot(); stays 0 when no poll errors.
        "events_potentially_missed": 0,
    }


# ---------------------------------------------------------------------------
# Artifact builder
# ---------------------------------------------------------------------------


def make_sniper_artifact(
    *,
    metrics: Optional[Dict[str, Any]] = None,
    status: str = "EMPTY",
    reasons: Optional[List[str]] = None,
    source: str = "new_pool_listener",
    freshness_s: Optional[float] = None,
    generated_at_utc: Optional[str] = None,
    recent_events: Optional[List[Dict[str, Any]]] = None,
    recent_events_by_dex: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    self_test_by_dex: Optional[Dict[str, Any]] = None,
    self_test_source: Optional[str] = None,
    run_scope: str = "all",
    dex_filter: Optional[str] = None,
    phase2_decision: Optional[Dict[str, Any]] = None,
    enricher_config: Optional[Dict[str, Any]] = None,
    provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a ``new_pool_sniper_latest.json`` artifact dict.

    Parameters
    ----------
    metrics:
        Counter dict.  Defaults to ``make_empty_sniper_state()``.
    status:
        One of ``VALID_STATUSES``.  Defaults to ``"EMPTY"``.
    reasons:
        List of human-readable reason strings.
    source:
        Identifies the writer (default: ``"new_pool_listener"``).
    freshness_s:
        Seconds since last event (None = unknown / not started).
    generated_at_utc:
        ISO-8601 UTC string.  Defaults to current UTC time.
    recent_events:
        Optional list of recent ``NewPoolEvent`` dicts for dashboard display.
        Capped at 20 entries in the artifact to avoid bloat.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status {status!r}. Expected one of: {sorted(VALID_STATUSES)}"
        )

    ts = generated_at_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    effective_metrics = dict(make_empty_sniper_state())
    if metrics:
        effective_metrics.update(metrics)

    artifact: Dict[str, Any] = {
        "schema_family": SCHEMA_FAMILY,
        "schema_revision": SCHEMA_REVISION,
        "generated_at_utc": ts,
        "source": source,
        "freshness_s": freshness_s,
        "status": status,
        "reasons": list(reasons) if reasons is not None else ["NO_EVENTS_YET"],
        "metrics": effective_metrics,
        # Dry-run scoring fields — Phase 1 stubs (all null / placeholder).
        # Phase 2 will populate these with real estimates from CEX depth + cost model.
        "scoring": {
            "spread_bps": None,        # estimated spread in basis-points
            "spread_usd": None,        # estimated spread in USD
            "volume_usd": None,        # estimated 24 h volume in USD
            "profit_usd": None,        # estimated net profit after fees
            "realizability_reason": "PHASE1_NO_SCORING",
        },
        # Phase 2 execution decision (all null in Phase 1; populated by
        # strategy/sniper_entry_decision.py + execution/slippage_guard.py + simulator).
        # If ``phase2_decision`` kwarg is provided, its values override the null stub.
        "phase2_decision": phase2_decision if phase2_decision is not None else {
            "honeypot_result": None,        # None | "SAFE" | "HONEYPOT" | "UNKNOWN"
            "simulation_result": None,      # None | "PASS" | "FAIL" | "REVERT:<reason>"
            "realisability_reason": None,   # None | "PROFITABLE" | "UNPROFITABLE" | "RISKY"
            "dry_run_decision": None,       # None | "WOULD_ENTER" | "SKIP"
            "reject_reason": None,          # None | "<reason_code>" if SKIP
            "expected_pnl_usd": None,       # None | float — Phase 2 paper-sim expected net PnL
        },
    }

    # Optional: include recent events for dashboard (capped).
    # 500 events: 24h lookback (~515 pools/day on Base); bridge builder reads this for M9 inventory.
    _MAX_RECENT = 500
    events = (recent_events or [])[:_MAX_RECENT]
    artifact["recent_events"] = events
    # Per-dex event window: last N events per dex so minority-dex events
    # (V2, V3, ve33) are not pushed out by high-volume V4 in the global window.
    artifact["recent_events_by_dex"] = dict(recent_events_by_dex) if recent_events_by_dex else {}

    # Run scope and self-test results (Steps 2+3: identify partial runs, include parser proof)
    artifact["run_scope"] = run_scope
    artifact["dex_filter"] = dex_filter
    artifact["self_test_by_dex"] = dict(self_test_by_dex) if self_test_by_dex else {}
    if self_test_source in ("live", "checkpoint", "skipped_unverified"):
        artifact["self_test_source"] = self_test_source
    # Step 7: enricher config snapshot — records anchor prices, probe size, etc.
    artifact["enricher_config"] = dict(enricher_config) if enricher_config else None
    if provenance:
        artifact["provenance"] = dict(provenance)

    from core.pipeline_provenance import apply_pipeline_provenance

    return apply_pipeline_provenance(artifact, run_timestamp=ts)


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_sniper_artifact(
    artifact: Dict[str, Any],
    path: Optional[Path] = None,
) -> Path:
    """Atomically write a sniper artifact to the rolling artifact path.

    Parameters
    ----------
    artifact:
        Dict built by ``make_sniper_artifact()``.
    path:
        Override the output path.  Defaults to ``ROLLING_ARTIFACT_PATH``
        (relative to the current working directory).

    Returns
    -------
    Path to the written file.
    """
    target = path or ROLLING_ARTIFACT_PATH
    return atomic_write_json(target, artifact)


# ---------------------------------------------------------------------------
# Validator (schema-contract enforcement)
# ---------------------------------------------------------------------------


def validate_sniper_artifact(artifact: Dict[str, Any]) -> List[str]:
    """Validate artifact dict against schema contract.

    Returns a list of violation strings (empty = valid).
    Does NOT raise; callers decide what to do with violations.
    """
    violations: List[str] = []

    # 1. Top-level required fields
    for field_name in REQUIRED_TOP_LEVEL_FIELDS:
        if field_name not in artifact:
            violations.append(f"Missing required field: {field_name!r}")

    # 2. schema_family must be fixed string
    if artifact.get("schema_family") != SCHEMA_FAMILY:
        violations.append(
            f"schema_family must be {SCHEMA_FAMILY!r}, "
            f"got {artifact.get('schema_family')!r}"
        )

    # 3. schema_revision must be non-empty string
    rev = artifact.get("schema_revision")
    if not rev or not isinstance(rev, str):
        violations.append(
            f"schema_revision must be a non-empty string, got {rev!r}"
        )

    # 4. status must be a known value
    status = artifact.get("status")
    if status not in VALID_STATUSES:
        violations.append(
            f"status {status!r} is not in {sorted(VALID_STATUSES)}"
        )

    # 5. metrics must contain required keys
    metrics = artifact.get("metrics", {})
    if not isinstance(metrics, dict):
        violations.append("'metrics' must be a dict")
    else:
        for key in REQUIRED_METRIC_KEYS:
            if key not in metrics:
                violations.append(f"metrics missing required key: {key!r}")
            elif not isinstance(metrics[key], (int, float)):
                violations.append(
                    f"metrics[{key!r}] must be numeric, got {type(metrics[key]).__name__}"
                )

    # 6. reasons must be a list
    reasons = artifact.get("reasons")
    if reasons is not None and not isinstance(reasons, list):
        violations.append("'reasons' must be a list")

    return violations


# ---------------------------------------------------------------------------
# M9 handoff operational gate (detect stub/minimal sniper artifacts)
# ---------------------------------------------------------------------------

M9_SNIPER_BLOCKER = "M8_SNIPER_ARTIFACT_INVALID_OR_STUB"

# Minimum hex chars (without 0x) for a real pool address on EVM chains.
_MIN_POOL_HEX_LEN = 40


def _is_placeholder_pool_address(pool: Optional[str]) -> bool:
    """True when pool looks like a test stub (0xabc) rather than a full address."""
    raw = (pool or "").strip().lower()
    if not raw.startswith("0x"):
        return True
    body = raw[2:]
    if not body:
        return True
    if len(body) < _MIN_POOL_HEX_LEN:
        return True
    return False


def assess_sniper_artifact_for_m9(
    artifact: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Assess whether rolling sniper artifact supports fresh M8→M9 claims.

    Universal heuristics only — no pool-address allowlists.
    Returns operational=False when schema/health/stub checks fail.
    """
    blockers: List[str] = []

    if artifact is None:
        return {
            "operational": False,
            "blockers": [M9_SNIPER_BLOCKER, "M8_SNIPER_ARTIFACT_MISSING"],
            "m8_health_present": False,
            "recent_events_by_dex_present": False,
            "recent_events_count": 0,
            "pool_creation_events_seen": 0,
        }

    schema_violations = validate_sniper_artifact(artifact)
    if schema_violations:
        blockers.append(M9_SNIPER_BLOCKER)
        blockers.append("M8_SNIPER_SCHEMA_INVALID")

    if "m8_health" not in artifact:
        blockers.append("M8_SNIPER_MISSING_M8_HEALTH")

    if "recent_events_by_dex" not in artifact:
        blockers.append("M8_SNIPER_MISSING_RECENT_EVENTS_BY_DEX")

    metrics = artifact.get("metrics") or {}
    if not isinstance(metrics, dict):
        blockers.append("M8_SNIPER_METRICS_INVALID")
        metrics = {}

    events_seen = int(metrics.get("pool_creation_events_seen") or 0)
    recent = artifact.get("recent_events") or []
    if not isinstance(recent, list):
        blockers.append("M8_SNIPER_RECENT_EVENTS_INVALID")
        recent = []

    # Stub: ACTIVE listener artifact with trivial event window (e.g. single 0xabc pool).
    status = str(artifact.get("status") or "")
    if status == "ACTIVE" and len(recent) <= 1 and events_seen <= 1:
        if not recent:
            blockers.append("M8_SNIPER_STUB_MINIMAL_CONTENT")
        else:
            pool = recent[0].get("pool") if isinstance(recent[0], dict) else None
            if _is_placeholder_pool_address(pool):
                blockers.append("M8_SNIPER_STUB_PLACEHOLDER_POOL")

    operational = (
        not schema_violations
        and "m8_health" in artifact
        and "recent_events_by_dex" in artifact
        and not any(b.startswith("M8_SNIPER_STUB") for b in blockers)
        and (events_seen > 1 or len(recent) > 1)
    )
    if not operational:
        blockers = sorted(set([M9_SNIPER_BLOCKER] + blockers))

    return {
        "operational": operational,
        "blockers": sorted(set(blockers)),
        "m8_health_present": "m8_health" in artifact,
        "recent_events_by_dex_present": "recent_events_by_dex" in artifact,
        "recent_events_count": len(recent),
        "pool_creation_events_seen": events_seen,
        "m8_health_goal_status": (artifact.get("m8_health") or {}).get("goal_status"),
    }
