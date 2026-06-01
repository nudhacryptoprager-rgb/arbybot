"""Unit tests for the M9 profit-validation layer (Steps 1-6).

Covers:
* Step 3 — depth-aware phantom ceiling + round-trip asymmetry
* Step 1 — toxicity gauntlet (evaluate_toxicity + apply_profit_gauntlet)
* Step 4 — size & tax aware honest net (cost_model + profit_validation)
* Step 5 — precision gate
* Step 6 — fork-sim revalidation + micro-live safety guard
* models — GraphEdge.reversed / GraphCycle.reversed
"""
from __future__ import annotations

import pytest

from m9.graph_arb.cost_model import (
    net_bps_size_aware,
    size_aware_slippage_bps,
)
from m9.graph_arb.fork_sim import (
    attempt_micro_live,
    fork_sim_revalidate,
)
from m9.graph_arb.models import CycleQuoteResult, GraphCycle, GraphEdge
from m9.graph_arb.profit_validation import (
    HONEYPOT_FAIL,
    HONEYPOT_PASS,
    HONEYPOT_UNKNOWN,
    MICRO_LIVE_ENABLED,
    MicroLiveBlocked,
    PrecisionConfig,
    apply_profit_gauntlet,
    assert_micro_live_blocked,
    depth_aware_phantom_ceiling_bps,
    detect_asymmetry,
    evaluate_toxicity,
    is_phantom_gross,
    passes_precision_gate,
    tax_adjusted_net_bps,
)

_ADDR_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_ADDR_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
_ADDR_C = "0xcccccccccccccccccccccccccccccccccccccccc"
_QUOTER = "0x1111111111111111111111111111111111111111"
_POOL1 = "0xpool1000000000000000000000000000000000001"
_POOL2 = "0xpool2000000000000000000000000000000000002"
_POOL3 = "0xpool3000000000000000000000000000000000003"


def _edge(sym_in, addr_in, sym_out, addr_out, pool, adapter_type="uniswap_v3",
          fee_bps=5.0, depth=None, in_idx=None, out_idx=None) -> GraphEdge:
    return GraphEdge(
        token_in_sym=sym_in,
        token_out_sym=sym_out,
        token_in_addr=addr_in,
        token_out_addr=addr_out,
        token_in_decimals=18,
        token_out_decimals=18,
        route_id=f"route_{sym_in}_{sym_out}",
        dex_id=adapter_type,
        adapter_type=adapter_type,
        fee=500,
        tick_spacing=None,
        quoter_addr=_QUOTER,
        pool_address=pool,
        fee_bps=fee_bps,
        factory_class="EFFICIENT_BASELINE",
        pair_id=f"{sym_in}_{sym_out}",
        token_in_index=in_idx,
        token_out_index=out_idx,
        effective_depth_usd=depth,
    )


def _cycle(depth=None) -> GraphCycle:
    e_ab = _edge("A", _ADDR_A, "B", _ADDR_B, _POOL1, depth=depth)
    e_bc = _edge("B", _ADDR_B, "C", _ADDR_C, _POOL2, depth=depth)
    e_ca = _edge("C", _ADDR_C, "A", _ADDR_A, _POOL3, depth=depth)
    return GraphCycle(edges=(e_ab, e_bc, e_ca))


def _result(cycle, gross, status="POSITIVE_GROSS", depth=None) -> CycleQuoteResult:
    return CycleQuoteResult(
        cycle=cycle,
        size_usd=100.0,
        amount_in=100,
        amount_out=100,
        gross_bps=gross,
        status=status,
        reject_reason=None,
        leg_results=[],
        elapsed_s=0.0,
        cycle_min_depth_usd=depth,
    )


# ---------------------------------------------------------------------------
# Step 3 — phantom ceiling
# ---------------------------------------------------------------------------


class TestPhantomCeiling:
    def test_no_depth_uses_strict_ceiling(self):
        assert depth_aware_phantom_ceiling_bps(None) == 500.0
        assert depth_aware_phantom_ceiling_bps(0) == 500.0

    def test_ceiling_scales_with_depth(self):
        assert depth_aware_phantom_ceiling_bps(500) == 500.0
        assert depth_aware_phantom_ceiling_bps(5_000) == 800.0
        assert depth_aware_phantom_ceiling_bps(50_000) == 1_200.0
        assert depth_aware_phantom_ceiling_bps(500_000) == 2_000.0

    def test_phantom_7882_bps_rejected_without_depth(self):
        # The audit's signature phantom: +7882 bps in a thin pool.
        assert is_phantom_gross(7882.0, None) is True

    def test_realistic_spread_passes(self):
        assert is_phantom_gross(45.0, None) is False
        assert is_phantom_gross(-120.0, 50_000) is False


# ---------------------------------------------------------------------------
# Step 3 — asymmetry
# ---------------------------------------------------------------------------


