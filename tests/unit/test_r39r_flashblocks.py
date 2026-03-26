"""
tests/unit/test_r39r_flashblocks.py — R39r Flashblocks integration contracts.

Tests:
1. FlashblocksState dataclass: is_healthy property logic
2. FlashblocksWatcher init: no side effects on construction
3. EXECUTABLE_TRUTH_GATE constant: values & presence in __all__
4. structural_advantage_met: lane summary respects flashblocks_healthy flag
5. classify_chain_profit_state: gate blocks ONE_LEG_ONLY_DIAGNOSTIC promotion
6. write_hot_loop_snapshot: flashblocks_watcher parameter accepted & surfaced
"""

from __future__ import annotations

import time
import unittest
from typing import Any
from unittest.mock import MagicMock


class TestFlashblocksState(unittest.TestCase):
    """FlashblocksState.is_healthy contract."""

    def test_not_healthy_when_disconnected(self):
        from chains.flashblocks import FlashblocksState
        s = FlashblocksState(connected=False)
        self.assertFalse(s.is_healthy)

    def test_not_healthy_when_no_sub_blocks(self):
        from chains.flashblocks import FlashblocksState
        s = FlashblocksState(connected=True, total_sub_blocks_received=0)
        self.assertFalse(s.is_healthy)

    def test_not_healthy_when_stale(self):
        from chains.flashblocks import FlashblocksState
        s = FlashblocksState(
            connected=True,
            total_sub_blocks_received=5,
            last_sub_block_ts=time.monotonic() - 30.0,  # 30s ago, threshold is 10s
        )
        self.assertFalse(s.is_healthy)

    def test_healthy_when_connected_and_recent(self):
        from chains.flashblocks import FlashblocksState
        s = FlashblocksState(
            connected=True,
            total_sub_blocks_received=5,
            last_sub_block_ts=time.monotonic() - 1.0,  # 1s ago
        )
        self.assertTrue(s.is_healthy)

    def test_to_dict_keys(self):
        from chains.flashblocks import FlashblocksState
        s = FlashblocksState(connected=True, last_sub_block_number=12345)
        d = s.to_dict()
        self.assertIn("connected", d)
        self.assertIn("is_healthy", d)
        self.assertIn("last_sub_block_number", d)
        self.assertEqual(d["last_sub_block_number"], 12345)


class TestFlashblocksWatcherInit(unittest.TestCase):
    """FlashblocksWatcher construction has no side effects."""

    def test_construction_no_thread(self):
        from chains.flashblocks import FlashblocksWatcher
        w = FlashblocksWatcher(ws_url="wss://dummy.example.com/ws")
        self.assertFalse(w.state.connected)
        self.assertFalse(w.state.is_healthy)
        self.assertEqual(w.state.total_sub_blocks_received, 0)
        # Thread should not be started yet
        self.assertIsNone(w._thread)

    def test_stop_before_start_is_noop(self):
        from chains.flashblocks import FlashblocksWatcher
        w = FlashblocksWatcher(ws_url="wss://dummy.example.com/ws")
        w.stop()  # should not raise


class TestFlashblocksConstants(unittest.TestCase):
    """Flashblocks-related constants."""

    def test_default_endpoints(self):
        from chains.flashblocks import DEFAULT_FLASHBLOCKS_WS, DEFAULT_FLASHBLOCKS_HTTP
        self.assertTrue(DEFAULT_FLASHBLOCKS_WS.startswith("wss://"))
        self.assertTrue(DEFAULT_FLASHBLOCKS_HTTP.startswith("https://"))

    def test_sub_block_interval(self):
        from chains.flashblocks import FLASHBLOCKS_SUB_BLOCK_MS
        self.assertEqual(FLASHBLOCKS_SUB_BLOCK_MS, 200)


