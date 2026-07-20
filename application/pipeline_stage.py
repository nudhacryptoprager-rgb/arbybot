"""Typed pipeline stage definitions.

Extracted from ``start.py`` (control-plane split).  Each stage has a typed
input/output contract plus its own timeout and retry budget, instead of an
opaque dict threaded through the orchestrator.

``from_legacy_dict`` / ``to_legacy_dict`` keep 1:1 compatibility with the
dict shape produced by ``start._pipeline_step`` so the migration is
behavior-preserving.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

__all__ = ["PipelineStage", "StageResult"]


@dataclass(frozen=True)
class PipelineStage:
    """One pipeline step with typed contract and execution budget."""

    name: str
    cmd: Tuple[str, ...] = ()
    allow_exit_codes: Tuple[int, ...] = (0,)
    env: Dict[str, str] = field(default_factory=dict)
    timeout_seconds: Optional[int] = None
    retries: int = 0
    internal: Optional[str] = None
    inputs: Tuple[str, ...] = ()    # declared input artifacts (advisory)
    outputs: Tuple[str, ...] = ()   # declared output artifacts (advisory)

    @classmethod
    def from_legacy_dict(cls, step: Dict[str, Any]) -> "PipelineStage":
        return cls(
            name=str(step["name"]),
            cmd=tuple(step.get("cmd") or ()),
            allow_exit_codes=tuple(step.get("allow_exit_codes") or (0,)),
            env=dict(step.get("env") or {}),
            timeout_seconds=(
                int(step["timeout_seconds"])
                if step.get("timeout_seconds") is not None
                else None
            ),
            retries=int(step.get("retries") or 0),
            internal=step.get("internal"),
            inputs=tuple(step.get("inputs") or ()),
            outputs=tuple(step.get("outputs") or ()),
        )

    def to_legacy_dict(self) -> Dict[str, Any]:
        step: Dict[str, Any] = {
            "name": self.name,
            "cmd": list(self.cmd),
            "allow_exit_codes": tuple(self.allow_exit_codes),
            "env": dict(self.env),
        }
        if self.timeout_seconds is not None:
            step["timeout_seconds"] = int(self.timeout_seconds)
        if self.retries:
            step["retries"] = int(self.retries)
        if self.internal:
            step["internal"] = self.internal
        if self.inputs:
            step["inputs"] = list(self.inputs)
        if self.outputs:
            step["outputs"] = list(self.outputs)
        return step


@dataclass(frozen=True)
class StageResult:
    """Typed outcome of one stage execution."""

    name: str
    exit_code: int
    duration_s: float
    outcome: str  # "ok" | "allowed_exit" | "failed" | "timeout" | "stale_heartbeat"
    fail_reason: Optional[str] = None
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return self.outcome in ("ok", "allowed_exit")
