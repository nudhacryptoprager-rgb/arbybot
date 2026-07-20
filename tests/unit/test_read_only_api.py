"""Unit tests for the read-only API (projections, ETag, pagination, safety)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from api.app import ApiApp
from api.projections import ProjectionCache


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "data/runs/_rolling").mkdir(parents=True)
    (tmp_path / "data/tmp").mkdir(parents=True)
    (tmp_path / "data/runs/_rolling/run_summary_latest.json").write_text(
        json.dumps({"metrics": {"signals_count": 2}, "opportunities": [{"id": i} for i in range(5)]}),
        encoding="utf-8",
    )
    (tmp_path / "data/runs/_rolling/new_pool_sniper_latest.json").write_text(
        json.dumps({"status": "ACTIVE"}), encoding="utf-8"
    )
    (tmp_path / "data/runs/_rolling/m4_stability_agg.json").write_text(
        json.dumps({"agg_status": "PASS"}), encoding="utf-8"
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
