# PATH: tests/unit/test_r34_stream_reprieve.py
"""
R34 regression tests for stream-to-analysis loss fix.

Covers:
1. token_decimals hoisted — no UnboundLocalError on reprieve-only path
2. except block preserves sweep_reprieve data
3. artifacts.py propagates error/sweep_reprieve_count to truth_report
4. live_stream builds rows from dynamic_sweep results when roundtrip_results is empty
5. live_stream builds rows from reprieve candidates as tertiary fallback
6. blocker_classification materialized in raw per_chain (not just frontier_ranking)
7. hot_loop write skipped for test sessions without explicit output_path
"""

import json
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Any, Dict, List
from unittest import TestCase
from unittest.mock import patch


class TestTokenDecimalsHoisted(TestCase):
    """R34 Step 1: token_decimals must not cause UnboundLocalError."""

    def test_token_decimals_initialized_before_opps_list(self):
        """token_decimals = {} must appear before `if opps_list:` in run_scan_real.py."""
        path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()

        token_decimals_init_line = None
        if_opps_list_line = None
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped == "token_decimals = {}" and token_decimals_init_line is None:
                token_decimals_init_line = i
            if stripped == "if opps_list:" and if_opps_list_line is None:
                if_opps_list_line = i

        self.assertIsNotNone(token_decimals_init_line,
                             "token_decimals = {} initialization not found")
        self.assertIsNotNone(if_opps_list_line,
                             "if opps_list: not found")
        self.assertLess(token_decimals_init_line, if_opps_list_line,
                        f"token_decimals init (line {token_decimals_init_line}) must be "
                        f"before if opps_list: (line {if_opps_list_line})")

    def test_token_decimals_not_inside_opps_list_block_only(self):
        """token_decimals must NOT be initialized only inside if opps_list: block."""
        path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()

        # Count how many times token_decimals = {} appears
        init_count = sum(1 for line in lines if line.strip() == "token_decimals = {}")
        # Should be exactly 1 — the hoisted version
        self.assertEqual(init_count, 1,
                         f"Expected exactly 1 'token_decimals = {{}}' but found {init_count}")


class TestRtTopNHoisted(TestCase):
    """R34: _rt_top_n must be hoisted before if opps_list: to prevent UnboundLocalError."""

    def test_rt_top_n_initialized_before_opps_list(self):
        """_rt_top_n default must appear before `if opps_list:`."""
        path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()

        rt_top_n_init_line = None
        if_opps_list_line = None
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if '_rt_top_n = config.get("roundtrip_top_n"' in stripped and rt_top_n_init_line is None:
                rt_top_n_init_line = i
            if stripped == "if opps_list:" and if_opps_list_line is None:
                if_opps_list_line = i

        self.assertIsNotNone(rt_top_n_init_line,
                             "_rt_top_n initialization not found before if opps_list:")
        self.assertIsNotNone(if_opps_list_line,
                             "if opps_list: not found")
        self.assertLess(rt_top_n_init_line, if_opps_list_line,
                        f"_rt_top_n init (line {rt_top_n_init_line}) must be "
                        f"before if opps_list: (line {if_opps_list_line})")


class TestExceptBlockPreservesReprieve(TestCase):
    """R34 Step 3: except block must preserve sweep_reprieve data."""

    def test_except_block_preserves_sweep_reprieve_count(self):
        """The except block should not blindly overwrite stats['roundtrip']."""
        path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
        content = path.read_text(encoding="utf-8")

        # The except block should reference sweep_reprieve_count
        self.assertIn("sweep_reprieve_count", content)
        # It should NOT have the old pattern of a simple dict replacement
        # that would lose all prior data
        except_idx = content.find("except Exception as rt_err:")
        self.assertNotEqual(except_idx, -1)
        except_block = content[except_idx:except_idx + 800]
        self.assertIn("sweep_reprieve_count", except_block,
                      "except block must preserve sweep_reprieve_count")
        self.assertIn("sweep_reprieve_stats", except_block,
                      "except block must preserve sweep_reprieve_stats")


