"""Spawn/stop background continuous pipeline services (sniper, broker)."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from core.pipeline_provenance import ENV_PIPELINE_SESSION_ID

SERVICE_PID_DIR = Path("data/tmp/continuous_service_pids")


def _pid_path(service: str, session_id: str) -> Path:
    safe = session_id.replace(":", "_").replace("/", "_")
    return SERVICE_PID_DIR / f"{service}_{safe}.json"


def write_service_pid(service: str, session_id: str, pid: int, *, cmd: List[str]) -> None:
    SERVICE_PID_DIR.mkdir(parents=True, exist_ok=True)
    doc = {"service": service, "session_id": session_id, "pid": pid, "cmd": cmd}
    path = _pid_path(service, session_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_service_pid(service: str, session_id: str) -> Optional[Dict[str, Any]]:
    path = _pid_path(service, session_id)
    if not path.is_file():
        return None
    try:
        return cast(Dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None


def stop_service(service: str, session_id: str, *, grace_s: float = 5.0) -> bool:
    doc = read_service_pid(service, session_id)
    if not doc:
        return False
    pid = int(doc.get("pid") or 0)
    if pid <= 0:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except OSError:
            break
    else:
        kill_sig = getattr(signal, "SIGKILL", signal.SIGTERM)
        try:
            os.kill(pid, kill_sig)
        except OSError:
            pass
    try:
        _pid_path(service, session_id).unlink()
    except OSError:
        pass
    return True


def spawn_sniper_service(session_id: str) -> int:
    env = dict(os.environ)
    env.setdefault(ENV_PIPELINE_SESSION_ID, session_id)
    env["ARBY_SNIPER_ENABLE"] = "1"
    cmd = [
        sys.executable,
        "scripts/sniper_smoke_run.py",
        "--chain",
        "base",
        "--acceptance-run",
        "--blocks-back",
        "50",
    ]
    proc = subprocess.Popen(cmd, env=env)
    write_service_pid("sniper", session_id, proc.pid, cmd=cmd)
    return proc.pid


def spawn_broker_service(session_id: str) -> int:
    env = dict(os.environ)
    env.setdefault(ENV_PIPELINE_SESSION_ID, session_id)
    cmd = [
        sys.executable,
        "scripts/continuous_worker_run.py",
        "--worker",
        "broker",
        "--session-id",
        session_id,
    ]
    proc = subprocess.Popen(cmd, env=env)
    write_service_pid("broker", session_id, proc.pid, cmd=cmd)
    return proc.pid


def stop_all_services(session_id: str) -> None:
    stop_service("broker", session_id)
    stop_service("sniper", session_id)
