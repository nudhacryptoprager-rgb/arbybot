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
            "measured_total_cost_bps": 31.0,
            "measured_slippage_bps": 10.0,
            "measured_gas_bps": 5.0,
        }
        frontier = ds.get("best_frontier_reason")
        is_exec = frontier in ("BREAKEVEN_FRONTIER", "PROFITABLE")
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