class TestArtifactsPropagateError(TestCase):
    """R34 Step 4: _build_roundtrip_summary must propagate error and sweep data."""

    def test_roundtrip_summary_includes_error_field(self):
        from strategy.artifacts import _build_roundtrip_summary

        stats = {
            "roundtrip": {
                "enabled": False,
                "error": "cannot access local variable 'token_decimals'",
                "sweep_reprieve_count": 3,
                "sweep_reprieve_stats": {"net_profit_too_low_total": 8},
            }
        }
        summary = _build_roundtrip_summary(stats)
        self.assertEqual(summary["error"],
                         "cannot access local variable 'token_decimals'")
        self.assertEqual(summary["sweep_reprieve_count"], 3)
        self.assertEqual(summary["sweep_reprieve_stats"]["net_profit_too_low_total"], 8)

    def test_roundtrip_summary_error_none_when_no_crash(self):
        from strategy.artifacts import _build_roundtrip_summary

        stats = {
            "roundtrip": {
                "enabled": True,
                "evaluated_count": 5,
                "profitable_count": 0,
                "real_quote_count": 3,
                "executable_candidates_count": 5,
            }
        }
        summary = _build_roundtrip_summary(stats)
        self.assertIsNone(summary["error"])
        self.assertEqual(summary["sweep_reprieve_count"], 0)


class TestLiveStreamSweepRows(TestCase):
    """R34 Steps 5-7: live_stream builds rows from sweep/reprieve when RT is empty."""

    def test_sweep_results_produce_diagnostic_frontier_rows(self):
        from strategy.live_stream import build_live_candidate_stream

        dynamic_sweep = {
            "results": [
                {
                    "pair": "WETH/USDC",
                    "buy_dex": "sushiswap",
                    "sell_dex": "uniswap_v3",
                    "best_net_pnl_bps": -3.5,
                    "best_size_usd": 25.0,
                    "best_total_cost_bps": 18.0,
                },
            ]
        }
        result = build_live_candidate_stream(
            chain_key="arbitrum_one",
            opportunities=[],
            roundtrip_results=[],
            dynamic_sweep=dynamic_sweep,
            default_size_usd=25.0,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["final_result"], "DIAGNOSTIC_FRONTIER")
        self.assertEqual(result[0]["pair"], "WETH/USDC")
        self.assertFalse(result[0]["is_actionable"])
        self.assertEqual(result[0]["final_net_pnl_bps"], -3.5)

    def test_sweep_results_fallback_to_reprieve_spread_context(self):
        """Reprieve-only sweep rows must keep spread and reject context for dashboard visibility."""
        from strategy.live_stream import build_live_candidate_stream

        dynamic_sweep = {
            "results": [
                {
                    "pair": "WETH/USDC",
                    "buy_dex": "sushiswap",
                    "sell_dex": "uniswap_v3",
                    "best_net_pnl_bps": -4.2,
                    "best_size_usd": 25.0,
                    "best_total_cost_bps": 18.0,
                },
            ]
        }
        sweep_candidates = [
            {
                "pair": "WETH/USDC",
                "buy_dex": "sushiswap",
                "sell_dex": "uniswap_v3",
                "spread_bps": 12.0,
                "reject_reason": "NET_PROFIT_TOO_LOW",
            },
        ]
        result = build_live_candidate_stream(
            chain_key="arbitrum_one",
            opportunities=[],
            roundtrip_results=[],
            dynamic_sweep=dynamic_sweep,
            default_size_usd=25.0,
            sweep_candidates=sweep_candidates,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["spread_bps"], 12.0)
        self.assertEqual(result[0]["reject_reason"], "NET_PROFIT_TOO_LOW")

    def test_reprieve_candidates_produce_rows_when_sweep_empty(self):
        from strategy.live_stream import build_live_candidate_stream

        sweep_candidates = [
            {
                "pair": "WETH/USDT",
                "buy_dex": "sushiswap",
                "sell_dex": "uniswap_v3",
                "spread_bps": 12.0,
                "reject_reason": "NET_PROFIT_TOO_LOW",
            },
        ]
        result = build_live_candidate_stream(
            chain_key="arbitrum_one",
            opportunities=[],
            roundtrip_results=[],
            dynamic_sweep=None,
            default_size_usd=25.0,
            sweep_candidates=sweep_candidates,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["final_result"], "REPRIEVE_CANDIDATE")
        self.assertEqual(result[0]["pair"], "WETH/USDT")
        self.assertFalse(result[0]["is_actionable"])
        self.assertEqual(result[0]["reject_reason"], "NET_PROFIT_TOO_LOW")

    def test_roundtrip_results_take_priority_over_sweep(self):
        """When roundtrip_results exist, sweep-only rows are NOT added."""
        from strategy.live_stream import build_live_candidate_stream
        from unittest.mock import MagicMock

        rt = MagicMock()
        rt.pair = "WETH/USDC"
        rt.buy_dex = "sushiswap"
        rt.sell_dex = "uniswap_v3"
        rt.leg1_fee = 300
        rt.leg2_fee = 300
        rt.gross_pnl_bps = 10.0
        rt.net_pnl_bps = -5.0
        rt.estimated_slippage_bps = 2.0
        rt.is_profitable = False
        rt.leg2_is_real_quote = True
        rt.reject_reason = None

        result = build_live_candidate_stream(
            chain_key="arbitrum_one",
            opportunities=[],
            roundtrip_results=[rt],
            dynamic_sweep=None,
            default_size_usd=25.0,
            sweep_candidates=[{"pair": "WETH/USDT", "buy_dex": "a", "sell_dex": "b"}],
        )
        # Only the RT row should be present
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["final_result"], "ROUNDTRIP_NOT_PROFITABLE")

    def test_empty_everything_returns_empty(self):
        from strategy.live_stream import build_live_candidate_stream

        result = build_live_candidate_stream(
            chain_key="arbitrum_one",
            opportunities=[],
            roundtrip_results=[],
            dynamic_sweep=None,
            default_size_usd=25.0,
            sweep_candidates=[],
        )
        self.assertEqual(result, [])


