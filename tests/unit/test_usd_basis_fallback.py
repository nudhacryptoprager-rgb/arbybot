"""E1.80 — tests for USD basis fallback defaults + override merging."""
from __future__ import annotations

import json

import pytest

from m7.orderflow.usd_basis_fallback import (
    fallback_usd_for_amount,
    load_fallback_table,
)


def test_default_table_includes_e180_cb_anchors(monkeypatch):
    monkeypatch.delenv("ARBY_USD_BASIS_FALLBACK", raising=False)
    monkeypatch.delenv("ARBY_USD_BASIS_FALLBACK_JSON", raising=False)
    table = load_fallback_table()
    # Pre-E1.80 anchors stay
    assert table["AERO"] == pytest.approx(0.50)
    assert table["VIRTUAL"] == pytest.approx(1.50)
    assert table["CBBTC"] == pytest.approx(66000.0)
    # E1.80 cb* expansion
    assert table["CBXRP"] == pytest.approx(1.43)
    assert table["CBLTC"] == pytest.approx(58.45)
    assert table["CBADA"] == pytest.approx(0.27)
    assert table["CBMEGA"] == pytest.approx(0.13)
    assert table["CBETH"] == pytest.approx(4500.0)
    assert table["WSTETH"] == pytest.approx(5300.0)


def test_env_inline_override_wins_over_default(monkeypatch):
    monkeypatch.setenv(
        "ARBY_USD_BASIS_FALLBACK", json.dumps({"CBXRP": 2.0, "NEWTOKEN": 7.5})
    )
    monkeypatch.delenv("ARBY_USD_BASIS_FALLBACK_JSON", raising=False)
    table = load_fallback_table()
    assert table["CBXRP"] == pytest.approx(2.0)
    assert table["NEWTOKEN"] == pytest.approx(7.5)
    # Other defaults untouched
    assert table["AERO"] == pytest.approx(0.50)


def test_fallback_usd_for_amount_uses_default_for_cbxrp(monkeypatch):
    monkeypatch.delenv("ARBY_USD_BASIS_FALLBACK", raising=False)
    monkeypatch.delenv("ARBY_USD_BASIS_FALLBACK_JSON", raising=False)
    # 100 cbXRP @ 18 decimals => 100 * 1.43 = 143.0 USD
    val = fallback_usd_for_amount(
        symbol="cbXRP", amount_wei=100 * 10**18, decimals=18
    )
    assert val == pytest.approx(143.0)


def test_fallback_returns_none_for_unknown_symbol():
    val = fallback_usd_for_amount(
        symbol="UNKNOWN_TOKEN_XYZ", amount_wei=10**18, decimals=18
    )
    assert val is None
