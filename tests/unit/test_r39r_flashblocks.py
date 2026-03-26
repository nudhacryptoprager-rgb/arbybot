"""
tests/unit/test_r39r_flashblocks.py — R39r Flashblocks integration contracts.

Tests:
1. FlashblocksState dataclass: is_healthy property logic
2. FlashblocksWatcher init: no side effects on construction
3. EXECUTABLE_TRUTH_GATE constant: values & presence in __all__
4. structural_advantage_met: lane summary respects flashblocks_healthy flag
5. classify_chain_profit_state: gate blocks ONE_LEG_ONLY_DIAGNOSTIC promotion
6. write_hot_loop_snapshot: flashblocks_watcher parameter accepted & surfaced
7. R39r+ steps 2-4: flashblocks_execution_proof propagated to truth data
8. encode_quote_exact_input_single wiring for Flashblocks probe
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


class TestFlashblocksEnvVarOverride(unittest.TestCase):
    """R39r+: Env var override for Flashblocks endpoints."""

    def test_get_ws_url_default(self):
        import os
        from chains.flashblocks import get_flashblocks_ws_url, DEFAULT_FLASHBLOCKS_WS
        os.environ.pop("ARBY_FLASHBLOCKS_WS", None)
        self.assertEqual(get_flashblocks_ws_url(), DEFAULT_FLASHBLOCKS_WS)

    def test_get_ws_url_config_override(self):
        import os
        from chains.flashblocks import get_flashblocks_ws_url
        os.environ.pop("ARBY_FLASHBLOCKS_WS", None)
        self.assertEqual(
            get_flashblocks_ws_url("wss://custom.example.com/ws"),
            "wss://custom.example.com/ws",
        )

    def test_get_ws_url_env_override(self):
        import os
        from chains.flashblocks import get_flashblocks_ws_url
        os.environ["ARBY_FLASHBLOCKS_WS"] = "wss://private.bloxroute.com/ws"
        try:
            self.assertEqual(
                get_flashblocks_ws_url("wss://config.example.com/ws"),
                "wss://private.bloxroute.com/ws",
            )
        finally:
            os.environ.pop("ARBY_FLASHBLOCKS_WS", None)

    def test_get_http_url_default(self):
        import os
        from chains.flashblocks import get_flashblocks_http_url, DEFAULT_FLASHBLOCKS_HTTP
        os.environ.pop("ARBY_FLASHBLOCKS_HTTP", None)
        self.assertEqual(get_flashblocks_http_url(), DEFAULT_FLASHBLOCKS_HTTP)

    def test_get_http_url_env_override(self):
        import os
        from chains.flashblocks import get_flashblocks_http_url
        os.environ["ARBY_FLASHBLOCKS_HTTP"] = "https://private.bloxroute.com"
        try:
            self.assertEqual(
                get_flashblocks_http_url("https://config.example.com"),
                "https://private.bloxroute.com",
            )
        finally:
            os.environ.pop("ARBY_FLASHBLOCKS_HTTP", None)


class TestEthSimulateV1Stub(unittest.TestCase):
    """R39r+: eth_simulateV1 stub returns structured result."""

    def test_importable(self):
        from chains.flashblocks import eth_simulate_v1
        self.assertTrue(callable(eth_simulate_v1))

    def test_returns_error_on_unreachable(self):
        """Calling against a non-existent endpoint returns error dict."""
        from chains.flashblocks import eth_simulate_v1
        result = eth_simulate_v1(
            tx={"from": "0x0", "to": "0x0", "data": "0x"},
            http_url="https://127.0.0.1:1/nonexistent",
            timeout_s=0.5,
        )
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"])
        self.assertIn("gas_used", result)

    def test_result_keys(self):
        """eth_simulate_v1 always returns expected keys."""
        from chains.flashblocks import eth_simulate_v1
        result = eth_simulate_v1(
            tx={"from": "0x0", "to": "0x0", "data": "0x"},
            http_url="https://127.0.0.1:1/nonexistent",
            timeout_s=0.5,
        )
        for key in ("success", "result", "error", "gas_used"):
            self.assertIn(key, result)


class TestBaseTransactionStatusStub(unittest.TestCase):
    """R39r+: base_transactionStatus stub returns structured result."""

    def test_importable(self):
        from chains.flashblocks import base_transaction_status
        self.assertTrue(callable(base_transaction_status))

    def test_returns_error_on_unreachable(self):
        from chains.flashblocks import base_transaction_status
        result = base_transaction_status(
            tx_hash="0xdead",
            http_url="https://127.0.0.1:1/nonexistent",
            timeout_s=0.5,
        )
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["confirmed"])
        self.assertIsNotNone(result["error"])

    def test_result_keys(self):
        from chains.flashblocks import base_transaction_status
        result = base_transaction_status(
            tx_hash="0xdead",
            http_url="https://127.0.0.1:1/nonexistent",
            timeout_s=0.5,
        )
        for key in ("status", "confirmed", "error"):
            self.assertIn(key, result)


class TestPoolUsageReportInTruthData(unittest.TestCase):
    """R39r+: pool_usage_report propagated to truth data."""

    def test_pool_usage_propagated(self):
        from strategy.artifacts import build_truth_data
        stats = {
            "quotes_total": 5,
            "quotes_fetched": 3,
            "dexes_active": 2,
            "price_sanity_passed": 3,
            "price_sanity_failed": 0,
            "pool_usage_report": [
                {
                    "pool_address": "0xabc",
                    "pair": "USDC/DAI",
                    "dex_id": "uniswap_v3",
                    "fee": 100,
                    "quotes_fetched": 2,
                    "quotes_rejected": 0,
                    "spread_signals": 1,
                    "opp_count": 0,
                    "rt_evaluated": 0,
                },
            ],
        }
        truth = build_truth_data(
            config={"chain_id": 8453, "chain": "base"},
            stats=stats,
            current_block=100,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        self.assertIn("pool_usage_report", truth)
        self.assertEqual(len(truth["pool_usage_report"]), 1)
        self.assertEqual(truth["pool_usage_report"][0]["pool_address"], "0xabc")

    def test_no_pool_usage_when_absent(self):
        from strategy.artifacts import build_truth_data
        stats = {
            "quotes_total": 0,
            "quotes_fetched": 0,
            "dexes_active": 0,
            "price_sanity_passed": 0,
            "price_sanity_failed": 0,
        }
        truth = build_truth_data(
            config={"chain_id": 8453, "chain": "base"},
            stats=stats,
            current_block=100,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        self.assertNotIn("pool_usage_report", truth)


class TestFlashblocksExecutionProofInTruthData(unittest.TestCase):
    """R39r+ steps 2-4: flashblocks_execution_proof propagated to truth data."""

    def _make_proof(self, **overrides):
        proof = {
            "http_endpoint": "https://base.flashblocks.base.org",
            "probed_count": 3,
            "sim_success_count": 2,
            "sim_results": [
                {"pair": "USDC/DAI", "dex": "uniswap_v3", "sim_success": True,
                 "sim_error": None, "sim_gas_used": 120000},
                {"pair": "USDC/USDT", "dex": "aerodrome_v3", "sim_success": True,
                 "sim_error": None, "sim_gas_used": 115000},
                {"pair": "WETH/USDC", "dex": "uniswap_v3", "sim_success": False,
                 "sim_error": "revert", "sim_gas_used": None},
            ],
            "tx_status_reachable": True,
            "tx_status_raw": {"status": "unknown", "confirmed": False, "error": None},
        }
        proof.update(overrides)
        return proof

    def _make_stats(self, proof=None):
        stats = {
            "quotes_total": 5,
            "quotes_fetched": 3,
            "dexes_active": 2,
            "price_sanity_passed": 3,
            "price_sanity_failed": 0,
        }
        if proof is not None:
            stats["flashblocks_execution_proof"] = proof
        return stats

    def test_proof_propagated_to_truth(self):
        from strategy.artifacts import build_truth_data
        proof = self._make_proof()
        truth = build_truth_data(
            config={"chain_id": 8453, "chain": "base"},
            stats=self._make_stats(proof),
            current_block=100,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        self.assertIn("flashblocks_execution_proof", truth)
        self.assertEqual(truth["flashblocks_execution_proof"]["probed_count"], 3)
        self.assertEqual(truth["flashblocks_execution_proof"]["sim_success_count"], 2)
        self.assertTrue(truth["flashblocks_execution_proof"]["tx_status_reachable"])

    def test_proof_absent_when_not_in_stats(self):
        from strategy.artifacts import build_truth_data
        truth = build_truth_data(
            config={"chain_id": 8453, "chain": "base"},
            stats=self._make_stats(proof=None),
            current_block=100,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        self.assertNotIn("flashblocks_execution_proof", truth)

    def test_proof_structure_keys(self):
        """Verify the expected keys in the proof dict."""
        from strategy.artifacts import build_truth_data
        proof = self._make_proof()
        truth = build_truth_data(
            config={"chain_id": 8453, "chain": "base"},
            stats=self._make_stats(proof),
            current_block=100,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        fb = truth["flashblocks_execution_proof"]
        for key in ("http_endpoint", "probed_count", "sim_success_count",
                     "sim_results", "tx_status_reachable", "tx_status_raw"):
            self.assertIn(key, fb, f"Missing key: {key}")

    def test_sim_results_per_candidate_keys(self):
        """Each sim result must have pair, dex, sim_success."""
        from strategy.artifacts import build_truth_data
        proof = self._make_proof()
        truth = build_truth_data(
            config={"chain_id": 8453, "chain": "base"},
            stats=self._make_stats(proof),
            current_block=100,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        for r in truth["flashblocks_execution_proof"]["sim_results"]:
            self.assertIn("pair", r)
            self.assertIn("dex", r)
            self.assertIn("sim_success", r)

    def test_proof_with_zero_successes(self):
        """Proof with 0 sim successes still propagated (endpoint was unreachable)."""
        from strategy.artifacts import build_truth_data
        proof = self._make_proof(
            sim_success_count=0,
            tx_status_reachable=False,
            tx_status_raw={"status": "error", "confirmed": False, "error": "timeout"},
        )
        truth = build_truth_data(
            config={"chain_id": 8453, "chain": "base"},
            stats=self._make_stats(proof),
            current_block=100,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        self.assertIn("flashblocks_execution_proof", truth)
        self.assertEqual(truth["flashblocks_execution_proof"]["sim_success_count"], 0)
        self.assertFalse(truth["flashblocks_execution_proof"]["tx_status_reachable"])

    def test_error_only_proof_propagated(self):
        """Error-only proof (from except branch) has minimal keys."""
        from strategy.artifacts import build_truth_data
        error_proof = {"probed_count": 0, "sim_success_count": 0, "error": "import failed"}
        truth = build_truth_data(
            config={"chain_id": 8453, "chain": "base"},
            stats=self._make_stats(error_proof),
            current_block=100,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        self.assertIn("flashblocks_execution_proof", truth)
        self.assertEqual(truth["flashblocks_execution_proof"]["probed_count"], 0)
        self.assertIn("error", truth["flashblocks_execution_proof"])


class TestEncodeQuoteExactInputSingleWiring(unittest.TestCase):
    """R39r+: Verify encode_quote_exact_input_single works for Flashblocks probe."""

    def test_encode_returns_hex_string(self):
        from dex.adapters.uniswap_v3 import encode_quote_exact_input_single
        result = encode_quote_exact_input_single(
            token_in="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
            token_out="0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",  # DAI on Base
            amount_in=int(50e6),
            fee=100,
        )
        self.assertIsInstance(result, str)
        # Should start with the selector (8 hex chars)
        self.assertTrue(len(result) >= 8)

    def test_encode_probe_amount_stablecoin(self):
        """50 USDC (6 decimals) = 50_000_000 correctly encoded."""
        from dex.adapters.uniswap_v3 import encode_quote_exact_input_single
        result = encode_quote_exact_input_single(
            token_in="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            token_out="0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
            amount_in=int(50e6),
            fee=100,
        )
        # amountIn = 50_000_000 = 0x2faf080 — should appear in encoded data
        self.assertIn("2faf080", result.lower())


if __name__ == "__main__":
    unittest.main()
