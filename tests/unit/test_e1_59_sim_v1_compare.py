"""E1.59 step #4: feature-gated eth_simulateV1 dry-compare harness."""

from __future__ import annotations

import pytest

from execution import sim_v1_dry_compare as svc
from execution.sim_v1_dry_compare import SimResult, compare_results


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setenv("ARBY_SIM_V1_DRY_COMPARE", "1")
    svc.reset_stats()
    yield


def test_disabled_does_not_record(monkeypatch):
    monkeypatch.setenv("ARBY_SIM_V1_DRY_COMPARE", "0")
    svc.reset_stats()
    rf = SimResult(success=True, profit_bps=100.0)
    sv = SimResult(success=False, revert_reason="REVERT:STF")
    s = compare_results(rf, sv, candidate_id="c1")
    assert s.agree_success is False
    assert svc.stats()["samples_total"] == 0


def test_full_agreement_recorded():
    rf = SimResult(success=True, profit_bps=120.0, gas_used=500_000)
    sv = SimResult(success=True, profit_bps=121.0, gas_used=510_000)
    s = compare_results(rf, sv, candidate_id="c1")
    assert s.agree_success is True
    assert s.agree_revert_reason is True
    assert s.bps_delta == pytest.approx(-1.0)
    st = svc.stats()
    assert st["samples_total"] == 1
    assert st["agree_success_count"] == 1
    assert st["bps_delta_samples"] == 1
    assert st["bps_delta_abs_mean"] == pytest.approx(1.0)


def test_disagreement_in_success():
    rf = SimResult(success=True, profit_bps=10.0)
    sv = SimResult(success=False, revert_reason="REVERT:STF")
    compare_results(rf, sv, candidate_id="c1")
    st = svc.stats()
    assert st["disagree_success_count"] == 1
    assert st["rpc_fork_only_success"] == 1
    assert st["sim_v1_only_success"] == 0
    assert len(st["recent_disagree_samples"]) == 1


def test_sim_v1_only_success():
    rf = SimResult(success=False, revert_reason="REVERT:STF")
    sv = SimResult(success=True, profit_bps=50.0)
    compare_results(rf, sv, candidate_id="c1")
    st = svc.stats()
    assert st["sim_v1_only_success"] == 1
    assert st["rpc_fork_only_success"] == 0


def test_revert_reason_prefix_match():
    rf = SimResult(success=False, revert_reason="REVERT:STF:0xabc")
    sv = SimResult(success=False, revert_reason="REVERT:STF:0xdef")
    compare_results(rf, sv, candidate_id="c1")
    st = svc.stats()
    assert st["agree_revert_reason_count"] == 1


def test_revert_reason_disagree_recorded():
    rf = SimResult(success=False, revert_reason="REVERT:STF")
    sv = SimResult(success=False, revert_reason="REVERT:OUT_OF_GAS")
    compare_results(rf, sv, candidate_id="c1")
    st = svc.stats()
    assert st["disagree_revert_reason_count"] == 1
    assert len(st["recent_disagree_samples"]) == 1


def test_bps_delta_max_tracked():
    compare_results(
        SimResult(True, profit_bps=100.0),
        SimResult(True, profit_bps=80.0),
        candidate_id="c1",
    )
    compare_results(
        SimResult(True, profit_bps=200.0),
        SimResult(True, profit_bps=150.0),
        candidate_id="c2",
    )
    st = svc.stats()
    assert st["bps_delta_max_abs"] == pytest.approx(50.0)
    assert st["bps_delta_abs_mean"] == pytest.approx((20.0 + 50.0) / 2)


def test_recent_disagree_capped_at_30():
    for i in range(40):
        compare_results(
            SimResult(True, profit_bps=10.0),
            SimResult(False, revert_reason="REVERT:X"),
            candidate_id=f"c{i}",
        )
    st = svc.stats()
    assert len(st["recent_disagree_samples"]) == 30
    # Oldest dropped, newest retained.
    assert st["recent_disagree_samples"][-1]["candidate_id"] == "c39"


def test_missing_bps_skipped_from_delta():
    compare_results(
        SimResult(True, profit_bps=None),
        SimResult(True, profit_bps=100.0),
        candidate_id="c1",
    )
    st = svc.stats()
    assert st["bps_delta_samples"] == 0
    assert st["bps_delta_abs_mean"] is None


def test_reset_stats_clears_all():
    compare_results(
        SimResult(True, profit_bps=10.0),
        SimResult(False, revert_reason="REVERT"),
        candidate_id="c1",
    )
    svc.reset_stats()
    st = svc.stats()
    assert st["samples_total"] == 0
    assert st["recent_disagree_samples"] == []
