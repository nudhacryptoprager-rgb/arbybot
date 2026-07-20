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

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

__all__ = ["CheckpointStore"]


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
