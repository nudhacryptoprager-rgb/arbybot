"""HTTP-level tests for legacy dashboard M_control cache + ETag."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer


def test_control_funnel_etag_and_cache_reuse(tmp_path, monkeypatch):
    import api.control_cache as control_cache_mod
    import monitoring.dashboard_server as ds
    from api.control_cache import get_control_projection_cache

    control_cache_mod._CACHE_SINGLETON = None

    (tmp_path / "data/tmp").mkdir(parents=True)
    (tmp_path / "data/runs/_rolling").mkdir(parents=True)
    (tmp_path / "data/tmp/m9_bridge_inventory_production_latest.json").write_text(
        json.dumps({"session_id": "sess_http", "fresh_long_tail_quote_ready_tokens": 0}),
        encoding="utf-8",
    )
    (tmp_path / "data/tmp/m9_capacity_cycle_diagnostic_latest.json").write_text(
        json.dumps({"capacity_valid_cycle_ids": [], "session_id": "sess_http"}),
        encoding="utf-8",
    )
    (tmp_path / "data/tmp/m9_shadow_capacity_smoke.json").write_text(
        json.dumps(
            {
                "cycles_found": 3,
                "cycles_quoteable": 0,
                "runner_outcome": "NO_SHADOW_TARGET_UNIVERSE",
                "quote_size_truth": {"econ_rpc_quote_attempts": 0},
                "run_context": {"session_id": "sess_http"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "data/tmp/start_pipeline_current.json").write_text(
        json.dumps({"shadow_artifact_path": "data/tmp/m9_shadow_capacity_smoke.json"}),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    get_control_projection_cache(".")._funnel_ts = 0.0

    server = HTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/api/control/funnel"
        req1 = urllib.request.Request(url)
        with urllib.request.urlopen(req1, timeout=5) as resp1:
            assert resp1.status == 200
            etag = resp1.headers.get("ETag")
            body1 = json.loads(resp1.read().decode("utf-8"))
        assert body1.get("shadow_source_path") == "data/tmp/m9_shadow_capacity_smoke.json"

        req2 = urllib.request.Request(url, headers={"If-None-Match": etag or ""})
        try:
            urllib.request.urlopen(req2, timeout=5)
            assert False, "expected HTTP 304"
        except urllib.error.HTTPError as exc:
            assert exc.code == 304

        cache = get_control_projection_cache(".")
        assert cache._funnel is not None
        _, etag2 = cache.funnel()
        assert etag2 == etag
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        control_cache_mod._CACHE_SINGLETON = None
