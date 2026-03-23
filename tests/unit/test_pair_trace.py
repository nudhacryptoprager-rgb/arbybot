# PATH: tests/unit/test_pair_trace.py
"""Tests for strategy.pair_trace — pair-level funnel trace builder."""

import pytest
from dataclasses import dataclass
from typing import Optional

from strategy.pair_trace import build_pair_funnel_trace


# Minimal mock for PairConfig-like object
@dataclass
class _FakePair:
    token_in: str
    token_out: str
    display_name: str = ""
    dex: str = ""
    fee: int = 0
    pool_address: str = ""
    token_in_decimals: int = 18
    token_out_decimals: int = 6


# Minimal mock for RoundTripResult-like object
@dataclass
class _FakeRT:
    pair: str
    net_pnl_bps: float
    gross_pnl_bps: float = 0.0
    gross_pnl_usd: float = 0.0
    estimated_slippage_bps: float = 0.0
    gas_cost_usd: float = 0.0
    net_pnl_usd: float = 0.0
    leg1_fee: int = 0
    leg2_fee: int = 0
    leg2_is_real_quote: bool = True
    is_profitable: bool = False
    reject_reason: Optional[str] = None


def test_empty_inputs():
    result = build_pair_funnel_trace([], [], [], [], [], [], [])
    assert result == []


def test_resolved_only():
    pairs = [_FakePair(token_in="WETH", token_out="USDC")]
    result = build_pair_funnel_trace(pairs, [], [], [], [], [], [])
    assert len(result) == 1
    assert result[0]["pair"] == "WETH/USDC"
    assert result[0]["terminal_stage"] == "resolved"
    assert result[0]["pools_resolved"] == 1


def test_quoted_stage():
    pairs = [_FakePair(token_in="WETH", token_out="USDC")]
    quotes = [
        {"token_in": "WETH", "token_out": "USDC", "dex_id": "uniswap_v3"},
        {"token_in": "WETH", "token_out": "USDC", "dex_id": "sushiswap_v3"},
    ]
    result = build_pair_funnel_trace(pairs, quotes, [], [], [], [], [])
    assert len(result) == 1
    t = result[0]
    assert t["quotes_fetched"] == 2
    assert sorted(t["dexes_quoted"]) == ["sushiswap_v3", "uniswap_v3"]
    assert t["terminal_stage"] == "quoted"


def test_signal_stage():
    pairs = [_FakePair(token_in="WETH", token_out="USDC")]
    quotes = [{"token_in": "WETH", "token_out": "USDC", "dex_id": "uniswap_v3"}]
    signals = [{"pair": "WETH/USDC", "spread_bps": 15}]
    result = build_pair_funnel_trace(pairs, quotes, [], signals, [], [], [])
    t = result[0]
    assert t["spread_signals"] == 1
    assert t["best_spread_bps"] == 15
    assert t["terminal_stage"] == "signal"


def test_opportunity_stage():
    pairs = [_FakePair(token_in="WETH", token_out="USDC")]
    quotes = [{"token_in": "WETH", "token_out": "USDC", "dex_id": "uniswap_v3"}]
    signals = [{"pair": "WETH/USDC", "spread_bps": 15}]
    opps = [{"pair": "WETH/USDC", "spread_minus_required_bps": 3.5, "gross_spread_bps": "15",
             "min_required_spread_bps": 11.5, "gas_cost_usd": 0.05, "fee_cost_usd": 0.01,
             "net_profit_usd": 0.02, "buy_fee": 500, "sell_fee": 3000}]
    result = build_pair_funnel_trace(pairs, quotes, [], signals, opps, [], [])
    t = result[0]
    assert t["opp_count"] == 1
    assert t["best_spread_minus_req_bps"] == 3.5
    assert t["terminal_stage"] == "opportunity"
    assert t["economics"]["buy_fee"] == 500