class TestDynamicSweepRouteIdentity(TestCase):
    """R35 follow-up: dynamic sweep results must keep OE route identity."""

    def test_run_sweep_normalizes_route_identity_to_opportunity(self):
        from engine.roundtrip import SizeSweepResult
        from strategy.dynamic_sweep_runtime import run_sweep

        class _DexCfg:
            def get_quoter_address(self):
                return "0xquoter"

        fake_quotes = types.ModuleType("strategy.quotes")
        fake_quotes.read_quoter_v2 = lambda **kwargs: None
        fake_config = types.ModuleType("config")
        fake_config.get_token_address = lambda chain, sym: f"0x{sym.lower()}"
        fake_registry = types.ModuleType("dex.registry")
        fake_registry.get_dex_config = lambda chain, dex: _DexCfg()

        opp = {
            "pair": "WETH/USDC",
            "buy_dex": "uniswap_v3",
            "sell_dex": "pancakeswap_v3",
            "buy_fee": 500,
            "sell_fee": 500,
            "diagnostics": {
                "buy_pool": "0xbuy",
                "sell_pool": "0xsell",
            },
        }
        quotes_by_key = {
            "uniswap_v3:0xbuy:500": {
                "dex_id": "uniswap_v3",
                "token_in": "WETH",
                "token_out": "USDC",
                "fee": 500,
            },
            "pancakeswap_v3:0xsell:500": {
                "dex_id": "pancakeswap_v3",
                "token_in": "WETH",
                "token_out": "USDC",
                "fee": 500,
            },
        }
        fake_result = SizeSweepResult(
            pair="WETH/USDC",
            buy_dex="pancakeswap_v3",
            sell_dex="uniswap_v3",
            sizes_evaluated=1,
            best_size_usd=25.0,
            best_net_pnl_bps=-4.2,
            best_total_cost_bps=18.0,
        )

        with patch.dict(
            sys.modules,
            {
                "strategy.quotes": fake_quotes,
                "config": fake_config,
                "dex.registry": fake_registry,
            },
            clear=False,
        ), patch(
            "engine.roundtrip.sweep_roundtrip_sizes",
            return_value=fake_result,
        ):
            result = run_sweep(
                eligible_opps=[opp],
                quotes_by_key=quotes_by_key,
                config={"dynamic_probe": {"enabled": True, "top_routes": 15}},
                chain_key="arbitrum_one",
                rpc_url="http://localhost:8545",
                current_block=1,
                live_gas_price_wei=1,
                l1_cost_wei=1,
                l1_cost_source="test",
                eth_usd=2000.0,
                token_decimals={"WETH": 18},
            )

        results = result["dynamic_sweep"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["buy_dex"], "uniswap_v3")
        self.assertEqual(results[0]["sell_dex"], "pancakeswap_v3")


