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
    return _RPC_ERR_OTHER


def _build_factory_breakdown(
    raw: Dict[str, int],
    parse_ok: Dict[str, int],
    errors: Dict[str, int],
    candidates: Dict[str, int],
) -> Dict[str, Dict[str, int]]:
    """Merge per-dex counters into a single breakdown dict.

    Returns a dict keyed by dex name with sub-keys:
    ``raw``, ``parse_ok``, ``errors``, ``candidates``.
    """
    all_dexes = set(raw) | set(parse_ok) | set(errors) | set(candidates)
    breakdown: Dict[str, Dict[str, int]] = {}
    for dex in sorted(all_dexes):
        breakdown[dex] = {
            "raw": raw.get(dex, 0),
            "parse_ok": parse_ok.get(dex, 0),
            "errors": errors.get(dex, 0),
            "candidates": candidates.get(dex, 0),
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
        # factory_breakdown — per-dex counters for raw/parse_ok/errors/candidates
        self._dex_raw: Dict[str, int] = {}
        self._dex_parse_ok: Dict[str, int] = {}
        self._dex_errors: Dict[str, int] = {}
        self._dex_candidates: Dict[str, int] = {}

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

    def inc_dex(self, dex: str, stage: str) -> None:
        """Increment a per-dex counter for one of: raw, parse_ok, error, candidate.

        Unknown stage names are silently ignored.
        """
        with self._lock:
            if stage == "raw":
                self._dex_raw[dex] = self._dex_raw.get(dex, 0) + 1
            elif stage == "parse_ok":
                self._dex_parse_ok[dex] = self._dex_parse_ok.get(dex, 0) + 1
            elif stage == "error":
                self._dex_errors[dex] = self._dex_errors.get(dex, 0) + 1
            elif stage == "candidate":
                self._dex_candidates[dex] = self._dex_candidates.get(dex, 0) + 1

    def complete_cycle(self) -> None:
        with self._lock:
            self._cycles_completed += 1

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
                # Per-factory breakdown
                "factory_breakdown": _build_factory_breakdown(
                    self._dex_raw, self._dex_parse_ok,
                    self._dex_errors, self._dex_candidates,
                ),
                # Session
                "cycles_completed": self._cycles_completed,
                "elapsed_s": round(elapsed, 1),
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
                lines.append(
                    f"    {dex:<24} raw={dcnt['raw']}  ok={dcnt['parse_ok']}"
                    f"  err={dcnt['errors']}  cand={dcnt['candidates']}"
                )
        lines.append("=" * 50)
        return lines
