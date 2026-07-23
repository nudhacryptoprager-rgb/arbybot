"""Typed pipeline stage definitions.

Extracted from ``start.py`` (control-plane split).  Each stage has a typed
input/output contract plus its own timeout and retry budget, instead of an
opaque dict threaded through the orchestrator.

``from_legacy_dict`` / ``to_legacy_dict`` keep 1:1 compatibility with the
dict shape produced by ``start._pipeline_step`` so the migration is
behavior-preserving.

Step 7 fix (production-readiness review): ``StageResult`` carries an
optional ``typed_outcome`` field (a ``core.typed_outcomes.Outcome``) so a
non-retryable failure raised inside a stage can be surfaced as ``FAILED``
instead of silently becoming "no data". The string ``outcome`` field keeps
the legacy taxonomy (``ok`` / ``allowed_exit`` / ``failed`` / ``timeout``
/ ``stale_heartbeat``) for callers that already key off it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from core.typed_outcomes import Outcome, ReasonCode

__all__ = ["PipelineStage", "StageResult", "classify_typed_outcome"]


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
    # Step 7 fix: typed outcome from core.typed_outcomes, set by the runner
    # for batches that were dominated by non-retryable failures. None when
    # the stage succeeded or failed with only retryable transient errors.
    typed_outcome: Optional[Outcome] = None

    @property
    def ok(self) -> bool:
        return self.outcome in ("ok", "allowed_exit")

    @property
    def hard_failure(self) -> bool:
        """True when ``typed_outcome`` is a non-retryable, propagated failure
        (e.g. ``INTERNAL_UNKNOWN`` or ``SCHEMA_CONFLICT``). Retryable transient
        outcomes (rate-limited, timeout) stay False so the caller can issue
        another bounded retry rather than failing the whole pipeline."""
        if self.typed_outcome is None:
            return False
        return (not self.typed_outcome.ok) and (not self.typed_outcome.retryable)


def classify_typed_outcome(
    exit_code: int,
    fail_reason: Optional[str],
    typed_failures: Optional[list] = None,
) -> Optional[Outcome]:
    """Map a stage exit code + fail_reason + recorded typed outcomes to a
    single representative ``Outcome``.

    Priority:
      1. Hard subprocess signature (timeout / stale heartbeat) -> retryable
         ``RPC_TIMEOUT`` (the stage was killed by the runner; the underlying
         RPC may have been rate-limited, but the operator-visible failure here
         is a timeout of the stage itself, which *is* retryable up to the
         retry budget declared on the stage).
      2. Non-zero exit code with no recorded typed outcomes -> ambiguous
         ``INTERNAL_UNKNOWN`` (non-retryable): the runner has no further
         evidence, so a downstream stage must not treat this as "no data".
      3. Recorded typed outcomes (e.g. ``AsyncRpcBatchClient.last_outcomes``):
         pick the highest-severity (non-retryable) one; if only retryable
         outcomes appear, return the most-recent retryable one so the stage
         result looks like a bounded retry instead of a hard failure.
    """
    if fail_reason is not None:
        if "hard_timeout" in fail_reason or "stale_heartbeat" in fail_reason:
            return Outcome.failure(
                ReasonCode.RPC_TIMEOUT, detail=fail_reason, retryable=True
            )
    if exit_code == 0:
        return Outcome.success()
    typed_failures = typed_failures or []
    non_retryable = [o for o in typed_failures if not getattr(o, "retryable", True)]
    if non_retryable:
        return non_retryable[-1]
    retryable = [o for o in typed_failures if getattr(o, "retryable", True)]
    if retryable:
        return retryable[-1]
    return Outcome.failure(ReasonCode.INTERNAL_UNKNOWN, detail=f"exit_code={exit_code}")
