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
    select_sweep_reprieve_candidates,
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


def _make_rejected_opp(
    pair="WETH_USDC",
    buy_dex="uniswap_v3",
    sell_dex="sushiswap_v3",
    buy_fee=500,
    sell_fee=500,
    gross_spread_bps=15.0,
    reject_reason="NET_PROFIT_TOO_LOW: -0.12 < 0.50",
    buy_quote_source="quoter_v2",
    sell_quote_source="quoter_v2",
):
    return {
        "pair": pair,
        "buy_dex": buy_dex,
        "sell_dex": sell_dex,
        "buy_fee": buy_fee,
        "sell_fee": sell_fee,
        "gross_spread_bps": gross_spread_bps,
        "gate_passed": False,
        "reject_reason": reject_reason,
        "buy_quote_source": buy_quote_source,
        "sell_quote_source": sell_quote_source,
    }


class TestSelectSweepReprieveCandidates:
    def test_basic_reprieve(self):
        opps = [
            _make_rejected_opp(pair="WETH_USDC", gross_spread_bps=15),
            _make_rejected_opp(pair="WETH_DAI", gross_spread_bps=10),
        ]
        result, stats = select_sweep_reprieve_candidates(opps)
        assert len(result) == 2
        assert stats["sweep_reprieve_selected"] == 2

    def test_filters_non_net_profit(self):
        opps = [
            _make_rejected_opp(reject_reason="SPREAD_TOO_LOW"),
            _make_rejected_opp(pair="OK"),
        ]
        result, stats = select_sweep_reprieve_candidates(opps)
        assert len(result) == 1
        assert result[0]["pair"] == "OK"

    def test_filters_mixed_source(self):
        opps = [
            _make_rejected_opp(buy_quote_source="slot0", sell_quote_source="quoter_v2"),
        ]
        result, _ = select_sweep_reprieve_candidates(opps)
        assert len(result) == 0

    def test_filters_same_dex(self):
        opps = [_make_rejected_opp(buy_dex="uniswap_v3", sell_dex="uniswap_v3")]
        result, _ = select_sweep_reprieve_candidates(opps)
        assert len(result) == 0

    def test_skips_gate_passed(self):
        opp = _make_rejected_opp()
        opp["gate_passed"] = True
        result, _ = select_sweep_reprieve_candidates([opp])
        assert len(result) == 0

    def test_dedup_by_pair_best_spread(self):
        opps = [
            _make_rejected_opp(pair="A", gross_spread_bps=5),
            _make_rejected_opp(pair="A", gross_spread_bps=20),
            _make_rejected_opp(pair="B", gross_spread_bps=10),
        ]
        result, stats = select_sweep_reprieve_candidates(opps)
        # 2 unique pairs
        assert len(result) == 2
        # Best spread for pair A = 20 (sorted first)
        assert result[0]["gross_spread_bps"] == 20

    def test_max_candidates(self):
        opps = [_make_rejected_opp(pair=f"P{i}") for i in range(20)]
        result, stats = select_sweep_reprieve_candidates(opps, max_candidates=5)
        assert len(result) <= 5

    def test_empty(self):
        result, stats = select_sweep_reprieve_candidates([])
        assert result == []
        assert stats["sweep_reprieve_selected"] == 0


class TestReprieveFromRejectedOEOpps:
    """R33 regression: reprieve must find candidates from OE rejected list,
    not from gated opps_list (which only has gate_passed=True)."""

    def test_gated_opps_yield_zero_reprieve(self):
        """Passing only gated (gate_passed=True) opps must yield 0 reprieve —
        this was the pre-R33 bug."""
        gated = [_make_rejected_opp(pair="A")]
        gated[0]["gate_passed"] = True
        result, stats = select_sweep_reprieve_candidates(gated)
        assert result == []
        assert stats["sweep_reprieve_selected"] == 0

    def test_rejected_opps_yield_reprieve(self):
        """Passing rejected (gate_passed=False) NET_PROFIT_TOO_LOW opps yields candidates."""
        rejected = [
            _make_rejected_opp(pair="WETH_USDC", gross_spread_bps=12),
            _make_rejected_opp(pair="WETH_DAI", gross_spread_bps=8),
            _make_rejected_opp(pair="WETH_USDT", reject_reason="SLOT0_DIAGNOSTIC"),
        ]
        result, stats = select_sweep_reprieve_candidates(rejected)
        # Only the 2 NET_PROFIT_TOO_LOW cross-DEX quoter_v2 opps qualify
        assert len(result) == 2
        assert stats["sweep_reprieve_selected"] == 2

    def test_evaluate_quotes_returns_rejected(self):
        """evaluate_quotes summary must contain _rejected_opportunities."""
        from engine.opportunity_engine import evaluate_quotes
        quotes = [
            {"dex_id": "uniswap_v3", "token_in": "A", "token_out": "B",
             "price": "100", "fee": 500, "usd_notional": 1000, "amount_in_wei": 1,
             "quote_source": "quoter_v2"},
            {"dex_id": "sushiswap_v3", "token_in": "A", "token_out": "B",
             "price": "101", "fee": 500, "usd_notional": 1000, "amount_in_wei": 1,
             "quote_source": "quoter_v2"},
        ]
        # min_net_profit_usd=9999 forces all opps to be rejected as NET_PROFIT_TOO_LOW
        _, summary = evaluate_quotes(quotes, min_net_profit_usd=9999.0)
        rejected = summary.get("_rejected_opportunities", [])
        assert len(rejected) > 0
        assert all(not r["gate_passed"] for r in rejected)

    def test_reprieve_from_evaluate_quotes_rejected_integration(self):
        """R33 integration: OE rejected list fed to reprieve yields candidates.

        Reproduces the exact failure mode where: OE has NET_PROFIT_TOO_LOW rejects,
        gated opps is empty, but reprieve must return >0 candidates.
        """
        from engine.opportunity_engine import evaluate_quotes
        quotes = [
            {"dex_id": "uniswap_v3", "token_in": "A", "token_out": "B",
             "price": "100", "fee": 500, "usd_notional": 1000, "amount_in_wei": 1,
             "quote_source": "quoter_v2"},
            {"dex_id": "sushiswap_v3", "token_in": "A", "token_out": "B",
             "price": "101", "fee": 500, "usd_notional": 1000, "amount_in_wei": 1,
             "quote_source": "quoter_v2"},
        ]
        gated, summary = evaluate_quotes(quotes, min_net_profit_usd=9999.0)
        # Gated is empty (all rejected by NET_PROFIT_TOO_LOW)
        assert gated == []
        assert summary["rejected_reasons"].get("NET_PROFIT_TOO_LOW", 0) > 0

        # Feed rejected list to reprieve — must find candidates
        rejected = summary["_rejected_opportunities"]
        reprieve, stats = select_sweep_reprieve_candidates(rejected)
        assert stats["sweep_reprieve_selected"] > 0
        assert all(r.get("reject_reason", "").startswith("NET_PROFIT_TOO_LOW") for r in reprieve)
