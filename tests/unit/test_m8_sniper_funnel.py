"""Tests for monitoring/sniper_funnel.py — M8 Phase 1 funnel tracker.

Coverage:
  - FunnelTracker counter increments
  - dedup_dropped / dedup_new accounting
  - snapshot() returns all required keys
  - snapshot() keys match sniper_artifacts REQUIRED_METRIC_KEYS
  - record_trace() ring-buffer behaviour
  - funnel_table_lines() output format
  - EventTrace.to_dict() completeness
  - Thread-safety (concurrent increments sum correctly)
  - sniper_smoke_run import + offline CLI path
  - smoke runner: ARBY_SNIPER_ENABLE=0 exits cleanly (exit 0, no artifact)
  - smoke runner: offline mode writes valid artifact
"""
from __future__ import annotations

import os
import sys
import threading
import tempfile
from pathlib import Path

import pytest

# Ensure repo root is importable.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from monitoring.sniper_funnel import (
    FUNNEL_STAGE_NAMES,
    EventTrace,
    FunnelTracker,
)
from monitoring.sniper_artifacts import (
    REQUIRED_METRIC_KEYS,
    validate_sniper_artifact,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trace(n: int = 0) -> EventTrace:
    return EventTrace(
        event_id=f"base:0xfactory:0xtx{n:04x}:{n}",
        chain="base",
        dex="uniswap_v3",
        factory="0xfactory",
        pool=f"0xpool{n:04x}",
        token0="0xtoken0",
        token1="0xtoken1",
        block_number=100 + n,
        received_ts=1_700_000_000.0 + n,
        filter_passed=True,
        candidate=True,
    )


# ---------------------------------------------------------------------------
# FunnelTracker — basic counter tests
# ---------------------------------------------------------------------------

class TestFunnelTrackerCounters:
    def test_initial_counters_all_zero(self):
        t = FunnelTracker()
        snap = t.snapshot()
        for stage in FUNNEL_STAGE_NAMES:
            assert snap[stage] == 0, f"stage {stage!r} should start at 0"

    def test_inc_single_stage(self):
        t = FunnelTracker()
        t.inc("raw_fetched", 5)
        assert t.snapshot()["raw_fetched"] == 5

    def test_inc_default_is_one(self):
        t = FunnelTracker()
        t.inc("parse_ok")
        t.inc("parse_ok")
        assert t.snapshot()["parse_ok"] == 2

    def test_inc_unknown_stage_silently_ignored(self):
        t = FunnelTracker()
        t.inc("nonexistent_stage_xyz")  # must not raise
        snap = t.snapshot()
        for stage in FUNNEL_STAGE_NAMES:
            assert snap[stage] == 0

    def test_all_stage_names_incrementable(self):
        t = FunnelTracker()
        for stage in FUNNEL_STAGE_NAMES:
            t.inc(stage)
        snap = t.snapshot()
        for stage in FUNNEL_STAGE_NAMES:
            assert snap[stage] == 1

    def test_rpc_call_counter(self):
        t = FunnelTracker()
        t.inc_rpc_call()
        t.inc_rpc_call()
        assert t.snapshot()["rpc_calls_made"] == 2

    def test_rpc_error_counter(self):
        t = FunnelTracker()
        t.inc_rpc_error()
        assert t.snapshot()["rpc_errors"] == 1

    def test_complete_cycle_counter(self):
        t = FunnelTracker()
        t.complete_cycle()
        t.complete_cycle()
        assert t.snapshot()["cycles_completed"] == 2

    def test_elapsed_s_positive(self):
        t = FunnelTracker()
        snap = t.snapshot()
        assert snap["elapsed_s"] >= 0.0

    def test_multiple_incs_accumulate(self):
        t = FunnelTracker()
        t.inc("raw_fetched", 10)
        t.inc("raw_fetched", 5)
        assert t.snapshot()["raw_fetched"] == 15


# ---------------------------------------------------------------------------
# FunnelTracker — snapshot schema tests
# ---------------------------------------------------------------------------

class TestFunnelTrackerSnapshot:
    def test_snapshot_contains_required_artifact_metric_keys(self):
        """Snapshot must expose all keys required by sniper_artifacts."""
        t = FunnelTracker()
        snap = t.snapshot()
        for key in REQUIRED_METRIC_KEYS:
            assert key in snap, f"required metric key {key!r} missing from snapshot"

    def test_pool_creation_events_seen_maps_to_raw_fetched(self):
        t = FunnelTracker()
        t.inc("raw_fetched", 7)
        snap = t.snapshot()
        assert snap["pool_creation_events_seen"] == 7

    def test_pool_creation_events_filtered_out_maps_to_filter_rejected(self):
        t = FunnelTracker()
        t.inc("filter_rejected", 3)
        snap = t.snapshot()
        assert snap["pool_creation_events_filtered_out"] == 3

    def test_snipe_candidates_maps_to_candidates_queued(self):
        t = FunnelTracker()
        t.inc("candidates_queued", 2)
        snap = t.snapshot()
        assert snap["snipe_candidates_total"] == 2

    def test_honeypot_placeholders_are_zero(self):
        t = FunnelTracker()
        snap = t.snapshot()
        assert snap["honeypot_check_pass"] == 0
        assert snap["honeypot_check_fail"] == 0

    def test_snapshot_all_stage_names_present(self):
        t = FunnelTracker()
        snap = t.snapshot()
        for stage in FUNNEL_STAGE_NAMES:
            assert stage in snap


# ---------------------------------------------------------------------------
# FunnelTracker — trace ring-buffer tests
# ---------------------------------------------------------------------------

class TestFunnelTrackerTraces:
    def test_record_trace_and_retrieve(self):
        t = FunnelTracker()
        trace = _make_trace(0)
        t.record_trace(trace)
        result = t.recent_traces(n=1)
        assert len(result) == 1
        assert result[0]["event_id"] == trace.event_id

    def test_recent_traces_ordering_newest_last(self):
        t = FunnelTracker()
        for i in range(5):
            t.record_trace(_make_trace(i))
        traces = t.recent_traces(n=3)
        assert len(traces) == 3
        assert traces[-1]["block_number"] == 104

    def test_ring_buffer_drops_oldest(self):
        max_traces = 5
        t = FunnelTracker(max_traces=max_traces)
        for i in range(10):
            t.record_trace(_make_trace(i))
        all_traces = t.recent_traces(n=100)
        assert len(all_traces) == max_traces
        # Should retain the 5 newest (indices 5-9)
        event_ids = [tr["event_id"] for tr in all_traces]
        assert "base:0xfactory:0xtx0000:0" not in event_ids
        assert "base:0xfactory:0xtx0009:9" in event_ids

    def test_recent_traces_n_larger_than_buffer_returns_all(self):
        t = FunnelTracker()
        for i in range(3):
            t.record_trace(_make_trace(i))
        traces = t.recent_traces(n=100)
        assert len(traces) == 3

    def test_recent_traces_empty_initial(self):
        t = FunnelTracker()
        assert t.recent_traces() == []


# ---------------------------------------------------------------------------
# EventTrace tests
# ---------------------------------------------------------------------------

class TestEventTrace:
    def test_to_dict_has_all_fields(self):
        trace = _make_trace(42)
        d = trace.to_dict()
        required_keys = {
            "event_id", "chain", "dex", "factory", "pool",
            "token0", "token1", "block_number", "received_ts",
            "filter_passed", "candidate", "reject_reason",
        }
        for key in required_keys:
            assert key in d, f"key {key!r} missing from EventTrace.to_dict()"

    def test_to_dict_reject_reason_none_by_default(self):
        trace = _make_trace(0)
        assert trace.to_dict()["reject_reason"] is None

    def test_to_dict_filter_passed_and_candidate(self):
        trace = _make_trace(0)
        d = trace.to_dict()
        assert d["filter_passed"] is True
        assert d["candidate"] is True


# ---------------------------------------------------------------------------
# funnel_table_lines tests
# ---------------------------------------------------------------------------

class TestFunnelTableLines:
    def test_returns_list_of_strings(self):
        t = FunnelTracker()
        lines = t.funnel_table_lines()
        assert isinstance(lines, list)
        assert all(isinstance(l, str) for l in lines)

    def test_contains_all_stage_labels(self):
        t = FunnelTracker()
        lines = t.funnel_table_lines()
        joined = "\n".join(lines)
        # Check for label substrings (the table uses human labels, not stage keys)
        for keyword in ("raw logs", "parsed ok", "dedup new", "candidates"):
            assert any(keyword in line.lower() for line in lines), (
                f"keyword {keyword!r} not found in funnel table lines: {lines}"
            )

    def test_contains_rpc_and_cycle_info(self):
        t = FunnelTracker()
        t.inc_rpc_call()
        t.complete_cycle()
        lines = t.funnel_table_lines()
        joined = "\n".join(lines)
        assert "rpc" in joined.lower()
        assert "cycles" in joined.lower()

    def test_non_zero_counters_appear_in_output(self):
        t = FunnelTracker()
        t.inc("raw_fetched", 99)
        lines = t.funnel_table_lines()
        joined = "\n".join(lines)
        assert "99" in joined


# ---------------------------------------------------------------------------
# Thread-safety test
# ---------------------------------------------------------------------------

class TestFunnelTrackerThreadSafety:
    def test_concurrent_increments(self):
        t = FunnelTracker()
        n_threads = 10
        n_incs_each = 100

        def _worker():
            for _ in range(n_incs_each):
                t.inc("raw_fetched")

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert t.snapshot()["raw_fetched"] == n_threads * n_incs_each


# ---------------------------------------------------------------------------
# sniper_smoke_run — import and feature-flag tests
# ---------------------------------------------------------------------------

class TestSniperSmokeRunImport:
    def test_module_importable(self):
        import importlib
        mod = importlib.import_module("scripts.sniper_smoke_run")
        assert hasattr(mod, "main")

    def test_main_callable(self):
        from scripts.sniper_smoke_run import main
        assert callable(main)


class TestSniperSmokeRunFeatureFlag:
    def test_exits_zero_when_flag_unset(self, monkeypatch):
        """ARBY_SNIPER_ENABLE not set → exit 0, no side effects."""
        monkeypatch.delenv("ARBY_SNIPER_ENABLE", raising=False)
        from scripts.sniper_smoke_run import main
        rc = main(argv=[])
        assert rc == 0

    def test_exits_zero_when_flag_zero(self, monkeypatch):
        monkeypatch.setenv("ARBY_SNIPER_ENABLE", "0")
        from scripts.sniper_smoke_run import main
        rc = main(argv=[])
        assert rc == 0

    def test_exits_zero_when_flag_false(self, monkeypatch):
        monkeypatch.setenv("ARBY_SNIPER_ENABLE", "false")
        from scripts.sniper_smoke_run import main
        rc = main(argv=[])
        assert rc == 0


class TestSniperSmokeRunOffline:
    def test_offline_mode_exits_zero(self, monkeypatch, tmp_path):
        """--offline with ARBY_SNIPER_ENABLE=1 runs one cycle and exits 0."""
        monkeypatch.setenv("ARBY_SNIPER_ENABLE", "1")
        # Redirect artifact output to tmp_path
        monkeypatch.setattr(
            "monitoring.sniper_artifacts.ROLLING_ARTIFACT_PATH",
            tmp_path / "new_pool_sniper_latest.json",
        )
        from scripts.sniper_smoke_run import main
        rc = main(argv=["--offline", "--duration-minutes", "0", "--chain", "base"])
        assert rc == 0

    def test_offline_mode_writes_artifact(self, monkeypatch, tmp_path):
        """Offline mode must produce a valid rolling artifact."""
        import json
        monkeypatch.setenv("ARBY_SNIPER_ENABLE", "1")
        artifact_path = tmp_path / "new_pool_sniper_latest.json"
        monkeypatch.setattr(
            "monitoring.sniper_artifacts.ROLLING_ARTIFACT_PATH",
            artifact_path,
        )
        from scripts.sniper_smoke_run import main
        main(argv=["--offline", "--duration-minutes", "0", "--chain", "base"])
        assert artifact_path.exists(), "rolling artifact must be written"
        with artifact_path.open() as f:
            art = json.load(f)
        violations = validate_sniper_artifact(art)
        assert violations == [], f"artifact has violations: {violations}"

    def test_offline_artifact_status_empty(self, monkeypatch, tmp_path):
        """Offline with no real events → status must be EMPTY."""
        import json
        monkeypatch.setenv("ARBY_SNIPER_ENABLE", "1")
        artifact_path = tmp_path / "new_pool_sniper_latest.json"
        monkeypatch.setattr(
            "monitoring.sniper_artifacts.ROLLING_ARTIFACT_PATH",
            artifact_path,
        )
        from scripts.sniper_smoke_run import main
        main(argv=["--offline", "--duration-minutes", "0", "--chain", "base"])
        with artifact_path.open() as f:
            art = json.load(f)
        assert art["status"] == "EMPTY"

    def test_offline_artifact_has_cycles_completed(self, monkeypatch, tmp_path):
        """Offline mode must complete ≥1 cycle."""
        import json
        monkeypatch.setenv("ARBY_SNIPER_ENABLE", "1")
        artifact_path = tmp_path / "new_pool_sniper_latest.json"
        monkeypatch.setattr(
            "monitoring.sniper_artifacts.ROLLING_ARTIFACT_PATH",
            artifact_path,
        )
        from scripts.sniper_smoke_run import main
        main(argv=["--offline", "--duration-minutes", "0", "--chain", "base"])
        with artifact_path.open() as f:
            art = json.load(f)
        assert art["metrics"]["cycles_completed"] >= 1

    def test_offline_artifact_funnel_keys_present(self, monkeypatch, tmp_path):
        """All required metric keys must be present in offline artifact."""
        import json
        monkeypatch.setenv("ARBY_SNIPER_ENABLE", "1")
        artifact_path = tmp_path / "new_pool_sniper_latest.json"
        monkeypatch.setattr(
            "monitoring.sniper_artifacts.ROLLING_ARTIFACT_PATH",
            artifact_path,
        )
        from scripts.sniper_smoke_run import main
        main(argv=["--offline", "--duration-minutes", "0", "--chain", "base"])
        with artifact_path.open() as f:
            art = json.load(f)
        for key in REQUIRED_METRIC_KEYS:
            assert key in art["metrics"], f"required metric key {key!r} missing"

    def test_offline_no_artifact_when_flag_off(self, monkeypatch, tmp_path):
        """When flag is off, no artifact should be written."""
        monkeypatch.setenv("ARBY_SNIPER_ENABLE", "0")
        artifact_path = tmp_path / "new_pool_sniper_latest.json"
        monkeypatch.setattr(
            "monitoring.sniper_artifacts.ROLLING_ARTIFACT_PATH",
            artifact_path,
        )
        from scripts.sniper_smoke_run import main
        rc = main(argv=["--offline", "--duration-minutes", "0"])
        assert rc == 0
        assert not artifact_path.exists(), "artifact must NOT be written when feature flag is off"


# ---------------------------------------------------------------------------
# rpc_error_histogram tests (Step 6)
# ---------------------------------------------------------------------------

class TestRpcErrorHistogram:
    def test_inc_rpc_error_no_arg_counts_as_other(self):
        """inc_rpc_error() with no string defaults to 'other' bucket."""
        t = FunnelTracker()
        t.inc_rpc_error()
        snap = t.snapshot()
        assert snap["rpc_errors"] == 1
        hist = snap["rpc_error_histogram"]
        assert hist.get("other", 0) == 1

    def test_inc_rpc_error_408_classified(self):
        t = FunnelTracker()
        t.inc_rpc_error("HTTPError 408 Request Timeout")
        snap = t.snapshot()
        hist = snap["rpc_error_histogram"]
        assert hist.get("408_timeout", 0) == 1

    def test_inc_rpc_error_429_classified(self):
        t = FunnelTracker()
        t.inc_rpc_error("HTTP 429 Too Many Requests")
        snap = t.snapshot()
        hist = snap["rpc_error_histogram"]
        assert hist.get("429_rate_limit", 0) == 1

    def test_inc_rpc_error_rate_limit_string(self):
        t = FunnelTracker()
        t.inc_rpc_error("rate limit exceeded")
        snap = t.snapshot()
        hist = snap["rpc_error_histogram"]
        assert hist.get("429_rate_limit", 0) == 1

    def test_inc_rpc_error_500_classified_as_5xx(self):
        t = FunnelTracker()
        t.inc_rpc_error("HTTP 500 server error")
        snap = t.snapshot()
        hist = snap["rpc_error_histogram"]
        assert hist.get("5xx_server", 0) == 1

    def test_inc_rpc_error_timeout_string(self):
        t = FunnelTracker()
        t.inc_rpc_error("connection timed out")
        snap = t.snapshot()
        hist = snap["rpc_error_histogram"]
        assert hist.get("timeout", 0) == 1

    def test_inc_rpc_error_multiple_types_accumulate(self):
        t = FunnelTracker()
        t.inc_rpc_error("408 timeout")
        t.inc_rpc_error("408 timeout")
        t.inc_rpc_error("429 rate limit")
        snap = t.snapshot()
        hist = snap["rpc_error_histogram"]
        assert hist.get("408_timeout", 0) == 2
        assert hist.get("429_rate_limit", 0) == 1
        assert snap["rpc_errors"] == 3

    def test_histogram_empty_when_no_errors(self):
        t = FunnelTracker()
        snap = t.snapshot()
        # no errors → histogram should be an empty dict (or have all zeros)
        hist = snap["rpc_error_histogram"]
        assert isinstance(hist, dict)
        assert sum(hist.values()) == 0

    def test_histogram_in_snapshot_always_present(self):
        t = FunnelTracker()
        snap = t.snapshot()
        assert "rpc_error_histogram" in snap

    def test_histogram_shown_in_funnel_table_when_errors(self):
        t = FunnelTracker()
        t.inc_rpc_error("408 timeout")
        lines = t.funnel_table_lines()
        joined = "\n".join(lines)
        assert "408" in joined

    def test_inc_rpc_error_range_too_wide_alchemy_free_tier(self):
        """Alchemy free-tier block range error is classified as range_too_wide."""
        t = FunnelTracker()
        t.inc_rpc_error(
            "400 Client Error: Bad Request -- Under the Free tier plan, "
            "you can make eth_getLogs requests with up to a 10 block range."
        )
        snap = t.snapshot()
        hist = snap["rpc_error_histogram"]
        assert hist.get("range_too_wide", 0) == 1, f"Expected range_too_wide, got: {hist}"

    def test_inc_rpc_error_range_exceeded_string(self):
        """Generic 'range exceeded' or '-32600' error is classified as range_too_wide."""
        t = FunnelTracker()
        t.inc_rpc_error("Log response size exceeded. -32600")
        snap = t.snapshot()
        hist = snap["rpc_error_histogram"]
        assert hist.get("range_too_wide", 0) == 1, f"Expected range_too_wide, got: {hist}"


# ---------------------------------------------------------------------------
# factory_breakdown tests (Step 7)
# ---------------------------------------------------------------------------

class TestFactoryBreakdown:
    def test_breakdown_empty_when_no_inc_dex(self):
        t = FunnelTracker()
        snap = t.snapshot()
        assert "factory_breakdown" in snap
        assert snap["factory_breakdown"] == {}

    def test_inc_dex_raw_increments_breakdown(self):
        t = FunnelTracker()
        t.inc_dex("uniswap_v3", "raw")
        snap = t.snapshot()
        fbd = snap["factory_breakdown"]
        assert "uniswap_v3" in fbd
        assert fbd["uniswap_v3"]["raw"] == 1

    def test_inc_dex_parse_ok_increments_breakdown(self):
        t = FunnelTracker()
        t.inc_dex("aerodrome", "parse_ok")
        snap = t.snapshot()
        fbd = snap["factory_breakdown"]
        assert fbd["aerodrome"]["parse_ok"] == 1

    def test_inc_dex_error_increments_breakdown(self):
        t = FunnelTracker()
        t.inc_dex("pancakeswap_v3", "error")
        snap = t.snapshot()
        fbd = snap["factory_breakdown"]
        assert fbd["pancakeswap_v3"]["errors"] == 1

    def test_inc_dex_candidate_increments_breakdown(self):
        t = FunnelTracker()
        t.inc_dex("uniswap_v3", "candidate")
        snap = t.snapshot()
        fbd = snap["factory_breakdown"]
        assert fbd["uniswap_v3"]["candidates"] == 1

    def test_inc_dex_unknown_stage_silently_ignored(self):
        t = FunnelTracker()
        t.inc_dex("uniswap_v3", "nonexistent_stage")  # must not raise
        snap = t.snapshot()
        fbd = snap["factory_breakdown"]
        # dex not in breakdown at all since no valid stage was incremented
        assert "uniswap_v3" not in fbd

    def test_multiple_dexes_tracked_independently(self):
        t = FunnelTracker()
        t.inc_dex("uniswap_v3", "raw")
        t.inc_dex("uniswap_v3", "raw")
        t.inc_dex("aerodrome", "raw")
        snap = t.snapshot()
        fbd = snap["factory_breakdown"]
        assert fbd["uniswap_v3"]["raw"] == 2
        assert fbd["aerodrome"]["raw"] == 1

    def test_breakdown_sub_keys_present(self):
        t = FunnelTracker()
        t.inc_dex("uniswap_v3", "raw")
        fbd = t.snapshot()["factory_breakdown"]
        entry = fbd["uniswap_v3"]
        # new canonical keys
        for sub_key in ("polls_ok", "raw_logs", "parse_ok", "errors", "candidates"):
            assert sub_key in entry, f"missing sub-key {sub_key!r}"
        # deprecated backward-compat key
        assert "raw" in entry, "missing deprecated 'raw' key (backward compat)"

    def test_breakdown_shown_in_funnel_table(self):
        t = FunnelTracker()
        t.inc_dex("uniswap_v3", "raw")
        lines = t.funnel_table_lines()
        joined = "\n".join(lines)
        assert "uniswap_v3" in joined

    # ------ new: polls_ok / raw_logs / pct fields ------

    def test_inc_dex_polls_ok_stage(self):
        t = FunnelTracker()
        t.inc_dex("uniswap_v3", "polls_ok")
        t.inc_dex("uniswap_v3", "polls_ok")
        fbd = t.snapshot()["factory_breakdown"]
        assert fbd["uniswap_v3"]["polls_ok"] == 2

    def test_inc_dex_raw_logs_stage_with_n(self):
        t = FunnelTracker()
        t.inc_dex("uniswap_v3", "raw_logs", 5)
        fbd = t.snapshot()["factory_breakdown"]
        assert fbd["uniswap_v3"]["raw_logs"] == 5

    def test_raw_deprecated_alias_equals_polls_ok(self):
        """'raw' key in breakdown must equal polls_ok (deprecated alias)."""
        t = FunnelTracker()
        t.inc_dex("uniswap_v3", "polls_ok", 3)
        fbd = t.snapshot()["factory_breakdown"]
        assert fbd["uniswap_v3"]["raw"] == 3
        assert fbd["uniswap_v3"]["raw"] == fbd["uniswap_v3"]["polls_ok"]

    def test_parse_rate_pct_computed(self):
        t = FunnelTracker()
        t.inc_dex("uniswap_v3", "raw_logs", 10)
        t.inc_dex("uniswap_v3", "parse_ok", 8)
        fbd = t.snapshot()["factory_breakdown"]
        assert fbd["uniswap_v3"]["parse_rate_pct"] == 80.0

    def test_candidate_rate_pct_computed(self):
        t = FunnelTracker()
        t.inc_dex("uniswap_v3", "raw_logs", 4)
        t.inc_dex("uniswap_v3", "candidate", 2)
        fbd = t.snapshot()["factory_breakdown"]
        assert fbd["uniswap_v3"]["candidate_rate_pct"] == 50.0

    def test_parse_rate_pct_none_when_no_raw_logs(self):
        """When raw_logs=0, parse_rate_pct must be None (no division by zero)."""
        t = FunnelTracker()
        t.inc_dex("uniswap_v3", "polls_ok")
        fbd = t.snapshot()["factory_breakdown"]
        assert fbd["uniswap_v3"]["parse_rate_pct"] is None
        assert fbd["uniswap_v3"]["candidate_rate_pct"] is None

    def test_inc_dex_n_parameter_default_is_one(self):
        t = FunnelTracker()
        t.inc_dex("aerodrome", "raw_logs")   # no n → default 1
        fbd = t.snapshot()["factory_breakdown"]
        assert fbd["aerodrome"]["raw_logs"] == 1