class TestExecutableTruthGate(unittest.TestCase):
    """EXECUTABLE_TRUTH_GATE constant from core.constants."""

    def test_gate_keys(self):
        from core.constants import EXECUTABLE_TRUTH_GATE
        self.assertIn("min_real_quote_count_total", EXECUTABLE_TRUTH_GATE)
        self.assertIn("min_roundtrip_evaluated_total", EXECUTABLE_TRUTH_GATE)
        self.assertIn("forbidden_profit_realism", EXECUTABLE_TRUTH_GATE)

    def test_gate_values(self):
        from core.constants import EXECUTABLE_TRUTH_GATE
        self.assertEqual(EXECUTABLE_TRUTH_GATE["min_real_quote_count_total"], 1)
        self.assertEqual(EXECUTABLE_TRUTH_GATE["min_roundtrip_evaluated_total"], 1)
        self.assertEqual(
            EXECUTABLE_TRUTH_GATE["forbidden_profit_realism"],
            "ONE_LEG_ONLY_DIAGNOSTIC",
        )

    def test_in_all(self):
        import core.constants as _mod
        self.assertIn("EXECUTABLE_TRUTH_GATE", _mod.__all__)


class TestStructuralAdvantageMetLaneSummary(unittest.TestCase):
    """_compute_lane_summary respects flashblocks_healthy for structural_advantage_met."""

    def _make_base_stats(self, **overrides: Any) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "runs": 3,
            "pass": 3,
            "fail": 0,
            "infra_fail": 0,
            "included_signals_total": 10,
            "profitable_roundtrips_total": 0,
            "sweep_gap_to_zero_bps": 8.0,
        }
        defaults.update(overrides)
        return defaults

    def test_structural_advantage_false_without_flashblocks(self):
        from strategy.long_scan_summary import _compute_lane_summary
        per_chain = {"base": self._make_base_stats()}
        lanes = _compute_lane_summary(per_chain)
        # Base is in lane_a which requires flashblocks_preconf
        lane_a = lanes.get("lane_a") or lanes.get("lane_b")
        # Find whichever lane has base
        for lane_name, lane_data in lanes.items():
            if "base" in lane_data["chains"]:
                self.assertFalse(
                    lane_data["structural_advantage_met"],
                    f"Lane {lane_name} should NOT have structural_advantage_met without flashblocks_healthy",
                )
                break

    def test_structural_advantage_true_with_flashblocks_healthy(self):
        from strategy.long_scan_summary import _compute_lane_summary
        per_chain = {"base": self._make_base_stats(flashblocks_healthy=True)}
        lanes = _compute_lane_summary(per_chain)
        for lane_name, lane_data in lanes.items():
            if "base" in lane_data["chains"]:
                self.assertTrue(
                    lane_data["structural_advantage_met"],
                    f"Lane {lane_name} should have structural_advantage_met with flashblocks_healthy=True",
                )
                break

    def test_structural_advantage_false_with_flashblocks_unhealthy(self):
        from strategy.long_scan_summary import _compute_lane_summary
        per_chain = {"base": self._make_base_stats(flashblocks_healthy=False)}
        lanes = _compute_lane_summary(per_chain)
        for lane_name, lane_data in lanes.items():
            if "base" in lane_data["chains"]:
                self.assertFalse(
                    lane_data["structural_advantage_met"],
                    f"Lane {lane_name} should NOT have structural_advantage_met with flashblocks_healthy=False",
                )
                break

    def test_non_base_chain_no_structural_req(self):
        """Chains without structural_advantage_required keep met=True."""
        from strategy.long_scan_summary import _compute_lane_summary
        per_chain = {
            "arbitrum_one": {
                "runs": 3, "pass": 3, "fail": 0, "infra_fail": 0,
                "included_signals_total": 5, "profitable_roundtrips_total": 1,
                "sweep_gap_to_zero_bps": -2.0,
            },
        }
        lanes = _compute_lane_summary(per_chain)
        for lane_name, lane_data in lanes.items():
            if "arbitrum_one" in lane_data["chains"]:
                self.assertTrue(lane_data["structural_advantage_met"])
                break


