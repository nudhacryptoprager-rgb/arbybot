"""Integration-style tests for streaming orchestration and related contracts."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from core.pipeline_slo import PipelineSloTracker
from core.pipeline_streaming import (
    m81_streaming_cli_args,
    resolve_streaming_batch_paths,
    sanitize_session_id,
)
from core.quote_lane_limiter import QuoteLaneLimiter
from m8.discovery.mirror_quote_cache import mirror_quote_cache_key
from m8.discovery.streaming_handoff import (
    detect_streaming_force_rerun_conflict,
    sniper_content_fingerprint,
    validate_force_rerun_streaming_session,
    validate_streaming_handoff,
    write_streaming_batch_manifest,
)
from m8_1.stable_anchor.quote_negative_cache import (
    PersistentQuoteNegativeCache,
    quote_cache_key,
)
from monitoring.bridge_content_hash import bridge_inventory_content_hash
from monitoring.runtime_truth_gate import evaluate_runtime_truth_gate
from start import (
    build_project_pipeline_steps,
    resolve_pipeline_session_id,
    validate_pipeline_session_cli_args,
)


def _fake_args(**overrides):
    class NS:
        pipeline = "m8_m9"
        streaming = True
        sniper_minutes = 45
        sniper_batch_minutes = 15
        token_concurrency = 4
        skip_coingecko = True
        skip_shadow = True
        skip_preflight = True
        max_radar_tokens = 100
        new_session = False
        resume_session = None
        force_rerun_steps = False
        dry_run = False
        pipeline_log = "data/tmp/start_pipeline_latest.log"
        resume_from = None
        allow_roadmap_edit = False
        heartbeat_stale_minutes = 15

    ns = NS()
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def test_streaming_plan_three_batches_with_full_handoff():
    steps = build_project_pipeline_steps(_fake_args())
    names = [s["name"] for s in steps]
    for idx in (1, 2, 3):
        assert f"m8_sniper_acceptance_batch_{idx}" in names
        assert f"m8_streaming_batch_manifest_{idx}" in names
        assert f"m8_1_stable_anchor_batch_{idx}" in names
        assert f"m8_2_radar_two_phase_batch_{idx}" in names
        assert f"m8_2_cross_dex_expand_batch_{idx}" in names
        assert f"m8_3_registry_refresh_batch_{idx}" in names
        assert f"m8_m9_runtime_truth_gate_upstream_batch_{idx}" in names
    assert "m8_2_radar_two_phase" not in names
    m81 = next(s for s in steps if s["name"] == "m8_1_stable_anchor_batch_2")
    joined = " ".join(m81["cmd"])
    assert "--streaming-batch-index" in joined
    assert "2" in joined


def test_streaming_lane_acceptance_uses_final_batch_artifacts(monkeypatch):
    from core.batch_path_resolver import resolve_streaming_step_cmd

    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", "session-final-batch")
    monkeypatch.setenv("ARBY_STREAMING_FINAL_BATCH_INDEX", "3")
    steps = build_project_pipeline_steps(_fake_args())
    names = [s["name"] for s in steps]
    assert "m8_2_acceptance_final_batch" in names
    lane = next(s for s in steps if s["name"] == "m9_lane_acceptance")
    joined = " ".join(resolve_streaming_step_cmd(lane, list(lane["cmd"])))
    assert "m8_2_acceptance_report.json" in joined
    assert "batch_3" in joined
    assert "--skip-shadow" in joined
    assert "m8_2_acceptance_report_latest.json" not in joined


def test_streaming_shadow_before_final_m82_acceptance(monkeypatch):
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", "session-final-batch")
    monkeypatch.setenv("ARBY_STREAMING_FINAL_BATCH_INDEX", "3")
    steps = build_project_pipeline_steps(_fake_args(skip_shadow=False))
    names = [s["name"] for s in steps]
    assert names.index("m9_shadow_10m") < names.index("m8_2_acceptance_final_batch")


def test_final_m82_acceptance_allows_shadow(tmp_path, monkeypatch):
    from core.pipeline_streaming import final_m82_acceptance_allows_shadow

    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", "session-m82-gate")
    monkeypatch.setenv("ARBY_STREAMING_FINAL_BATCH_INDEX", "1")
    paths = resolve_streaming_batch_paths(1)
    paths.batch_dir.mkdir(parents=True, exist_ok=True)
    paths.m82_acceptance.write_text(
        '{"goal_status":"REACHED","handoff_ready":true}',
        encoding="utf-8",
    )
    assert final_m82_acceptance_allows_shadow() is True
    paths.m82_acceptance.write_text(
        '{"goal_status":"BLOCKED","handoff_ready":false}',
        encoding="utf-8",
    )
    assert final_m82_acceptance_allows_shadow() is False


def test_streaming_paths_are_session_namespaced(monkeypatch):
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", "2026-07-23T12:00:00Z")
    paths = resolve_streaming_batch_paths(2)
    assert sanitize_session_id("2026-07-23T12:00:00Z") in str(paths.batch_dir)
    assert paths.manifest.name == "manifest.json"
    assert paths.m81_output.name == "m8_1_stable_anchor.json"
    assert paths.m82_hints.name == "m8_external_pool_hints.json"
    assert paths.m83_registry.name == "m8_3_token_metadata_registry.json"
    assert paths.m82_checkpoint_secondary.name == "m8_hint_refresh_checkpoint_secondary.json"


def test_final_m9_commands_use_batch_expansion_not_rolling(monkeypatch):
    from core.batch_path_resolver import (
        ROLLING_EXPANSION_PATH,
        resolve_streaming_step_cmd,
    )

    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", "session-final-batch")
    monkeypatch.setenv("ARBY_STREAMING_FINAL_BATCH_INDEX", "3")
    steps = build_project_pipeline_steps(_fake_args())
    for step_name in ("m9_bridge_production", "m9_bridge_curve_probe_for_indices"):
        step = next(s for s in steps if s["name"] == step_name)
        cmd = resolve_streaming_step_cmd(step, list(step["cmd"]))
        joined = " ".join(cmd)
        assert ROLLING_EXPANSION_PATH not in joined
        assert "m8_cross_dex_expansion.json" in joined
        assert "batch_3" in joined
    bundle = next(s for s in steps if s["name"] == "m8_m9_runtime_truth_gate_bundle")
    bundle_cmd = resolve_streaming_step_cmd(bundle, list(bundle["cmd"]))
    assert ROLLING_EXPANSION_PATH not in " ".join(bundle_cmd)
    assert "m8_cross_dex_expansion.json" in " ".join(bundle_cmd)


def test_m81_streaming_cli_uses_batch_index():
    args = m81_streaming_cli_args(batch_index=3)
    assert "--streaming-batch-index" in args
    assert "3" in args
    assert "--publish-rolling" in args


def test_streaming_manifest_blocks_fingerprint_mismatch(tmp_path: Path):
    sniper = tmp_path / "sniper.json"
    sniper.write_text(json.dumps({"recent_events": []}), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    write_streaming_batch_manifest(
        session_id="session-a",
        batch_index=1,
        batch_minutes=15,
        sniper_artifact=str(sniper),
        output_path=tmp_path / "latest.json",
        immutable_path=manifest_path,
        token_subset_path=tmp_path / "subset.json",
    )
    sniper.write_text(json.dumps({"recent_events": [{"token0": "0x" + "1" * 40}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="SNIPER_FINGERPRINT_MISMATCH"):
        validate_streaming_handoff(manifest_path, expected_session_id="session-a")


def test_immutable_manifest_collision(tmp_path: Path):
    sniper = tmp_path / "sniper.json"
    sniper.write_text(json.dumps({"recent_events": []}), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    write_streaming_batch_manifest(
        session_id="session-a",
        batch_index=1,
        batch_minutes=15,
        sniper_artifact=str(sniper),
        immutable_path=manifest_path,
        token_subset_path=tmp_path / "subset.json",
    )
    with pytest.raises(ValueError, match="IMMUTABLE_MANIFEST_COLLISION"):
        write_streaming_batch_manifest(
            session_id="session-b",
            batch_index=1,
            batch_minutes=15,
            sniper_artifact=str(sniper),
            immutable_path=manifest_path,
            token_subset_path=tmp_path / "subset2.json",
        )


def test_streaming_manifest_resume_is_idempotent(tmp_path: Path, monkeypatch):
    sniper = tmp_path / "sniper.json"
    sniper.write_text(json.dumps({"recent_events": []}), encoding="utf-8")
    session_id = "session-resume"
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", session_id)
    monkeypatch.setattr(
        "core.pipeline_streaming.STREAMING_ROOT_DIR",
        tmp_path / "streaming_batches",
    )
    manifest_path = (
        tmp_path / "streaming_batches" / session_id / "batch_1" / "manifest.json"
    )
    write_streaming_batch_manifest(
        session_id=session_id,
        batch_index=1,
        batch_minutes=15,
        sniper_artifact=str(sniper),
        immutable_path=manifest_path,
    )
    sniper.write_text(json.dumps({"recent_events": [{"token0": "0x" + "9" * 40}]}), encoding="utf-8")
    second = write_streaming_batch_manifest(
        session_id=session_id,
        batch_index=1,
        batch_minutes=15,
        sniper_artifact=str(sniper),
        immutable_path=manifest_path,
    )
    assert second == json.loads(manifest_path.read_text(encoding="utf-8"))
    assert second["sniper_input_fingerprint"] != sniper_content_fingerprint(str(sniper))


def test_streaming_batch_fingerprint_uses_manifest_not_rolling(monkeypatch, tmp_path: Path):
    from application.checkpoint_store import fingerprint_paths
    from start import _pipeline_step_fingerprint

    session_id = "session-fp"
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", session_id)
    monkeypatch.setattr(
        "core.pipeline_streaming.STREAMING_ROOT_DIR",
        tmp_path / "streaming_batches",
    )
    sniper = tmp_path / "sniper.json"
    sniper.write_text(json.dumps({"recent_events": []}), encoding="utf-8")
    manifest_path = (
        tmp_path / "streaming_batches" / session_id / "batch_1" / "manifest.json"
    )
    write_streaming_batch_manifest(
        session_id=session_id,
        batch_index=1,
        batch_minutes=15,
        sniper_artifact=str(sniper),
        immutable_path=manifest_path,
    )
    fp_before = _pipeline_step_fingerprint("m8_sniper_acceptance_batch_1")
    sniper.write_text(json.dumps({"recent_events": [{"token0": "0x" + "2" * 40}]}), encoding="utf-8")
    fp_after = _pipeline_step_fingerprint("m8_sniper_acceptance_batch_1")
    assert fp_before == fp_after == fingerprint_paths([manifest_path])


def test_quote_cache_key_isolates_quoter():
    base = {
        "route_id": "curve:poolA",
        "token_in": "0x" + "a" * 40,
        "token_out": "0x" + "b" * 40,
        "size_usd": 50.0,
        "fee": 0,
    }
    k1 = quote_cache_key(**base, quoter="0x" + "1" * 40)
    k2 = quote_cache_key(**base, quoter="0x" + "2" * 40)
    assert k1 != k2


def test_mirror_cache_key_includes_direction_amount_bucket():
    k1 = mirror_quote_cache_key(
        route_id="r1",
        direction="0xa->0xb",
        amount_wei=10**15,
        block_bucket="100",
    )
    k2 = mirror_quote_cache_key(
        route_id="r1",
        direction="0xb->0xa",
        amount_wei=10**15,
        block_bucket="100",
    )
    assert k1 != k2


def test_quote_lane_limiter_splits_metrics():
    limiter = QuoteLaneLimiter(max_concurrent=1, timeout_s=2.0, max_retries=1)

    def _work() -> int:
        time.sleep(0.01)
        return 1

    assert limiter.call("http://rpc", _work) == 1
    stats = limiter.stats()
    assert stats["queue_wait_s"] >= 0.0
    assert stats["rpc_service_s"] >= 0.0


def test_post_depth_gate_recomputes_bridge_hash():
    from monitoring.sniper_artifacts import make_sniper_artifact

    ts = "2026-07-23T10:00:00Z"
    sniper = make_sniper_artifact(
        metrics={"pool_creation_events_seen": 5},
        status="ACTIVE",
        reasons=[],
        generated_at_utc=ts,
        recent_events=[
            {"event_id": "e1", "pool_address": "0x" + "a" * 40, "pool": "0x" + "a" * 40},
            {"event_id": "e2", "pool_address": "0x" + "b" * 40, "pool": "0x" + "b" * 40},
        ],
        recent_events_by_dex={"uniswap_v4": [{"event_id": "e1"}]},
        self_test_by_dex={"uniswap_v4": {"status": "PASS"}},
    )
    sniper["m8_health"] = {"goal_status": "REACHED"}
    sid = "session-x"
    sniper["run_context"] = {"session_id": sid, "run_timestamp": ts}
    upstream = {"run_context": {"session_id": sid, "run_timestamp": ts}}
    bridge_body = {"active_routes": [], "run_context": {"session_id": sid, "run_timestamp": ts}}
    post_hash = bridge_inventory_content_hash(bridge_body)
    bridge = dict(bridge_body)
    bridge["depth_enrichment"] = {
        "pre_depth_content_hash": "pre",
        "post_depth_content_hash": post_hash,
        "depth_enriched_at_utc": "2026-07-23T10:05:00Z",
        "depth_enrichment_session_id": sid,
    }
    gate_now = datetime(2026, 7, 23, 10, 5, 0, tzinfo=timezone.utc)
    verdict = evaluate_runtime_truth_gate(
        sniper=sniper,
        anchor=upstream,
        hints=upstream,
        expansion=upstream,
        m8_3_registry=upstream,
        bridge=bridge,
        phase="post_depth",
        now=gate_now,
    )
    assert verdict["truth_status"] == "PASS"

    bridge_bad = dict(bridge)
    bridge_bad["depth_enrichment"]["post_depth_content_hash"] = "deadbeef"
    verdict_bad = evaluate_runtime_truth_gate(
        sniper=sniper,
        anchor=upstream,
        hints=upstream,
        expansion=upstream,
        m8_3_registry=upstream,
        bridge=bridge_bad,
        phase="post_depth",
        now=gate_now,
    )
    assert "DEPTH_ENRICHMENT_HASH_MISMATCH" in verdict_bad["blockers"]


def test_slo_writes_on_failure(tmp_path: Path):
    tracker = PipelineSloTracker(path=tmp_path / "slo.json")
    t0 = time.monotonic()
    tracker.mark_failed("step_a", "exit=1")
    tracker.end_step("step_a", t0, 0.0, status="failed", failure_reason="exit=1")
    tracker.write(session_id="sess", pipeline_mode="m8_m9")
    doc = json.loads((tmp_path / "slo.json").read_text(encoding="utf-8"))
    assert doc["pipeline_status"] == "failed"


def test_slo_batch_work_duration_field(tmp_path: Path):
    tracker = PipelineSloTracker(path=tmp_path / "slo.json")
    t0 = time.monotonic()
    tracker.end_step("m8_sniper_acceptance_batch_1", t0, 0.0)
    tracker.write(session_id="sess", pipeline_mode="m8_m9")
    doc = json.loads((tmp_path / "slo.json").read_text(encoding="utf-8"))
    assert doc["schema_version"] == "pipeline_slo.4"
    assert "batch_work_duration_s" in doc
    assert "batch_wall_clock_s" not in doc
    assert "1" in doc["batch_work_duration_s"]


def test_m81_deadline_respects_wall_clock():
    from scripts.m8_1_stable_anchor_run import _probe_all
    from m8_1.stable_anchor.pairs import TokenInfo
    from m8_1.stable_anchor.pool_discovery import DexRoute

    class SlowW3:
        @property
        def eth(self):
            return self

        @property
        def block_number(self):
            return 1

    t0 = TokenInfo(symbol="USDC", address="0x" + "a" * 40, decimals=6)
    t1 = TokenInfo(symbol="WETH", address="0x" + "b" * 40, decimals=18)
    route = DexRoute(
        dex_id="uni",
        adapter_type="uniswap_v3",
        quoter="0x" + "c" * 40,
        fee=500,
        tick_spacing=None,
        curve_coin0_sym=None,
    )

    with patch("scripts.m8_1_stable_anchor_run._probe_one") as probe_mock:
        def _slow(*_a, **_k):
            time.sleep(0.2)
            return False, "QUOTE_REVERT", False

        probe_mock.side_effect = _slow
        wall_t0 = time.monotonic()
        deadline = time.time() + 0.05
        routes = [route] * 8
        _probe_all(
            SlowW3(),
            [(t0, t1)],
            routes,
            [50.0],
            deadline,
            async_max_workers=4,
        )
        elapsed = time.monotonic() - wall_t0
    assert elapsed < 0.35


def test_persistent_negative_cache_roundtrip(tmp_path: Path):
    path = tmp_path / "neg.json"
    cache = PersistentQuoteNegativeCache(path=path, ttl_s=60.0)
    key = quote_cache_key(
        route_id="dex:f500",
        quoter="0x" + "9" * 40,
        token_in="0x" + "a" * 40,
        token_out="0x" + "b" * 40,
        size_usd=50.0,
        fee=500,
    )
    cache.put(key, "QUOTE_REVERT")
    cache.flush()
    cache2 = PersistentQuoteNegativeCache(path=path, ttl_s=60.0)
    assert cache2.get(key) == "QUOTE_REVERT"


def test_force_rerun_reused_session_conflict_detected_before_sniper(tmp_path, monkeypatch):
    session_id = "2026-07-26T13:04:06Z"
    sniper_path = tmp_path / "sniper.json"
    sniper_path.write_text('{"candidates": [{"token0": "0x1"}]}', encoding="utf-8")
    monkeypatch.setattr(
        "m8.discovery.streaming_handoff.DEFAULT_SNIPER_ARTIFACT",
        str(sniper_path),
    )
    write_streaming_batch_manifest(
        session_id=session_id,
        batch_index=1,
        batch_minutes=15,
        sniper_artifact=str(sniper_path),
    )
    sniper_path.write_text('{"candidates": [{"token0": "0x2"}]}', encoding="utf-8")
    conflict = detect_streaming_force_rerun_conflict(session_id, [1], sniper_artifact=sniper_path)
    assert conflict is not None
    assert conflict.batch_index == 1
    with pytest.raises(ValueError, match="STREAMING_SESSION_REUSE_REQUIRES_NEW_SESSION"):
        validate_force_rerun_streaming_session(session_id, [1], sniper_artifact=sniper_path)


def test_new_session_ignores_env_and_produces_valid_handoff(tmp_path, monkeypatch):
    session_a = "session-a"
    sniper_path = tmp_path / "sniper.json"
    sniper_path.write_text('{"candidates": [{"token0": "0xabc"}]}', encoding="utf-8")
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", session_a)
    write_streaming_batch_manifest(
        session_id=session_a,
        batch_index=1,
        batch_minutes=15,
        sniper_artifact=str(sniper_path),
    )
    resolved = resolve_pipeline_session_id(_fake_args(new_session=True))
    assert resolved != session_a
    manifest = write_streaming_batch_manifest(
        session_id=resolved,
        batch_index=1,
        batch_minutes=15,
        sniper_artifact=str(sniper_path),
    )
    validate_streaming_handoff(
        resolve_streaming_batch_paths(1, session_id=resolved).manifest,
        expected_session_id=resolved,
    )
    assert manifest["session_id"] == resolved


def test_resume_session_rejects_force_rerun():
    class NS:
        new_session = False
        resume_session = "2026-07-26T13:04:06Z"
        force_rerun_steps = True

    assert validate_pipeline_session_cli_args(NS()) is not None


def test_pipeline_preflight_blocks_force_rerun_before_steps(tmp_path, monkeypatch):
    session_id = "2026-07-26T13:04:06Z"
    sniper_path = tmp_path / "sniper.json"
    sniper_path.write_text('{"candidates": [{"token0": "0x1"}]}', encoding="utf-8")
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", session_id)
    monkeypatch.setattr(
        "m8.discovery.streaming_handoff.DEFAULT_SNIPER_ARTIFACT",
        str(sniper_path),
    )
    write_streaming_batch_manifest(
        session_id=session_id,
        batch_index=1,
        batch_minutes=15,
        sniper_artifact=str(sniper_path),
    )
    from start import _run_project_pipeline

    args = _fake_args(force_rerun_steps=True, skip_preflight=True, dry_run=False)
    rc = _run_project_pipeline(args)
    assert rc == 2
    fail_text = Path("data/tmp/start_pipeline_latest.fail").read_text(encoding="utf-8")
    assert "STREAMING_SESSION_REUSE_REQUIRES_NEW_SESSION" in fail_text
    assert f"session_id={session_id}" in fail_text