class TestBlockerFieldsInPerChain(TestCase):
    """R34 Step 8: blocker_classification materialized in raw per_chain."""

    def test_blocker_fields_materialized_in_per_chain(self):
        from strategy.long_scan_summary import build_summary
        from strategy.chain_stats import new_chain_stats

        per_chain = {"arb": new_chain_stats()}
        per_chain["arb"]["runs"] = 5
        per_chain["arb"]["pass"] = 5
        per_chain["arb"]["included_signals_total"] = 50
        per_chain["arb"]["blocker_evidence"] = "OE_ECONOMICS"

        summary = build_summary(per_chain, wall_seconds=60.0, warnings=[])
        # blocker_classification must be in raw per_chain, not just frontier_ranking
        arb_raw = summary["per_chain"]["arb"]
        self.assertEqual(arb_raw["blocker_classification"], "OE_ECONOMICS")
        self.assertIsNotNone(arb_raw["blocker_reason"])
        self.assertIn("NET_PROFIT_TOO_LOW", arb_raw["blocker_reason"])

    def test_blocker_fields_null_when_no_evidence(self):
        from strategy.long_scan_summary import build_summary
        from strategy.chain_stats import new_chain_stats

        per_chain = {"base": new_chain_stats()}
        per_chain["base"]["runs"] = 0

        summary = build_summary(per_chain, wall_seconds=10.0, warnings=[])
        base_raw = summary["per_chain"]["base"]
        self.assertIsNone(base_raw["blocker_classification"])
        self.assertIsNone(base_raw["blocker_reason"])


class TestHotLoopTestSessionProtection(TestCase):
    """R34 Step 9: test sessions must not overwrite canonical hot_loop_latest.json."""

    def test_test_session_skips_canonical_write(self):
        from strategy.rolling_outputs import write_hot_loop_snapshot, HOT_LOOP_LATEST
        from strategy.chain_stats import new_chain_stats

        per_chain = {"arb": new_chain_stats()}
        per_chain["arb"]["runs"] = 1

        # If canonical file exists, it should NOT be modified
        HOT_LOOP_LATEST.parent.mkdir(parents=True, exist_ok=True)
        existed_before = HOT_LOOP_LATEST.exists()
        if existed_before:
            before_content = HOT_LOOP_LATEST.read_text(encoding="utf-8")

        write_hot_loop_snapshot(
            per_chain, None, time.monotonic() - 5,
            is_test_session=True,
            # No output_path → would default to canonical path
        )

        if existed_before:
            after_content = HOT_LOOP_LATEST.read_text(encoding="utf-8")
            self.assertEqual(before_content, after_content,
                             "Test session must NOT modify canonical hot_loop_latest.json")

    def test_test_session_with_explicit_path_still_writes(self):
        from strategy.rolling_outputs import write_hot_loop_snapshot
        from strategy.chain_stats import new_chain_stats

        per_chain = {"arb": new_chain_stats()}
        per_chain["arb"]["runs"] = 1

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td) / "test_hot_loop.json"
            write_hot_loop_snapshot(
                per_chain, None, time.monotonic() - 5,
                is_test_session=True,
                output_path=tmp_path,
            )
            self.assertTrue(tmp_path.exists(),
                            "Explicit output_path should still write even in test session")
            data = json.loads(tmp_path.read_text(encoding="utf-8"))
            self.assertTrue(data["is_test_session"])


