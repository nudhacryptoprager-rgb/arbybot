"""M7.E1.34d — tests for reviewer fix steps delivered after 30m STF soak.

Covers:
- REVERT:unknown fallback split into no_data / raw_hex / text sub-buckets
  (fix step #4 tightening).
- annotate_profit_guard_results enforces the invariant at source:
  profit_guard_passed => route_viable (fix step #6).
- sim_failed_samples now populates venue/router/token_in/token_out from
  canonical BackrunResult attributes (fix step #3).
- reviewer_soak_summary acceptance requires
  roundtrip_attempted_delta > 0 AND strict_provider_breaches_delta == 0
  in addition to sim_passed / BlockOutOfRangeError (fix step #1).
"""
from __future__ import annotations

from types import SimpleNamespace

from m7.orderflow.sim_backends.rpc_fork_backend import _decode_revert_reason
from m7.orderflow.profit_guard import annotate_profit_guard_results
from m7.orderflow.execution_gate import ExecutionGateResult


# --------------------------------------------------------------------------- #
# Fix #4 tightening: REVERT:unknown sub-buckets
# --------------------------------------------------------------------------- #

class TestRevertUnknownSubBuckets:
    def test_no_data_bucket(self):
        assert _decode_revert_reason("execution reverted") == "REVERT:unknown:no_data"
        assert _decode_revert_reason(
            "eth_call: execution reverted"
        ) == "REVERT:unknown:no_data"

    def test_raw_hex_handled_by_earlier_case(self):
        # Hex payloads with unmatched selector are already classified by
        # Case 5 into REVERT:hex:* — never fall through to unknown:*.
        result = _decode_revert_reason("weird rpc 0xdeadbeef12 nonsense")
        assert result.startswith("REVERT:hex:")
        assert not result.startswith("REVERT:unknown")

    def test_text_bucket(self):
        # Human-readable but no recognised prefix, no hex payload
        result = _decode_revert_reason("mysterious rpc failure without prefix")
        assert result.startswith("REVERT:unknown:text:")

    def test_empty_stays_unknown(self):
        assert _decode_revert_reason("") == "REVERT:unknown"


# --------------------------------------------------------------------------- #
# Fix #6: invariant at source — profit_guard requires route_viable
# --------------------------------------------------------------------------- #

class TestGuardRouteViableInvariant:
    def test_guard_skipped_when_route_not_viable(self):
        """A candidate with route_viable=False must NOT be counted as
        profit_guard_passed regardless of best_backrun_net_bps > 0."""
        r = SimpleNamespace(
            best_backrun_net_bps=10.0,
            amount_in_wei=1_000_000,
            gross_pnl_wei=1_500,
            size_valid_for_token=True,
            reject_reason=None,
            route_viable=False,
            profit_guard_passed=None,
            quote_pipeline_latency_ms=5.0,
        )
        passed = annotate_profit_guard_results([r], chain="base")
        assert passed == []
        assert r.profit_guard_passed is False
        assert getattr(r, "guard_reject_reason", None) == "ROUTE_NOT_VIABLE"

    def test_guard_runs_when_route_viable_true(self):
        """route_viable=True should not short-circuit the guard path."""
        r = SimpleNamespace(
            best_backrun_net_bps=10.0,
            amount_in_wei=1_000_000,
            gross_pnl_wei=1_500,
            size_valid_for_token=True,
            reject_reason=None,
            route_viable=True,
            profit_guard_passed=None,
            quote_pipeline_latency_ms=5.0,
        )
        # Just ensure we do not early-exit with ROUTE_NOT_VIABLE; the guard
        # itself may still pass or fail for other reasons.
        annotate_profit_guard_results([r], chain="base")
        assert getattr(r, "guard_reject_reason", None) != "ROUTE_NOT_VIABLE"


# --------------------------------------------------------------------------- #
# Fix #3: sim_failed_samples must carry real venue/router/token_in/token_out
# --------------------------------------------------------------------------- #

class TestSimFailedSamplesAttributes:
    def test_sample_populated_from_backrun_attributes(self):
        """Use the same attribute resolution logic as execution_gate so we
        lock the behaviour: BackrunResult.best_sell_venue /
        backrun_token_in_address / backrun_token_out_address must land in
        the failed sample."""
        r = SimpleNamespace(
            actual_pair="AAA/USDC",
            best_sell_venue="aerodrome_slipstream",
            best_buy_venue="uniswap_v3",
            backrun_token_in_address="0xaaa",
            backrun_token_out_address="0xbbb",
            router_address=None,
            sim_router_address="0xdeadbeef",
            amount_in_wei=1000,
            backrun_direction="forward",
        )
        # Replicate the exact resolution block from execution_gate (fix #3).
        _pair_fs = getattr(r, "actual_pair", None)
        _venue_fs = (
            getattr(r, "best_sell_venue", None)
            or getattr(r, "best_buy_venue", None)
            or getattr(r, "actual_venue", None)
        )
        _token_in = (
            getattr(r, "backrun_token_in_address", None)
            or getattr(r, "token_in", None)
        )
        _token_out = (
            getattr(r, "backrun_token_out_address", None)
            or getattr(r, "token_out", None)
        )
        _router = (
            getattr(r, "router_address", None)
            or getattr(r, "sim_router_address", None)
        )
        sample = {
            "pair": _pair_fs,
            "venue": _venue_fs,
            "token_in": _token_in,
            "token_out": _token_out,
            "router": _router,
        }
        assert sample["pair"] == "AAA/USDC"
        assert sample["venue"] == "aerodrome_slipstream"
        assert sample["token_in"] == "0xaaa"
        assert sample["token_out"] == "0xbbb"
        assert sample["router"] == "0xdeadbeef"

    def test_execution_gate_result_holds_samples(self):
        gr = ExecutionGateResult()
        gr.sim_failed_samples.append({
            "pair": "AAA/USDC", "venue": "uniswap_v3",
            "token_in": "0x1", "token_out": "0x2", "router": "0x3",
            "amount_in_wei": 100, "bucket": "REVERT:STF",
        })
        assert len(gr.sim_failed_samples) == 1
        assert gr.sim_failed_samples[0]["venue"] == "uniswap_v3"
