"""M8 sniper listener health gate (acceptance / handoff)."""
from __future__ import annotations

from typing import Any, Dict, List

_RPC_ERROR_RATE_MAX = 0.05


def _classify_factory_window(
    dex: str,
    row: Dict[str, Any],
) -> str:
    """Classify per-factory outcome: ok, market_window, or degraded."""
    polls_ok = int(row.get("polls_ok") or 0)
    errors = int(row.get("errors") or 0)
    raw_logs = int(row.get("raw_logs") or 0)
    parse_ok = int(row.get("parse_ok") or 0)
    candidates = int(row.get("candidates") or 0)
    if errors > 0 and polls_ok == 0 and parse_ok == 0 and candidates == 0:
        return "degraded"
    if raw_logs == 0 and polls_ok > 0 and errors == 0:
        return "market_window"
    return "ok"


def _ws_lane_healthy(metrics: Dict[str, Any]) -> bool:
    listener_mode = str(metrics.get("listener_mode") or "http_only")
    ws_connected = bool(metrics.get("ws_connected"))
    ws_events = int(metrics.get("ws_events_seen") or 0)
    return listener_mode.startswith("ws") and ws_connected and ws_events > 0


def _resolve_self_test_source(artifact: Dict[str, Any]) -> str | None:
    """Return self_test_source from artifact, with legacy reason fallback."""
    explicit = artifact.get("self_test_source")
    if explicit in ("live", "checkpoint", "skipped_unverified"):
        return str(explicit)
    reasons = list(artifact.get("reasons") or [])
    if "SELF_TEST_SKIPPED" in reasons:
        return "skipped_unverified"
    self_test = artifact.get("self_test_by_dex") or (artifact.get("metrics") or {}).get(
        "self_test_by_dex"
    ) or {}
    if self_test:
        return "live"
    return None


def evaluate_m8_sniper_health(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Return health blockers for M8 sniper rolling artifact."""
    metrics = artifact.get("metrics") or {}
    blockers: List[str] = []

    rpc_calls = int(metrics.get("rpc_calls_made") or 0)
    rpc_errors = int(metrics.get("rpc_errors") or 0)
    error_rate = round(rpc_errors / rpc_calls, 4) if rpc_calls else 0.0
    ws_healthy = _ws_lane_healthy(metrics)

    if rpc_calls > 0 and error_rate >= _RPC_ERROR_RATE_MAX and not ws_healthy:
        blockers.append("M8_RPC_ERROR_RATE_HIGH")

    if int(metrics.get("parse_failed") or 0) > 0:
        blockers.append("M8_PARSE_FAILED")

    self_test_source = _resolve_self_test_source(artifact)
    if self_test_source == "skipped_unverified":
        blockers.append("M8_SELF_TEST_SKIPPED")

    self_test = artifact.get("self_test_by_dex") or metrics.get("self_test_by_dex") or {}
    for dex, row in self_test.items():
        if str((row or {}).get("status") or "").upper() != "PASS":
            blockers.append(f"M8_SELF_TEST_FAIL:{dex}")

    listener_mode = str(metrics.get("listener_mode") or "http_only")
    ws_connected = bool(metrics.get("ws_connected"))
    if listener_mode == "http_only" and not ws_connected:
        blockers.append("M8_HTTP_ONLY_DEGRADED")

    factory_last_success = metrics.get("factory_last_success_ts") or {}
    if rpc_calls > 0 and not factory_last_success and not ws_healthy:
        blockers.append("M8_FACTORY_NO_HTTP_SUCCESS")

    factory_bd = metrics.get("factory_breakdown") or {}
    degraded_dexes: List[str] = []
    market_window_dexes: List[str] = []
    for dex, row in factory_bd.items():
        kind = _classify_factory_window(dex, row or {})
        if kind == "degraded":
            degraded_dexes.append(dex)
        elif kind == "market_window":
            market_window_dexes.append(dex)

    if degraded_dexes and not ws_healthy:
        blockers.append("M8_FACTORY_DEGRADED")

    recent_by_dex = artifact.get("recent_events_by_dex") or {}
    has_recent = any(len(v or []) > 0 for v in recent_by_dex.values())
    market_only = bool(market_window_dexes) and not has_recent and not degraded_dexes
    if (
        not has_recent
        and not market_only
        and int(metrics.get("snipe_candidates_total") or 0) == 0
        and rpc_errors > 0
        and not ws_healthy
    ):
        blockers.append("M8_NO_EVENTS_AND_RPC_ERRORS")

    pending_sync = metrics.get("pending_registry_sync") or {}
    if pending_sync.get("registry_out_of_sync"):
        blockers.append("M8_PENDING_REGISTRY_OUT_OF_SYNC")

    goal = "REACHED" if not blockers else "BLOCKED"
    return {
        "goal_status": goal,
        "blockers": sorted(set(blockers)),
        "rpc_error_rate": error_rate,
        "listener_mode": listener_mode,
        "ws_connected": ws_connected,
        "degraded_dexes": sorted(degraded_dexes),
        "market_window_dexes": sorted(market_window_dexes),
        "has_recent_events_by_dex": has_recent,
        "ws_lane_healthy": ws_healthy,
    }