def test_rt_evaluated():
    pairs = [_FakePair(token_in="WETH", token_out="USDC")]
    quotes = [{"token_in": "WETH", "token_out": "USDC", "dex_id": "uniswap_v3"}]
    signals = [{"pair": "WETH/USDC", "spread_bps": 15}]
    opps = [{"pair": "WETH/USDC", "spread_minus_required_bps": 3.5, "gross_spread_bps": "15"}]
    rts = [_FakeRT(pair="WETH/USDC", net_pnl_bps=-12.5, gross_pnl_bps=5.0,
                   reject_reason="NET_PROFIT_TOO_LOW")]
    eligible = [{"pair": "WETH/USDC"}]
    result = build_pair_funnel_trace(pairs, quotes, [], signals, opps, rts, eligible)
    t = result[0]
    assert t["rt_evaluated"] == 1
    assert t["rt_candidates"] == 1
    assert t["rt_best_net_pnl_bps"] == -12.5
    assert t["terminal_stage"] == "rt_evaluated"
    assert t["rt_reject_reasons"] == {"NET_PROFIT_TOO_LOW": 1}
    assert t["economics"]["rt_gap_to_zero_bps"] == 12.5


def test_rt_profitable():
    pairs = [_FakePair(token_in="WETH", token_out="USDC")]
    quotes = [{"token_in": "WETH", "token_out": "USDC", "dex_id": "uniswap_v3"}]
    signals = [{"pair": "WETH/USDC", "spread_bps": 25}]
    opps = [{"pair": "WETH/USDC", "spread_minus_required_bps": 10.0, "gross_spread_bps": "25"}]
    rts = [_FakeRT(pair="WETH/USDC", net_pnl_bps=5.0, gross_pnl_bps=15.0, is_profitable=True)]
    eligible = [{"pair": "WETH/USDC"}]
    result = build_pair_funnel_trace(pairs, quotes, [], signals, opps, rts, eligible)
    t = result[0]
    assert t["terminal_stage"] == "rt_profitable"
    assert t["economics"]["rt_gap_to_zero_bps"] == 0.0


def test_sort_order():
    """Pairs furthest in pipeline are first; within same stage, best PnL first."""
    pairs = [
        _FakePair(token_in="WETH", token_out="USDC"),
        _FakePair(token_in="WBTC", token_out="WETH"),
        _FakePair(token_in="ARB", token_out="WETH"),
    ]
    quotes = [
        {"token_in": "WETH", "token_out": "USDC", "dex_id": "d1"},
        {"token_in": "WBTC", "token_out": "WETH", "dex_id": "d1"},
        {"token_in": "ARB", "token_out": "WETH", "dex_id": "d1"},
    ]
    signals = [
        {"pair": "WETH/USDC", "spread_bps": 10},
        {"pair": "WBTC/WETH", "spread_bps": 20},
    ]
    opps = [
        {"pair": "WETH/USDC", "spread_minus_required_bps": -5.0, "gross_spread_bps": "10"},
        {"pair": "WBTC/WETH", "spread_minus_required_bps": 3.0, "gross_spread_bps": "20"},
    ]
    rts = [_FakeRT(pair="WBTC/WETH", net_pnl_bps=-8.0)]
    result = build_pair_funnel_trace(pairs, quotes, [], signals, opps, rts, [])
    # WBTC/WETH (rt_evaluated) > WETH/USDC (opportunity) > ARB/WETH (quoted)
    assert result[0]["pair"] == "WBTC/WETH"
    assert result[1]["pair"] == "WETH/USDC"
    assert result[2]["pair"] == "ARB/WETH"


def test_reject_reasons_accumulated():
    pairs = [_FakePair(token_in="WETH", token_out="USDC")]
    rejects = [
        {"pair": "WETH/USDC", "reason": "PRICE_SANITY_FAILED"},
        {"pair": "WETH/USDC", "reason": "PRICE_SANITY_FAILED"},
        {"pair": "WETH/USDC", "reason": "POOL_MISSING"},
    ]
    result = build_pair_funnel_trace(pairs, [], rejects, [], [], [], [])
    t = result[0]
    assert t["quotes_rejected"] == 3
    assert t["reject_reasons"] == {"PRICE_SANITY_FAILED": 2, "POOL_MISSING": 1}


def test_multiple_pairs_mixed_stages():
    pairs = [
        _FakePair(token_in="WETH", token_out="USDC"),
        _FakePair(token_in="WBTC", token_out="WETH"),
    ]
    quotes = [
        {"token_in": "WETH", "token_out": "USDC", "dex_id": "uni"},
    ]
    # WBTC/WETH resolved but never quoted
    result = build_pair_funnel_trace(pairs, quotes, [], [], [], [], [])
    assert len(result) == 2
    weth = [t for t in result if t["pair"] == "WETH/USDC"][0]
    wbtc = [t for t in result if t["pair"] == "WBTC/WETH"][0]
    assert weth["terminal_stage"] == "quoted"
    assert wbtc["terminal_stage"] == "resolved"
