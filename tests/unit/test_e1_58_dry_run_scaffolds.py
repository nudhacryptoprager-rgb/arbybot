"""Unit tests for E1.58 fix steps #3/#5/#7 dry-run scaffolds."""

from __future__ import annotations

import pytest

from execution import canary_submitter as cs
from execution import pnl_accounting as pa
from execution import private_submitter as ps


# -----------------------------------------------------------------------------
# private_submitter
# -----------------------------------------------------------------------------


def test_private_supported_relays_frozen():
    assert "flashbots" in ps.SUPPORTED_RELAYS
    assert "mev_share" in ps.SUPPORTED_RELAYS
    assert "blink" in ps.SUPPORTED_RELAYS


def test_private_dry_run_default(monkeypatch):
    monkeypatch.delenv("ARBY_PRIVATE_SUBMIT_DRY_RUN", raising=False)
    out = ps.submit_private("0xdeadbeef", relay="flashbots", chain="base")
    assert out["status"] == "dry_run_submitted"
    assert out["dry_run"] is True
    assert out["bundle_hash"] is not None
    assert out["bundle_hash"].startswith("0x")
    assert len(out["bundle_hash"]) == 66


def test_private_explicit_dry_run_false_without_impl(monkeypatch):
    monkeypatch.setenv("ARBY_PRIVATE_SUBMIT_DRY_RUN", "0")
    out = ps.submit_private("0xdeadbeef", relay="flashbots", chain="base")
    assert out["status"] == "rejected"
    assert out["error"] == "REAL_SUBMIT_NOT_IMPLEMENTED"


def test_private_unsupported_relay():
    out = ps.submit_private("0xdeadbeef", relay="bogus", chain="base", dry_run=True)
    assert out["status"] == "rejected"
    assert out["error"].startswith("UNSUPPORTED_RELAY:")


def test_private_empty_signed_tx():
    out = ps.submit_private("", relay="flashbots", chain="base", dry_run=True)
    assert out["status"] == "rejected"
    assert out["error"] == "EMPTY_SIGNED_TX"


def test_private_bundle_hash_deterministic():
    a = ps.submit_private("0xabc", relay="flashbots", chain="base", dry_run=True)
    b = ps.submit_private("0xabc", relay="mev_share", chain="base", dry_run=True)
    assert a["bundle_hash"] == b["bundle_hash"]


# -----------------------------------------------------------------------------
# canary_submitter
# -----------------------------------------------------------------------------


def test_canary_dry_run_happy_path(monkeypatch):
    monkeypatch.delenv("ARBY_CANARY_DRY_RUN", raising=False)
    out = cs.submit_canary(None, owner="0xowner", chain="base", amount_wei=1)
    assert out["status"] == "dry_run_submitted"
    assert out["tx_hash"] is not None
    assert out["tx_hash"].startswith("0x")
    assert out["amount_wei"] == 1
    assert out["dry_run"] is True


def test_canary_owner_missing():
    out = cs.submit_canary(None, owner="", chain="base", amount_wei=1, dry_run=True)
    assert out["status"] == "rejected"
    assert out["error"] == "OWNER_MISSING"


def test_canary_amount_non_positive():
    out = cs.submit_canary(None, owner="0xowner", chain="base", amount_wei=0, dry_run=True)
    assert out["status"] == "rejected"
    assert out["error"] == "AMOUNT_NON_POSITIVE"


def test_canary_live_not_implemented(monkeypatch):
    monkeypatch.setenv("ARBY_CANARY_DRY_RUN", "0")
    out = cs.submit_canary(None, owner="0xowner", chain="base", amount_wei=1)
    assert out["status"] == "rejected"
    assert out["error"] == "LIVE_CANARY_NOT_IMPLEMENTED"


# -----------------------------------------------------------------------------
# pnl_accounting
# -----------------------------------------------------------------------------


def test_pnl_snapshot_dry_run_with_override(monkeypatch):
    monkeypatch.delenv("ARBY_PNL_DRY_RUN", raising=False)
    snap = pa.snapshot_balances(
        None, "0xowner", ["0xtok"], override={"0xtok": 1234}
    )
    assert snap == {"0xtok": 1234}


def test_pnl_snapshot_dry_run_no_override():
    snap = pa.snapshot_balances(None, "0xowner", ["0xa", "0xb"], dry_run=True)
    assert snap == {"0xa": 0, "0xb": 0}


def test_pnl_compute_pnl_basic():
    before = {"0xtok": 1_000_000_000_000_000_000}  # 1.0 token
    after = {"0xtok": 1_500_000_000_000_000_000}   # 1.5 token
    prices = {"0xtok": 2.0}
    out = pa.compute_pnl(before, after, prices)
    assert out["per_token_delta_wei"]["0xtok"] == 500_000_000_000_000_000
    assert pytest.approx(out["total_pnl_usd"], rel=1e-6) == 1.0
    assert out["unpriced_tokens"] == []


def test_pnl_compute_pnl_unpriced():
    before = {"0xtok": 0}
    after = {"0xtok": 10**18}
    out = pa.compute_pnl(before, after, prices_usd={})
    assert out["unpriced_tokens"] == ["0xtok"]
    assert out["total_pnl_usd"] == 0.0


def test_pnl_compute_pnl_negative():
    before = {"0xtok": 10**18}
    after = {"0xtok": 0}
    out = pa.compute_pnl(before, after, {"0xtok": 5.0})
    assert out["per_token_delta_wei"]["0xtok"] == -(10**18)
    assert pytest.approx(out["total_pnl_usd"], rel=1e-6) == -5.0