class TestAsymmetry:
    def test_both_directions_profit_is_asymmetric(self):
        assert detect_asymmetry(120.0, 90.0) is True

    def test_consistent_roundtrip_passes(self):
        # forward +40, reverse roughly -55 → sum within tolerance
        assert detect_asymmetry(40.0, -55.0) is False

    def test_large_unreconciled_sum_is_asymmetric(self):
        assert detect_asymmetry(600.0, -50.0) is True


# ---------------------------------------------------------------------------
# Step 4 — size & tax aware net
# ---------------------------------------------------------------------------


class TestSizeAwareNet:
    def test_unknown_depth_adds_penalty(self):
        assert size_aware_slippage_bps(100.0, None) == 55.0  # 5 base + 50 penalty

    def test_impact_scales_with_size_over_depth(self):
        # size 1000 / depth 10000 → 0.1 * 1000 = 100 bps impact + 5 base
        assert size_aware_slippage_bps(1_000.0, 10_000.0) == 105.0

    def test_net_subtracts_all_costs(self):
        adapters = ["uniswap_v3", "uniswap_v3", "uniswap_v3"]
        net = net_bps_size_aware(300.0, adapters, 1_000.0, 10_000.0,
                                 token_tax_bps=20.0, mev_haircut_bps=10.0)
        # cost = 8*3=24; slippage = 105*3=315; tax 20; mev 10 → 300-24-315-20-10
        assert net == pytest.approx(300 - 24 - 315 - 20 - 10)

    def test_tax_adjusted_wrapper_matches_cost_model(self):
        adapters = ["uniswap_v2", "uniswap_v2", "uniswap_v2"]
        a = tax_adjusted_net_bps(100.0, adapters, 500.0, 5_000.0, token_tax_bps=15.0)
        b = net_bps_size_aware(100.0, adapters, 500.0, 5_000.0, token_tax_bps=15.0)
        assert a == b


# ---------------------------------------------------------------------------
# Step 1 — toxicity
# ---------------------------------------------------------------------------


class TestToxicity:
    def test_honeypot_fail_is_toxic(self):
        v = evaluate_toxicity(gross_bps=40.0, depth_usd=50_000,
                              honeypot_verdict=HONEYPOT_FAIL)
        assert v.is_toxic is True
        assert "HONEYPOT_FAIL" in v.reasons

    def test_phantom_is_toxic(self):
        v = evaluate_toxicity(gross_bps=7882.0, depth_usd=None,
                              honeypot_verdict=HONEYPOT_PASS)
        assert v.is_toxic is True
        assert "SUSPECT_PHANTOM" in v.reasons

    def test_clean_candidate_not_toxic(self):
        v = evaluate_toxicity(gross_bps=40.0, depth_usd=50_000,
                              honeypot_verdict=HONEYPOT_PASS)
        assert v.is_toxic is False

    def test_unknown_honeypot_not_hard_toxic(self):
        v = evaluate_toxicity(gross_bps=40.0, depth_usd=50_000,
                              honeypot_verdict=HONEYPOT_UNKNOWN)
        assert v.is_toxic is False

    def test_require_known_depth_flags_unknown(self):
        v = evaluate_toxicity(gross_bps=40.0, depth_usd=None,
                              honeypot_verdict=HONEYPOT_PASS,
                              require_known_depth=True)
        assert v.is_toxic is True
        assert "UNKNOWN_DEPTH" in v.reasons


class TestGauntlet:
    def test_downgrades_phantom_positive(self):
        cyc = _cycle(depth=None)
        qr = _result(cyc, gross=7882.0)
        telem = apply_profit_gauntlet([qr], honeypot_fn=lambda a: HONEYPOT_PASS)
        assert qr.status == "GAUNTLET_REJECTED"
        assert qr.gross_bps == 0.0
        assert qr.reject_reason == "SUSPECT_PHANTOM"
        assert telem["downgraded"] == 1

    def test_downgrades_honeypot_failure(self):
        cyc = _cycle(depth=50_000)
        qr = _result(cyc, gross=40.0, depth=50_000)
        telem = apply_profit_gauntlet([qr], honeypot_fn=lambda a: HONEYPOT_FAIL)
        assert qr.status == "GAUNTLET_REJECTED"
        assert qr.reject_reason == "HONEYPOT_FAIL"
        assert telem["downgraded"] == 1

    def test_keeps_clean_positive(self):
        cyc = _cycle(depth=50_000)
        qr = _result(cyc, gross=40.0, depth=50_000)
        telem = apply_profit_gauntlet([qr], honeypot_fn=lambda a: HONEYPOT_PASS)
        assert qr.status == "POSITIVE_GROSS"
        assert qr.gross_bps == 40.0
        assert telem["downgraded"] == 0
        assert telem["kept"] == 1

    def test_ignores_non_positive(self):
        cyc = _cycle(depth=50_000)
        qr = _result(cyc, gross=-30.0, status="NEGATIVE_GROSS", depth=50_000)
        telem = apply_profit_gauntlet([qr], honeypot_fn=lambda a: HONEYPOT_FAIL)
        assert qr.status == "NEGATIVE_GROSS"
        assert telem["evaluated_positive"] == 0


