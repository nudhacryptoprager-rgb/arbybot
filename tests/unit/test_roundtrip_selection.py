# PATH: tests/unit/test_roundtrip_selection.py
"""
Contract tests for strategy/roundtrip_selection.py.

Verifies the candidate selection pipeline: LP-fee viability, cross-DEX check,
roundtrip eligibility, margin thresholds, best-per-pair dedup, and the
composite select_roundtrip_candidates() function.
"""

from strategy.roundtrip_selection import (
    DEFAULT_MIN_SPREAD_MINUS_THRESHOLD,
    best_per_pair,
    is_cross_dex,
    lp_fee_viable,
    margin_viable,
    roundtrip_eligible,
    select_roundtrip_candidates,
)


def _make_opp(
    pair="WETH_USDC",
    buy_dex="uniswap_v3",
    sell_dex="sushiswap_v3",
    buy_fee=500,
    sell_fee=500,
    gross_spread_bps=20.0,
    spread_minus_required_bps=5.0,
    is_diagnostic_only=False,
):
    return {
        "pair": pair,
        "buy_dex": buy_dex,
        "sell_dex": sell_dex,
        "buy_fee": buy_fee,
        "sell_fee": sell_fee,
        "gross_spread_bps": gross_spread_bps,
        "spread_minus_required_bps": spread_minus_required_bps,
        "is_diagnostic_only": is_diagnostic_only,
    }


class TestLpFeeViable:
    def test_covers_fees(self):
        opp = _make_opp(buy_fee=500, sell_fee=500, gross_spread_bps=20)
        assert lp_fee_viable(opp) is True

    def test_does_not_cover_fees(self):
        opp = _make_opp(buy_fee=3000, sell_fee=3000, gross_spread_bps=5)
        assert lp_fee_viable(opp) is False

    def test_exact_boundary(self):
        # buy_fee=500 + sell_fee=500 = 10 bps LP cost, spread exactly 10 → not viable
        opp = _make_opp(buy_fee=500, sell_fee=500, gross_spread_bps=10)
        assert lp_fee_viable(opp) is False

    def test_missing_fees_conservative(self):
        opp = {"gross_spread_bps": 5}
        assert lp_fee_viable(opp) is True  # 0/100 + 0/100 = 0, 5 > 0


class TestIsCrossDex:
    def test_cross_dex(self):
        assert is_cross_dex(_make_opp()) is True

    def test_same_dex(self):
        opp = _make_opp(buy_dex="uniswap_v3", sell_dex="uniswap_v3")
        assert is_cross_dex(opp) is False


class TestRoundtripEligible:
    def test_eligible(self):
        opp = _make_opp()
        assert roundtrip_eligible(opp) is True

    def test_same_dex_not_eligible(self):
        opp = _make_opp(buy_dex="uniswap_v3", sell_dex="uniswap_v3")
        assert roundtrip_eligible(opp) is False

    def test_diagnostic_only_not_eligible(self):
        opp = _make_opp(is_diagnostic_only=True)
        assert roundtrip_eligible(opp) is False


class TestMarginViable:
    def test_above_threshold(self):
        opp = _make_opp(spread_minus_required_bps=0.0)
        assert margin_viable(opp) is True

    def test_below_threshold(self):
        opp = _make_opp(spread_minus_required_bps=-10.0)
        assert margin_viable(opp) is False

    def test_custom_threshold(self):
        opp = _make_opp(spread_minus_required_bps=-3.0)
        assert margin_viable(opp, threshold=-5.0) is True
        assert margin_viable(opp, threshold=-2.0) is False


class TestBestPerPair:
    def test_dedup_by_pair(self):
        opps = [
            _make_opp(pair="A", spread_minus_required_bps=5),
            _make_opp(pair="A", spread_minus_required_bps=10),
            _make_opp(pair="B", spread_minus_required_bps=3),
        ]
        result = best_per_pair(opps)
        assert len(result) == 2
        pairs = {r["pair"] for r in result}
        assert pairs == {"A", "B"}
        # Best margin for pair A should be 10
        a = next(r for r in result if r["pair"] == "A")
        assert a["spread_minus_required_bps"] == 10

    def test_respects_max_candidates(self):
        opps = [_make_opp(pair=f"P{i}") for i in range(20)]
        result = best_per_pair(opps, max_candidates=5)
        assert len(result) <= 5


class TestSelectRoundtripCandidates:
    def test_full_pipeline(self):
        opps = [
            _make_opp(pair="WETH_USDC", spread_minus_required_bps=5),
            _make_opp(pair="WETH_DAI", spread_minus_required_bps=-10),  # below margin
            _make_opp(pair="WETH_USDT", buy_dex="x", sell_dex="x"),  # same dex
        ]
        eligible, stats = select_roundtrip_candidates(opps)
        # Only WETH_USDC passes (cross-dex + margin viable)
        assert len(eligible) == 1
        assert eligible[0]["pair"] == "WETH_USDC"
        assert stats["passed_to_roundtrip"] == 1
        assert stats["candidates_considered"] == 3

    def test_empty_input(self):
        eligible, stats = select_roundtrip_candidates([])
        assert eligible == []
        assert stats["passed_to_roundtrip"] == 0

    def test_default_threshold(self):
        assert DEFAULT_MIN_SPREAD_MINUS_THRESHOLD == -5.0
