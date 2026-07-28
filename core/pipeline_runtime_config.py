"""Load ``config/pipeline_runtime.yaml`` with optional CLI overrides."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

_DEFAULT_CONFIG_PATH = Path("config/pipeline_runtime.yaml")


@dataclass(frozen=True)
class TimeoutConfig:
    rpc_timeout_s: float = 45.0
    work_item_lease_s: float = 300.0
    retry_budget: int = 3
    heartbeat_stale_s: float = 300.0
    sniper_batch_timeout_factor: float = 1.47
    sniper_self_test_budget_s: int = 900
    sniper_startup_grace_s: int = 120


@dataclass(frozen=True)
class ShadowConfig:
    duration_minutes: int = 10
    max_cycles_per_sweep: int = 20
    quote_workers: int = 1


@dataclass(frozen=True)
class EconomicsConfig:
    require_config: bool = True
    config_path: str = "config/exotic_base_anchor.yaml"
    fallback_allowed: bool = False


@dataclass(frozen=True)
class PipelineRuntimeConfig:
    schema_version: str = "pipeline_runtime.1"
    mode_default: str = "continuous"
    sniper_minutes_default: Optional[int] = None
    sniper_batch_minutes: int = 15
    streaming_total_minutes: Optional[int] = None
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    workers: Dict[str, Any] = field(default_factory=dict)
    shadow: ShadowConfig = field(default_factory=ShadowConfig)
    token_concurrency: int = 4
    max_radar_tokens: int = 753
    step_timeout_s: Optional[int] = None
    economics: EconomicsConfig = field(default_factory=EconomicsConfig)
    m9_trigger_event: str = "quote_ready"


def _as_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "none", "null", "unlimited"}:
        return None
    return int(value)


def load_pipeline_runtime_config(
    path: str | Path = _DEFAULT_CONFIG_PATH,
    *,
    overrides: Optional[Dict[str, Any]] = None,
) -> PipelineRuntimeConfig:
    cfg_path = Path(path)
    raw: Dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            import yaml

            with cfg_path.open(encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh) or {}
            raw = dict(loaded) if isinstance(loaded, dict) else {}
        except Exception:
            raw = {}

    if overrides:
        for key, value in overrides.items():
            if value is not None:
                raw[key] = value

    orch = raw.get("orchestration") or {}
    timeouts_raw = raw.get("timeouts") or {}
    shadow_raw = raw.get("shadow") or {}
    limits = raw.get("limits") or {}
    economics_raw = raw.get("economics") or {}
    workers = dict(raw.get("workers") or {})

    timeouts = TimeoutConfig(
        rpc_timeout_s=float(timeouts_raw.get("rpc_timeout_s", 45)),
        work_item_lease_s=float(timeouts_raw.get("work_item_lease_s", 300)),
        retry_budget=int(timeouts_raw.get("retry_budget", 3)),
        heartbeat_stale_s=float(timeouts_raw.get("heartbeat_stale_s", 300)),
        sniper_batch_timeout_factor=float(
            timeouts_raw.get("sniper_batch_timeout_factor", 1.47)
        ),
        sniper_self_test_budget_s=int(
            timeouts_raw.get("sniper_self_test_budget_s", 900)
        ),
        sniper_startup_grace_s=int(timeouts_raw.get("sniper_startup_grace_s", 120)),
    )
    shadow = ShadowConfig(
        duration_minutes=int(shadow_raw.get("duration_minutes", 10)),
        max_cycles_per_sweep=int(shadow_raw.get("max_cycles_per_sweep", 20)),
        quote_workers=int(shadow_raw.get("quote_workers", 1)),
    )
    economics = EconomicsConfig(
        require_config=bool(economics_raw.get("require_config", True)),
        config_path=str(economics_raw.get("config_path", "config/exotic_base_anchor.yaml")),
        fallback_allowed=bool(economics_raw.get("fallback_allowed", False)),
    )
    m9_trigger = str(
        workers.get("m9_trigger_event")
        or (workers.get("m9_graph_quote") or {}).get("trigger_on")
        or "quote_ready"
    )

    return PipelineRuntimeConfig(
        schema_version=str(raw.get("schema_version", "pipeline_runtime.1")),
        mode_default=str(orch.get("mode_default", "continuous")),
        sniper_minutes_default=_as_int_or_none(orch.get("sniper_minutes_default")),
        sniper_batch_minutes=int(orch.get("sniper_batch_minutes", 15)),
        streaming_total_minutes=_as_int_or_none(orch.get("streaming_total_minutes")),
        timeouts=timeouts,
        workers=workers,
        shadow=shadow,
        token_concurrency=int(limits.get("token_concurrency", 4)),
        max_radar_tokens=int(limits.get("max_radar_tokens", 753)),
        step_timeout_s=_as_int_or_none(limits.get("step_timeout_s")),
        economics=economics,
        m9_trigger_event=m9_trigger,
    )


def resolve_sniper_minutes_from_config(
    requested: Optional[int],
    *,
    config: PipelineRuntimeConfig,
    continuous: bool,
) -> Optional[int]:
    """``None`` means unbounded until process stop (continuous mode)."""
    if requested is not None:
        return max(1, int(requested)) if int(requested) > 0 else None
    if continuous:
        return config.sniper_minutes_default
    default = config.sniper_minutes_default
    if default is None:
        return 45
    return default