# ---------------------------------------------------------------------------
# Step 5 — precision gate
# ---------------------------------------------------------------------------


class TestPrecisionGate:
    def test_accepts_strong_verified_candidate(self):
        res = passes_precision_gate(
            net_bps=45.0, honeypot_verdict=HONEYPOT_PASS, quoteable_venues=2,
        )
        assert res.passed is True

    def test_rejects_low_net(self):
        res = passes_precision_gate(
            net_bps=10.0, honeypot_verdict=HONEYPOT_PASS, quoteable_venues=2,
        )
        assert res.passed is False
        assert "NET_BELOW_BUFFER" in res.reasons

    def test_rejects_unverified_sell(self):
        res = passes_precision_gate(
            net_bps=45.0, honeypot_verdict=HONEYPOT_UNKNOWN, quoteable_venues=2,
        )
        assert res.passed is False
        assert "SELL_NOT_VERIFIED" in res.reasons

    def test_rejects_single_venue_without_launch(self):
        res = passes_precision_gate(
            net_bps=45.0, honeypot_verdict=HONEYPOT_PASS, quoteable_venues=1,
        )
        assert res.passed is False
        assert "INSUFFICIENT_VENUES" in res.reasons

    def test_launch_mispricing_satisfies_venue_rule(self):
        res = passes_precision_gate(
            net_bps=45.0, honeypot_verdict=HONEYPOT_PASS, quoteable_venues=1,
            launch_mispricing=True,
        )
        assert res.passed is True

    def test_toxic_never_passes(self):
        res = passes_precision_gate(
            net_bps=999.0, honeypot_verdict=HONEYPOT_PASS, quoteable_venues=5,
            toxic=True,
        )
        assert res.passed is False
        assert "TOXIC" in res.reasons

    def test_custom_config_buffer(self):
        cfg = PrecisionConfig(min_net_bps=100.0)
        res = passes_precision_gate(
            net_bps=50.0, honeypot_verdict=HONEYPOT_PASS, quoteable_venues=2, cfg=cfg,
        )
        assert res.passed is False


# ---------------------------------------------------------------------------
# Step 6 — fork-sim + micro-live guard
# ---------------------------------------------------------------------------


class TestForkSim:
    def test_revalidate_positive_sell_path(self):
        cyc = _cycle(depth=100_000)

        def fake_quote(c, s):
            return _result(c, gross=300.0, depth=100_000)

        res = fork_sim_revalidate(cyc, 100.0, quote_fn=fake_quote)
        assert res.simulate_only is True
        assert res.quoteable is True
        assert res.sell_path_ok is True
        assert res.net_bps is not None

    def test_revalidate_unquoteable(self):
        cyc = _cycle(depth=100_000)

        def fake_quote(c, s):
            return _result(c, gross=0.0, status="QUOTE_FAILED")

        res = fork_sim_revalidate(cyc, 100.0, quote_fn=fake_quote)
        assert res.quoteable is False
        assert res.sell_path_ok is False

    def test_revalidate_negative_net_blocks(self):
        cyc = _cycle(depth=100_000)

        def fake_quote(c, s):
            # tiny gross but huge size vs depth → negative net
            return _result(c, gross=5.0, depth=100_000)

        res = fork_sim_revalidate(cyc, 100_000.0, quote_fn=fake_quote)
        assert res.sell_path_ok is False
        assert res.reject_reason == "FORK_NET_NEGATIVE"


class TestMicroLiveGuard:
    def test_flag_is_off(self):
        assert MICRO_LIVE_ENABLED is False

    def test_always_blocks_under_safety_posture(self):
        with pytest.raises(MicroLiveBlocked):
            assert_micro_live_blocked(execution_enabled=True, kill_switch_active=False)

    def test_attempt_micro_live_raises(self):
        with pytest.raises(MicroLiveBlocked):
            attempt_micro_live(execution_enabled=True, kill_switch_active=False)


# ---------------------------------------------------------------------------
# models — reversed()
# ---------------------------------------------------------------------------


class TestReversed:
    def test_edge_reversed_swaps_orientation(self):
        e = _edge("A", _ADDR_A, "B", _ADDR_B, _POOL1, in_idx=0, out_idx=1)
        r = e.reversed()
        assert r.token_in_sym == "B"
        assert r.token_out_sym == "A"
        assert r.token_in_addr == _ADDR_B
        assert r.token_out_addr == _ADDR_A
        assert r.token_in_index == 1
        assert r.token_out_index == 0
        # pool identity preserved
        assert r.pool_address == e.pool_address
        assert r.fee_bps == e.fee_bps

    def test_cycle_reversed_is_closed_and_opposite(self):
        cyc = _cycle()
        rev = cyc.reversed()
        assert rev.length == 3
        # forward path A->B->C, reverse path should start at A and go A->C->B
        assert rev.token_path[0] == "A"
        assert rev.token_path == ["A", "C", "B"]

    def test_double_reverse_restores_path(self):
        cyc = _cycle()
        assert cyc.reversed().reversed().token_path == cyc.token_path