class TestBuildLiveCandidateStreamWrapper(TestCase):
    """R34 Step 6: Wrapper in run_scan_real.py passes sweep_candidates."""

    def test_wrapper_accepts_sweep_candidates(self):
        path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
        content = path.read_text(encoding="utf-8")
        # The wrapper must accept and pass sweep_candidates
        self.assertIn("sweep_candidates=sweep_candidates", content)
        # The call site in the try block must pass sweep_candidates
        idx = content.find("stats[\"live_candidate_stream\"] = _build_live_candidate_stream(")
        self.assertNotEqual(idx, -1)
        call_block = content[idx:idx + 500]
        self.assertIn("sweep_candidates=sweep_candidates", call_block)


class TestSerializeLiveStreamPerChainFallback(TestCase):
    """R34: _serialize_live_stream uses per_chain as fallback source for diagnostic_pairs."""

    def test_per_chain_last_live_candidates_populate_diagnostic_pairs(self):
        """When active_runs is empty but per_chain has candidates, diagnostic_pairs is populated."""
        from strategy.rolling_outputs import _serialize_live_stream

        per_chain = {
            "arbitrum_one": {
                "last_live_candidates": [
                    {"pair": "WETH/USDC", "route": "uni->sushi", "is_actionable": False,
                     "final_result": "DIAGNOSTIC_FRONTIER", "final_net_pnl_bps": -25.0},
                    {"pair": "WBTC/USDC", "route": "pan->uni", "is_actionable": False,
                     "final_result": "DIAGNOSTIC_FRONTIER", "final_net_pnl_bps": -15.0},
                ]
            }
        }
        result = _serialize_live_stream(
            active_runs={},  # Empty! Scan finished, _clear_active_run was called
            live_events=[],
            pair_hot_queue_pending=0,
            per_chain=per_chain,
        )
        self.assertEqual(len(result["diagnostic_pairs"]), 2)
        self.assertEqual(result["diagnostic_pairs"][0]["pair"], "WETH/USDC")
        self.assertEqual(result["diagnostic_pairs"][1]["pair"], "WBTC/USDC")
        self.assertEqual(result["verified_pairs"], [])

    def test_per_chain_also_adds_network_field(self):
        """Rows from per_chain should have `network` set."""
        from strategy.rolling_outputs import _serialize_live_stream

        per_chain = {
            "linea": {
                "last_live_candidates": [
                    {"pair": "WETH/USDC", "route": "uni->pan", "is_actionable": False}
                ]
            }
        }
        result = _serialize_live_stream({}, [], 0, per_chain=per_chain)
        self.assertEqual(result["diagnostic_pairs"][0]["network"], "linea")


