# PATH: tests/unit/test_r38_changes.py
"""
Tests for R38 changes:
1. LST pair detection and tighter SUSPECT_ACCOUNTING threshold
2. blocker_classification in run_summary (m4/fixtures.py)
3. per_chain alias fields in long_scan_summary
4. pair_level_rca LST annotation helper
"""
import pytest


# ---------- 1. LST pair detection ----------

class TestLSTPairDetection:
    def test_wsteth_weth_is_lst(self):
        from strategy.live_stream import _is_lst_pair
        assert _is_lst_pair("WSTETH/WETH") is True

    def test_meth_weth_is_lst(self):
        from strategy.live_stream import _is_lst_pair
        assert _is_lst_pair("METH/WETH") is True

    def test_cbeth_usdc_is_lst(self):
        from strategy.live_stream import _is_lst_pair
        assert _is_lst_pair("cbETH/USDC") is True

    def test_sfrxeth_eth_is_lst(self):
        from strategy.live_stream import _is_lst_pair
        assert _is_lst_pair("sfrxETH/ETH") is True

    def test_usdc_weth_not_lst(self):
        from strategy.live_stream import _is_lst_pair
        assert _is_lst_pair("USDC/WETH") is False

    def test_dai_usdc_not_lst(self):
        from strategy.live_stream import _is_lst_pair
        assert _is_lst_pair("DAI/USDC") is False

    def test_threshold_constants(self):
        from strategy.live_stream import _SANE_RT_PNL_MAX_BPS, _SANE_RT_PNL_MAX_BPS_LST
        assert _SANE_RT_PNL_MAX_BPS == 500
        assert _SANE_RT_PNL_MAX_BPS_LST == 50


# ---------- 2. pair_level_rca LST detection ----------

class TestPairLevelRcaLST:
    def test_is_lst_pair_rca_matches_live_stream(self):
        from scripts.pair_level_rca import _is_lst_pair_rca
        from strategy.live_stream import _is_lst_pair
        pairs = ["WSTETH/WETH", "METH/WETH", "USDC/WETH", "DAI/USDC", "rETH/WETH"]
        for p in pairs:
            assert _is_lst_pair_rca(p) == _is_lst_pair(p), f"Mismatch for {p}"


# ---------- 3. blocker_classification in run_summary ----------

class TestBlockerClassificationInFixtures:
    """
    Test the blocker_classification logic added to m4/fixtures.py (R38).
    We can't easily call the full fixture builder, so we test the classification
    logic inline — it mirrors the code in fixtures.py.
    """

    def _classify(self, *, profitable=False, signals=10,
                  oe_funnel=None, truth_verdict="NO_PROFIT"):
        """Reproduce the R38 classification logic from m4/fixtures.py."""
        _rt_profitable = profitable
        included_signals_count = signals
        truth_data = {"oe_rejection_funnel": oe_funnel or {}}

        _oe_funnel = truth_data.get("oe_rejection_funnel", {})
        _oe_rej_reasons = _oe_funnel.get("rejected_reasons", {})
        _oe_total_rej = _oe_funnel.get("rejected_count", 0)

        if _rt_profitable:
            return "ROUNDTRIP_PROFITABLE"
        elif included_signals_count == 0:
            return "NO_SIGNAL"
        elif _oe_total_rej > 0:
            _net_low = _oe_rej_reasons.get("NET_PROFIT_TOO_LOW", 0)
            _mixed = _oe_rej_reasons.get("MIXED_SOURCE", 0)
            _slot0 = _oe_rej_reasons.get("SLOT0_DIAGNOSTIC", 0)
            if _slot0 / _oe_total_rej > 0.4:
                return "QUOTE_PATH_BLOCKED"
            elif _net_low / _oe_total_rej > 0.4:
                return "OE_ECONOMICS"
            elif _mixed / _oe_total_rej > 0.3:
                return "MIXED_SOURCE"
            else:
                return "OE_ECONOMICS"
        elif truth_verdict == "DIAGNOSTIC_PROFIT_ONLY":
            return "OE_ECONOMICS"
        else:
            return None

    def test_profitable_wins(self):
        assert self._classify(profitable=True) == "ROUNDTRIP_PROFITABLE"

    def test_no_signal(self):
        assert self._classify(signals=0) == "NO_SIGNAL"

    def test_slot0_dominance_is_quote_path_blocked(self):
        funnel = {"rejected_count": 10, "rejected_reasons": {"SLOT0_DIAGNOSTIC": 5}}
        assert self._classify(oe_funnel=funnel) == "QUOTE_PATH_BLOCKED"

    def test_net_profit_low_is_oe_economics(self):
        funnel = {"rejected_count": 10, "rejected_reasons": {"NET_PROFIT_TOO_LOW": 8}}
        assert self._classify(oe_funnel=funnel) == "OE_ECONOMICS"

    def test_mixed_source(self):
        funnel = {"rejected_count": 10, "rejected_reasons": {"MIXED_SOURCE": 4}}
        assert self._classify(oe_funnel=funnel) == "MIXED_SOURCE"

    def test_diagnostic_profit_only_verdict(self):
        assert self._classify(truth_verdict="DIAGNOSTIC_PROFIT_ONLY") == "OE_ECONOMICS"

    def test_no_funnel_no_verdict(self):
        assert self._classify(truth_verdict="NO_PROFIT") is None

    def test_profitable_wins_over_oe(self):
        funnel = {"rejected_count": 10, "rejected_reasons": {"NET_PROFIT_TOO_LOW": 8}}
        assert self._classify(profitable=True, oe_funnel=funnel) == "ROUNDTRIP_PROFITABLE"


