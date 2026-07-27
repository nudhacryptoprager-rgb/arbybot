"""Unit tests for the application control plane (checkpoint store, stage
definitions, stage runner) extracted from start.py."""
from __future__ import annotations

import os
import sys
import time

import pytest

from application.checkpoint_store import CheckpointStore
from application.pipeline_stage import PipelineStage, StageResult
from application.stage_runner import run_stage_subprocess, run_with_retries, terminate_process_tree


# ---------------------------------------------------------------------------
# CheckpointStore
# ---------------------------------------------------------------------------


def test_marker_paths_namespace_and_mkdir(tmp_path):
    store = CheckpointStore(tmp_path / "steps")
    done_a, fail_a = store.marker_paths("step_a", pipeline_mode="time_to_mirror")
    done_b, fail_b = store.marker_paths("step_b", pipeline_mode="time_to_mirror")
    assert done_a != done_b and fail_a != fail_b
    assert done_a.parent == tmp_path / "steps" / "time_to_mirror"
    assert done_a.parent.is_dir()
    plain_done, _ = store.marker_paths("step_a")
    assert plain_done.parent == tmp_path / "steps"


def test_mark_done_clears_fail_and_is_done(tmp_path):
    store = CheckpointStore(tmp_path)
    store.mark_failed("s1", pipeline_mode="m")
    assert not store.is_done("s1", pipeline_mode="m")
    store.mark_done("s1", pipeline_mode="m")
    assert store.is_done("s1", pipeline_mode="m")
    _, fail = store.marker_paths("s1", pipeline_mode="m")
    assert not fail.exists()


def test_clear_fail_markers_only_removes_fail(tmp_path):
    store = CheckpointStore(tmp_path)
    store.mark_failed("a", pipeline_mode="m")
    store.mark_done("b", pipeline_mode="m")
    cleared = store.clear_fail_markers("m", ["a", "b", "ghost"])
    assert cleared == 1
    assert store.is_done("b", pipeline_mode="m")


def test_collect_progress_counts_done_and_failed(tmp_path):
    store = CheckpointStore(tmp_path)
    store.mark_done("a", pipeline_mode="m")
    store.mark_failed("b", pipeline_mode="m")
    progress = store.collect_progress(["a", "b", "c"], pipeline_mode="m")
    assert progress["done_steps"] == ["a"]
    assert progress["failed_steps"] == ["b"]
    assert progress["done_count"] == 1
    assert progress["failed_count"] == 1
    assert progress["marker_namespace"] == "m"


def test_checkpoint_activity_since_detects_fresh_file(tmp_path):
    watched = tmp_path / "ck.json"
    watched.write_text("{}", encoding="utf-8")
    assert CheckpointStore.checkpoint_activity_since([watched], time.time() - 5)
    assert not CheckpointStore.checkpoint_activity_since([watched], time.time() + 3600)
    assert not CheckpointStore.checkpoint_activity_since([tmp_path / "nope.json"], time.time() - 5)


# ---------------------------------------------------------------------------
# PipelineStage / StageResult
# ---------------------------------------------------------------------------


def test_stage_legacy_dict_roundtrip_compatible_with_start_shape():
    legacy = {
        "name": "m8_2_radar_two_phase",
        "cmd": ["py", "-3.11", "scripts/x.py"],
        "allow_exit_codes": (0, 2),
        "env": {"A": "1"},
        "timeout_seconds": 600,
        "internal": "queue_export",
    }
    stage = PipelineStage.from_legacy_dict(legacy)
    assert stage.name == "m8_2_radar_two_phase"
    assert stage.allow_exit_codes == (0, 2)
    back = stage.to_legacy_dict()
    assert back["name"] == legacy["name"]
    assert back["cmd"] == legacy["cmd"]
    assert back["allow_exit_codes"] == (0, 2)
    assert back["env"] == {"A": "1"}
    assert back["timeout_seconds"] == 600
    assert back["internal"] == "queue_export"


