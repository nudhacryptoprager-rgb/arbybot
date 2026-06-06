"""M8 Phase 1 — Event funnel tracker for new-pool sniper.

Tracks the complete event processing pipeline with per-stage counters
and a bounded ring-buffer of per-event traces.

Funnel stages (ordered):
    raw_fetched         — raw log entries returned by eth_getLogs
    parse_ok            — successfully parsed into NewPoolEvent
    parse_failed        — parse_raw_log returned None (malformed log)
    dedup_new           — event_id not seen before (unique event)
    dedup_dropped       — event_id already seen (duplicate block / re-org)
    filter_passed       — passed all downstream filters (Phase 1: = dedup_new)
    filter_rejected     — rejected by downstream filter (Phase 2+: honeypot, blacklist)
    candidates_queued   — queued for cold-lane evaluation (= filter_passed in Phase 1)

This module is pure: no network calls, no artifact writes.
All state is held in FunnelTracker instances.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional

__all__ = [
    "EventTrace",
    "FunnelTracker",
    "FUNNEL_STAGE_NAMES",
]

# ---------------------------------------------------------------------------
# Ordered funnel stage names (canonical)
# ---------------------------------------------------------------------------

FUNNEL_STAGE_NAMES: List[str] = [
    "raw_fetched",
    "parse_ok",
    "parse_failed",
    "dedup_new",
    "dedup_dropped",
    "filter_passed",
    "filter_rejected",
    "candidates_queued",
]

# Maximum per-event traces kept in memory (ring-buffer behaviour).
_MAX_TRACES = 200

# RPC error type labels
_RPC_ERR_408 = "408_timeout"
_RPC_ERR_429 = "429_rate_limit"
_RPC_ERR_5XX = "5xx_server"
_RPC_ERR_TIMEOUT = "timeout"
_RPC_ERR_OTHER = "other"


def _classify_rpc_error(error_str: str) -> str:
    """Classify an RPC error string into a histogram bucket.

    Parameters
    ----------
    error_str:
        The str() of the exception raised by the RPC call.

    Returns
    -------
    One of: ``"408_timeout"``, ``"429_rate_limit"``, ``"5xx_server"``,
    ``"timeout"``, ``"other"``.
    """
    s = error_str.lower()
    if "408" in s:
        return _RPC_ERR_408
    if "429" in s or "too many requests" in s or "rate limit" in s:
        return _RPC_ERR_429
    if any(code in s for code in ("500", "502", "503", "504", "server error")):
        return _RPC_ERR_5XX
    if "timeout" in s or "timed out" in s or "time out" in s:
        return _RPC_ERR_TIMEOUT
    if any(p in s for p in ("block range", "range exceeded", "free tier", "range limit", "-32600")):
        return "range_too_wide"
    return _RPC_ERR_OTHER


def _percentile_summary(samples: List[float]) -> Dict[str, Optional[float]]:
    """Return p50/p95/max summary for a list of latency samples (ms).

    All keys present even if list is empty (values become ``None``).
    """
    if not samples:
        return {"count": 0, "p50": None, "p95": None, "max": None}
    s = sorted(samples)
    n = len(s)
    def _q(q: float) -> float:
        # Nearest-rank percentile (cheap, no numpy dependency).
        idx = max(0, min(n - 1, int(round(q * (n - 1)))))
        return round(s[idx], 1)
    return {
        "count": n,
        "p50": _q(0.50),
        "p95": _q(0.95),
        "max": round(s[-1], 1),
    }


def _estimate_events_potentially_missed(
    polls_ok: Dict[str, int],
    raw_logs: Dict[str, int],
    errors: Dict[str, int],
) -> int:
    """Estimate events dropped due to RPC poll failures (Step 12).

    For each DEX:
        missed ≈ errors[dex] * (raw_logs[dex] / max(polls_ok[dex], 1))

    Rationale: each failed poll likely would have returned roughly the
    same number of logs as the average successful poll.  When a DEX has
    zero successful polls or zero errors, it is skipped.
    """
    total: float = 0.0
    all_dexes = set(polls_ok) | set(raw_logs) | set(errors)
    for dex in all_dexes:
        p_ok = int(polls_ok.get(dex, 0) or 0)
        r_logs = int(raw_logs.get(dex, 0) or 0)
        err = int(errors.get(dex, 0) or 0)
        if p_ok <= 0 or err <= 0:
            continue
        avg_logs_per_poll = r_logs / p_ok
        total += err * avg_logs_per_poll
    return int(round(total))


def _build_factory_breakdown(
    polls_ok: Dict[str, int],
    raw_logs: Dict[str, int],
    parse_ok: Dict[str, int],
    errors: Dict[str, int],
    candidates: Dict[str, int],
) -> Dict[str, Dict[str, Any]]:
    """Merge per-dex counters into a single breakdown dict.

    Returns a dict keyed by dex name with sub-keys:
    ``polls_ok`` (successful polls), ``raw_logs`` (actual log count),
    ``parse_ok``, ``errors``, ``candidates``,
    ``parse_rate_pct``, ``candidate_rate_pct``.

    ``raw`` is kept as a deprecated backward-compat alias for ``polls_ok``.
    """
    all_dexes = (
        set(polls_ok) | set(raw_logs) | set(parse_ok)
        | set(errors) | set(candidates)
    )
    breakdown: Dict[str, Dict[str, Any]] = {}
    for dex in sorted(all_dexes):
        p_ok = polls_ok.get(dex, 0)
        r_logs = raw_logs.get(dex, 0)
        pk = parse_ok.get(dex, 0)
        cands = candidates.get(dex, 0)
        parse_rate = round(100.0 * pk / r_logs, 1) if r_logs > 0 else None
        cand_rate = round(100.0 * cands / r_logs, 1) if r_logs > 0 else None
        breakdown[dex] = {
            "polls_ok": p_ok,
            "raw_logs": r_logs,
            "parse_ok": pk,
            "errors": errors.get(dex, 0),
            "candidates": cands,
            "parse_rate_pct": parse_rate,
            "candidate_rate_pct": cand_rate,
            # deprecated: kept for backward compat; equals polls_ok
            "raw": p_ok,
        }
    return breakdown


@dataclass
class EventTrace:
    """Per-event pipeline trace.

    Carries the minimal fields needed to reconstruct a single event's
    journey through the funnel without holding the full NewPoolEvent.
    """

    event_id: str
    chain: str
    dex: str
    factory: str
    pool: str
    token0: str
    token1: str
    block_number: int
    received_ts: float          # unix timestamp when first seen
    filter_passed: bool = False
    candidate: bool = False
    reject_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "chain": self.chain,
            "dex": self.dex,
            "factory": self.factory,
            "pool": self.pool,
            "token0": self.token0,
            "token1": self.token1,
            "block_number": self.block_number,
            "received_ts": self.received_ts,
            "filter_passed": self.filter_passed,
            "candidate": self.candidate,
            "reject_reason": self.reject_reason,
        }


class FunnelTracker:
    """Thread-safe funnel counter + bounded per-event trace log.

    Usage::

        tracker = FunnelTracker()
        tracker.inc("raw_fetched", 5)
        tracker.inc("parse_ok")
        tracker.record_trace(EventTrace(...))
        snap = tracker.snapshot()
    """

    def __init__(self, *, max_traces: int = _MAX_TRACES) -> None:
        self._max_traces = max_traces
        self._lock = Lock()
        self._counters: Dict[str, int] = {k: 0 for k in FUNNEL_STAGE_NAMES}
        self._traces: List[EventTrace] = []
        self._rpc_calls: int = 0
        self._rpc_errors: int = 0
        self._cycles_completed: int = 0
        self._started_at: float = time.monotonic()
        # rpc_error_histogram — classify errors by HTTP status / type
        self._rpc_error_types: Dict[str, int] = {}
        # factory_breakdown — per-dex counters
        self._dex_polls_ok: Dict[str, int] = {}    # successful polls (no RPC error)
        self._dex_raw_logs: Dict[str, int] = {}    # actual log count (sum of len(logs))
        self._dex_parse_ok: Dict[str, int] = {}
        self._dex_errors: Dict[str, int] = {}
        self._dex_candidates: Dict[str, int] = {}
        # Latency tracking (Step 8: latency metrics in artifact)
        # cycle_durations_ms: ring buffer of last N cycle wall-clock durations.
        # factory_latency_ms: last observed per-factory eth_getLogs latency.
        self._cycle_durations_ms: List[float] = []
        self._factory_latency_ms_last: Dict[str, float] = {}
        self._max_cycle_latency_samples: int = 256
        # Listener mode and WS stats (Step 2/5: --prefer-ws integration)
        self._listener_mode: str = "http_only"
        self._ws_connected: bool = False
        self._ws_subscriptions: int = 0
        self._ws_events_seen: int = 0
        self._ws_reconnects: int = 0
        self._ws_last_event_seen_ts: Optional[float] = None
        self._http_fallback_polls: int = 0
        self._ws_events_by_dex: Dict[str, int] = {}
        self._ws_callbacks_ok_by_dex: Dict[str, int] = {}
        # Self-test results (Step 2: historical archive probe results per DEX)
        self._self_test_by_dex: Dict[str, Any] = {}
        # Run scope (Step 3: identifies full vs isolated --dex runs)
        self._run_scope: str = "all"
        self._dex_filter: Optional[str] = None
        # Phase 2 decision counters
        self._phase2_reject_histogram: Dict[str, int] = {}
        self._phase2_would_enter_count: int = 0
        self._phase2_expected_pnl_non_null_count: int = 0
        # Discovery vs arb split:
        #   discovery = reference_source NONE (no spread reference found)
        #   arb       = reference_source not NONE (MIRROR_POOL / ANCHOR_RATIO / TRIANGULAR_ROUTE)
        self._discovery_candidates_total: int = 0
        self._arb_candidates_total: int = 0
        # Sniper discovery RPC lane (M8 getLogs — separate from M9 quote PRIMARY)
        self._sniper_rpc_provider: str = "unknown"
        self._sniper_rpc_secondary_provider: str = "none"
        self._sniper_rpc_failover_count: int = 0
        self._getlogs_400_count: int = 0
        self._getlogs_429_count: int = 0
        self._getlogs_chunk_size: int = 0
        self._ws_provider: str = "none"
        self._http_fallback_provider: str = "unknown"

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def inc(self, stage: str, n: int = 1) -> None:
        """Increment a funnel stage counter by *n*.

        Unknown stage names are silently ignored to keep the tracker
        resilient against future additions.
        """
        with self._lock:
            if stage in self._counters:
                self._counters[stage] += n

    def inc_rpc_call(self) -> None:
        with self._lock:
            self._rpc_calls += 1

    def inc_rpc_error(self, error_str: str = "") -> None:
        """Increment rpc_errors counter and classify by error type.

        Recognised types: ``408``, ``429``, ``5xx``, ``timeout``, ``other``.
        The ``error_str`` is the exception message from the failed RPC call.
        """
        error_type = _classify_rpc_error(error_str)
        with self._lock:
            self._rpc_errors += 1
            self._rpc_error_types[error_type] = self._rpc_error_types.get(error_type, 0) + 1

    def inc_dex(self, dex: str, stage: str, n: int = 1) -> None:
        """Increment a per-dex counter.

        Stages:
        - ``"polls_ok"`` — one per successful RPC poll (no error).
        - ``"raw_logs"`` — actual log count from that poll (pass ``n=len(logs)``).
        - ``"parse_ok"`` — one per successfully parsed event.
        - ``"error"``    — one per failed RPC call for this dex.
        - ``"candidate"`` — one per event that becomes a snipe candidate.
        - ``"raw"`` (deprecated) — backward-compat alias for ``"polls_ok"``.

        Unknown stage names are silently ignored.
        """
        with self._lock:
            if stage in ("polls_ok", "raw"):  # "raw" is deprecated alias
                self._dex_polls_ok[dex] = self._dex_polls_ok.get(dex, 0) + n
            elif stage == "raw_logs":
                self._dex_raw_logs[dex] = self._dex_raw_logs.get(dex, 0) + n
            elif stage == "parse_ok":
                self._dex_parse_ok[dex] = self._dex_parse_ok.get(dex, 0) + n
            elif stage == "error":
                self._dex_errors[dex] = self._dex_errors.get(dex, 0) + n
            elif stage == "candidate":
                self._dex_candidates[dex] = self._dex_candidates.get(dex, 0) + n

    def complete_cycle(self) -> None:
        with self._lock:
            self._cycles_completed += 1

    def record_cycle_latency(
        self,
        cycle_duration_ms: float,
        per_factory_latency_ms: Optional[Dict[str, float]] = None,
    ) -> None:
        """Record latency samples for one polling cycle (Step 8).

        - ``cycle_duration_ms`` appended to ring buffer (bounded length).
        - ``per_factory_latency_ms`` overwrites the "last observed" map.
        """
        with self._lock:
            self._cycle_durations_ms.append(float(cycle_duration_ms))
            if len(self._cycle_durations_ms) > self._max_cycle_latency_samples:
                self._cycle_durations_ms = self._cycle_durations_ms[
                    -self._max_cycle_latency_samples:
                ]
            if per_factory_latency_ms:
                # Shallow copy (small dict).
                self._factory_latency_ms_last = dict(per_factory_latency_ms)

    def set_listener_mode(self, mode: str) -> None:
        """Set listener mode: 'http_only' or 'ws+http_fallback'."""
        with self._lock:
            self._listener_mode = mode

    def update_ws_stats(
        self,
        *,
        connected: bool = False,
        subscriptions: int = 0,
        events_seen: int = 0,
        reconnects: int = 0,
        last_event_seen_ts: Optional[float] = None,
        events_by_dex: Optional[Dict[str, int]] = None,
        callbacks_ok_by_dex: Optional[Dict[str, int]] = None,
    ) -> None:
        """Sync WS listener stats into funnel for artifact export."""
        with self._lock:
            self._ws_connected = connected
            self._ws_subscriptions = subscriptions
            self._ws_events_seen = events_seen
            self._ws_reconnects = reconnects
            self._ws_last_event_seen_ts = last_event_seen_ts
            if events_by_dex is not None:
                self._ws_events_by_dex = dict(events_by_dex)
            if callbacks_ok_by_dex is not None:
                self._ws_callbacks_ok_by_dex = dict(callbacks_ok_by_dex)

    def inc_http_fallback_poll(self) -> None:
        """Increment HTTP fallback poll counter (used in --prefer-ws mode)."""
        with self._lock:
            self._http_fallback_polls += 1

    def set_sniper_rpc_lane(
        self,
        *,
        primary_provider: str,
        secondary_provider: str = "none",
    ) -> None:
        """Record sniper discovery HTTP lane providers for artifact export."""
        with self._lock:
            self._sniper_rpc_provider = primary_provider
            self._sniper_rpc_secondary_provider = secondary_provider

    def set_prefer_ws_rpc_providers(
        self,
        *,
        ws_provider: str,
        http_fallback_provider: str,
    ) -> None:
        """Record WS + HTTP fallback providers when ``--prefer-ws`` is active."""
        with self._lock:
            self._ws_provider = ws_provider
            self._http_fallback_provider = http_fallback_provider

    def inc_sniper_rpc_failover(self) -> None:
        with self._lock:
            self._sniper_rpc_failover_count += 1

    def inc_getlogs_400(self) -> None:
        with self._lock:
            self._getlogs_400_count += 1

    def inc_getlogs_429(self) -> None:
        with self._lock:
            self._getlogs_429_count += 1

    def set_getlogs_chunk_size(self, chunk_blocks: int) -> None:
        with self._lock:
            self._getlogs_chunk_size = max(0, int(chunk_blocks))

    def set_self_test_results(self, results: Dict[str, Any]) -> None:
        """Store self-test archive probe results for inclusion in snapshot/artifact.

        *results* maps dex_name -> dict(raw, parse_ok, parse_failed, range, status).
        """
        with self._lock:
            self._self_test_by_dex = dict(results)

    def set_run_scope(self, run_scope: str, dex_filter: Optional[str] = None) -> None:
        """Record run scope so artifact clearly identifies partial vs full runs."""
        with self._lock:
            self._run_scope = run_scope
            self._dex_filter = dex_filter

    def inc_phase2_reject(self, reason: str) -> None:
        """Increment reject histogram for a Phase 2 engine rejection."""
        with self._lock:
            self._phase2_reject_histogram[reason] = (
                self._phase2_reject_histogram.get(reason, 0) + 1
            )

    def inc_phase2_would_enter(self) -> None:
        """Increment WOULD_ENTER counter."""
        with self._lock:
            self._phase2_would_enter_count += 1

    def inc_phase2_expected_pnl_non_null(self) -> None:
        """Increment counter of candidates with non-null expected_pnl_usd."""
        with self._lock:
            self._phase2_expected_pnl_non_null_count += 1

    def inc_discovery_candidate(self) -> None:
        """Increment discovery-only counter (reference_source == NONE).

        Discovery candidates are new pools where no spread reference was found
        (no mirror, no dual-anchor, no triangular route).  They are useful for
        listener health but do NOT prove arbitrage economics.
        """
        with self._lock:
            self._discovery_candidates_total += 1

    def inc_arb_candidate(self) -> None:
        """Increment arb-candidate counter (reference_source != NONE).

        Arb candidates have a price reference (mirror pool, anchor ratio, or
        triangular route) and are eligible for PnL estimation.  A non-zero
        count is the minimum requirement for the ARB gate.
        """
        with self._lock:
            self._arb_candidates_total += 1

    def record_trace(self, trace: EventTrace) -> None:
        """Append a per-event trace (ring-buffer, drops oldest if full)."""
        with self._lock:
            self._traces.append(trace)
            if len(self._traces) > self._max_traces:
                self._traces = self._traces[-self._max_traces :]

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a serialisable snapshot of current funnel state.

        All fields match the ``metrics`` schema in ``sniper_artifacts.py``.
        """
        with self._lock:
            elapsed = time.monotonic() - self._started_at
            counters_copy = dict(self._counters)
            return {
                # Required by sniper_artifacts REQUIRED_METRIC_KEYS
                "pool_creation_events_seen": counters_copy["raw_fetched"],
                "pool_creation_events_filtered_out": counters_copy["filter_rejected"],
                "honeypot_check_pass": 0,   # Phase 2 placeholder
                "honeypot_check_fail": 0,   # Phase 2 placeholder
                "snipe_candidates_total": counters_copy["candidates_queued"],
                # Extended funnel detail
                "raw_fetched": counters_copy["raw_fetched"],
                "parse_ok": counters_copy["parse_ok"],
                "parse_failed": counters_copy["parse_failed"],
                "dedup_new": counters_copy["dedup_new"],
                "dedup_dropped": counters_copy["dedup_dropped"],
                "filter_passed": counters_copy["filter_passed"],
                "filter_rejected": counters_copy["filter_rejected"],
                "candidates_queued": counters_copy["candidates_queued"],
                # RPC health
                "rpc_calls_made": self._rpc_calls,
                "rpc_errors": self._rpc_errors,
                "rpc_error_histogram": dict(self._rpc_error_types),
                # Step 12 (CURRENT_STRATEGY): estimate of events dropped due to
                # per-DEX poll failures. For each DEX:
                #   missed ≈ error_polls * (raw_logs / max(polls_ok, 1))
                # i.e. failed polls × average log-rate from successful polls.
                "events_potentially_missed": _estimate_events_potentially_missed(
                    self._dex_polls_ok, self._dex_raw_logs, self._dex_errors,
                ),
                # Per-factory breakdown
                "factory_breakdown": _build_factory_breakdown(
                    self._dex_polls_ok, self._dex_raw_logs,
                    self._dex_parse_ok, self._dex_errors, self._dex_candidates,
                ),
                # Session
                "cycles_completed": self._cycles_completed,
                "elapsed_s": round(elapsed, 1),
                # Latency (Step 8)
                "cycle_latency_ms": _percentile_summary(self._cycle_durations_ms),
                "factory_latency_ms_last": dict(self._factory_latency_ms_last),
                # WS listener stats (Step 5: --prefer-ws metrics)
                "listener_mode": self._listener_mode,
                "ws_connected": self._ws_connected,
                "ws_subscriptions": self._ws_subscriptions,
                "ws_events_seen": self._ws_events_seen,
                "ws_reconnects": self._ws_reconnects,
                "ws_last_event_seen_ts": self._ws_last_event_seen_ts,
                "http_fallback_polls": self._http_fallback_polls,
                "ws_events_by_dex": dict(self._ws_events_by_dex),
                "ws_callbacks_ok_by_dex": dict(self._ws_callbacks_ok_by_dex),
                # Self-test results and run scope (Steps 2+3)
                "self_test_by_dex": dict(self._self_test_by_dex),
                "run_scope": self._run_scope,
                "dex_filter": self._dex_filter,
                # Phase 2 decision metrics
                "phase2_reject_histogram": dict(self._phase2_reject_histogram),
                "phase2_would_enter_count": self._phase2_would_enter_count,
                "phase2_expected_pnl_non_null_count": self._phase2_expected_pnl_non_null_count,
                # Discovery vs arb split
                "discovery_candidates_total": self._discovery_candidates_total,
                "arb_candidates_total": self._arb_candidates_total,
                # Sniper discovery RPC lane (additive — separate from M9 quote PRIMARY)
                "sniper_rpc_provider": self._sniper_rpc_provider,
                "sniper_rpc_secondary_provider": self._sniper_rpc_secondary_provider,
                "sniper_rpc_failover_count": self._sniper_rpc_failover_count,
                "getlogs_400_count": self._getlogs_400_count,
                "getlogs_429_count": self._getlogs_429_count,
                "getlogs_chunk_size": self._getlogs_chunk_size,
                "ws_provider": self._ws_provider,
                "http_fallback_provider": self._http_fallback_provider,
            }

    def recent_traces(self, n: int = 20) -> List[Dict[str, Any]]:
        """Return last *n* per-event traces as dicts (newest last)."""
        with self._lock:
            return [t.to_dict() for t in self._traces[-n:]]

    def funnel_table_lines(self) -> List[str]:
        """Return a human-readable funnel table for console output."""
        snap = self.snapshot()
        stages = [
            ("raw_fetched",       "Raw logs fetched"),
            ("parse_ok",          "  Parsed OK"),
            ("parse_failed",      "  Parse FAILED"),
            ("dedup_new",         "    Dedup NEW"),
            ("dedup_dropped",     "    Dedup DROPPED (dup)"),
            ("filter_passed",     "      Filter PASSED"),
            ("filter_rejected",   "      Filter REJECTED"),
            ("candidates_queued", "        Candidates queued"),
        ]
        lines = [
            "=" * 50,
            "SNIPER FUNNEL — run summary",
            "=" * 50,
        ]
        for key, label in stages:
            count = snap.get(key, 0)
            lines.append(f"  {label:<32} {count:>6}")
        lines.extend([
            "-" * 50,
            f"  RPC calls made                   {snap['rpc_calls_made']:>6}",
            f"  RPC errors                       {snap['rpc_errors']:>6}",
            f"  Cycles completed                 {snap['cycles_completed']:>6}",
            f"  Elapsed (s)                      {snap['elapsed_s']:>6.1f}",
        ])
        hist = snap.get("rpc_error_histogram", {})
        if hist:
            lines.append("  RPC error breakdown:")
            for err_type, cnt in sorted(hist.items()):
                lines.append(f"    {err_type:<28} {cnt:>4}")
        fbd = snap.get("factory_breakdown", {})
        if fbd:
            lines.append("  Per-dex breakdown:")
            for dex, dcnt in fbd.items():
                parse_pct = dcnt.get("parse_rate_pct")
                pct_str = f" ({parse_pct}%ok)" if parse_pct is not None else ""
                lines.append(
                    f"    {dex:<24} polls={dcnt['polls_ok']}  logs={dcnt['raw_logs']}"
                    f"  ok={dcnt['parse_ok']}{pct_str}"
                    f"  err={dcnt['errors']}  cand={dcnt['candidates']}"
                )
        lines.append("=" * 50)
        return lines