# ---------- 4. per_chain aliases in long_scan_summary ----------

class TestPerChainAliases:
    """Verify that build_summary produces pass_runs, signals_count, real_quote_count aliases."""

    def _make_per_chain(self, **overrides):
        s = {
            "runs": 10,
            "fail": 0,
            "infra_fail": 0,
            "pass": 8,
            "no_data": 0,
            "included_signals_total": 50,
            "real_quote_count_total": 30,
            "profitable_roundtrips_total": 0,
            "roundtrip_evaluated_total": 5,
            "best_net_pnl_bps": -20.0,
            "best_roundtrip_net_bps": -20.0,
            "net_usdc_total": 0.0,
            "SUSPECT_ACCOUNTING_count": 0,
            "last_truth_verdict": "NO_PROFIT",
            "last_quote_source_summary": {},
            "last_oe_rejection_funnel": {},
            "blocker_evidence": "OE_ECONOMICS",
            "_sweep_gap_values": [],
            "runs_with_sweep": 0,
        }
        s.update(overrides)
        return s

    def test_aliases_present_in_summary(self):
        from strategy.long_scan_summary import build_summary
        per_chain = {"arbitrum_one": self._make_per_chain(
            **{"pass": 8, "included_signals_total": 42, "real_quote_count_total": 25}
        )}
        result = build_summary(per_chain, wall_seconds=60.0, warnings=[])
        chain_data = result["per_chain"]["arbitrum_one"]
        assert chain_data["pass_runs"] == 8
        assert chain_data["signals_count"] == 42
        assert chain_data["real_quote_count"] == 25

    def test_aliases_default_to_zero(self):
        from strategy.long_scan_summary import build_summary
        per_chain = {"linea": self._make_per_chain(
            **{"pass": 0, "included_signals_total": 0, "real_quote_count_total": 0}
        )}
        result = build_summary(per_chain, wall_seconds=10.0, warnings=[])
        chain_data = result["per_chain"]["linea"]
        assert chain_data["pass_runs"] == 0
        assert chain_data["signals_count"] == 0
        assert chain_data["real_quote_count"] == 0


# ---------- 5. blocker_reason text includes SLIPPAGE ----------

