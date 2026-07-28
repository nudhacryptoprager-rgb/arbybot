"""Quote-size truth helpers: liveness vs economics ladders."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

# Sizes at or below this USD notional are liveness probes only.
LIVENESS_MAX_SIZE_USD: float = 5.0

_DEFAULT_CONFIG_PATH = "config/exotic_base_anchor.yaml"

ECONOMICS_INPUT_UNAVAILABLE = "ECONOMICS_INPUT_UNAVAILABLE"


class EconomicsInputUnavailable(RuntimeError):
    """Raised when production economics inputs are missing (no synthetic fallback)."""

    code = ECONOMICS_INPUT_UNAVAILABLE

KNOWN_ECONOMICS_PROFILES: Tuple[str, ...] = (
    "production_conservative",
    "base_realistic",
    "diagnostic_near_econ",
)


def is_patient_lane_mode() -> bool:
    """Thin-liquidity diagnostic lane: depth-aware sizing, no profit claims."""
    return os.environ.get("ARBY_M9_PATIENT_LANE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def economic_size_floor_usd(
    *,
    gas_usd: float = 0.05,
    l1_fee_usd: float = 0.01,
    slippage_bps: float = 5.0,
    target_net_bps: float = 10.0,
    safety_factor: float = 1.5,
    min_floor_usd: float = 25.0,
    economics_floor_usd: Optional[float] = None,
) -> float:
    """Minimum notional so fixed gas/L1 is not dominant vs target net edge."""
    if economics_floor_usd is not None:
        return round(max(min_floor_usd, float(economics_floor_usd)), 2)
    if target_net_bps <= slippage_bps:
        return max(min_floor_usd, 100.0)
    fixed = max(gas_usd + l1_fee_usd, 0.0)
    variable_budget_bps = target_net_bps - slippage_bps
    if variable_budget_bps <= 0:
        return max(min_floor_usd, 100.0)
    raw = fixed / (variable_budget_bps / 10_000.0) * safety_factor
    return round(max(min_floor_usd, raw), 2)


def load_cost_model(config_path: str = _DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """Load ``cost_model`` section from M9 YAML config."""
    path = Path(config_path)
    if not path.is_file():
        return {}
    try:
        import yaml

        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        cm = raw.get("cost_model") or {}
        return dict(cm) if isinstance(cm, dict) else {}
    except Exception:
        return {}


def resolve_active_economics_profile_name(
    cost_model: Optional[Dict[str, Any]] = None,
) -> str:
    env = (os.environ.get("ARBY_M9_ECONOMICS_PROFILE") or "").strip()
    if env:
        return env
    cm = cost_model or {}
    return str(cm.get("default_profile") or "production_conservative")


def _economics_fallback_allowed() -> bool:
    if os.environ.get("ARBY_ECONOMICS_STRICT", "1").strip().lower() in ("0", "false", "no"):
        return True
    try:
        from core.pipeline_runtime_config import load_pipeline_runtime_config

        return bool(load_pipeline_runtime_config().economics.fallback_allowed)
    except Exception:
        return False


def require_cost_model(config_path: str = _DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """Load cost model or fail closed for production paths."""
    cm = load_cost_model(config_path)
    if not cm and not _economics_fallback_allowed():
        raise EconomicsInputUnavailable(ECONOMICS_INPUT_UNAVAILABLE)
    return cm


def profile_params(profile: Optional[Dict[str, Any]]) -> Dict[str, float]:
    p = profile or {}
    out: Dict[str, float] = {
        "gas_usd": float(p.get("gas_usd", 0.05)),
        "l1_fee_usd": float(p.get("l1_fee_usd", 0.01)),
        "slippage_bps": float(p.get("slippage_bps", 5.0)),
        "target_net_bps": float(p.get("target_net_bps", 10.0)),
        "safety_factor": float(p.get("safety_factor", 1.5)),
        "min_floor_usd": float(p.get("min_floor_usd", 25.0)),
    }
    if p.get("economics_floor_usd") is not None:
        out["economics_floor_usd"] = float(p["economics_floor_usd"])
    return out


def economic_size_floor_for_profile(
    cost_model: Optional[Dict[str, Any]],
    profile_name: str,
) -> float:
    cm = cost_model or {}
    profiles = cm.get("profiles") or {}
    prof = profiles.get(profile_name) or profiles.get("default") or {}
    params = profile_params(prof)
    override = params.pop("economics_floor_usd", None)
    return economic_size_floor_usd(economics_floor_usd=override, **params)


def economics_profile_specs(
    cost_model: Optional[Dict[str, Any]] = None,
    *,
    config_path: str = _DEFAULT_CONFIG_PATH,
) -> Dict[str, Dict[str, Any]]:
    """Return named economics profiles with computed floors and metadata."""
    cm = cost_model if cost_model is not None else require_cost_model(config_path)
    profiles = cm.get("profiles") or {}
    meta = cm.get("economics_profiles") or {}
    names = list(meta.keys()) or list(KNOWN_ECONOMICS_PROFILES)
    out: Dict[str, Dict[str, Any]] = {}
    for name in names:
        prof = profiles.get(name) or profiles.get("default") or {}
        params = profile_params(prof)
        floor = economic_size_floor_for_profile(cm, name)
        m = dict(meta.get(name) or {})
        out[name] = {
            **params,
            "economics_floor_usd": floor,
            "profit_claim_allowed": bool(m.get("profit_claim_allowed", name != "diagnostic_near_econ")),
            "profit_claim_mode": str(m.get("profit_claim_mode") or "immediate"),
            "role": m.get("role", "production"),
        }
    return out


def split_liveness_econ_sizes(
    sizes_usd: Sequence[float],
    econ_floor_usd: float,
) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    """Partition a size ladder into liveness probes and economics sizes."""
    liveness = tuple(sorted({float(s) for s in sizes_usd if float(s) <= LIVENESS_MAX_SIZE_USD}))
    econ = tuple(sorted({float(s) for s in sizes_usd if float(s) >= econ_floor_usd}))
    return liveness, econ


def is_liveness_size(size_usd: float) -> bool:
    return float(size_usd) <= LIVENESS_MAX_SIZE_USD


def is_econ_size(size_usd: float, econ_floor_usd: float) -> bool:
    return float(size_usd) >= float(econ_floor_usd)


def quote_size_truth_metrics(
    cycle_results: Sequence[Any],
    *,
    econ_floor_usd: float,
    liveness_max_size_usd: float = LIVENESS_MAX_SIZE_USD,
) -> Dict[str, Any]:
    """Histograms for attempted/selected quote sizes vs economics floor."""
    from collections import Counter

    from m9.graph_arb.cycle_capacity import (
        is_econ_gate_attempt,
        is_econ_rpc_quote_attempt,
    )

    attempted: Counter[str] = Counter()
    selected: Counter[str] = Counter()
    below_econ = 0
    liveness_attempts = 0
    econ_attempts = 0
    econ_gate_attempts = 0
    econ_rpc_quote_attempts = 0
    for qr in cycle_results:
        sz = round(float(getattr(qr, "size_usd", 0.0) or 0.0), 4)
        key = str(sz)
        attempted[key] += 1
        if is_liveness_size(sz):
            liveness_attempts += 1
        if is_econ_size(sz, econ_floor_usd):
            econ_attempts += 1
            if is_econ_gate_attempt(qr, econ_floor_usd):
                econ_gate_attempts += 1
            if is_econ_rpc_quote_attempt(qr, econ_floor_usd):
                econ_rpc_quote_attempts += 1
        if sz < econ_floor_usd:
            below_econ += 1
        status = getattr(qr, "status", "")
        if status in ("POSITIVE_GROSS", "NEGATIVE_GROSS"):
            selected[key] += 1
    return {
        "liveness_max_size_usd": liveness_max_size_usd,
        "economic_size_floor_usd": econ_floor_usd,
        "econ_floor_usd": econ_floor_usd,
        "liveness_quote_attempts": liveness_attempts,
        "econ_quote_attempts": econ_attempts,
        "econ_gate_attempts": econ_gate_attempts,
        "econ_rpc_quote_attempts": econ_rpc_quote_attempts,
        "below_econ_quote_attempts": below_econ,
        "attempted_size_usd_histogram": dict(sorted(attempted.items(), key=lambda kv: float(kv[0]))),
        "selected_size_usd_histogram": dict(sorted(selected.items(), key=lambda kv: float(kv[0]))),
    }


def cost_profile_from_model(cost_model: Optional[Dict]) -> Dict[str, float]:
    if not cost_model:
        return profile_params({})
    profile_name = resolve_active_economics_profile_name(cost_model)
    profile = (cost_model.get("profiles") or {}).get(profile_name) or {}
    if not profile:
        profile = (cost_model.get("profiles") or {}).get("default") or {}
    return profile_params(profile)


def active_economics_floor_usd(
    cost_model: Optional[Dict] = None,
    *,
    config_path: str = _DEFAULT_CONFIG_PATH,
) -> float:
    cm = cost_model if cost_model is not None else load_cost_model(config_path)
    name = resolve_active_economics_profile_name(cm)
    return economic_size_floor_for_profile(cm, name)


def economics_profile_context(
    *,
    cost_model: Optional[Dict] = None,
    config_path: str = _DEFAULT_CONFIG_PATH,
    profile_name: Optional[str] = None,
    shadow: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Active economics profile metadata for acceptance / operator reports."""
    cm = cost_model if cost_model is not None else load_cost_model(config_path)
    name = profile_name or resolve_active_economics_profile_name(cm)
    specs = economics_profile_specs(cm, config_path=config_path)
    spec = dict(specs.get(name) or {})
    floor = float(spec.get("economics_floor_usd") or active_economics_floor_usd(cm))
    claim_mode = str(spec.get("profit_claim_mode") or "immediate")
    claim_allowed = bool(spec.get("profit_claim_allowed", False))
    patient_lane = is_patient_lane_mode()
    if patient_lane:
        claim_allowed = False
    qst = (shadow or {}).get("quote_size_truth") or {}
    econ_rpc = int(qst.get("econ_rpc_quote_attempts") or 0)
    pos_gross = int((shadow or {}).get("cycles_positive_gross") or 0)
    if not claim_allowed or spec.get("role") == "diagnostic":
        claim_status = "denied"
    elif claim_mode == "runtime_conditional":
        if econ_rpc > 0 and pos_gross > 0:
            claim_status = "allowed"
        else:
            claim_status = "runtime_conditional"
    elif econ_rpc > 0:
        claim_status = "allowed" if pos_gross > 0 else "market_blocked"
    else:
        claim_status = "runtime_conditional"
    if patient_lane:
        claim_status = "denied_patient_lane"
    return {
        "active_economics_profile": name,
        "economics_floor_usd": floor,
        "profit_claim_allowed": claim_allowed,
        "profit_claim_mode": claim_mode,
        "profit_claim_status": claim_status,
        "role": spec.get("role", "production"),
        "patient_lane": patient_lane,
        "patient_lane_profit_claim_allowed": False if patient_lane else claim_allowed,
    }
