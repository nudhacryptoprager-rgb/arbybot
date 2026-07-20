"""Read-only API application — pure request handler (transport-agnostic).

Endpoints (all GET, all read-only):

* ``/health/live``   — liveness probe (no artifact checks)
* ``/health/ready``  — readiness: canonical rolling artifacts present
* ``/v1/pipeline``   — pipeline control-plane state (current + checkpoints)
* ``/v1/runs/{id}``  — run summary for one runDir (path-traversal safe)
* ``/v1/opportunities`` — latest opportunities/signals with pagination
* ``/v1/artifacts/{family}/latest`` — canonical artifact by family allowlist
* ``/metrics``       — Prometheus text exposition (cache + request stats)

Conditional requests: every JSON response carries ``ETag``; a matching
``If-None-Match`` yields ``304 Not Modified``.

This module is transport-agnostic: ``ApiApp.handle`` returns
``(status, headers, body_bytes)``; ``api.server`` adapts it to HTTP.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union

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
}

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")

_MAX_LIMIT = 500


class ApiApp:
    """Read-only API over materialized projections."""

    def __init__(
        self,
        repo_root: Union[str, Path] = ".",
        *,
        cache: Optional[ProjectionCache] = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.cache = cache or ProjectionCache()
        self.request_counts: Dict[str, int] = {}

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
        self.request_counts[route] = self.request_counts.get(route, 0) + 1

        if route == "/health/live":
            return self._json_response({"status": "alive"})
        if route == "/health/ready":
            return self._ready()
        if route == "/v1/pipeline":
            return self._pipeline(headers)
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
        required = ["run_summary", "sniper", "m4_stability"]
        missing = [
            fam for fam in required if self.cache.get(self.repo_root / _ARTIFACT_FAMILIES[fam]) is None
        ]
        body = {"status": "ready" if not missing else "not_ready", "missing": missing}
        return self._json_response(body, status=200 if not missing else 503)

    def _pipeline(self, headers: Mapping[str, str]) -> Response:
        proj = self.cache.get(self.repo_root / _ARTIFACT_FAMILIES["pipeline_current"])
        body = proj.data if proj is not None else {"status": "idle"}
        return self._json_with_etag(body, proj.etag if proj else None, headers)

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