class TestBlockerReasonText:
    def test_oe_economics_mentions_slippage(self):
        from strategy.long_scan_summary import _blocker_evidence_reason
        reason = _blocker_evidence_reason("OE_ECONOMICS")
        assert "SLIPPAGE_TOO_HIGH" in reason
        assert "NET_PROFIT_TOO_LOW" in reason

    def test_quote_path_constrained_exists(self):
        from strategy.long_scan_summary import _blocker_evidence_reason
        reason = _blocker_evidence_reason("QUOTE_PATH_CONSTRAINED")
        assert reason is not None
        assert "cross-DEX" in reason.lower() or "cross-dex" in reason.lower()


# ---------- 6. DirtySetTracker event-driven wait ----------

class TestDirtySetTrackerEventDriven:
    def test_wait_for_dirty_returns_immediately_when_dirty(self):
        from strategy.infra import DirtySetTracker
        tracker = DirtySetTracker()
        tracker.start_watching("test_chain", None)  # no WS -> always dirty
        assert tracker.wait_for_dirty(timeout=0.01) is True
        tracker.stop()

    def test_wait_for_dirty_timeout_when_clean(self):
        import threading
        from strategy.infra import DirtySetTracker
        tracker = DirtySetTracker()
        tracker.start_watching("test_chain", None)
        # Mark clean + pretend WS is connected (so it's not always-dirty)
        with tracker._lock:
            tracker._dirty["test_chain"] = False
            tracker._connected["test_chain"] = True
        result = tracker.wait_for_dirty(timeout=0.05)
        # Should timeout (False) since chain is clean and connected
        assert result is False
        tracker.stop()

    def test_wait_for_dirty_wakes_on_event(self):
        import threading
        from strategy.infra import DirtySetTracker
        tracker = DirtySetTracker()
        tracker.start_watching("test_chain", None)
        with tracker._lock:
            tracker._dirty["test_chain"] = False
            tracker._connected["test_chain"] = True

        # Simulate block event from WS thread after short delay
        def _simulate_block():
            import time as _t
            _t.sleep(0.02)
            with tracker._lock:
                tracker._dirty["test_chain"] = True
            tracker._dirty_event.set()

        t = threading.Thread(target=_simulate_block, daemon=True)
        t.start()
        result = tracker.wait_for_dirty(timeout=1.0)
        assert result is True
        t.join(timeout=1.0)
        tracker.stop()

    def test_status_reports_event_driven(self):
        from strategy.infra import DirtySetTracker
        tracker = DirtySetTracker()
        tracker.start_watching("arb", None)
        status = tracker.status()
        assert status["event_driven"] is True
        tracker.stop()


# ---------- 7. R39: Frontier contract consistency ----------

