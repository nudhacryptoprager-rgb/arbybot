"""Unit tests for the promotion ladder (execution/promotion_ladder.py)."""
from __future__ import annotations

from execution.promotion_ladder import (
    RESILIENCE_CHECKS,
    LadderEvidence,
    evaluate_ladder)
from scripts.check_promotion_ladder import build_evidence


def _full_resilience() -> dict:
    return {name: True for name in RESILIENCE_CHECKS}


def test_research_is_default_stage():
    verdict = evaluate_ladder(LadderEvidence())
    assert verdict.current_stage == "research"
    assert verdict.next_stage == "shadow_soak"
    assert not verdict.promotion_allowed
    assert "CODE_GATES_NOT_PASS" in verdict.blockers
    assert not verdict.execution_unlock_allowed


def test_shadow_soak_reached_with_code_gates():
    verdict = evaluate_ladder(LadderEvidence(code_gates_pass=True))
    assert verdict.current_stage == "shadow_soak"
    assert verdict.next_stage == "simulation_canary"
    assert any(b.startswith("SHADOW_RUNS_LOW") for b in verdict.blockers)


def test_simulation_canary_requires_100_stable_shadow_runs():
    ev = LadderEvidence(
        code_gates_pass=True,
        shadow_runs=100,
        shadow_agg_status_pass=True,
        cycles_quoteable=3,
    )
    verdict = evaluate_ladder(ev)
    assert verdict.current_stage == "simulation_canary"
    assert any(b.startswith("SIM_POSITIVE_RUNS_LOW") for b in verdict.blockers)


def test_manual_canary_requires_5_positive_repeatable_sim_runs():
    ev = LadderEvidence(
        code_gates_pass=True,
        shadow_runs=120,
        shadow_agg_status_pass=True,
        cycles_quoteable=3,
        simulation_positive_runs=5,
        simulation_repeatable=True,
    )
    verdict = evaluate_ladder(ev)
    assert verdict.current_stage == "manual_single_trade_canary"
    # Next stage blocked by unproven resilience + missing human unlock.
    assert "HUMAN_UNLOCK_MISSING" in verdict.blockers
    assert any(b.startswith("RESILIENCE_UNPROVEN") for b in verdict.blockers)


def test_limited_production_requires_full_resilience_and_human_unlock():
    ev = LadderEvidence(
        code_gates_pass=True,
        shadow_runs=120,
        shadow_agg_status_pass=True,
        cycles_quoteable=3,
        simulation_positive_runs=5,
        simulation_repeatable=True,
        resilience=_full_resilience(),
        human_unlock=True,
    )
    verdict = evaluate_ladder(ev)
    assert verdict.current_stage == "limited_production"
    assert verdict.next_stage is None
    assert verdict.execution_unlock_allowed


def test_one_missing_resilience_check_blocks_unlock():
    resilience = _full_resilience()
    resilience["nonce_collision"] = False
    ev = LadderEvidence(
        code_gates_pass=True,
        shadow_runs=120,
        shadow_agg_status_pass=True,
        cycles_quoteable=3,
        simulation_positive_runs=5,
        simulation_repeatable=True,
        resilience=resilience,
        human_unlock=True,
    )
    verdict = evaluate_ladder(ev)
    assert not verdict.execution_unlock_allowed
    assert "RESILIENCE_UNPROVEN(nonce_collision)" in verdict.blockers


def test_execution_enabled_without_unlock_is_contract_violation():
    verdict = evaluate_ladder(LadderEvidence(execution_enabled=True))
    assert verdict.safety.get("contract_violation") == "EXECUTION_ENABLED_WITHOUT_UNLOCK"


def test_build_evidence_maps_rolling_artifacts():
    ev = build_evidence(
        stability={
            "agg_status": "PASS",
            "runs": [
                {"total_net_usdc": 1.5, "run_mode": "REGISTRY_REAL", "block_is_synthetic": False},
                {"total_net_usdc": -1.0, "run_mode": "REGISTRY_REAL", "block_is_synthetic": False},
                {"total_net_usdc": 9.9, "run_mode": "FIXTURE_OFFLINE", "block_is_synthetic": True},
            ],
        },
        run_summary={"metrics": {"kill_switch_active": True, "execution_enabled": False}},
        m9_acceptance={"quote_liveness_metrics": {"cycles_quoteable": 4}},
        resilience_doc={"checks": {"reorg_handling": True}, "human_unlock": False},
    )
    assert ev.code_gates_pass is True
    assert ev.shadow_runs == 3
    assert ev.simulation_positive_runs == 1  # fixture + negative excluded
    assert ev.cycles_quoteable == 4
    assert ev.resilience["reorg_handling"] is True
    assert ev.kill_switch_active is True
    assert ev.execution_enabled is False
