"""Read-only API application — pure request handler (transport-agnostic).

Endpoints (all GET, all read-only):

* ``/health/live``   — liveness probe (no artifact checks)
* ``/health/ready``  — readiness: canonical rolling artifacts present,
                        sniper schema/stub/freshness valid, no critical
                        rolling quality blockers (Step 8 fix; previously a
                        stub sniper + stale artifacts counted as "ready").
* ``/v1/control/funnel`` — M_control session-coherent M8→M9 funnel projection
* ``/v1/control/traces`` — entity trace summary (token/pool/route/cycle)
* ``/v1/runs/{id}``  — run summary for one runDir (path-traversal safe)
* ``/v1/opportunities`` — latest opportunities/signals with pagination
* ``/v1/artifacts/{family}/latest`` — canonical artifact by family allowlist
* ``/metrics``       — Prometheus text exposition (cache + request stats)

Conditional requests: every JSON response carries ``ETag``; a matching
``If-None-Match`` yields ``304 Not Modified``.

This module is transport-agnostic: ``ApiApp.handle`` returns
``(status, headers, body_bytes)``; ``api.server`` adapts it to HTTP.

Thread-safety (Step 8 fix): ``request_counts`` and ETag/stats counters on
``ProjectionCache`` are guarded by a ``threading.Lock`` so the API is safe
to serve from ``ThreadingHTTPServer`` (which was not the case before).
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Union

from api.projections import ProjectionCache

__all__ = ["ApiApp"]

JsonDict = Dict[str, Any]
Response = Tuple[int, Dict[str, str], bytes]

_JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}
_PROMETHEUS_HEADERS = {"Content-Type": "text/plain; version=0.0.4; charset=utf-8"}

# Canonical artifact families (allowlist — no arbitrary path reads).
_ARTIFACT_FAMILIES = {
    "sniper": "data/runs/_rolling/new_pool_sniper_latest.json",
    "run_summary": "data/runs/_rolling/run_summary_latest.json",
    "m4_stability": "data/runs/_rolling/m4_stability_agg.json",
    "long_scan": "data/runs/_rolling/long_scan_latest.json",
    "m8_2_acceptance": "data/tmp/m8_2_acceptance_report_latest.json",
    "m8_3_registry": "data/runs/_rolling/m8_3_token_metadata_registry_latest.json",
    "m9_bridge": "data/tmp/m9_bridge_inventory_production_latest.json",
    "m9_capacity": "data/tmp/m9_capacity_cycle_diagnostic_latest.json",
    "m9_acceptance": "data/tmp/m9_lane_acceptance_report_latest.json",
    "pipeline_current": "data/tmp/start_pipeline_current.json",
    "runtime_truth_gate": "data/tmp/m8_m9_runtime_truth_gate_latest.json",
    # Step 4 vertical migration: M8 sniper pools persisted through the
    # StateRepository and exported as a canonical money-safe JSON projection.
    # Legacy sniper JSON writer stays untouched; this projection is pure
    # addition until evidence justifies removing the legacy writer.
    "m8_pools": "data/tmp/m8_pools_repository_projection_latest.json",
}

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")

_MAX_LIMIT = 500

# Per-artifact freshness ceilings accepted by /health/ready (seconds).
# Matches the runtime-truth-gate staleness thresholds.
_READINESS_STALE_S: Dict[str, int] = {
    "sniper": 30 * 60,
    "run_summary": 30 * 60,
    "m4_stability": 6 * 3600,
}


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _artifact_timestamp(doc: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not doc:
        return None
    rc = doc.get("run_context")
    if isinstance(rc, Mapping):
        rts = rc.get("run_timestamp")
        if rts:
            return str(rts)
    ts = doc.get("generated_at_utc")
    return str(ts) if ts else None


class ApiApp:
    """Read-only API over materialized projections."""

    def __init__(
        self,
        repo_root: Union[str, Path] = ".",
        *,
        cache: Optional[ProjectionCache] = None,
        now: Optional[Callable[[], datetime]] = None,
        sniper_assessor: Optional[Callable[[Optional[Mapping[str, Any]]], Dict[str, Any]]] = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.cache = cache or ProjectionCache()
        self.request_counts: Dict[str, int] = {}
        # Step 8 fix: ThreadingHTTPServer runs handle() across worker
        # threads. Guard mutable counters/stats so concurrent reads do not
        # observe torn writes (or under-count requests) and a write from one
        # thread cannot lose an update racing with another thread.
        self._lock = threading.Lock()
        self._now = now or (lambda: datetime.now(tz=timezone.utc))
        # Allowing injection of sniper assessment so tests can stub it; the
        # production assessor (monitoring.sniper_artifacts) is loaded
        # lazily to keep the API module importable without the sniper module.
        self._sniper_assessor: Optional[
            Callable[[Optional[Mapping[str, Any]]], Dict[str, Any]]
        ] = sniper_assessor

    # -- transport-neutral entry point ---------------------------------------

    def handle(
        self,
        method: str,
        path: str,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Response:
        if method != "GET":
            return self._json_response({"error": "method_not_allowed"}, status=405)
        headers = headers or {}
        route, _, query = path.partition("?")
        route = route.rstrip("/") or "/"
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        # Thread-safe request counter (Step 8 fix; protects ThreadingHTTPServer).
        with self._lock:
            self.request_counts[route] = self.request_counts.get(route, 0) + 1

        if route == "/health/live":
            return self._json_response({"status": "alive"})
        if route == "/health/ready":
            return self._ready()
        if route == "/v1/pipeline":
            return self._pipeline(headers)
        if route == "/v1/control/funnel":
            return self._control_funnel(headers)
        if route == "/v1/control/traces":
            return self._control_traces(headers)
        if route.startswith("/v1/runs/"):
            return self._run(route[len("/v1/runs/"):], headers)
        if route == "/v1/opportunities":
            return self._opportunities(params, headers)
        if route.startswith("/v1/artifacts/"):
            return self._artifact(route, headers)
        if route == "/metrics":
            return self._metrics()
        return self._json_response({"error": "not_found"}, status=404)

    # -- endpoints ------------------------------------------------------------

    def _ready(self) -> Response:
        """Readiness now performs real evidence checks (Step 8 fix):

          * canonical rolling artifacts are present;
          * sniper artifact is operationally valid (not a stub, not a
            0xabc placeholder, schema_family / required top-level fields
            present) via monitoring.sniper_artifacts.assess_sniper_artifact_for_m9;
          * every freshness-bearing artifact (sniper, run_summary,
            m4_stability) has a parseable timestamp inside its
            ``_READINESS_STALE_S`` window;
          * runtime_truth_gate, when present, must be in ``PASS`` state;
            absence is not a readiness blocker (it gates M9 shadow, not
            basic dashboard readiness);
          * run_summary.quality_status must not be ``FAIL``.

        The response is backward compatible — ``status`` is "ready" or
        "not_ready", ``missing`` lists missing families — plus an additive
        ``critical_blockers`` array and per-artifact ``checks`` breakdown
        so operators can tell a stub sniper from a stale one.
        """
        now_dt = self._now()
        required = ["run_summary", "sniper", "m4_stability"]
        missing: List[str] = []
        checks: Dict[str, Dict[str, Any]] = {}
        critical_blockers: List[str] = []

        for fam in required:
            proj = self.cache.get(self.repo_root / _ARTIFACT_FAMILIES[fam])
            entry: Dict[str, Any] = {"present": proj is not None}
            if proj is None:
                missing.append(fam)
                entry["status"] = "missing"
                critical_blockers.append(f"{fam.upper()}_ARTIFACT_MISSING")
                checks[fam] = entry
                continue
            data = proj.data if isinstance(proj.data, dict) else {}
            ts_str = _artifact_timestamp(data)
            entry["timestamp"] = ts_str
            ts_dt = _parse_iso(ts_str)
            if ts_dt is None:
                entry["status"] = "no_timestamp"
                critical_blockers.append(f"{fam.upper()}_TIMESTAMP_MISSING")
                checks[fam] = entry
                continue
            age_s = (now_dt - ts_dt).total_seconds()
            threshold = _READINESS_STALE_S.get(fam)
            entry["age_seconds"] = round(age_s, 1)
            entry["stale_threshold_seconds"] = threshold
            if threshold is not None and age_s > threshold:
                entry["status"] = "stale"
                critical_blockers.append(f"{fam.upper()}_STALE")
            else:
                entry["status"] = "fresh"
            checks[fam] = entry

        # Sniper stub / schema truth (Step 8 fix point 2).
        sniper_proj = self.cache.get(self.repo_root / _ARTIFACT_FAMILIES["sniper"])
        if sniper_proj is not None and isinstance(sniper_proj.data, dict):
            assessor = self._sniper_assessor
            if assessor is None:
                try:
                    from monitoring.sniper_artifacts import (
                        assess_sniper_artifact_for_m9,
                    )

                    assessor = assess_sniper_artifact_for_m9
                except ImportError:
                    assessor = None
            if assessor is not None:
                verdict = assessor(sniper_proj.data) or {}
                checks.setdefault("sniper", {}).setdefault("extra", {})["operational"] = (
                    verdict.get("operational")
                )
                checks["sniper"]["blockers"] = list(verdict.get("blockers") or [])
                if not verdict.get("operational"):
                    for b in verdict.get("blockers") or []:
                        if b not in critical_blockers:
                            critical_blockers.append(str(b))

        # run_summary.quality_status must not be FAIL.
        rs_proj = self.cache.get(self.repo_root / _ARTIFACT_FAMILIES["run_summary"])
        if rs_proj is not None and isinstance(rs_proj.data, dict):
            qs = rs_proj.data.get("quality_status")
            checks.setdefault("run_summary", {})["quality_status"] = qs
            if isinstance(qs, str) and qs.upper() == "FAIL":
                critical_blockers.append("RUN_SUMMARY_QUALITY_FAIL")

        # Optional runtime truth gate (gates M9 shadow). Absence is not a
        # readiness blocker for the dashboard; PASS confirms bundle coherent.
        truth_proj = self.cache.get(
            self.repo_root / _ARTIFACT_FAMILIES["runtime_truth_gate"]
        )
        if truth_proj is not None and isinstance(truth_proj.data, dict):
            truth_status = str(truth_proj.data.get("truth_status") or "").upper()
            checks["runtime_truth_gate"] = {"truth_status": truth_status}
            if truth_status == "BLOCKED":
                # Surface as an advisory blocker so operators see it, but do
                # NOT fail /health/ready entirely — runtime truth is an M9
                # admission concern, not a dashboard liveness concern.
                critical_blockers.append("M9_RUNTIME_TRUTH_BLOCKED")

        ready = (not missing) and (not critical_blockers)
        body: Dict[str, Any] = {
            "status": "ready" if ready else "not_ready",
            "missing": missing,
            "checks": checks,
            "critical_blockers": sorted(set(critical_blockers)),
        }
        return self._json_response(body, status=200 if ready else 503)

    def _pipeline(self, headers: Mapping[str, str]) -> Response:
        proj = self.cache.get(self.repo_root / _ARTIFACT_FAMILIES["pipeline_current"])
        body = proj.data if proj is not None else {"status": "idle"}
        return self._json_with_etag(body, proj.etag if proj else None, headers)

    def _control_funnel(self, headers: Mapping[str, str]) -> Response:
        from api.control_projection import build_control_funnel

        body = build_control_funnel(self.repo_root)
        return self._json_response(body)

    def _control_traces(self, headers: Mapping[str, str]) -> Response:
        from api.control_projection import build_control_traces

        body = build_control_traces(self.repo_root)
        return self._json_response(body)

    def _run(self, run_id: str, headers: Mapping[str, str]) -> Response:
        run_id = run_id.strip()
        if not _RUN_ID_RE.match(run_id) or ".." in run_id:
            return self._json_response({"error": "invalid_run_id"}, status=400)
        summary = self.cache.get(
            self.repo_root / "data" / "runs" / run_id / "reports" / "run_summary.json"
        )
        if summary is None:
            return self._json_response({"error": "run_not_found"}, status=404)
        return self._json_with_etag(summary.data, summary.etag, headers)

    def _opportunities(self, params: Dict[str, str], headers: Mapping[str, str]) -> Response:
        proj = self.cache.get(self.repo_root / _ARTIFACT_FAMILIES["run_summary"])
        items: list = []
        if proj is not None and isinstance(proj.data, dict):
            metrics = proj.data.get("metrics") or {}
            raw = proj.data.get("opportunities") or metrics.get("opportunities") or []
            if isinstance(raw, list):
                items = raw
        offset = _bounded_int(params.get("offset"), default=0, lo=0, hi=10**9)
        limit = _bounded_int(params.get("limit"), default=100, lo=1, hi=_MAX_LIMIT)
        page = items[offset:offset + limit]
        body = {
            "items": page,
            "offset": offset,
            "limit": limit,
            "total": len(items),
        }
        return self._json_with_etag(body, proj.etag if proj else None, headers)

    def _artifact(self, route: str, headers: Mapping[str, str]) -> Response:
        # /v1/artifacts/{family}/latest
        parts = route.split("/")
        if len(parts) != 5 or parts[-1] != "latest":
            return self._json_response({"error": "not_found"}, status=404)
        family = parts[3]
        rel = _ARTIFACT_FAMILIES.get(family)
        if rel is None:
            return self._json_response(
                {"error": "unknown_artifact_family", "known": sorted(_ARTIFACT_FAMILIES)},
                status=404,
            )
        proj = self.cache.get(self.repo_root / rel)
        if proj is None:
            return self._json_response({"error": "artifact_missing"}, status=404)
        return self._json_with_etag(proj.data, proj.etag, headers)

    def _metrics(self) -> Response:
        cache_stats = self.cache.stats()
        lines = [
            "# HELP arby_api_requests_total Requests by route",
            "# TYPE arby_api_requests_total counter",
        ]
        for route, count in sorted(self.request_counts.items()):
            safe = route.replace('"', "")
            lines.append(f'arby_api_requests_total{{route="{safe}"}} {count}')
        lines += [
            "# HELP arby_api_projection_cache_entries Cached projections",
            "# TYPE arby_api_projection_cache_entries gauge",
            f"arby_api_projection_cache_entries {cache_stats['entries']}",
            "# HELP arby_api_projection_cache_hits_total Projection cache hits",
            "# TYPE arby_api_projection_cache_hits_total counter",
            f"arby_api_projection_cache_hits_total {cache_stats['hits']}",
            "# HELP arby_api_projection_cache_misses_total Projection cache misses",
            "# TYPE arby_api_projection_cache_misses_total counter",
            f"arby_api_projection_cache_misses_total {cache_stats['misses']}",
        ]
        body = ("\n".join(lines) + "\n").encode("utf-8")
        return 200, dict(_PROMETHEUS_HEADERS), body

    # -- helpers ----------------------------------------------------------------

    def _json_response(self, body: Any, *, status: int = 200, etag: Optional[str] = None) -> Response:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = dict(_JSON_HEADERS)
        if etag:
            headers["ETag"] = etag
        return status, headers, raw

    def _json_with_etag(
        self,
        body: Any,
        etag: Optional[str],
        request_headers: Mapping[str, str],
    ) -> Response:
        if etag:
            inm = request_headers.get("If-None-Match") or request_headers.get("if-none-match")
            if inm and etag in inm:
                return 304, {"ETag": etag}, b""
        return self._json_response(body, etag=etag)


def _bounded_int(raw: Optional[str], *, default: int, lo: int, hi: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))