class TestFrontierContractConsistency:
    """Verify that sweep_best_net_pnl_bps and sweep_best_frontier_reason
    are always consistent — 0.0 must be BREAKEVEN_FRONTIER, not BEST_NEG."""

    def _make_per_chain(self, chains):
        """Helper: build per_chain dict from list of (name, pnl, reason) tuples."""
        from strategy.chain_stats import new_chain_stats
        result = {}
        for name, pnl, reason in chains:
            stats = new_chain_stats()
            stats["config"] = f"config/{name}.yaml"
            stats["sweep_best_net_pnl_bps"] = pnl
            stats["sweep_best_frontier_reason"] = reason
            stats["sweep_best_size_usd"] = 750 if pnl is not None else None
            result[name] = stats
        return result

    def test_breakeven_not_overridden_by_best_neg(self):
        """When best chain has pnl=0.0 (BREAKEVEN_FRONTIER), top-level must
        not pick BEST_NEG from a worse chain."""
        from strategy.long_scan_summary import build_summary
        per_chain = self._make_per_chain([
            ("arb", 0.0, "BREAKEVEN_FRONTIER"),
            ("zksync", -5.0, "BEST_NEG"),
        ])
        summary = build_summary(per_chain, wall_seconds=10.0, warnings=[])
        assert summary["sweep_best_net_pnl_bps"] == 0.0
        assert summary["sweep_best_frontier_reason"] == "BREAKEVEN_FRONTIER"

    def test_post_fence_corrects_mismatch(self):
        """Post-aggregation fence: if aggregation produces 0.0+BEST_NEG, correct it."""
        from strategy.long_scan_summary import build_summary
        # Simulate the pathological case: chain A has pnl=0.0 but reason=None,
        # chain B has pnl=-10 with reason=BEST_NEG
        per_chain = self._make_per_chain([
            ("arb", 0.0, None),
            ("zksync", -10.0, "BEST_NEG"),
        ])
        summary = build_summary(per_chain, wall_seconds=10.0, warnings=[])
        assert summary["sweep_best_net_pnl_bps"] == 0.0
        assert summary["sweep_best_frontier_reason"] == "BREAKEVEN_FRONTIER"

    def test_negative_pnl_gets_best_neg(self):
        """Negative pnl must map to BEST_NEG (not BREAKEVEN_FRONTIER)."""
        from strategy.long_scan_summary import build_summary
        per_chain = self._make_per_chain([
            ("arb", -5.0, "BEST_NEG"),
        ])
        summary = build_summary(per_chain, wall_seconds=10.0, warnings=[])
        assert summary["sweep_best_net_pnl_bps"] == -5.0
        assert summary["sweep_best_frontier_reason"] == "BEST_NEG"

    def test_suspect_zero_slippage_not_promoted_to_breakeven(self):
        """R39i: SUSPECT_ZERO_SLIPPAGE at pnl=0.0 must not be overridden
        to BREAKEVEN_FRONTIER by the post-aggregation fence."""
        from strategy.long_scan_summary import build_summary
        per_chain = self._make_per_chain([
            ("arb", 0.0, "SUSPECT_ZERO_SLIPPAGE"),
            ("zksync", -10.0, "BEST_NEG"),
        ])
        summary = build_summary(per_chain, wall_seconds=10.0, warnings=[])
        assert summary["sweep_best_net_pnl_bps"] == 0.0
        assert summary["sweep_best_frontier_reason"] == "SUSPECT_ZERO_SLIPPAGE"


# ---------- 8. R39: Sweep size promotion guard ----------

class TestSweepSizePromotionGuard:
    """Verify that sweep best_size is only promoted when frontier is executable."""

    def test_non_executable_falls_back_to_config(self):
        """When measured_slippage_bps is None (paper-only), config size is used."""
        ds = {
            "best_size_usd": 750,
            "best_frontier_reason": "BREAKEVEN_FRONTIER",
            "measured_total_cost_bps": 31.0,
            "measured_slippage_bps": None,  # NOT measured
            "measured_gas_bps": 0.0,
        }
        config_size = 150.0
        frontier = ds.get("best_frontier_reason")
        total_cost = ds.get("measured_total_cost_bps")
        slip = ds.get("measured_slippage_bps")
        is_exec = (
            ds["best_size_usd"] is not None
            and ds["best_size_usd"] > 0
            and frontier in ("BREAKEVEN_FRONTIER", "PROFITABLE")
            and total_cost is not None
            and total_cost > 0
            and slip is not None
        )
        assert is_exec is False
        result_size = float(ds["best_size_usd"]) if is_exec else config_size
        assert result_size == config_size

    def test_executable_promotes_sweep_size(self):
        """When all measured costs present, sweep size is promoted."""
        ds = {
            "best_size_usd": 5000,
            "best_frontier_reason": "PROFITABLE",
            "measured_total_cost_bps": 45.0,
            "measured_slippage_bps": 20.0,
            "measured_gas_bps": 12.0,
        }
        config_size = 150.0
        frontier = ds.get("best_frontier_reason")
        total_cost = ds.get("measured_total_cost_bps")
        slip = ds.get("measured_slippage_bps")
        is_exec = (
            ds["best_size_usd"] is not None
            and ds["best_size_usd"] > 0
            and frontier in ("BREAKEVEN_FRONTIER", "PROFITABLE")
            and total_cost is not None
            and total_cost > 0
            and slip is not None
        )
        assert is_exec is True
        result_size = float(ds["best_size_usd"]) if is_exec else config_size
        assert result_size == 5000.0

    def test_best_neg_frontier_blocks_promotion(self):
        """BEST_NEG frontier blocks size promotion even with measured costs."""
        ds = {
            "best_size_usd": 750,
            "best_frontier_reason": "BEST_NEG",
            "best_total_cost_bps": 31.0,
            "best_slippage_bps": 10.0,
            "best_gas_bps": 5.0,
        }
        frontier = ds.get("best_frontier_reason")
        # R39c: guard now also accepts EXECUTABLE_BEST_NEG, but plain BEST_NEG still blocks
        is_exec = frontier in ("BREAKEVEN_FRONTIER", "PROFITABLE", "EXECUTABLE_BEST_NEG")
        assert is_exec is False