class TestQuotePathBlockedSweepOverride(TestCase):
    """R35: QUOTE_PATH_BLOCKED should not apply when sweep evidence is strong."""

    def test_sweep_evidence_overrides_quoter_failure(self):
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 5,
            "fail": 0,
            "included_signals_total": 50,
            "runs_with_sweep": 3,
            "last_quote_source_summary": {
                "quotes_fetched_executable": 5,
                "quotes_fetched_diagnostic": 5,
                "quoter_v2_failed_count": 60,  # >50% failure
            },
            "last_oe_rejection_funnel": {
                "rejected_count": 10,
                "rejected_reasons": {"NET_PROFIT_TOO_LOW": 8},
            },
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        # Should NOT be QUOTE_PATH_BLOCKED because sweep is active
        self.assertNotEqual(stats["blocker_evidence"], "QUOTE_PATH_BLOCKED")
        self.assertEqual(stats["blocker_evidence"], "OE_ECONOMICS")

    def test_sweep_evidence_overrides_slot0_diagnostic(self):
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 5,
            "fail": 0,
            "included_signals_total": 50,
            "runs_with_sweep": 2,
            "last_quote_source_summary": {},
            "last_oe_rejection_funnel": {
                "rejected_count": 20,
                "rejected_reasons": {"SLOT0_DIAGNOSTIC": 10, "NET_PROFIT_TOO_LOW": 10},
            },
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        # With sweep evidence, SLOT0_DIAGNOSTIC should not trigger QUOTE_PATH_BLOCKED
        # Instead falls through to OE_ECONOMICS (NET_PROFIT_TOO_LOW is 50% > 40%)
        self.assertNotEqual(stats["blocker_evidence"], "QUOTE_PATH_BLOCKED")
        self.assertEqual(stats["blocker_evidence"], "OE_ECONOMICS")

    def test_no_sweep_evidence_still_labels_quote_blocked(self):
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 5,
            "fail": 0,
            "included_signals_total": 50,
            "runs_with_sweep": 0,
            "last_quote_source_summary": {
                "quotes_fetched_executable": 5,
                "quotes_fetched_diagnostic": 5,
                "quoter_v2_failed_count": 60,
            },
            "last_oe_rejection_funnel": {},
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        self.assertEqual(stats["blocker_evidence"], "QUOTE_PATH_BLOCKED")


class TestHotLoopNonCanonicalGuard(TestCase):
    """R35: Non-canonical sessions (no _rolling summary_file) must not overwrite HOT_LOOP_LATEST."""

    def test_empty_summary_file_skips_canonical_write(self):
        from strategy.rolling_outputs import write_hot_loop_snapshot, HOT_LOOP_LATEST
        from strategy.chain_stats import new_chain_stats

        per_chain = {"arb": new_chain_stats()}
        per_chain["arb"]["runs"] = 1

        HOT_LOOP_LATEST.parent.mkdir(parents=True, exist_ok=True)
        existed_before = HOT_LOOP_LATEST.exists()
        if existed_before:
            before_content = HOT_LOOP_LATEST.read_text(encoding="utf-8")

        write_hot_loop_snapshot(
            per_chain, None, time.monotonic() - 5,
            summary_file="",  # Non-canonical: no summary file
        )

        if existed_before:
            after_content = HOT_LOOP_LATEST.read_text(encoding="utf-8")
            self.assertEqual(before_content, after_content,
                             "Non-canonical session must NOT modify canonical hot_loop_latest.json")

    def test_non_rolling_summary_file_skips_canonical_write(self):
        from strategy.rolling_outputs import write_hot_loop_snapshot, HOT_LOOP_LATEST
        from strategy.chain_stats import new_chain_stats

        per_chain = {"base": new_chain_stats()}
        per_chain["base"]["runs"] = 1

        HOT_LOOP_LATEST.parent.mkdir(parents=True, exist_ok=True)
        existed_before = HOT_LOOP_LATEST.exists()
        if existed_before:
            before_content = HOT_LOOP_LATEST.read_text(encoding="utf-8")

        write_hot_loop_snapshot(
            per_chain, None, time.monotonic() - 5,
            summary_file="C:\\Users\\tmp\\test_summary.json",  # Non-rolling path
        )

        if existed_before:
            after_content = HOT_LOOP_LATEST.read_text(encoding="utf-8")
            self.assertEqual(before_content, after_content,
                             "Non-rolling summary_file must NOT modify canonical hot_loop_latest.json")

    def test_rolling_summary_file_writes_canonical(self):
        from strategy.rolling_outputs import write_hot_loop_snapshot
        from strategy.chain_stats import new_chain_stats

        per_chain = {"arb": new_chain_stats()}
        per_chain["arb"]["runs"] = 1

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td) / "hot_loop_test.json"
            write_hot_loop_snapshot(
                per_chain, None, time.monotonic() - 5,
                summary_file="data/runs/_rolling/long_scan_latest.json",
                output_path=tmp_path,  # Explicit path to avoid modifying real file
            )
            self.assertTrue(tmp_path.exists(),
                            "Rolling summary_file with explicit output_path should write")
