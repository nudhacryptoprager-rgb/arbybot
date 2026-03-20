# PATH: tests/unit/test_quote_policy_exports.py
"""Tests for strategy.quote_policy module exports and basic contracts."""
from decimal import Decimal


def test_get_runtime_filter_switches_importable():
    from strategy.quote_policy import get_runtime_filter_switches
    flags = get_runtime_filter_switches({})
    assert "quarantine_enabled" in flags
    assert "runtime_disabled_enabled" in flags
    assert flags["quarantine_enabled"] is True
    assert flags["runtime_disabled_enabled"] is True


def test_get_runtime_filter_switches_disable_all():
    from strategy.quote_policy import get_runtime_filter_switches
    flags = get_runtime_filter_switches({"disable_runtime_suppression": True})
    assert flags["quarantine_enabled"] is False
    assert flags["runtime_disabled_enabled"] is False


def test_apply_price_sanity_gate_importable():
    from strategy.quote_policy import apply_price_sanity_gate
    assert callable(apply_price_sanity_gate)


def test_apply_price_sanity_gate_skips_when_disabled():
    from strategy.quote_policy import apply_price_sanity_gate
    result = apply_price_sanity_gate(
        price_exact=Decimal("1.0"),
        anchor_price=1.0,
        anchor_source="tokens_anchor_price",
        pair_tag="WETH/USDC",
        dex="uniswap_v3",
        fee_tier=500,
        pool_addr="0x0000000000000000000000000000000000000001",
        config={"price_sanity_enabled": False},
    )
    assert result is None


def test_apply_price_sanity_gate_skips_no_anchor():
    from strategy.quote_policy import apply_price_sanity_gate
    result = apply_price_sanity_gate(
        price_exact=Decimal("1.0"),
        anchor_price=None,
        anchor_source="tokens_anchor_price",
        pair_tag="WETH/USDC",
        dex="uniswap_v3",
        fee_tier=500,
        pool_addr="0x0000000000000000000000000000000000000001",
        config={},
    )
    assert result is None


def test_apply_price_sanity_gate_passes_close_price():
    from strategy.quote_policy import apply_price_sanity_gate
    # Anchor=2000.0, price=2001.0 → deviation ~5 bps, well within 5000 default
    result = apply_price_sanity_gate(
        price_exact=Decimal("2001.0"),
        anchor_price=2000.0,
        anchor_source="tokens_anchor_price",
        pair_tag="WETH/USDC",
        dex="uniswap_v3",
        fee_tier=500,
        pool_addr="0x0000000000000000000000000000000000000001",
        config={},
    )
    assert result is None


def test_apply_price_sanity_gate_rejects_wild_price():
    from strategy.quote_policy import apply_price_sanity_gate
    # Anchor=2000.0, price=20000.0 → 900% deviation, way over 5000 bps
    result = apply_price_sanity_gate(
        price_exact=Decimal("20000.0"),
        anchor_price=2000.0,
        anchor_source="tokens_anchor_price",
        pair_tag="WETH/USDC",
        dex="uniswap_v3",
        fee_tier=500,
        pool_addr="0x0000000000000000000000000000000000000001",
        config={},
    )
    assert result is not None
    assert result["reason"] == "PRICE_SANITY_FAILED"
    assert result["gate_passed"] is False
    assert "deviation_bps" in result


def test_apply_price_sanity_gate_includes_optional_fields():
    from strategy.quote_policy import apply_price_sanity_gate
    result = apply_price_sanity_gate(
        price_exact=Decimal("20000.0"),
        anchor_price=2000.0,
        anchor_source="tokens_anchor_price",
        pair_tag="WETH/USDC",
        dex="uniswap_v3",
        fee_tier=500,
        pool_addr="0x0000000000000000000000000000000000000001",
        config={},
        quote_source="slot0",
        tick_val=12345,
        amount_in_wei=1000000,
        target_usd_notional=10.0,
    )
    assert result is not None
    assert result["quote_source"] == "slot0"
    assert result["tick"] == 12345
    assert result["amount_in_wei"] == 1000000
    assert result["notional_usd_target"] == 10.0


def test_reexport_from_quotes():
    """The old import path must still work."""
    from strategy.quotes import _get_runtime_filter_switches
    flags = _get_runtime_filter_switches({})
    assert flags["quarantine_enabled"] is True