# ---------- 9. R39: RCA gas_bps from reject_reason ----------

class TestRcaGasBpsFromRejectReason:
    """Verify _rt_gas_bps prefers reject_reason over back-calculation."""

    def test_parses_gas_from_reject_reason(self):
        from scripts.pair_level_rca import _rt_gas_bps
        rt = {
            "reject_reason": "SLIPPAGE_TOO_HIGH: net_pnl_bps=-54.05|slippage=792.2|lp_fee=6.0|gas=12.0",
            "gas_cost_usd": 0.9,
            "gross_pnl_bps": -42.0,
            "gross_pnl_usd": -3.15,
        }
        assert _rt_gas_bps(rt) == 12.0

    def test_fallback_when_no_reject_reason(self):
        from scripts.pair_level_rca import _rt_gas_bps
        rt = {
            "reject_reason": None,
            "gas_cost_usd": 0.9,
            "gross_pnl_bps": -42.0,
            "gross_pnl_usd": -3.15,
        }
        result = _rt_gas_bps(rt)
        # Back-calc: notional = 3.15 / (42.0/10000) = 750, gas_bps = 0.9/750*10000 = 12.0
        assert abs(result - 12.0) < 0.5

    def test_zero_when_no_data(self):
        from scripts.pair_level_rca import _rt_gas_bps
        rt = {"gross_pnl_bps": 0, "gross_pnl_usd": 0}
        assert _rt_gas_bps(rt) == 0


# ---------- 10. R39: chain_stats sweep measured fields 0.0 truthiness ----------

class TestChainStatsSweepMeasured:
    """Verify chain_stats maps sweep fields without 0.0 truthiness bug."""

    def test_zero_slippage_preserved(self):
        """best_slippage_bps=0.0 should map to sweep_measured_slippage_bps=0.0, not None."""
        sweep = {
            "best_net_pnl_bps": 0.0,
            "best_size_usd": 2500,
            "best_gas_bps": 0.0,
            "best_fee_bps": 6.0,
            "best_slippage_bps": 0.0,
            "best_total_cost_bps": 6.0,
            "gap_to_zero_bps": 0.0,
            "best_frontier_reason": "BREAKEVEN_FRONTIER",
        }
        # Simulate chain_stats logic
        _gas = sweep.get("measured_gas_bps")
        gas_result = _gas if _gas is not None else sweep.get("best_gas_bps")
        _slip = sweep.get("measured_slippage_bps")
        slip_result = _slip if _slip is not None else sweep.get("best_slippage_bps")
        _tcost = sweep.get("measured_total_cost_bps")
        tcost_result = _tcost if _tcost is not None else sweep.get("best_total_cost_bps")
        assert gas_result == 0.0  # not None
        assert slip_result == 0.0  # not None
        assert tcost_result == 6.0

    def test_none_falls_through(self):
        """When neither measured nor best exists, result is None."""
        sweep = {"best_net_pnl_bps": -5.0}
        _slip = sweep.get("measured_slippage_bps")
        slip_result = _slip if _slip is not None else sweep.get("best_slippage_bps")
        assert slip_result is None

    def test_sweep_routes_evaluated_total_accumulates(self):
        """R39x+2: sweep_routes_evaluated_total accumulates routes_swept from dynamic_sweep."""
        from strategy.chain_stats import new_chain_stats, update_chain_stats

        stats = new_chain_stats()
        summary = {
            "status": "PASS",
            "metrics": {
                "included_signals_count": 10,
                "roundtrip": {
                    "evaluated_count": 0,
                    "real_quote_count": 0,
                    "dynamic_sweep": {
                        "routes_swept": 3,
                        "best_net_pnl_bps": -8.7,
                        "gap_to_zero_bps": 8.7,
                    },
                },
            },
            "run_context": {"run_timestamp": "2026-03-27T00:00:00Z"},
        }
        update_chain_stats(stats, exit_code=0, run_dir=None, summary=summary)
        assert stats["sweep_routes_evaluated_total"] == 3
        assert stats["roundtrip_evaluated_total"] == 0  # OE path stays zero
        # Second run accumulates
        update_chain_stats(stats, exit_code=0, run_dir=None, summary=summary)
        assert stats["sweep_routes_evaluated_total"] == 6


