"""Single-writer lock for M8.2 external pool hint refresh."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lock_path_for(checkpoint_path: str) -> Path:
    return Path(checkpoint_path).with_suffix(Path(checkpoint_path).suffix + ".lock")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_hint_refresh_lock(
    *,
    checkpoint_path: str,
    output_path: str,
    chain: str,
    sources: list[str],
) -> Path:
    """Create lock file; raise RuntimeError if another live refresh holds it."""
    path = lock_path_for(checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prior = {}
        old_pid = int(prior.get("pid") or 0)
        if _pid_alive(old_pid):
            raise RuntimeError(
                f"Hint refresh already running (pid={old_pid}, lock={path})"
            )
    doc: Dict[str, Any] = {
        "pid": os.getpid(),
        "started_at_utc": _iso_now(),
        "checkpoint_path": checkpoint_path,
        "output_path": output_path,
        "chain": chain,
        "sources": list(sources),
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def release_hint_refresh_lock(checkpoint_path: str) -> None:
    path = lock_path_for(checkpoint_path)
    if not path.is_file():
        return
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if int(doc.get("pid") or 0) == os.getpid():
            path.unlink()
    except (json.JSONDecodeError, OSError):
        try:
            path.unlink()
        except OSError:
            pass
