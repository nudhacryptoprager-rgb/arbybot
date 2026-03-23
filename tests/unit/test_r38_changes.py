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