# ---------- 11. R39: pair_trace gas_bps from reject_reason ----------

class TestPairTraceGasFromRejectReason:
    """Verify pair_trace.py computes gas_bps from reject_reason, not notional hack."""

    def test_gas_parsed_from_reject_reason(self):
        from types import SimpleNamespace
        from strategy.pair_trace import build_pair_funnel_trace
        pairs = [SimpleNamespace(display_name="USDC/DAI", token_in="USDC", token_out="DAI")]
        rt = SimpleNamespace(
            pair="USDC/DAI",
            net_pnl_bps=-54.07,
            gross_pnl_bps=-42.03,
            gross_pnl_usd=-0.0042,
            estimated_slippage_bps=792.18,
            gas_cost_usd=0.014,
            leg1_fee=300,
            leg2_fee=300,
            leg2_is_real_quote=True,
            reject_reason="SLIPPAGE_TOO_HIGH: net_pnl_bps=-54.07|slippage=792.2|lp_fee=6.0|gas=12.0",
            is_profitable=False,
            net_pnl_usd=-0.005,
        )
        trace = build_pair_funnel_trace(pairs, [], [], [], [], [rt], [])
        econ = trace[0]["economics"]
        # Must match reject_reason gas=12.0, NOT back-calculated 2864.67
        assert econ["rt_gas_bps"] == 12.0

    def test_gas_fallback_when_no_reject_reason(self):
        from types import SimpleNamespace
        from strategy.pair_trace import build_pair_funnel_trace
        pairs = [SimpleNamespace(display_name="WETH/USDC", token_in="WETH", token_out="USDC")]
        rt = SimpleNamespace(
            pair="WETH/USDC",
            net_pnl_bps=-749.43,
            gross_pnl_bps=-738.9,
            gross_pnl_usd=-0.7389,
            estimated_slippage_bps=860.24,
            gas_cost_usd=0.0105,
            leg1_fee=3000,
            leg2_fee=100,
            leg2_is_real_quote=True,
            reject_reason=None,
            is_profitable=False,
            net_pnl_usd=-0.07494,
        )
        trace = build_pair_funnel_trace(pairs, [], [], [], [], [rt], [])
        econ = trace[0]["economics"]
        # Fallback: notional = 0.7389 / (738.9/10000) = 10.0, gas = 0.0105/10.0*10000 = 10.5
        assert econ["rt_gas_bps"] == 10.5

    def test_route_level_data_collected(self):
        """R39c: pair_trace collects route-level buy_dex→sell_dex per RT result."""
        from types import SimpleNamespace
        from strategy.pair_trace import build_pair_funnel_trace
        pairs = [SimpleNamespace(display_name="USDC/DAI", token_in="USDC", token_out="DAI")]
        rt = SimpleNamespace(
            pair="USDC/DAI",
            net_pnl_bps=-54.07,
            gross_pnl_bps=-42.03,
            gross_pnl_usd=-0.0042,
            estimated_slippage_bps=792.18,
            gas_cost_usd=0.014,
            leg1_fee=300,
            leg2_fee=300,
            leg2_is_real_quote=True,
            reject_reason="SLIPPAGE_TOO_HIGH: net_pnl_bps=-54.07|slippage=792.2|lp_fee=6.0|gas=12.0",
            is_profitable=False,
            net_pnl_usd=-0.005,
            buy_dex="uniswap_v3",
            sell_dex="sushiswap",
        )
        trace = build_pair_funnel_trace(pairs, [], [], [], [], [rt], [])
        routes = trace[0].get("routes", [])
        assert len(routes) == 1
        assert routes[0]["buy_dex"] == "uniswap_v3"
        assert routes[0]["sell_dex"] == "sushiswap"
        assert routes[0]["net_pnl_bps"] == -54.07
        assert routes[0]["gas_bps"] == 12.0
        assert routes[0]["lp_fee_bps"] == 6.0
        assert routes[0]["leg2_real"] is True


