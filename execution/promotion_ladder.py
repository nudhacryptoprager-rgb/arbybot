"""Promotion ladder — staged path from research to limited production.

Canonical ladder (production-readiness review)::

    research -> shadow_soak -> simulation_canary
             -> manual_single_trade_canary -> limited_production

Rules:

* Promotion is earned only by *evidence* (metrics from fresh runtime
  artifacts), never by declaration.
* Auto-execution stays forbidden until: repeated positive simulation is
  proven, every resilience check passes, and an explicit human unlock is
  recorded.  ``execution_enabled=false`` / ``kill_switch_active=true`` are
  the default and are asserted by the ladder verdict.
* Resilience checks required before limited production: reorg handling,
  duplicate events, nonce collision, replacement transaction, receipt
  timeout, partial provider outage, decimals conflict, kill-switch
  recovery.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    "STAGES",
    "RESILIENCE_CHECKS",
    "LadderEvidence",
    "LadderVerdict",
    "evaluate_ladder",
]

STAGES = (
    "research",
    "shadow_soak",
    "simulation_canary",
    "manual_single_trade_canary",
    "limited_production",
)

RESILIENCE_CHECKS = (
    "reorg_handling",
    "duplicate_events",
    "nonce_collision",
    "replacement_transaction",
    "receipt_timeout",
    "partial_provider_outage",
    "decimals_conflict",
    "kill_switch_recovery",
)

# Promotion thresholds (aligned with Roadmap M4.1/M4 online DoD).
_SHADOW_RUNS_MIN = 100            # M4.1: N>=100 consecutive stable shadow runs
_SIM_POSITIVE_RUNS_MIN = 5        # M4 online DoD: N=5 positive runs


@dataclass(frozen=True)
class LadderEvidence:
    """Evidence snapshot evaluated by the ladder."""

    # research
    code_gates_pass: bool = False
    # shadow soak
    shadow_runs: int = 0
    shadow_agg_status_pass: bool = False
    cycles_quoteable: int = 0
    # simulation canary
    simulation_positive_runs: int = 0
    simulation_repeatable: bool = False
    # resilience matrix (missing check = not proven)
    resilience: Dict[str, bool] = field(default_factory=dict)
    # operator flags
    kill_switch_active: bool = True
    execution_enabled: bool = False
    human_unlock: bool = False


@dataclass(frozen=True)
class LadderVerdict:
    current_stage: str
    next_stage: Optional[str]
    promotion_allowed: bool
    blockers: List[str]
    execution_unlock_allowed: bool
    safety: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_stage": self.current_stage,
            "next_stage": self.next_stage,
            "promotion_allowed": self.promotion_allowed,
            "blockers": list(self.blockers),
            "execution_unlock_allowed": self.execution_unlock_allowed,
            "safety": dict(self.safety),
        }


def _shadow_soak_entry(ev: LadderEvidence) -> List[str]:
    return [] if ev.code_gates_pass else ["CODE_GATES_NOT_PASS"]


def _simulation_canary_entry(ev: LadderEvidence) -> List[str]:
    blockers: List[str] = []
    if ev.shadow_runs < _SHADOW_RUNS_MIN:
        blockers.append(f"SHADOW_RUNS_LOW({ev.shadow_runs}<{_SHADOW_RUNS_MIN})")
    if not ev.shadow_agg_status_pass:
        blockers.append("SHADOW_AGG_NOT_PASS")
    if ev.cycles_quoteable <= 0:
        blockers.append("NO_QUOTEABLE_CYCLES")
    return blockers


def _manual_canary_entry(ev: LadderEvidence) -> List[str]:
    blockers: List[str] = []
    if ev.simulation_positive_runs < _SIM_POSITIVE_RUNS_MIN:
        blockers.append(
            f"SIM_POSITIVE_RUNS_LOW({ev.simulation_positive_runs}<{_SIM_POSITIVE_RUNS_MIN})"
        )
    if not ev.simulation_repeatable:
        blockers.append("SIMULATION_NOT_REPEATABLE")
    return blockers


def _limited_production_entry(ev: LadderEvidence) -> List[str]:
    blockers = [
        f"RESILIENCE_UNPROVEN({name})"
        for name in RESILIENCE_CHECKS
        if not ev.resilience.get(name, False)
    ]
    if not ev.human_unlock:
        blockers.append("HUMAN_UNLOCK_MISSING")
    return blockers


_STAGE_ENTRY = {
    "shadow_soak": _shadow_soak_entry,
    "simulation_canary": _simulation_canary_entry,
    "manual_single_trade_canary": _manual_canary_entry,
    "limited_production": _limited_production_entry,
}


def evaluate_ladder(evidence: LadderEvidence) -> LadderVerdict:
    """Evaluate the current ladder position from evidence.

    The current stage is the highest stage whose entry criteria are met
    (``research`` always holds).  ``promotion_allowed`` is True when the
    next stage's entry criteria are already satisfied by the evidence.
    """
    current = "research"
    for stage in STAGES[1:]:
        if not _STAGE_ENTRY[stage](evidence):
            current = stage
        else:
            break

    idx = STAGES.index(current)
    next_stage: Optional[str] = STAGES[idx + 1] if idx + 1 < len(STAGES) else None
    blockers: List[str] = (
        list(_STAGE_ENTRY[next_stage](evidence)) if next_stage is not None else []
    )
    promotion_allowed = next_stage is not None and not blockers

    # Auto-execution unlock: only at limited production entry readiness,
    # with every resilience check proven and an explicit human unlock.
    unlock_blockers = _limited_production_entry(evidence)
    execution_unlock_allowed = (
        not unlock_blockers
        and evidence.simulation_positive_runs >= _SIM_POSITIVE_RUNS_MIN
        and evidence.simulation_repeatable
    )

    safety = {
        "kill_switch_active": evidence.kill_switch_active,
        "execution_enabled": evidence.execution_enabled,
        "human_unlock": evidence.human_unlock,
        "resilience_proven": {
            name: bool(evidence.resilience.get(name, False)) for name in RESILIENCE_CHECKS
        },
        "thresholds": {
            "shadow_runs_min": _SHADOW_RUNS_MIN,
            "sim_positive_runs_min": _SIM_POSITIVE_RUNS_MIN,
        },
        "policy": (
            "auto-execution forbidden until repeated positive simulation, "
            "all resilience checks, and explicit human unlock"
        ),
    }
    if evidence.execution_enabled and not execution_unlock_allowed:
        # Contract violation: execution must never be enabled without unlock.
        safety["contract_violation"] = "EXECUTION_ENABLED_WITHOUT_UNLOCK"

    return LadderVerdict(
        current_stage=current,
        next_stage=next_stage,
        promotion_allowed=promotion_allowed,
        blockers=blockers,
        execution_unlock_allowed=execution_unlock_allowed,
        safety=safety,
    )
