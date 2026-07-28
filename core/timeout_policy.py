"""Timeout policy: RPC/work-item only — no global service caps in continuous mode."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from core.pipeline_runtime_config import PipelineRuntimeConfig, TimeoutConfig


@dataclass(frozen=True)
class TimeoutPolicy:
    rpc_timeout_s: float
    work_item_lease_s: float
    retry_budget: int
    heartbeat_stale_s: float
    continuous_mode: bool = False

    @classmethod
    def from_config(
        cls,
        config: PipelineRuntimeConfig,
        *,
        continuous: bool,
    ) -> "TimeoutPolicy":
        t = config.timeouts
        return cls(
            rpc_timeout_s=t.rpc_timeout_s,
            work_item_lease_s=t.work_item_lease_s,
            retry_budget=t.retry_budget,
            heartbeat_stale_s=t.heartbeat_stale_s,
            continuous_mode=continuous,
        )


def resolve_step_timeout_seconds(
    step: dict[str, Any],
    *,
    policy: TimeoutPolicy,
    config: PipelineRuntimeConfig,
    batch_index: int = 1,
) -> Optional[int]:
    """Return pipeline wrapper timeout for a step, or ``None`` (no global cap)."""
    if policy.continuous_mode:
        return None

    explicit = step.get("timeout_seconds")
    if explicit is not None:
        return int(explicit)

    name = str(step.get("name") or "")
    if name.startswith("m8_sniper_acceptance_batch_"):
        from core.pipeline_streaming import resolve_sniper_batch_step_timeout_s

        batch_minutes = int(config.sniper_batch_minutes)
        return resolve_sniper_batch_step_timeout_s(
            batch_minutes,
            batch_index=int(name.rsplit("_", 1)[-1]),
            timeout_config=config.timeouts,
        )

    if config.step_timeout_s is not None:
        return int(config.step_timeout_s)
    return None


def resolve_batched_sniper_timeout_s(
    batch_minutes: int,
    *,
    batch_index: int,
    timeout_config: TimeoutConfig,
) -> int:
    from core.pipeline_streaming import resolve_sniper_batch_step_timeout_s

    return resolve_sniper_batch_step_timeout_s(
        batch_minutes,
        batch_index=batch_index,
        timeout_config=timeout_config,
    )