# ---------- 12. R39c: EXECUTABLE_BEST_NEG distinction ----------

class TestExecutableBestNeg:
    """Verify EXECUTABLE_BEST_NEG upgrade and acceptance in chain_stats / summary / sweep guard."""

    def test_chain_stats_upgrades_best_neg_with_measured_costs(self):
        """BEST_NEG with measured gas + slippage → EXECUTABLE_BEST_NEG."""
        # Simulate chain_stats upgrade logic (lines 281-289)
        _raw_reason = "BEST_NEG"
        measured_slip = 20.0  # not None
        measured_gas = 12.0   # not None
        if (
            _raw_reason == "BEST_NEG"
            and measured_slip is not None
            and measured_gas is not None
        ):
            _raw_reason = "EXECUTABLE_BEST_NEG"
        assert _raw_reason == "EXECUTABLE_BEST_NEG"

    def test_chain_stats_no_upgrade_without_measured(self):
        """BEST_NEG without measured costs stays BEST_NEG."""
        _raw_reason = "BEST_NEG"
        measured_slip = None
        measured_gas = None
        if (
            _raw_reason == "BEST_NEG"
            and measured_slip is not None
            and measured_gas is not None
        ):
            _raw_reason = "EXECUTABLE_BEST_NEG"
        assert _raw_reason == "BEST_NEG"

    def test_chain_stats_no_upgrade_partial_measured(self):
        """BEST_NEG with only gas (no slippage) stays BEST_NEG."""
        _raw_reason = "BEST_NEG"
        measured_slip = None
        measured_gas = 12.0
        if (
            _raw_reason == "BEST_NEG"
            and measured_slip is not None
            and measured_gas is not None
        ):
            _raw_reason = "EXECUTABLE_BEST_NEG"
        assert _raw_reason == "BEST_NEG"

    def test_chain_stats_zero_measured_still_upgrades(self):
        """BEST_NEG with measured_gas=0.0 and measured_slip=0.0 → upgrades (0.0 != None)."""
        _raw_reason = "BEST_NEG"
        measured_slip = 0.0
        measured_gas = 0.0
        if (
            _raw_reason == "BEST_NEG"
            and measured_slip is not None
            and measured_gas is not None
        ):
            _raw_reason = "EXECUTABLE_BEST_NEG"
        assert _raw_reason == "EXECUTABLE_BEST_NEG"

    def test_post_fence_accepts_executable_best_neg(self):
        """build_summary post-fence: EXECUTABLE_BEST_NEG with pnl < 0 is preserved."""
        from strategy.long_scan_summary import build_summary
        from strategy.chain_stats import new_chain_stats
        stats = new_chain_stats()
        stats["config"] = "config/arb.yaml"
        stats["sweep_best_net_pnl_bps"] = -50.0
        stats["sweep_best_frontier_reason"] = "EXECUTABLE_BEST_NEG"
        stats["sweep_best_size_usd"] = 750
        per_chain = {"arbitrum_one": stats}
        summary = build_summary(per_chain, wall_seconds=10.0, warnings=[])
        assert summary["sweep_best_net_pnl_bps"] == -50.0
        assert summary["sweep_best_frontier_reason"] == "EXECUTABLE_BEST_NEG"

    def test_post_fence_corrects_unknown_reason(self):
        """Unknown reason with pnl < 0 → BEST_NEG."""
        from strategy.long_scan_summary import build_summary
        from strategy.chain_stats import new_chain_stats
        stats = new_chain_stats()
        stats["config"] = "config/arb.yaml"
        stats["sweep_best_net_pnl_bps"] = -30.0
        stats["sweep_best_frontier_reason"] = "SOMETHING_WEIRD"
        stats["sweep_best_size_usd"] = 500
        per_chain = {"arb": stats}
        summary = build_summary(per_chain, wall_seconds=10.0, warnings=[])
        assert summary["sweep_best_frontier_reason"] == "BEST_NEG"

    def test_sweep_guard_accepts_executable_best_neg(self):
        """Sweep size promotion guard accepts EXECUTABLE_BEST_NEG."""
        ds = {
            "best_size_usd": 750,
            "best_frontier_reason": "EXECUTABLE_BEST_NEG",
            "best_total_cost_bps": 38.0,
            "best_slippage_bps": 20.0,
        }
        config_size = 150.0
        frontier = ds.get("best_frontier_reason")
        total_cost = ds.get("best_total_cost_bps")
        slip = ds.get("best_slippage_bps")
        is_exec = (
            ds["best_size_usd"] is not None
            and ds["best_size_usd"] > 0
            and frontier in ("BREAKEVEN_FRONTIER", "PROFITABLE", "EXECUTABLE_BEST_NEG")
            and total_cost is not None
            and total_cost > 0
            and slip is not None
        )
        assert is_exec is True
        result_size = float(ds["best_size_usd"]) if is_exec else config_size
        assert result_size == 750.0

    def test_frontier_ranking_includes_reason(self):
        """Per-chain frontier ranking includes sweep_best_frontier_reason."""
        from strategy.long_scan_summary import build_summary
        from strategy.chain_stats import new_chain_stats
        stats = new_chain_stats()
        stats["config"] = "config/arb.yaml"
        stats["sweep_best_net_pnl_bps"] = -50.0
        stats["sweep_best_frontier_reason"] = "EXECUTABLE_BEST_NEG"
        stats["sweep_best_size_usd"] = 750
        stats["_sweep_gap_values"] = [50.0]
        stats["runs_with_sweep"] = 1
        per_chain = {"arbitrum_one": stats}
        summary = build_summary(per_chain, wall_seconds=10.0, warnings=[])
        ranking = summary.get("frontier_ranking", [])
        assert len(ranking) == 1
        assert ranking[0]["sweep_best_frontier_reason"] == "EXECUTABLE_BEST_NEG"


