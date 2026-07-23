"""Integration-style tests for streaming orchestration and related contracts."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.pipeline_slo import PipelineSloTracker
from core.pipeline_streaming import m81_streaming_cli_args, resolve_streaming_batches
from core.quote_lane_limiter import QuoteLaneLimiter
from m8.discovery.mirror_quote_cache import mirror_quote_cache_key
from m8.discovery.streaming_handoff import (
    sniper_content_fingerprint,
    validate_streaming_handoff,
    write_streaming_batch_manifest,
)
from m8_1.stable_anchor.quote_negative_cache import (
    PersistentQuoteNegativeCache,
    quote_cache_key,
)
from monitoring.runtime_truth_gate import evaluate_runtime_truth_gate
from start import build_project_pipeline_steps


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

    ns = NS()
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def test_streaming_plan_three_batches_with_subset_and_manifest():
    steps = build_project_pipeline_steps(_fake_args())
    names = [s["name"] for s in steps]
    assert names.count("m8_sniper_acceptance_batch_1") == 1
    assert names.count("m8_sniper_acceptance_batch_2") == 1
    assert names.count("m8_sniper_acceptance_batch_3") == 1
    assert names.index("m8_streaming_batch_manifest_1") < names.index(
        "m8_1_stable_anchor_batch_1"
    )
    m81 = next(s for s in steps if s["name"] == "m8_1_stable_anchor_batch_2")
    joined = " ".join(m81["cmd"])
    assert "--token-subset-file" in joined
    assert "--streaming-manifest" in joined
    assert "fresh_delta" in joined


def test_resolve_streaming_batches_wired_to_forty_five_minutes():
    assert resolve_streaming_batches(45, batch_minutes=15) == [15, 15, 15]


def test_streaming_manifest_blocks_fingerprint_mismatch(tmp_path: Path):
    sniper = tmp_path / "sniper.json"
    sniper.write_text(json.dumps({"recent_events": []}), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    write_streaming_batch_manifest(
        session_id="session-a",
        batch_index=1,
        batch_minutes=15,
        sniper_artifact=str(sniper),
        output_path=manifest_path,
        immutable_path=manifest_path,
        token_subset_path=tmp_path / "subset.json",
    )
    sniper.write_text(json.dumps({"recent_events": [{"token0": "0x" + "1" * 40}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="SNIPER_FINGERPRINT_MISMATCH"):
        validate_streaming_handoff(manifest_path, expected_session_id="session-a")


def test_quote_cache_key_isolates_quoter():
    base = dict(
        route_id="curve:poolA",
        token_in="0x" + "a" * 40,
        token_out="0x" + "b" * 40,
        size_usd=50.0,
        fee=0,
    )
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


def test_quote_lane_limiter_serializes_calls():
    limiter = QuoteLaneLimiter(max_concurrent=1, timeout_s=2.0, max_retries=1)
    order: list[int] = []

    def _work(v: int) -> int:
        order.append(v)
        return v

    assert limiter.call("http://rpc", _work, 1) == 1
    assert limiter.call("http://rpc", _work, 2) == 2
    assert order == [1, 2]


def test_post_depth_gate_requires_depth_hashes():
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
    for doc in (sniper,):
        doc["run_context"] = {"session_id": sid, "run_timestamp": ts}
    upstream = {"run_context": {"session_id": sid, "run_timestamp": ts}}
    bridge = {
        "run_context": {"session_id": sid, "run_timestamp": ts},
        "generated_at_utc": ts,
        "depth_enrichment": {
            "pre_depth_content_hash": "abc",
            "post_depth_content_hash": "def",
            "depth_enriched_at_utc": "2026-07-23T10:05:00Z",
            "depth_enrichment_session_id": sid,
        },
    }
    verdict = evaluate_runtime_truth_gate(
        sniper=sniper,
        anchor=upstream,
        hints=upstream,
        expansion=upstream,
        m8_3_registry=upstream,
        bridge=bridge,
        phase="post_depth",
    )
    assert verdict["truth_status"] == "PASS"


def test_post_depth_gate_blocks_unchanged_hash():
    bridge = {
        "run_context": {
            "session_id": "session-x",
            "run_timestamp": "2026-07-23T10:00:00Z",
        },
        "depth_enrichment": {
            "pre_depth_content_hash": "same",
            "post_depth_content_hash": "same",
            "depth_enriched_at_utc": "2026-07-23T10:05:00Z",
            "depth_enrichment_session_id": "session-x",
        },
    }
    verdict = evaluate_runtime_truth_gate(
        sniper={"status": "ACTIVE", "recent_events": [{"token0": "0x" + "1" * 40, "token1": "0x" + "2" * 40}], "run_context": {"session_id": "session-x", "run_timestamp": "2026-07-23T10:00:00Z"}},
        anchor={"run_context": {"session_id": "session-x", "run_timestamp": "2026-07-23T10:00:00Z"}},
        hints={"run_context": {"session_id": "session-x", "run_timestamp": "2026-07-23T10:00:00Z"}},
        expansion={"run_context": {"session_id": "session-x", "run_timestamp": "2026-07-23T10:00:00Z"}},
        m8_3_registry={"run_context": {"session_id": "session-x", "run_timestamp": "2026-07-23T10:00:00Z"}},
        bridge=bridge,
        phase="post_depth",
    )
    assert "DEPTH_ENRICHMENT_HASH_UNCHANGED" in verdict["blockers"]


def test_slo_writes_on_failure(tmp_path: Path):
    tracker = PipelineSloTracker(path=tmp_path / "slo.json")
    t0 = time.monotonic()
    tracker.mark_failed("step_a", "exit=1")
    tracker.end_step("step_a", t0, 0.0, status="failed", failure_reason="exit=1")
    tracker.write(session_id="sess", pipeline_mode="m8_m9")
    doc = json.loads((tmp_path / "slo.json").read_text(encoding="utf-8"))
    assert doc["pipeline_status"] == "failed"
    assert doc["failure_step"] == "step_a"
    assert doc["steps"][0]["status"] == "failed"


def test_m81_deadline_cancels_pending_tasks():
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
        deadline = time.time() + 0.15
        routes = [route] * 8
        _, metrics = _probe_all(
            SlowW3(),
            [(t0, t1)],
            routes,
            [50.0],
            deadline,
            async_max_workers=4,
        )
    assert metrics["stable_anchor_candidates_total"] < 8


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
    cache2 = PersistentQuoteNegativeCache(path=path, ttl_s=60.0)
    assert cache2.get(key) == "QUOTE_REVERT"
