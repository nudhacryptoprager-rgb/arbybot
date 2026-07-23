"""Unit tests for the read-only API (projections, ETag, pagination, safety)."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from api.app import ApiApp
from api.projections import ProjectionCache


_NOW_ISO = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "data/runs/_rolling").mkdir(parents=True)
    (tmp_path / "data/tmp").mkdir(parents=True)
    (tmp_path / "data/runs/_rolling/run_summary_latest.json").write_text(
        json.dumps(
            {
                "metrics": {"signals_count": 2},
                "opportunities": [{"id": i} for i in range(5)],
                "quality_status": "PASS",
                "generated_at_utc": _NOW_ISO,
            }
        ),
        encoding="utf-8",
    )
    # Step 8 fixture upgrade: write a *real* sniper artifact with proper
    # schema_family + required top-level fields + recent_events + recent_events_by_dex.
    # The previous stub {status:"ACTIVE"} was exactly the wrong-shaped input
    # the corrected /health/ready is now designed to reject.
    sniper_artifact = {
        "schema_family": "m8_sniper",
        "schema_revision": "phase2.0",
        "generated_at_utc": _NOW_ISO,
        "source": "test_fixture",
        "freshness_s": 0.0,
        "status": "ACTIVE",
        "reasons": [],
        "metrics": {
            "pool_creation_events_seen": 2,
            "pool_creation_events_filtered_out": 0,
            "honeypot_check_pass": 0,
            "honeypot_check_fail": 0,
            "snipe_candidates_total": 2,
        },
        "recent_events": [
            {
                "event_id": "e1",
                "pool_address": "0x" + "a" * 40,
                "pool": "0x" + "a" * 40,
            },
            {
                "event_id": "e2",
                "pool_address": "0x" + "b" * 40,
                "pool": "0x" + "b" * 40,
            },
        ],
        "recent_events_by_dex": {"uniswap_v4": [{"event_id": "e1"}]},
        "self_test_by_dex": {"uniswap_v4": {"status": "PASS"}},
        "m8_health": {"goal_status": "REACHED"},
    }
    (tmp_path / "data/runs/_rolling/new_pool_sniper_latest.json").write_text(
        json.dumps(sniper_artifact), encoding="utf-8"
    )
    (tmp_path / "data/runs/_rolling/m4_stability_agg.json").write_text(
        json.dumps({"agg_status": "PASS", "generated_at_utc": _NOW_ISO}),
        encoding="utf-8",
    )
    return tmp_path


def _json(resp):
    return json.loads(resp[2].decode("utf-8"))


def test_health_live(repo):
    app = ApiApp(repo)
    status, _, body = app.handle("GET", "/health/live")
    assert status == 200 and _json((status, _, body))["status"] == "alive"


def test_health_ready_and_not_ready(repo, tmp_path):
    app = ApiApp(repo)
    status, _, body = app.handle("GET", "/health/ready")
    assert status == 200 and _json((status, _, body))["status"] == "ready"
    empty = ApiApp(tmp_path / "empty")
    status2, _, body2 = empty.handle("GET", "/health/ready")
    assert status2 == 503
    assert "run_summary" in _json((status2, _, body2))["missing"]


def test_health_ready_rejects_stub_sniper(tmp_path):
    """Step 8 fix regression: a stub sniper (0xabc placeholder) must NOT
    be treated as ready even if run_summary / m4_stability are valid."""
    (tmp_path / "data/runs/_rolling").mkdir(parents=True)
    fresh = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "data/runs/_rolling/run_summary_latest.json").write_text(
        json.dumps({"quality_status": "PASS", "generated_at_utc": fresh}),
        encoding="utf-8",
    )
    (tmp_path / "data/tmp").mkdir(parents=True)
    (tmp_path / "data/runs/_rolling/new_pool_sniper_latest.json").write_text(
        json.dumps(
            {
                "status": "ACTIVE",
                "recent_events": [
                    {"event_id": "stub", "pool_address": "0xabc"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "data/runs/_rolling/m4_stability_agg.json").write_text(
        json.dumps({"agg_status": "PASS", "generated_at_utc": fresh}),
        encoding="utf-8",
    )
    app = ApiApp(tmp_path)
    status, _, body = app.handle("GET", "/health/ready")
    assert status == 503
    data = _json((status, _, body))
    assert data["status"] == "not_ready"
    assert "SNIPER_STUB_PLACEHOLDER_POOL" in data.get("critical_blockers", []) or any(
        "SNIPER" in b for b in data.get("critical_blockers", [])
    )


def test_health_ready_rejects_stale_sniper(tmp_path):
    """A sniper artifact whose timestamp is older than 30 minutes must
    not be treated as ready, even with a valid schema."""
    (tmp_path / "data/runs/_rolling").mkdir(parents=True)
    (tmp_path / "data/tmp").mkdir(parents=True)
    fresh = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    (tmp_path / "data/runs/_rolling/run_summary_latest.json").write_text(
        json.dumps({"quality_status": "PASS", "generated_at_utc": fresh}),
        encoding="utf-8",
    )
    (tmp_path / "data/runs/_rolling/new_pool_sniper_latest.json").write_text(
        json.dumps(
            {
                "schema_family": "m8_sniper",
                "schema_revision": "phase2.0",
                "generated_at_utc": stale,
                "source": "test",
                "freshness_s": 7200.0,
                "status": "STALE",
                "reasons": ["STALE"],
                "metrics": {
                    "pool_creation_events_seen": 0,
                    "pool_creation_events_filtered_out": 0,
                    "honeypot_check_pass": 0,
                    "honeypot_check_fail": 0,
                    "snipe_candidates_total": 0,
                },
                "recent_events": [],
                "recent_events_by_dex": {},
                "m8_health": {"goal_status": "STALE"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "data/runs/_rolling/m4_stability_agg.json").write_text(
        json.dumps({"agg_status": "PASS", "generated_at_utc": fresh}),
        encoding="utf-8",
    )
    app = ApiApp(tmp_path)
    status, _, body = app.handle("GET", "/health/ready")
    assert status == 503
    data = _json((status, _, body))
    assert data["status"] == "not_ready"
    assert "SNIPER_STALE" in data.get("critical_blockers", [])


def test_health_ready_reports_runtime_truth_blocker_advisory(tmp_path):
    """When runtime_truth_gate is BLOCKED, /health/ready surfaces it as a
    critical blocker (advisory) so operators see why M9 shadow has not
    started, while the rest of the dashboard is still usable."""
    (tmp_path / "data/runs/_rolling").mkdir(parents=True)
    (tmp_path / "data/tmp").mkdir(parents=True)
    fresh = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "data/runs/_rolling/run_summary_latest.json").write_text(
        json.dumps({"quality_status": "PASS", "generated_at_utc": fresh}),
        encoding="utf-8",
    )
    (tmp_path / "data/runs/_rolling/new_pool_sniper_latest.json").write_text(
        json.dumps(
            {
                "schema_family": "m8_sniper",
                "schema_revision": "phase2.0",
                "generated_at_utc": fresh,
                "source": "test",
                "freshness_s": 0.0,
                "status": "ACTIVE",
                "reasons": [],
                "metrics": {
                    "pool_creation_events_seen": 1,
                    "pool_creation_events_filtered_out": 0,
                    "honeypot_check_pass": 0,
                    "honeypot_check_fail": 0,
                    "snipe_candidates_total": 1,
                },
                "recent_events": [{"event_id": "e1", "pool_address": "0x" + "a" * 40}],
                "recent_events_by_dex": {"uniswap_v4": [{"event_id": "e1"}]},
                "m8_health": {"goal_status": "REACHED"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "data/runs/_rolling/m4_stability_agg.json").write_text(
        json.dumps({"agg_status": "PASS", "generated_at_utc": fresh}),
        encoding="utf-8",
    )
    (tmp_path / "data/tmp/m8_m9_runtime_truth_gate_latest.json").write_text(
        json.dumps(
            {
                "truth_status": "BLOCKED",
                "blocker_class": "CODE_ARTIFACT_CONTRACT",
                "blockers": ["SNIPER_STALE"],
            }
        ),
        encoding="utf-8",
    )
    app = ApiApp(tmp_path)
    status, _, body = app.handle("GET", "/health/ready")
    # BLOCKED truth -> not ready overall (the bundle is incoherent).
    assert status == 503
    data = _json((status, _, body))
    assert "M9_RUNTIME_TRUTH_BLOCKED" in data.get("critical_blockers", [])


def test_artifact_family_latest_and_etag(repo):
    app = ApiApp(repo)
    status, headers, body = app.handle("GET", "/v1/artifacts/sniper/latest")
    assert status == 200
    etag = headers.get("ETag")
    assert etag and etag.startswith('W/"')
    # Conditional request -> 304
    status2, headers2, body2 = app.handle(
        "GET", "/v1/artifacts/sniper/latest", {"If-None-Match": etag}
    )
    assert status2 == 304 and body2 == b""


def test_artifact_unknown_family_and_missing(repo, tmp_path):
    app = ApiApp(repo)
    status, _, body = app.handle("GET", "/v1/artifacts/ghost/latest")
    assert status == 404
    assert "known" in _json((status, _, body))
    status2, _, _ = app.handle("GET", "/v1/artifacts/m9_bridge/latest")
    assert status2 == 404  # not written in fixture repo


def test_opportunities_pagination(repo):
    app = ApiApp(repo)
    status, _, body = app.handle("GET", "/v1/opportunities?offset=2&limit=2")
    data = _json((status, _, body))
    assert status == 200
    assert data["total"] == 5
    assert [i["id"] for i in data["items"]] == [2, 3]
    # limit clamped
    status2, _, body2 = app.handle("GET", "/v1/opportunities?limit=99999")
    assert _json((status2, _, body2))["limit"] == 500


def test_run_summary_and_traversal_guard(repo):
    run_dir = repo / "data/runs/test_run_1/reports"
    run_dir.mkdir(parents=True)
    (run_dir / "run_summary.json").write_text('{"ok": true}', encoding="utf-8")
    app = ApiApp(repo)
    status, _, body = app.handle("GET", "/v1/runs/test_run_1")
    assert status == 200 and _json((status, _, body))["ok"] is True
    status2, _, _ = app.handle("GET", "/v1/runs/..%2F..%2Fetc")
    assert status2 == 400
    status3, _, _ = app.handle("GET", "/v1/runs/nonexistent_run")
    assert status3 == 404


def test_pipeline_idle_when_missing(repo):
    app = ApiApp(repo)
    status, _, body = app.handle("GET", "/v1/pipeline")
    assert status == 200 and _json((status, _, body))["status"] == "idle"


def test_metrics_prometheus_format(repo):
    app = ApiApp(repo)
    app.handle("GET", "/health/live")
    status, headers, body = app.handle("GET", "/metrics")
    text = body.decode("utf-8")
    assert status == 200
    assert "arby_api_requests_total" in text
    assert 'route="/health/live"' in text


def test_method_not_allowed(repo):
    app = ApiApp(repo)
    status, _, _ = app.handle("POST", "/health/live")
    assert status == 405


# ---------------------------------------------------------------------------
# ProjectionCache
# ---------------------------------------------------------------------------


def test_projection_cache_revalidates_on_change(tmp_path):
    path = tmp_path / "a.json"
    path.write_text('{"v": 1}', encoding="utf-8")
    cache = ProjectionCache()
    first = cache.get(path)
    assert first is not None and first.data["v"] == 1
    # Same file: served from cache.
    second = cache.get(path)
    assert second is first and cache.hits == 1
    # Changed content with bumped mtime: re-read exactly once.
    path.write_text('{"v": 2}', encoding="utf-8")
    new_mtime = first.mtime + 10
    import os

    os.utime(path, (new_mtime, new_mtime))
    third = cache.get(path)
    assert third is not first and third.data["v"] == 2
    assert cache.misses == 2


def test_projection_cache_missing_and_invalid(tmp_path):
    cache = ProjectionCache()
    assert cache.get(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert cache.get(bad) is None


# ---------------------------------------------------------------------------
# Step 8 — thread-safe metrics for ThreadingHTTPServer
# ---------------------------------------------------------------------------


def test_request_counter_is_thread_safe():
    """ThreadingHTTPServer runs handle() on worker threads; the per-route
    request counter must not lose or duplicate increments under concurrent
    requests."""
    import threading

    app = ApiApp(repo_root=".")
    n_workers = 16
    reps = 50

    def _hit():
        for _ in range(reps):
            app.handle("GET", "/health/live")

    threads = [threading.Thread(target=_hit) for _ in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert app.request_counts["/health/live"] == n_workers * reps


def test_projection_cache_hits_misses_thread_safe(tmp_path):
    """The hits/misses counters must survive concurrent get() calls without
    losing updates. Under concurrency every thread that misses the very
    first cache lookup will fall through to file I/O and insert; this is
    correct behavior — the lock only guarantees the counter updates are
    not lost, not that exactly one miss is recorded.
    """
    import threading

    path = tmp_path / "shared.json"
    path.write_text('{"v": 1}', encoding="utf-8")
    cache = ProjectionCache()
    n_workers = 8
    reps = 25

    def _read():
        for _ in range(reps):
            assert cache.get(path) is not None

    threads = [threading.Thread(target=_read) for _ in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Invariant under concurrency: hits + misses == total successful get() calls.
    assert cache.hits + cache.misses == n_workers * reps
    assert cache.misses >= 1
    assert cache.hits >= 1