class TestClassifyChainProfitStateGate(unittest.TestCase):
    """classify_chain_profit_state uses EXECUTABLE_TRUTH_GATE."""

    def test_diagnostic_only_blocks_confirmed(self):
        """Chain with profitable RT but ONE_LEG_ONLY_DIAGNOSTIC → THIN_POSITIVE, not CONFIRMED."""
        from strategy.long_scan_summary import classify_chain_profit_state
        stats = {
            "profitable_roundtrips_total": 3,
            "roundtrip_evaluated_total": 5,
            "real_quote_count_total": 10,
            "runs": 5,
            "last_profit_realism_status": "ONE_LEG_ONLY_DIAGNOSTIC",
            "last_quality_status": "PASS",
        }
        self.assertEqual(classify_chain_profit_state(stats), "THIN_POSITIVE")

    def test_non_diagnostic_allows_confirmed(self):
        """Chain with real quotes and no diagnostic flag → CONFIRMED."""
        from strategy.long_scan_summary import classify_chain_profit_state
        stats = {
            "profitable_roundtrips_total": 3,
            "roundtrip_evaluated_total": 5,
            "real_quote_count_total": 10,
            "runs": 5,
            "last_profit_realism_status": "EXECUTABLE_PROFIT",
            "last_quality_status": "PASS",
        }
        self.assertEqual(classify_chain_profit_state(stats), "CONFIRMED_POSITIVE_CONTROL")

    def test_zero_roundtrips_stays_candidate(self):
        """Base-like stats: runs>0, rq=0, eval=0 → CANDIDATE."""
        from strategy.long_scan_summary import classify_chain_profit_state
        stats = {
            "profitable_roundtrips_total": 0,
            "roundtrip_evaluated_total": 0,
            "real_quote_count_total": 0,
            "runs": 5,
            "last_profit_realism_status": "ONE_LEG_ONLY_DIAGNOSTIC",
        }
        self.assertEqual(classify_chain_profit_state(stats), "CANDIDATE")

    def test_fail_quality_blocks_confirmed(self):
        from strategy.long_scan_summary import classify_chain_profit_state
        stats = {
            "profitable_roundtrips_total": 2,
            "roundtrip_evaluated_total": 5,
            "real_quote_count_total": 10,
            "runs": 5,
            "last_profit_realism_status": "EXECUTABLE_PROFIT",
            "last_quality_status": "FAIL_QUALITY",
        }
        self.assertEqual(classify_chain_profit_state(stats), "THIN_POSITIVE")


class TestHotLoopSnapshotFlashblocks(unittest.TestCase):
    """write_hot_loop_snapshot accepts flashblocks_watcher param."""

    def test_signature_accepts_flashblocks_watcher(self):
        """Verify the parameter exists in the function signature."""
        import inspect
        from strategy.rolling_outputs import write_hot_loop_snapshot
        sig = inspect.signature(write_hot_loop_snapshot)
        self.assertIn("flashblocks_watcher", sig.parameters)

    def test_flashblocks_surfaced_in_snapshot(self):
        """When flashblocks_watcher is provided, snapshot includes flashblocks key."""
        import json
        import tempfile
        from pathlib import Path
        from strategy.rolling_outputs import write_hot_loop_snapshot
        from chains.flashblocks import FlashblocksState

        # Create a mock watcher with a healthy state
        mock_watcher = MagicMock()
        mock_state = FlashblocksState(
            connected=True,
            last_sub_block_number=99999,
            last_sub_block_ts=time.monotonic() - 1.0,
            total_sub_blocks_received=42,
        )
        mock_watcher.state = mock_state

        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "hot_test.json"
            write_hot_loop_snapshot(
                per_chain={"base": {"runs": 1, "pass": 1, "fail": 0, "infra_fail": 0}},
                dirty_tracker=None,
                wall_start=time.monotonic() - 10.0,
                summary_file="",
                output_path=out,
                flashblocks_watcher=mock_watcher,
            )
            self.assertTrue(out.exists(), "Snapshot file should be written")
            data = json.loads(out.read_text())
            self.assertIn("flashblocks", data)
            self.assertTrue(data["flashblocks"]["connected"])
            self.assertTrue(data["flashblocks"]["is_healthy"])
            self.assertEqual(data["flashblocks"]["last_sub_block_number"], 99999)

    def test_no_flashblocks_watcher_no_key(self):
        """When flashblocks_watcher is None, snapshot has no flashblocks key."""
        import json
        import tempfile
        from pathlib import Path
        from strategy.rolling_outputs import write_hot_loop_snapshot

        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "hot_test.json"
            write_hot_loop_snapshot(
                per_chain={"base": {"runs": 1, "pass": 1, "fail": 0, "infra_fail": 0}},
                dirty_tracker=None,
                wall_start=time.monotonic() - 10.0,
                summary_file="",
                output_path=out,
            )
            self.assertTrue(out.exists())
            data = json.loads(out.read_text())
            self.assertNotIn("flashblocks", data)


if __name__ == "__main__":
    unittest.main()
