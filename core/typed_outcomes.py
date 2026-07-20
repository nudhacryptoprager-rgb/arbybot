"""Typed outcomes — reason codes, retryability and stage/provider context.

Replaces silent ``except Exception: pass`` degradation with an explicit
outcome taxonomy (production-readiness review): every failure carries

* ``reason_code`` — stable machine-readable code (e.g. ``RPC_RATE_LIMITED``);
* ``retryable`` — whether a retry is admissible for this class of failure;
* ``provider`` / ``stage`` — context for quarantine and RCA;
* ``detail`` — short human-readable message.

Contract: an unknown/unclassified exception maps to ``INTERNAL_UNKNOWN``
(non-retryable) and MUST surface as a stage ``FAILED`` outcome — it must
never silently produce a half-valid ``latest`` artifact.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

__all__ = [
    "Outcome",
    "ReasonCode",
    "outcome_from_exception",
    "outcome_from_http_status",
]


class ReasonCode:
    """Canonical reason codes (stable strings; additive-only contract)."""

    RPC_TIMEOUT = "RPC_TIMEOUT"
    RPC_REQUEST_TIMEOUT = "RPC_REQUEST_TIMEOUT"      # HTTP 408
    RPC_RATE_LIMITED = "RPC_RATE_LIMITED"            # HTTP 429
    RPC_SERVER_ERROR = "RPC_SERVER_ERROR"            # HTTP 5xx
    RPC_CONNECTION_ERROR = "RPC_CONNECTION_ERROR"
    REVERT = "REVERT"
    REVERT_NO_LIQUIDITY = "REVERT_NO_LIQUIDITY"
    STALE_BLOCK = "STALE_BLOCK"
    SCHEMA_CONFLICT = "SCHEMA_CONFLICT"
    ARTIFACT_IO_ERROR = "ARTIFACT_IO_ERROR"
    ARTIFACT_DECODE_ERROR = "ARTIFACT_DECODE_ERROR"
    INTERNAL_UNKNOWN = "INTERNAL_UNKNOWN"


# Retryability per reason code (explicit table; unknown -> not retryable).
_RETRYABLE: Dict[str, bool] = {
    ReasonCode.RPC_TIMEOUT: True,
    ReasonCode.RPC_REQUEST_TIMEOUT: True,
    ReasonCode.RPC_RATE_LIMITED: True,
    ReasonCode.RPC_SERVER_ERROR: True,
    ReasonCode.RPC_CONNECTION_ERROR: True,
    ReasonCode.REVERT: False,
    ReasonCode.REVERT_NO_LIQUIDITY: False,
    ReasonCode.STALE_BLOCK: False,
    ReasonCode.SCHEMA_CONFLICT: False,
    ReasonCode.ARTIFACT_IO_ERROR: False,
    ReasonCode.ARTIFACT_DECODE_ERROR: False,
    ReasonCode.INTERNAL_UNKNOWN: False,
}


@dataclass(frozen=True)
class Outcome:
    """Typed outcome of one operation."""

    ok: bool
    reason_code: Optional[str] = None
    retryable: bool = False
    provider: Optional[str] = None
    stage: Optional[str] = None
    detail: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, *, provider: Optional[str] = None, stage: Optional[str] = None) -> "Outcome":
        return cls(ok=True, provider=provider, stage=stage)

    @classmethod
    def failure(
        cls,
        reason_code: str,
        *,
        retryable: Optional[bool] = None,
        provider: Optional[str] = None,
        stage: Optional[str] = None,
        detail: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> "Outcome":
        return cls(
            ok=False,
            reason_code=reason_code,
            retryable=_RETRYABLE.get(reason_code, False) if retryable is None else retryable,
            provider=provider,
            stage=stage,
            detail=detail,
            extra=dict(extra or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason_code": self.reason_code,
            "retryable": self.retryable,
            "provider": self.provider,
            "stage": self.stage,
            "detail": self.detail,
            "extra": dict(self.extra),
        }


def outcome_from_http_status(
    status_code: int,
    *,
    provider: Optional[str] = None,
    stage: Optional[str] = None,
    detail: Optional[str] = None,
) -> Outcome:
    """Map an HTTP status code to a typed failure outcome."""
    if status_code == 408:
        code = ReasonCode.RPC_REQUEST_TIMEOUT
    elif status_code == 429:
        code = ReasonCode.RPC_RATE_LIMITED
    elif status_code >= 500:
        code = ReasonCode.RPC_SERVER_ERROR
    else:
        code = ReasonCode.INTERNAL_UNKNOWN
    return Outcome.failure(
        code,
        provider=provider,
        stage=stage,
        detail=detail or f"http_status={status_code}",
        extra={"http_status": status_code},
    )


def outcome_from_exception(
    exc: BaseException,
    *,
    provider: Optional[str] = None,
    stage: Optional[str] = None,
) -> Outcome:
    """Classify an exception into a typed outcome.

    Unknown exception types map to ``INTERNAL_UNKNOWN`` (non-retryable) —
    they must fail the stage, not degrade silently.
    """
    detail = f"{type(exc).__name__}: {exc}"[:300]

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return Outcome.failure(
            ReasonCode.RPC_TIMEOUT, provider=provider, stage=stage, detail=detail
        )
    if isinstance(exc, (ConnectionError, ConnectionResetError, ConnectionAbortedError)):
        return Outcome.failure(
            ReasonCode.RPC_CONNECTION_ERROR, provider=provider, stage=stage, detail=detail
        )
    if isinstance(exc, json.JSONDecodeError):
        return Outcome.failure(
            ReasonCode.ARTIFACT_DECODE_ERROR, provider=provider, stage=stage, detail=detail
        )
    if isinstance(exc, (OSError, IOError)):
        return Outcome.failure(
            ReasonCode.ARTIFACT_IO_ERROR, provider=provider, stage=stage, detail=detail
        )

    # httpx-style status errors (duck-typed to avoid a hard dependency).
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return outcome_from_http_status(
            status_code, provider=provider, stage=stage, detail=detail
        )
    if isinstance(exc, asyncio.CancelledError):
        return Outcome.failure(
            ReasonCode.RPC_TIMEOUT, provider=provider, stage=stage, detail=detail
        )
    return Outcome.failure(
        ReasonCode.INTERNAL_UNKNOWN, provider=provider, stage=stage, detail=detail
    )
