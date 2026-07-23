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
    # No M9 shadow artifacts supplied -> fallback to M4 stability runs count.
    assert ev.shadow_runs == 3
    assert ev.simulation_positive_runs == 1  # fixture + negative excluded
    assert ev.cycles_quoteable == 4
    assert ev.resilience["reorg_handling"] is True
    assert ev.kill_switch_active is True
    assert ev.execution_enabled is False


def test_build_evidence_reads_canonical_net_usdc_field_not_synthetic_total():
    """Step 9 golden regression: the real canonical m4_stability_agg.json
    artifact stores net profit under ``net_usdc`` (not the legacy
    ``total_net_usdc`` the previous mapper queried). The golden fixture
    ``m4_stability_agg_promotion_golden.json`` mirrors that real shape —
    three REGISTRY_REAL positive runs (12.34, 5.43, 18.99), one REGISTRY_REAL
    negative run (-2.5), and one FIXTURE_OFFLINE 100.0 run (must NOT count).

    simulate-only M4.1 positive count = 3 (positive net_usdc on real blocks).
    """
    import json
    from pathlib import Path

    golden = Path("docs/artifacts/golden/m4_stability_agg_promotion_golden.json")
    stability = json.loads(golden.read_text(encoding="utf-8"))
    ev = build_evidence(
        stability=stability,
        run_summary={"metrics": {"kill_switch_active": True, "execution_enabled": False}},
        m9_acceptance=None,
        resilience_doc=None,
    )
    # Regression: previous mapper read ``total_net_usdc`` and so ALWAYS returned 0
    # here. With this fix the canonical ``net_usdc`` field is read.
    assert ev.simulation_positive_runs == 3
    assert ev.code_gates_pass is True
    # The fixture-offline synthetic-block run must NOT count toward
    # simulation_positive_runs even though its net_usdc is positive.
    assert ev.simulation_positive_runs != 4  # would have been wrong: 3+1
    # Audit fields record the M4/M9 split (Step 9 fix).
    assert ev.extra["m4_stability_run_count"] == 5
    assert ev.extra["m9_shadow_run_count"] == 0
    assert ev.extra["shadow_runs_source"] == "m4_stability_legacy_fallback"


def test_build_evidence_uses_m9_shadow_when_supplied():
    """Step 9 fix: ``shadow_runs`` MUST track M9 shadow soak, not M4
    stability. When M9 shadow artifacts are supplied (and they completed a
    full duration-fufilled run), they override the M4 stability fallback
    for ``shadow_runs``."""
    import json
    from pathlib import Path

    stability = json.loads(
        Path("docs/artifacts/golden/m4_stability_agg_promotion_golden.json").read_text(
            encoding="utf-8"
        )
    )
    m9_shadow = json.loads(
        Path("docs/artifacts/golden/m9_shadow_promotion_golden.json").read_text(
            encoding="utf-8"
        )
    )
    ev = build_evidence(
        stability=stability,
        run_summary={"metrics": {"kill_switch_active": True}},
        m9_acceptance={"quote_liveness_metrics": {"cycles_quoteable": 225}},
        resilience_doc=None,
        m9_shadow_artifacts=[m9_shadow, m9_shadow],  # two completed M9 runs
    )
    # shadow_runs source = M9 shadow soak, NOT m4 stability counts.
    assert ev.shadow_runs == 2
    assert ev.extra["m9_shadow_run_count"] == 2
    assert ev.extra["shadow_runs_source"] == "m9_shadow"
    assert ev.extra["m4_stability_run_count"] == 5  # diagnostic, separate


def test_build_evidence_ignores_non_completed_or_unfulfilled_m9_shadow():
    """STARTING/in-flight shadow artifacts must not count toward shadow
    soak promotion evidence even though the file exists."""
    in_flight = {
        "runner_outcome": "STARTING",
        "duration_fulfilled": False,
        "cycles_found": 0,
    }
    ev = build_evidence(
        stability={"agg_status": "PASS", "runs": [{"net_usdc": 1, "run_mode": "REGISTRY_REAL", "block_is_synthetic": False}]},
        run_summary=None,
        m9_acceptance=None,
        resilience_doc=None,
        m9_shadow_artifacts=[in_flight],
    )
    # In-flight M9 must not count; fallback to M4 stability runs (1).
    assert ev.shadow_runs == 1
    assert ev.extra["m9_shadow_run_count"] == 0
    assert ev.extra["shadow_runs_source"] == "m4_stability_legacy_fallback"


def test_build_evidence_net_usdc_with_legacy_total_net_usdc_fallback():
    """Legacy fixtures (with ``total_net_usdc`` only) keep working — the
    canonical field wins when present; the legacy field is read only when
    the canonical one is missing."""
    runs = [
        # canonical path
        {"net_usdc": 2.0, "run_mode": "REGISTRY_REAL", "block_is_synthetic": False},
        # legacy/missing canonical path falls back to total_net_usdc
        {"total_net_usdc": 3.0, "run_mode": "REGISTRY_REAL", "block_is_synthetic": False},
        # both fields present -> canonical wins (this run's profit IS 5.5,
        # not the legacy 100.0)
        {
            "net_usdc": 5.5,
            "total_net_usdc": 100.0,
            "run_mode": "REGISTRY_REAL",
            "block_is_synthetic": False,
        },
    ]
    ev = build_evidence(
        stability={"agg_status": "PASS", "runs": runs},
        run_summary=None,
        m9_acceptance=None,
        resilience_doc=None,
    )
    assert ev.simulation_positive_runs == 3
