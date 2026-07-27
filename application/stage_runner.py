"""Stage runner — subprocess execution with timeout/heartbeat/retry budget.

Extracted from ``start.py`` (control-plane split).  The process-management
loop is identical to the legacy inline implementation:

* streamed stdout via a reader thread + queue (no pipe deadlock);
* hard timeout kills the child process tree (``hard_timeout_<s>s``);
* stale heartbeat kills the child process tree (``stale_heartbeat_<s>s``) — quiet steps
  may refresh liveness through ``has_external_activity`` (checkpoint files);
* final ``proc.wait(timeout=30)`` with a defensive tree kill.

``run_with_retries`` adds the per-stage retry budget declared on
``PipelineStage.retries``.
"""
from __future__ import annotations

import os
import queue as _queue
import signal
import subprocess
import sys
import threading
import time
from typing import Callable, Mapping, Optional, Sequence, Tuple

__all__ = ["run_stage_subprocess", "run_with_retries", "terminate_process_tree"]


def _popen_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_process_tree(proc: subprocess.Popen) -> None:
    """Terminate *proc* and any child processes it spawned."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        proc.kill()


def run_stage_subprocess(
    cmd: Sequence[str],
    *,
    env: Optional[Mapping[str, str]] = None,
    timeout_s: float = 0,
    heartbeat_stale_s: float = 0,
    on_output: Optional[Callable[[str], None]] = None,
    on_heartbeat: Optional[Callable[[], None]] = None,
    has_external_activity: Optional[Callable[[], bool]] = None,
    on_spawn: Optional[Callable[[subprocess.Popen], None]] = None,
) -> Tuple[int, Optional[str]]:
    """Run a stage subprocess; return ``(exit_code, fail_reason)``.

    ``fail_reason`` is None on a clean exit; otherwise one of
    ``hard_timeout_<s>s`` / ``stale_heartbeat_<s>s``.
    """
    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=dict(env) if env is not None else None,
        **_popen_kwargs(),
    )
    assert proc.stdout is not None
    if on_spawn is not None:
        on_spawn(proc)

    line_queue: "_queue.Queue[tuple[str, Optional[str]]]" = _queue.Queue()

    def _reader() -> None:
        try:
            for line in proc.stdout:
                line_queue.put(("line", line))
        finally:
            line_queue.put(("done", None))

    threading.Thread(target=_reader, daemon=True).start()
    start_mono = time.monotonic()
    last_output_mono = start_mono
    fail_reason: Optional[str] = None

    while True:
        try:
            kind, payload = line_queue.get(timeout=1.0)
        except _queue.Empty:
            kind = None
            payload = None

        now_mono = time.monotonic()
        if kind == "line" and payload is not None:
            last_output_mono = now_mono
            if on_output is not None:
                on_output(payload)
            if on_heartbeat is not None:
                on_heartbeat()
        elif kind == "done":
            break
        elif (
            kind is None
            and has_external_activity is not None
            and has_external_activity()
        ):
            last_output_mono = now_mono
            if on_heartbeat is not None:
                on_heartbeat()

        if proc.poll() is not None and line_queue.empty():
            break

        if timeout_s > 0 and (now_mono - start_mono) > timeout_s:
            terminate_process_tree(proc)
            fail_reason = f"hard_timeout_{int(timeout_s)}s"
            break
        if heartbeat_stale_s > 0 and (now_mono - last_output_mono) > heartbeat_stale_s:
            terminate_process_tree(proc)
            fail_reason = f"stale_heartbeat_{int(heartbeat_stale_s)}s"
            break

    try:
        rc = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        terminate_process_tree(proc)
        rc = 3
    if fail_reason:
        return rc or 1, fail_reason
    return rc, None


def run_with_retries(
    run_once: Callable[[], Tuple[int, Optional[str]]],
    *,
    retries: int = 0,
    allow_exit_codes: Sequence[int] = (0,),
    retry_delay_s: float = 0.0,
) -> Tuple[int, Optional[str], int]:
    """Run ``run_once`` with a bounded retry budget.

    Returns ``(exit_code, fail_reason, attempts)``.  A result counts as
    successful when ``fail_reason`` is None and the exit code is allowed;
    anything else triggers another attempt until the budget is exhausted.
    """
    attempts = 0
    last_rc = 1
    last_reason: Optional[str] = "no_attempt"
    max_attempts = max(1, retries + 1)
    while attempts < max_attempts:
        attempts += 1
        last_rc, last_reason = run_once()
        if last_reason is None and last_rc in allow_exit_codes:
            return last_rc, None, attempts
        if attempts < max_attempts and retry_delay_s > 0:
            time.sleep(retry_delay_s)
    return last_rc, last_reason, attempts
