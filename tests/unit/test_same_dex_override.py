"""R28.27: Tests for ARBY_ALLOW_SAME_DEX override in spreads.py.

Verifies that the same-DEX override toggle correctly bypasses
require_cross_dex=true policy when ARBY_ALLOW_SAME_DEX=1 or
config allow_same_dex=true.
"""

import os
from unittest.mock import patch

from strategy.spreads import _compute_pair_spread


def _make_quotes(pair="WETH/USDC", dex="uniswap_v3", fee=500, pool_prefix="0xaaa"):
    """Create minimal same-DEX quote pair for testing the gate."""
    return [
        {
            "token_in": pair.split("/")[0],
            "token_out": pair.split("/")[1],
            "dex_id": dex,
            "fee": fee,
            "pool_address": f"{pool_prefix}1",
            "price": "1.0010",
            "price_exact": "1.0010",
            "amount_in_human": "100",
            "amount_out_human": "100.1",
            "amount_in_wei": 100_000_000,
            "amount_out_wei": 100_100_000,
            "block_number": 100,
            "rpc_success": True,
            "gate_passed": True,
            "is_diagnostic_only": False,
        },
        {
            "token_in": pair.split("/")[0],
            "token_out": pair.split("/")[1],
            "dex_id": dex,
            "fee": 3000,
            "pool_address": f"{pool_prefix}2",
            "price": "1.0050",
            "price_exact": "1.0050",
            "amount_in_human": "100",
            "amount_out_human": "100.5",
            "amount_in_wei": 100_000_000,
            "amount_out_wei": 100_500_000,
            "block_number": 100,
            "rpc_success": True,
            "gate_passed": True,
            "is_diagnostic_only": False,
        },
    ]


def test_require_cross_dex_blocks_same_dex(monkeypatch):
    """When require_cross_dex=true and no override, same-DEX quotes produce no signal."""
    monkeypatch.delenv("ARBY_ALLOW_SAME_DEX", raising=False)

    config = {"require_cross_dex": True, "truth_mode_m42": False}
    rejected = []
    signals = _compute_pair_spread(
        "WETH/USDC", _make_quotes(), config, 100, 0, 10000, rejected
    )
    assert signals == []


def test_allow_same_dex_env_override(monkeypatch):
    """ARBY_ALLOW_SAME_DEX=1 overrides require_cross_dex=true."""
    monkeypatch.setenv("ARBY_ALLOW_SAME_DEX", "1")

    config = {"require_cross_dex": True, "truth_mode_m42": False}
    rejected = []
    signals = _compute_pair_spread(
        "WETH/USDC", _make_quotes(), config, 100, 0, 10000, rejected
    )
    # Should produce a signal now since same-DEX fallback is allowed
    assert len(signals) >= 1


def test_allow_same_dex_config_override(monkeypatch):
    """Config allow_same_dex=True overrides require_cross_dex=true."""
    monkeypatch.delenv("ARBY_ALLOW_SAME_DEX", raising=False)

    config = {"require_cross_dex": True, "allow_same_dex": True, "truth_mode_m42": False}
    rejected = []
    signals = _compute_pair_spread(
        "WETH/USDC", _make_quotes(), config, 100, 0, 10000, rejected
    )
    assert len(signals) >= 1


def test_no_require_cross_dex_allows_same_dex(monkeypatch):
    """When require_cross_dex=false, same-DEX signals are produced without override."""
    monkeypatch.delenv("ARBY_ALLOW_SAME_DEX", raising=False)

    config = {"require_cross_dex": False, "truth_mode_m42": False}
    rejected = []
    signals = _compute_pair_spread(
        "WETH/USDC", _make_quotes(), config, 100, 0, 10000, rejected
    )
    assert len(signals) >= 1


def test_allow_same_dex_env_truthy_variants(monkeypatch):
    """All truthy env var values work."""
    config = {"require_cross_dex": True, "truth_mode_m42": False}

    for val in ("1", "true", "yes", "on"):
        monkeypatch.setenv("ARBY_ALLOW_SAME_DEX", val)
        rejected = []
        signals = _compute_pair_spread(
            "WETH/USDC", _make_quotes(), config, 100, 0, 10000, rejected
        )
        assert len(signals) >= 1, f"Failed for value: {val}"
