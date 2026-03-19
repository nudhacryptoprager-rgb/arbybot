from strategy.jobs.run_scan_real import _build_live_candidate_stream
from engine.roundtrip import RoundTripResult


def test_build_live_candidate_stream_prefers_sweep_fields():
    opps = [{
        "pair": "WETH/USDC",
        "buy_dex": "a",
        "sell_dex": "b",
        "usd_notional": 100.0,
        "spread_bps": 18.0,
    }]
    results = [
        RoundTripResult(
            pair="WETH/USDC",
            buy_dex="a",
            sell_dex="b",
            amount_in_wei=1,
            token_in="WETH",
            token_out="USDC",
            leg1_amount_out=1,
            leg2_amount_out=1,
            leg2_is_real_quote=True,
            is_profitable=False,
            gross_pnl_bps=-10.0,
            net_pnl_bps=-12.0,
            estimated_slippage_bps=5.0,
            leg1_fee=500,
            leg2_fee=500,
        )
    ]
    dynamic_sweep = {
        "results": [{
            "pair": "WETH/USDC",
            "buy_dex": "a",
            "sell_dex": "b",
            "best_size_usd": 75.0,
            "best_net_pnl_bps": -4.5,
            "best_total_cost_bps": 11.25,
        }]
    }

    candidates = _build_live_candidate_stream("arb", opps, results, dynamic_sweep, 100.0)
    assert len(candidates) == 1
    assert candidates[0]["optimal_size_usd"] == 75.0
    assert candidates[0]["execution_cost_bps"] == 11.25
    assert candidates[0]["final_net_pnl_bps"] == -4.5
    # R28.22b: new fields
    assert candidates[0]["is_actionable"] is True  # real_quote + not SUSPECT
    assert candidates[0]["spread_bps"] == 18.0  # from opp
    assert candidates[0]["final_net_pnl_usd"] is not None
    assert round(candidates[0]["final_net_pnl_usd"], 4) == round(75.0 * -4.5 / 10000.0, 4)


def test_build_live_candidate_stream_marks_diagnostic_when_no_real_quote():
    results = [
        RoundTripResult(
            pair="USDC/DAI",
            buy_dex="a",
            sell_dex="b",
            amount_in_wei=1,
            token_in="USDC",
            token_out="DAI",
            leg1_amount_out=1,
            leg2_amount_out=1,
            leg2_is_real_quote=False,
            is_profitable=False,
            gross_pnl_bps=1.0,
            net_pnl_bps=-2.0,
            estimated_slippage_bps=1.0,
            leg1_fee=100,
            leg2_fee=100,
        )
    ]

    candidates = _build_live_candidate_stream("base", [], results, None, 50.0)
    assert len(candidates) == 1
    assert candidates[0]["final_result"] == "ONE_LEG_ONLY_DIAGNOSTIC"
    assert candidates[0]["network"] == "base"
    # R28.22b: diagnostic is NOT actionable
    assert candidates[0]["is_actionable"] is False
    # spread_bps falls back to gross_pnl_bps when opp is empty
    assert candidates[0]["spread_bps"] == 1.0


def test_build_live_candidate_stream_spread_bps_fallback_to_gross_pnl():
    """spread_bps must never be null when gross_pnl_bps is available."""
    results = [
        RoundTripResult(
            pair="WBTC/USDC",
            buy_dex="x",
            sell_dex="y",
            amount_in_wei=1,
            token_in="WBTC",
            token_out="USDC",
            leg1_amount_out=1,
            leg2_amount_out=1,
            leg2_is_real_quote=True,
            is_profitable=False,
            gross_pnl_bps=25.5,
            net_pnl_bps=-8.0,
            estimated_slippage_bps=3.0,
            leg1_fee=300,
            leg2_fee=300,
        )
    ]
    # No opp with spread_bps — forces fallback
    candidates = _build_live_candidate_stream("arb", [], results, None, 200.0)
    assert len(candidates) == 1
    assert candidates[0]["spread_bps"] == 25.5  # from gross_pnl_bps
    assert candidates[0]["is_actionable"] is True
    assert candidates[0]["final_net_pnl_usd"] is not None


def test_build_live_candidate_stream_suspect_not_actionable():
    """SUSPECT_ACCOUNTING rows must NOT be actionable."""
    results = [
        RoundTripResult(
            pair="WETH/USDC",
            buy_dex="a",
            sell_dex="b",
            amount_in_wei=1,
            token_in="WETH",
            token_out="USDC",
            leg1_amount_out=1,
            leg2_amount_out=1,
            leg2_is_real_quote=True,
            is_profitable=True,
            gross_pnl_bps=600.0,  # >500 with profitable → SUSPECT
            net_pnl_bps=590.0,
            estimated_slippage_bps=5.0,
            leg1_fee=500,
            leg2_fee=500,
        )
    ]
    candidates = _build_live_candidate_stream("arb", [], results, None, 100.0)
    assert len(candidates) == 1
    assert candidates[0]["final_result"] == "SUSPECT_ACCOUNTING"
    assert candidates[0]["is_actionable"] is False


def test_serialize_live_stream_splits_actionable_diagnostic():
    """_serialize_live_stream must separate actionable from diagnostic rows."""
    from start import _serialize_live_stream
    import time

    active = {
        "arb": {
            "_started_monotonic": time.monotonic() - 5.0,
            "chain": "arb",
            "verified_pairs": [
                {"pair": "WETH/USDC", "is_actionable": True, "final_result": "ROUNDTRIP_NOT_PROFITABLE"},
                {"pair": "WBTC/USDC", "is_actionable": False, "final_result": "ONE_LEG_ONLY_DIAGNOSTIC"},
            ],
        }
    }
    result = _serialize_live_stream(active, [])
    assert len(result["verified_pairs"]) == 1
    assert result["verified_pairs"][0]["pair"] == "WETH/USDC"
    assert len(result["diagnostic_pairs"]) == 1
    assert result["diagnostic_pairs"][0]["pair"] == "WBTC/USDC"