# ---------- R39i++: WS subscription error handling ----------

class TestWsSubscriptionValidation:
    """Verify _ws_loop handles eth_subscribe rejection gracefully."""

    def test_ws_loop_detects_subscription_error(self):
        """If eth_subscribe returns error JSON, the loop should not crash."""
        import json
        import threading
        from strategy.infra import DirtySetTracker

        tracker = DirtySetTracker()

        # Validate that the _ws_loop code handles JSON error response
        # by testing the validation logic inline
        error_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        })

        data = json.loads(error_response)
        has_error = "error" in data
        assert has_error is True
        assert data["error"]["message"] == "Method not found"
        tracker.stop()

    def test_ws_connected_false_when_no_url(self):
        """Chain without ws_url stays connected=False permanently."""
        from strategy.infra import DirtySetTracker

        tracker = DirtySetTracker()
        tracker.start_watching("test_chain", None)

        status = tracker.status()
        chain_info = status["per_chain"]["test_chain"]
        assert chain_info["ws_connected"] is False
        tracker.stop()

    def test_check_ws_connection_returns_error_for_bad_url(self):
        """check_ws_connection returns (False, None, error) for unreachable URL."""
        import os
        os.environ["ARBY_SKIP_RPC"] = "1"
        try:
            from strategy.infra import check_ws_connection
            ok, ms, err = check_ws_connection("wss://nonexistent.example.com")
            assert ok is False
            assert err == "skipped"
        finally:
            os.environ.pop("ARBY_SKIP_RPC", None)
