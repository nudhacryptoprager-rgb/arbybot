"""Boundary tests for money-safe JSON serialization (Roadmap §3.2).

Locks:
  * Decimal -> exact string in money mode (no float degradation);
  * legacy float mode unchanged (backward compatibility);
  * zero-profit, fee-threshold, decimals 6/8/18 and >2^53 wei boundaries
    round-trip exactly.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from core.json_io import atomic_write_json, read_json, write_money_json
from core.math import safe_decimal


def test_money_mode_decimal_exact_roundtrip(tmp_path):
    payload = {
        "net_pnl_usd": Decimal("0.000000000000000001"),  # 1 wei-scale USD
        "gas_usd": Decimal("0.014325000000000000"),
        "slippage_bps": Decimal("12.5"),
    }
    out = write_money_json(tmp_path / "money.json", payload)
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["net_pnl_usd"] == "0.000000000000000001"
    assert raw["gas_usd"] == "0.014325000000000000"  # Decimal preserves scale
    assert raw["slippage_bps"] == "12.5"
    # Exact Decimal recovery — no binary float in the loop.
    assert safe_decimal(raw["net_pnl_usd"]) == Decimal("0.000000000000000001")


def test_legacy_float_mode_unchanged(tmp_path):
    out = atomic_write_json(tmp_path / "legacy.json", {"v": Decimal("1.5")})
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["v"] == 1.5
    assert isinstance(raw["v"], float)


def test_unknown_decimal_mode_rejected(tmp_path):
    with pytest.raises(ValueError):
        atomic_write_json(tmp_path / "x.json", {"v": 1}, decimal_mode="hex")


def test_zero_profit_boundary(tmp_path):
    # Zero-profit edge: sign must survive exactly; -0.0 float must not appear.
    out = write_money_json(tmp_path / "zero.json", {"net_pnl_usd": Decimal("0")})
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["net_pnl_usd"] == "0"
    assert safe_decimal(raw["net_pnl_usd"]) == Decimal("0")


def test_fee_threshold_boundary(tmp_path):
    # Fee threshold edge: values straddling a 1-wei fee boundary stay distinct.
    below = Decimal("0.499999999999999999")
    above = Decimal("0.500000000000000001")
    out = write_money_json(tmp_path / "fee.json", {"below": below, "above": above})
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert safe_decimal(raw["below"]) == below
    assert safe_decimal(raw["above"]) == above
    assert safe_decimal(raw["below"]) != safe_decimal(raw["above"])


@pytest.mark.parametrize("decimals", [6, 8, 18])
def test_token_decimals_scale_exact(tmp_path, decimals):
    # 1 unit at the given token decimals scale must round-trip exactly.
    scale = Decimal(10) ** -decimals
    out = write_money_json(tmp_path / f"d{decimals}.json", {"one_unit": scale})
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert safe_decimal(raw["one_unit"]) == scale


def test_large_wei_int_above_2pow53_exact(tmp_path):
    # 2^53 + 1 is not representable as float64; int path must stay exact.
    wei = 2**53 + 1
    out = write_money_json(tmp_path / "wei.json", {"amount_wei": wei})
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["amount_wei"] == wei
    assert isinstance(raw["amount_wei"], int)


def test_float_mode_degrades_but_money_mode_does_not(tmp_path):
    # Documents why canonical money artifacts must use decimal_mode="str":
    # 2^53+1 is not representable as float64, so float mode silently
    # rewrites the amount; money mode keeps it exact.
    precise = Decimal("9007199254740993")  # 2**53 + 1
    out_money = write_money_json(tmp_path / "m.json", {"v": precise})
    out_float = atomic_write_json(tmp_path / "f.json", {"v": precise})
    assert json.loads(out_money.read_text(encoding="utf-8"))["v"] == "9007199254740993"
    float_v = json.loads(out_float.read_text(encoding="utf-8"))["v"]
    assert int(float_v) == 9007199254740992  # degraded by exactly 1 wei


def test_export_rows_to_json_preserves_decimal_in_extra(tmp_path):
    """state.json_export.export_rows_to_json must serialize Decimal inside
    extra/payload as exact strings, not float. Regression for the
    production-readiness review finding that the canonical JSON export
    lost money precision through legacy atomic_write_json()."""
    from state.json_export import export_rows_to_json

    rows = [
        {
            "chain_id": 8453,
            "pool_address": "0x" + "ab" * 20,
            "extra": {
                "liquidity_usd": Decimal("123456789.000000000000000001"),
                "price_quote_to_base": Decimal("0.000000000000000001"),
                "fee_bps": Decimal("12.5"),
            },
        }
    ]
    out = export_rows_to_json(rows, tmp_path / "export.json")
    raw = json.loads(out.read_text(encoding="utf-8"))
    extra = raw["items"][0]["extra"]
    assert extra["liquidity_usd"] == "123456789.000000000000000001"
    assert extra["price_quote_to_base"] == "0.000000000000000001"
    assert extra["fee_bps"] == "12.5"
    assert safe_decimal(extra["liquidity_usd"]) == Decimal("123456789.000000000000000001")
    assert safe_decimal(extra["price_quote_to_base"]) == Decimal("0.000000000000000001")


def test_export_rows_to_json_rejects_float_for_decimal(tmp_path):
    """The Decimal-as-str export must never silently emit a float for a
    Decimal input even at 2^53+1."""
    from state.json_export import export_rows_to_json

    rows = [{"extra": {"amount": Decimal("9007199254740993")}}]
    out = export_rows_to_json(rows, tmp_path / "exp.json")
    raw = json.loads(out.read_text(encoding="utf-8"))
    v = raw["items"][0]["extra"]["amount"]
    assert v == "9007199254740993"
    assert isinstance(v, str)