def test_stage_typed_contract_fields():
    stage = PipelineStage(
        name="graph_quote",
        cmd=("py", "-3.11", "worker.py"),
        retries=2,
        inputs=("data/tmp/m9_bridge_inventory_production_latest.json",),
        outputs=("data/tmp/m9_graph_latest.json",),
    )
    assert stage.retries == 2
    assert stage.inputs and stage.outputs
    assert "retries" in stage.to_legacy_dict()


def test_stage_result_ok_semantics():
    assert StageResult(name="s", exit_code=0, duration_s=1.0, outcome="ok").ok
    assert StageResult(name="s", exit_code=2, duration_s=1.0, outcome="allowed_exit").ok
    assert not StageResult(name="s", exit_code=1, duration_s=1.0, outcome="failed").ok


# ---------------------------------------------------------------------------
# run_stage_subprocess
# ---------------------------------------------------------------------------


def test_run_stage_subprocess_success_captures_output():
    lines: list[str] = []
    rc, reason = run_stage_subprocess(
        [sys.executable, "-c", "print('hello')"],
        on_output=lines.append,
    )
    assert rc == 0 and reason is None
    assert any("hello" in line for line in lines)


def test_run_stage_subprocess_propagates_exit_code():
    rc, reason = run_stage_subprocess([sys.executable, "-c", "import sys; sys.exit(4)"])
    assert rc == 4 and reason is None


def test_run_stage_subprocess_hard_timeout_kills():
    started = time.monotonic()
    rc, reason = run_stage_subprocess(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        timeout_s=1,
    )
    elapsed = time.monotonic() - started
    assert reason is not None and reason.startswith("hard_timeout_")
    assert rc != 0
    assert elapsed < 30


def test_run_stage_subprocess_hard_timeout_kills_child_tree(tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    script = f"""
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
open(r"{pid_file}", "w", encoding="utf-8").write(str(child.pid))
time.sleep(120)
"""
    rc, reason = run_stage_subprocess([sys.executable, "-c", script], timeout_s=2)
    assert reason is not None and reason.startswith("hard_timeout_")
    assert rc != 0
    assert pid_file.is_file()
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises((ProcessLookupError, OSError)):
        os.kill(pid, 0)


def test_run_stage_subprocess_stale_heartbeat_kills():
    rc, reason = run_stage_subprocess(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        heartbeat_stale_s=1,
    )
    assert reason is not None and reason.startswith("stale_heartbeat_")
    assert rc != 0


def test_run_stage_subprocess_external_activity_refreshes_heartbeat(tmp_path):
    # External checkpoint file touched mid-run must prevent stale-heartbeat kill.
    watched = tmp_path / "ck.json"
    state = {"touched": False}

    def _activity() -> bool:
        return state["touched"]

    import threading

    def _touch_later() -> None:
        time.sleep(1.0)
        state["touched"] = True
        watched.write_text("{}", encoding="utf-8")

    threading.Thread(target=_touch_later, daemon=True).start()
    rc, reason = run_stage_subprocess(
        [sys.executable, "-c", "import time; time.sleep(3)"],
        heartbeat_stale_s=2,
        has_external_activity=_activity,
    )
    # Heartbeat refreshed at ~1s -> process allowed to finish at ~3s.
    assert reason is None
    assert rc == 0


# ---------------------------------------------------------------------------
# run_with_retries
# ---------------------------------------------------------------------------


def test_run_with_retries_succeeds_after_flaky_failure():
    attempts = {"n": 0}

    def _flaky() -> tuple[int, str | None]:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return 1, None
        return 0, None

    rc, reason, used = run_with_retries(_flaky, retries=2)
    assert rc == 0 and reason is None and used == 2


def test_run_with_retries_exhausts_budget():
    rc, reason, used = run_with_retries(lambda: (3, None), retries=2)
    assert rc == 3 and used == 3


def test_run_with_retries_allowed_exit_codes():
    rc, reason, used = run_with_retries(lambda: (2, None), retries=3, allow_exit_codes=(0, 2))
    assert rc == 2 and reason is None and used == 1


def test_run_with_retries_fail_reason_counts_as_failure():
    rc, reason, used = run_with_retries(lambda: (0, "hard_timeout_1s"), retries=1)
    assert reason == "hard_timeout_1s" and used == 2
