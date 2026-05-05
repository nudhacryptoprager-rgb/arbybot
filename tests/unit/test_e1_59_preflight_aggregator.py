"""E1.59 step #8: preflight outcome aggregator."""

from __future__ import annotations

import pytest

from m7.orderflow import preflight_aggregator as pa


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setenv("ARBY_EXECUTION_PREFLIGHT", "1")
    pa.reset()
    yield


def test_disabled_does_not_persist(monkeypatch):
    monkeypatch.setenv("ARBY_EXECUTION_PREFLIGHT", "0")
    pa.reset()
    out = pa.record(["PREFLIGHT_ROUTER_NO_CODE"], router="0xR")
    assert out == {"blocked": True, "blocker_count": 1, "passed": False}
    snap = pa.snapshot()
    assert snap["candidates_total"] == 0


def test_passed_increments_passed_total():
    out = pa.record([], router="0xR", candidate_id="c1")
    assert out["passed"] is True
    snap = pa.snapshot()
    assert snap["candidates_total"] == 1
    assert snap["passed_total"] == 1
    assert snap["blocked_total"] == 0


def test_blocked_records_reasons_and_sample():
    pa.record(
        ["PREFLIGHT_BALANCE_INSUFFICIENT:5<10", "PREFLIGHT_ROUTER_NO_CODE"],
        router="0xR",
        token_in="0xT",
        owner="0xO",
        amount_wei=1_000,
        candidate_id="c1",
    )
    snap = pa.snapshot()
    assert snap["candidates_total"] == 1
    assert snap["blocked_total"] == 1
    assert snap["reason_counts"]["PREFLIGHT_BALANCE_INSUFFICIENT"] == 1
    assert snap["reason_counts"]["PREFLIGHT_ROUTER_NO_CODE"] == 1
    sample = snap["recent_blockers"][0]
    assert sample["candidate_id"] == "c1"
    assert sample["router"] == "0xR"
    assert sample["token_in"] == "0xT"
    assert sample["owner"] == "0xO"
    assert sample["amount_wei"] == 1_000
    assert sample["blockers"] == [
        "PREFLIGHT_BALANCE_INSUFFICIENT:5<10",
        "PREFLIGHT_ROUTER_NO_CODE",
    ]


def test_reason_prefix_normalised():
    pa.record(["PREFLIGHT_ALLOWANCE_INSUFFICIENT:0<100"], router="0xR")
    pa.record(["PREFLIGHT_ALLOWANCE_INSUFFICIENT:50<200"], router="0xR")
    snap = pa.snapshot()
    assert snap["reason_counts"]["PREFLIGHT_ALLOWANCE_INSUFFICIENT"] == 2


def test_recent_blockers_capped_at_30():
    for i in range(40):
        pa.record(["PREFLIGHT_ROUTER_NO_CODE"], candidate_id=f"c{i}")
    snap = pa.snapshot()
    assert len(snap["recent_blockers"]) == 30
    assert snap["recent_blockers"][-1]["candidate_id"] == "c39"


def test_mixed_passed_and_blocked():
    pa.record([])
    pa.record(["PREFLIGHT_ROUTER_NO_CODE"])
    pa.record([])
    pa.record(["PREFLIGHT_BALANCE_INSUFFICIENT:0<1"])
    snap = pa.snapshot()
    assert snap["candidates_total"] == 4
    assert snap["passed_total"] == 2
    assert snap["blocked_total"] == 2


def test_reset_clears():
    pa.record(["PREFLIGHT_ROUTER_NO_CODE"])
    pa.reset()
    snap = pa.snapshot()
    assert snap["candidates_total"] == 0
    assert snap["reason_counts"] == {}
    assert snap["recent_blockers"] == []


def test_summary_returned_even_when_disabled(monkeypatch):
    monkeypatch.setenv("ARBY_EXECUTION_PREFLIGHT", "0")
    out = pa.record([])
    assert out["passed"] is True
    out = pa.record(["X"])
    assert out["blocked"] is True
