"""Checkpoint store — per-step .done/.fail markers + quiet-file watching.

Extracted from ``start.py`` (control-plane split).  Semantics are preserved
exactly:

* markers live under ``<markers_dir>[/<pipeline_mode>]/<step>.done|.fail``;
* ``pipeline_mode`` namespaces markers per lane so parallel plans do not
  collide;
* quiet child steps may refresh watched checkpoint files instead of writing
  stdout — ``checkpoint_activity_since`` detects that liveness.

Runtime-only: markers under ``data/tmp/start_pipeline_steps/`` are never
committed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

__all__ = [
    "CheckpointStore",
    "fingerprint_paths",
    "read_done_record",
    "write_done_record",
    "done_fingerprint_matches",
]


def fingerprint_paths(paths: Iterable[Union[str, Path]]) -> str:
    """Stable short fingerprint from file content (missing paths included)."""
    parts: List[str] = []
    for raw in sorted(str(p) for p in paths):
        path = Path(raw)
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            parts.append(f"{raw}:{digest}")
        else:
            parts.append(f"{raw}:missing")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def read_done_record(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"legacy": text, "fingerprint": None, "completed_at_utc": text}
    if isinstance(data, dict):
        return data
    return {"legacy": text, "fingerprint": None}


def write_done_record(path: Path, *, fingerprint: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fingerprint": fingerprint,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def done_fingerprint_matches(path: Path, expected: str) -> bool:
    rec = read_done_record(path)
    if not rec:
        return False
    return str(rec.get("fingerprint") or "") == expected


class CheckpointStore:
    """Filesystem checkpoint marker store for pipeline steps."""

    def __init__(self, markers_dir: Union[str, Path]) -> None:
        self.markers_dir = Path(markers_dir)

    # -- marker paths --------------------------------------------------------

    def marker_paths(
        self,
        step_name: str,
        *,
        pipeline_mode: Optional[str] = None,
    ) -> Tuple[Path, Path]:
        base = self.markers_dir
        if pipeline_mode:
            base = base / pipeline_mode
        base.mkdir(parents=True, exist_ok=True)
        return (
            base / f"{step_name}.done",
            base / f"{step_name}.fail",
        )

    # -- marker lifecycle -----------------------------------------------------

    def mark_done(self, step_name: str, *, pipeline_mode: Optional[str] = None) -> Path:
        done, fail = self.marker_paths(step_name, pipeline_mode=pipeline_mode)
        try:
            fail.unlink()
        except FileNotFoundError:
            pass
        done.write_text("done\n", encoding="utf-8")
        return done

    def mark_failed(self, step_name: str, *, pipeline_mode: Optional[str] = None) -> Path:
        done, fail = self.marker_paths(step_name, pipeline_mode=pipeline_mode)
        fail.write_text("failed\n", encoding="utf-8")
        return fail

    def is_done(self, step_name: str, *, pipeline_mode: Optional[str] = None) -> bool:
        done, _ = self.marker_paths(step_name, pipeline_mode=pipeline_mode)
        return done.exists()

    def clear_fail_markers(self, pipeline_mode: str, step_names: List[str]) -> int:
        """Drop prior .fail markers so aborted runs cannot block reruns."""
        cleared = 0
        for name in step_names:
            _, fail_marker = self.marker_paths(name, pipeline_mode=pipeline_mode)
            try:
                fail_marker.unlink()
                cleared += 1
            except FileNotFoundError:
                pass
        return cleared

    def clear_markers(self, pipeline_mode: str, step_names: Iterable[str]) -> int:
        """Drop both .done and .fail markers for the given steps."""
        cleared = 0
        for name in step_names:
            done_marker, fail_marker = self.marker_paths(name, pipeline_mode=pipeline_mode)
            for marker in (done_marker, fail_marker):
                try:
                    marker.unlink()
                    cleared += 1
                except FileNotFoundError:
                    pass
        return cleared

    # -- progress -------------------------------------------------------------

    def collect_progress(
        self,
        step_names: List[str],
        *,
        pipeline_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        done_steps: List[str] = []
        failed_steps: List[str] = []
        for name in step_names:
            done_marker, fail_marker = self.marker_paths(name, pipeline_mode=pipeline_mode)
            if done_marker.exists():
                done_steps.append(name)
            elif fail_marker.exists():
                failed_steps.append(name)
        return {
            "done_steps": done_steps,
            "failed_steps": failed_steps,
            "done_count": len(done_steps),
            "failed_count": len(failed_steps),
            "marker_namespace": pipeline_mode,
        }

    # -- quiet-step liveness ---------------------------------------------------

    @staticmethod
    def checkpoint_activity_since(
        watched_paths: Iterable[Union[str, Path]],
        since_wall_ts: float,
    ) -> bool:
        """True when any watched checkpoint file was touched after the step started."""
        for rel in watched_paths:
            path = Path(rel)
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime >= since_wall_ts - 1.0:
                    return True
            except OSError:
                continue
        return False
