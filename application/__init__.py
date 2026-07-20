"""Application layer — pipeline control plane.

Canonical home for the M8/M9 pipeline control plane extracted from
``start.py``: checkpoint store, typed stage definitions and the stage
runner.  ``start.py`` keeps CLI/argparse and delegates here.

Boundary rule: this package must not import ``scripts.*`` or milestone
packages (``m8*``, ``m9``); it is orchestration infrastructure only.
"""
from __future__ import annotations

from application.checkpoint_store import CheckpointStore
from application.pipeline_stage import PipelineStage, StageResult

__all__ = [
    "CheckpointStore",
    "PipelineStage",
    "StageResult",
]
