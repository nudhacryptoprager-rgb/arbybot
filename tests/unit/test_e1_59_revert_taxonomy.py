"""E1.59 step #6: extended revert taxonomy + samples."""

from __future__ import annotations

import pytest

from m7.orderflow import revert_taxonomy as rt


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setenv("ARBY_REVERT_TAXONOMY", "1")
    rt.reset()
    yield


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("REVERT:STF:0xabc", "STF"),
        ("safeTransferFrom failed", "STF"),
        ("HTTP 408 timeout", "HTTP_408"),
        ("Connection timeout", "HTTP_408"),
        ("HTTP 429 rate limit exceeded", "HTTP_429"),
        ("too many requests", "HTTP_429"),
        ("out of gas", "OUT_OF_GAS"),
        ("OUT_OF_GAS", "OUT_OF_GAS"),
        ("REVERT:unknown:no_data", "NO_DATA"),
        ("execution reverted", "EXECUTION_REVERTED"),
        ("totally unexpected", "OTHER"),
        (None, "OTHER"),
        ("", "OTHER"),
    ],
)
def test_classify(reason, expected):
    assert rt.classify(reason) == expected


def test_disabled_does_not_record(monkeypatch):
    monkeypatch.setenv("ARBY_REVERT_TAXONOMY", "0")
    rt.reset()
    rt.record("REVERT:STF", pair="TIG/WETH")
    snap = rt.snapshot()
    assert snap["total"] == 0
    assert snap["buckets"]["STF"]["count"] == 0


def test_record_increments_correct_bucket():
    rt.record("REVERT:STF", pair="TIG/WETH", fee=3000, pool="0xabc")
    rt.record("REVERT:STF", pair="PING/WETH", fee=500, pool="0xdef")
    rt.record("HTTP 408 timeout", pair="TIG/WETH", fee=3000)
    rt.record("REVERT:unknown:no_data", pair="X/Y", fee=500)
    snap = rt.snapshot()
    assert snap["buckets"]["STF"]["count"] == 2
    assert snap["buckets"]["HTTP_408"]["count"] == 1
    assert snap["buckets"]["NO_DATA"]["count"] == 1
    assert snap["total"] == 4


def test_sample_payload_has_context_fields():
    rt.record(
        "REVERT:STF",
        pair="TIG/WETH",
        fee=3000,
        pool="0xabc",
        size_wei=10**18,
        block=12345,
        extra={"router": "0xRouter"},
    )
    s = rt.snapshot()["buckets"]["STF"]["recent_samples"][0]
    assert s["pair"] == "TIG/WETH"
    assert s["fee"] == 3000
    assert s["pool"] == "0xabc"
    assert s["size_wei"] == 10**18
    assert s["block"] == 12345
    assert s["extra"]["router"] == "0xRouter"


def test_sample_buffer_capped_at_20_per_bucket():
    for i in range(35):
        rt.record("REVERT:STF", pair=f"P{i}", fee=3000)
    bucket = rt.snapshot()["buckets"]["STF"]
    assert bucket["count"] == 35
    assert len(bucket["recent_samples"]) == 20
    # Oldest (P0..P14) dropped; newest (P15..P34) retained.
    pairs = [s["pair"] for s in bucket["recent_samples"]]
    assert pairs[0] == "P15"
    assert pairs[-1] == "P34"


def test_buckets_isolated():
    for _ in range(5):
        rt.record("REVERT:STF")
    for _ in range(3):
        rt.record("HTTP 429")
    snap = rt.snapshot()
    assert snap["buckets"]["STF"]["count"] == 5
    assert snap["buckets"]["HTTP_429"]["count"] == 3
    assert snap["buckets"]["NO_DATA"]["count"] == 0


def test_reset_clears_all():
    rt.record("REVERT:STF")
    rt.record("HTTP 429")
    rt.reset()
    snap = rt.snapshot()
    assert snap["total"] == 0
    for bucket in snap["buckets"].values():
        assert bucket["count"] == 0
        assert bucket["recent_samples"] == []


def test_record_returns_bucket_name():
    assert rt.record("REVERT:STF") == "STF"
    assert rt.record("HTTP 408") == "HTTP_408"
    assert rt.record("totally weird") == "OTHER"


def test_priority_stf_over_no_data():
    # Reason mentions both 'no_data' and 'stf' — STF takes priority.
    assert rt.classify("REVERT:STF:no_data") == "STF"
