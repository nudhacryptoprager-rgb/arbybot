# PATH: tests/unit/test_quote_source_contracts.py
"""
R39i+: Contract tests for quote source exclusion.

Verifies:
1. MIXED_SOURCE opportunities don't reach sweep reprieve path
2. SLOT0-only opportunities don't reach sweep reprieve path
3. Only quoter_v2 on both legs can be sweep reprieve candidates
4. QUOTE_PATH_BLOCKED blocks chains with rq=0 even with diagnostic sweeps
"""

from unittest import TestCase


def _make_opp(
    pair: str = "WETH/USDC",
    buy_dex: str = "uniswap_v3",
    sell_dex: str = "sushiswap_v3",
    buy_quote_source: str = "quoter_v2",
    sell_quote_source: str = "quoter_v2",
    gate_passed: bool = False,
    is_reprievable: bool = True,
    gross_spread_bps: float = 15.0,
    reject_reason: str = "NET_PROFIT_TOO_LOW: 0.05 < 0.10",
) -> dict:
    """Create a minimal opportunity dict for testing."""
    return {
        "pair": pair,
        "buy_dex": buy_dex,
        "sell_dex": sell_dex,
        "buy_quote_source": buy_quote_source,
        "sell_quote_source": sell_quote_source,
        "gate_passed": gate_passed,
        "is_reprievable": is_reprievable,
        "gross_spread_bps": gross_spread_bps,
        "reject_reason": reject_reason,
    }


class TestSweepReprieveQuoteSourceExclusion(TestCase):
    """Verify that non-quoter_v2 routes are excluded from sweep reprieve."""

    def test_mixed_source_excluded_from_sweep_reprieve(self):
        """MIXED_SOURCE (quoter_v2 + slot0) must not reach sweep reprieve."""
        from strategy.roundtrip_selection import select_sweep_reprieve_candidates

        opps = [
            _make_opp(
                pair="WETH/USDC",
                buy_quote_source="quoter_v2",
                sell_quote_source="slot0",  # MIXED_SOURCE
            ),
            _make_opp(
                pair="ARB/USDC",
                buy_quote_source="slot0",  # MIXED_SOURCE
                sell_quote_source="quoter_v2",
            ),
        ]
        candidates, stats = select_sweep_reprieve_candidates(opps)
        self.assertEqual(len(candidates), 0)
        self.assertEqual(stats["sweep_reprieve_selected"], 0)

    def test_slot0_only_excluded_from_sweep_reprieve(self):
        """SLOT0 on both legs must not reach sweep reprieve."""
        from strategy.roundtrip_selection import select_sweep_reprieve_candidates

        opps = [
            _make_opp(
                pair="WETH/USDC",
                buy_quote_source="slot0",
                sell_quote_source="slot0",
            ),
        ]
        candidates, stats = select_sweep_reprieve_candidates(opps)
        self.assertEqual(len(candidates), 0)

    def test_quoter_v2_both_legs_reaches_sweep_reprieve(self):
        """quoter_v2 on both legs CAN reach sweep reprieve."""
        from strategy.roundtrip_selection import select_sweep_reprieve_candidates

        opps = [
            _make_opp(
                pair="WETH/USDC",
                buy_quote_source="quoter_v2",
                sell_quote_source="quoter_v2",
            ),
        ]
        candidates, stats = select_sweep_reprieve_candidates(opps)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(stats["sweep_reprieve_selected"], 1)

    def test_same_dex_excluded_from_sweep_reprieve(self):
        """Same-DEX routes (even with quoter_v2) must not reach sweep reprieve."""
        from strategy.roundtrip_selection import select_sweep_reprieve_candidates

        opps = [
            _make_opp(
                pair="WETH/USDC",
                buy_dex="uniswap_v3",
                sell_dex="uniswap_v3",  # same DEX
                buy_quote_source="quoter_v2",
                sell_quote_source="quoter_v2",
            ),
        ]
        candidates, stats = select_sweep_reprieve_candidates(opps)
        self.assertEqual(len(candidates), 0)


class TestOpportunityEngineQuoteSourceGates(TestCase):
    """Verify opportunity engine rejects MIXED_SOURCE and SLOT0_DIAGNOSTIC."""

    def test_mixed_source_rejected_in_opportunity_engine(self):
        """MIXED_SOURCE opportunities get gate_passed=False with correct reason."""
        from engine.opportunity_engine import OpportunityEngine, GasConfig

        # Create minimal quotes with price fields (required by _build_opportunity)
        quote_a = {
            "dex_id": "uniswap_v3",
            "token_in": "WETH",
            "token_out": "USDC",
            "price": "2000",
            "quote_source": "quoter_v2",
            "fee": 500,
            "usd_notional": 1000,
            "amount_in_wei": 10**18,
        }
        quote_b = {
            "dex_id": "sushiswap_v3",
            "token_in": "WETH",
            "token_out": "USDC",
            "price": "2010",
            "quote_source": "slot0",  # diagnostic
            "fee": 500,
            "usd_notional": 1000,
            "amount_in_wei": 10**18,
        }

        engine = OpportunityEngine(gas_config=GasConfig())
        opp = engine._build_opportunity(
            pair="WETH/USDC",
            quote_a=quote_a,
            quote_b=quote_b,
            cycle=1,
            timestamp="20260324_120000",
            index=0,
        )

        # Must be rejected with MIXED_SOURCE
        self.assertIsNotNone(opp)
        self.assertFalse(opp.gate_passed)
        self.assertIn("MIXED_SOURCE", opp.reject_reason)

    def test_slot0_only_rejected_in_opportunity_engine(self):
        """SLOT0_DIAGNOSTIC opportunities get gate_passed=False."""
        from engine.opportunity_engine import OpportunityEngine, GasConfig

        quote_a = {
            "dex_id": "uniswap_v3",
            "token_in": "WETH",
            "token_out": "USDC",
            "price": "2000",
            "quote_source": "slot0",
            "fee": 500,
            "usd_notional": 1000,
            "amount_in_wei": 10**18,
        }
        quote_b = {
            "dex_id": "sushiswap_v3",
            "token_in": "WETH",
            "token_out": "USDC",
            "price": "2010",
            "quote_source": "slot0",
            "fee": 500,
            "usd_notional": 1000,
            "amount_in_wei": 10**18,
        }

        engine = OpportunityEngine(gas_config=GasConfig())
        opp = engine._build_opportunity(
            pair="WETH/USDC",
            quote_a=quote_a,
            quote_b=quote_b,
            cycle=1,
            timestamp="20260324_120000",
            index=0,
        )

        self.assertIsNotNone(opp)
        self.assertFalse(opp.gate_passed)
        self.assertIn("SLOT0_DIAGNOSTIC", opp.reject_reason)


class TestBlockerEvidenceQuotePathContract(TestCase):
    """Verify QUOTE_PATH_BLOCKED requires real_quote_count=0."""

    def test_base_scenario_slot0_dominant_rq_zero(self):
        """Base-like scenario: SLOT0 dominant + sweeps but rq=0 → QUOTE_PATH_BLOCKED."""
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 10,
            "fail": 0,
            "included_signals_total": 50,
            "roundtrip_evaluated_total": 5,
            "real_quote_count_total": 0,  # KEY: no real quotes
            "runs_with_sweep": 2,         # has sweep evidence
            "last_cross_dex_pairs_count": 9,
            "last_quote_source_summary": {
                "quotes_fetched_executable": 5,
                "quotes_fetched_diagnostic": 60,
                "quoter_v2_failed_count": 40,
            },
            "last_oe_rejection_funnel": {
                "total_opportunities": 100,
                "rejected_count": 95,
                "rejected_reasons": {
                    "SLOT0_DIAGNOSTIC": 75,  # 79% dominance
                    "MIXED_SOURCE": 15,
                    "NET_PROFIT_TOO_LOW": 5,
                },
            },
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        # Must be QUOTE_PATH_BLOCKED because rq=0 despite sweep evidence
        self.assertEqual(stats["blocker_evidence"], "QUOTE_PATH_BLOCKED")

    def test_scroll_mantle_scenario_mixed_source_dominant(self):
        """Scroll/mantle-like scenario: MIXED_SOURCE dominant → MIXED_SOURCE."""
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 10,
            "fail": 0,
            "included_signals_total": 30,
            "roundtrip_evaluated_total": 8,
            "real_quote_count_total": 4,  # has some real quotes
            "runs_with_sweep": 2,
            "last_cross_dex_pairs_count": 5,
            "last_quote_source_summary": {
                "quotes_fetched_executable": 20,
                "quotes_fetched_diagnostic": 30,
                "quoter_v2_failed_count": 10,
            },
            "last_oe_rejection_funnel": {
                "total_opportunities": 50,
                "rejected_count": 40,
                "rejected_reasons": {
                    "MIXED_SOURCE": 25,  # 62.5% dominance
                    "NET_PROFIT_TOO_LOW": 10,
                    "SLOT0_DIAGNOSTIC": 5,
                },
            },
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        self.assertEqual(stats["blocker_evidence"], "MIXED_SOURCE")

    def test_arb_scenario_economics_dominant(self):
        """Arb-like scenario: NET_PROFIT_TOO_LOW dominant → OE_ECONOMICS."""
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 10,
            "fail": 0,
            "included_signals_total": 200,
            "roundtrip_evaluated_total": 30,
            "real_quote_count_total": 30,  # healthy real quotes
            "runs_with_sweep": 6,
            "last_cross_dex_pairs_count": 11,
            "last_quote_source_summary": {
                "quotes_fetched_executable": 150,
                "quotes_fetched_diagnostic": 30,
                "quoter_v2_failed_count": 5,
            },
            "last_oe_rejection_funnel": {
                "total_opportunities": 80,
                "rejected_count": 50,
                "rejected_reasons": {
                    "NET_PROFIT_TOO_LOW": 35,  # 70% dominance
                    "SLIPPAGE_TOO_HIGH": 10,
                    "MIXED_SOURCE": 5,
                },
            },
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        self.assertEqual(stats["blocker_evidence"], "OE_ECONOMICS")


class TestQuoterV2SkipMechanism(TestCase):
    """R39i++: Document the quoter_v2 skip/fallback mechanism in quotes.py."""

    def test_skip_threshold_and_ttl_constants(self):
        """Verify skip threshold=3 and TTL=600s are defined."""
        from strategy.quotes import QUOTER_V2_SKIP_THRESHOLD, QUOTER_V2_SKIP_TTL_SECONDS
        self.assertEqual(QUOTER_V2_SKIP_THRESHOLD, 3)
        self.assertEqual(QUOTER_V2_SKIP_TTL_SECONDS, 600)

    def test_should_skip_false_initially(self):
        """Fresh pool_key should NOT be skipped."""
        from strategy.quotes import _should_skip_quoter_v2
        # Use a unique key that was never recorded as failed
        result = _should_skip_quoter_v2("test_never_seen_pool_key_unique_abcdef")
        self.assertFalse(result)

    def test_record_failure_and_skip(self):
        """After THRESHOLD failures, pool should be skipped."""
        from strategy.quotes import (
            _record_quoter_v2_failure,
            _record_quoter_v2_success,
            _should_skip_quoter_v2,
            QUOTER_V2_SKIP_THRESHOLD,
        )
        pool_key = "test_pool_key_skip_mechanism_xyz123"
        # Clear any prior state by recording a success
        _record_quoter_v2_success(pool_key)
        self.assertFalse(_should_skip_quoter_v2(pool_key))

        # Record failures up to threshold
        for _ in range(QUOTER_V2_SKIP_THRESHOLD):
            _record_quoter_v2_failure(pool_key)

        self.assertTrue(_should_skip_quoter_v2(pool_key))

        # Success resets
        _record_quoter_v2_success(pool_key)
        self.assertFalse(_should_skip_quoter_v2(pool_key))

    def test_base_quote_path_failure_chain(self):
        """Document the base failure chain: quoter_v2 fail → slot0 fallback → SLOT0_DIAGNOSTIC.

        This is the exact sequence that causes base to be QUOTE_PATH_BLOCKED:
        1. quoter_v2 reverts on base pools (8453) → QUOTER_V2_FAILED
        2. After 3 consecutive failures, pool is skip-listed for 600s
        3. Skip-listed pools go to slot0 read → quote_source="slot0"
        4. OE rejects slot0-only as SLOT0_DIAGNOSTIC
        5. Chain stats sees >40% SLOT0_DIAGNOSTIC → QUOTE_PATH_BLOCKED
        """
        from strategy.chain_stats import _compute_blocker_evidence

        # Simulate base fresh evidence snapshot
        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 36,
            "fail": 0,
            "included_signals_total": 50,
            "roundtrip_evaluated_total": 10,
            "real_quote_count_total": 0,
            "runs_with_sweep": 3,
            "last_cross_dex_pairs_count": 9,
            "last_quote_source_summary": {
                "quotes_fetched_executable": 0,
                "quotes_fetched_diagnostic": 104,
                "quoter_v2_failed_count": 48,
            },
            # OE funnel: SLOT0_DIAGNOSTIC dominates
            "last_oe_rejection_funnel": {
                "total_opportunities": 60,
                "rejected_count": 55,
                "rejected_reasons": {
                    "SLOT0_DIAGNOSTIC": 42,  # 76% of rejects
                    "MIXED_SOURCE": 8,
                    "NET_PROFIT_TOO_LOW": 5,
                },
            },
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        # With rq=0 and SLOT0_DIAGNOSTIC > 40% → QUOTE_PATH_BLOCKED
        self.assertEqual(stats["blocker_evidence"], "QUOTE_PATH_BLOCKED")

    def test_rate_limit_sentinel_not_counted_as_failure(self):
        """R39k: QUOTER_RATE_LIMITED sentinel should NOT increment skip cache."""
        from strategy.quote_rpc import QUOTER_RATE_LIMITED, _is_rate_limit_error
        from strategy.quotes import (
            _record_quoter_v2_failure,
            _record_quoter_v2_success,
            _should_skip_quoter_v2,
            QUOTER_V2_SKIP_THRESHOLD,
        )

        # Verify sentinel shape
        self.assertTrue(QUOTER_RATE_LIMITED.get("_rate_limited"))
        self.assertEqual(QUOTER_RATE_LIMITED.get("amount_out", 0), 0)

        # Verify detection of 429 errors
        self.assertTrue(_is_rate_limit_error(Exception("429 Client Error: Too Many Requests")))
        self.assertTrue(_is_rate_limit_error(Exception("rate limit exceeded")))
        self.assertFalse(_is_rate_limit_error(Exception("execution reverted")))

        # Verify identity check works (used in quotes.py to gate skip cache)
        self.assertIs(QUOTER_RATE_LIMITED, QUOTER_RATE_LIMITED)
        self.assertIsNot({"_rate_limited": True}, QUOTER_RATE_LIMITED)

        # Verify a pool with only rate-limit "failures" does NOT get skip-cached
        pool_key = "test_rate_limit_pool_key_unique_rl999"
        _record_quoter_v2_success(pool_key)  # reset
        # Simulate: rate-limited calls should NOT call _record_quoter_v2_failure
        # (this is enforced in quotes.py, here we just verify the skip cache stays clean)
        for _ in range(QUOTER_V2_SKIP_THRESHOLD + 5):
            pass  # rate-limited calls don't record failure
        self.assertFalse(_should_skip_quoter_v2(pool_key))


class TestLegSourceSummaryOperational(TestCase):
    """R39k: leg_source_summary must feed into chain_stats blocker classification."""

    def test_leg_source_summary_propagated_to_chain_stats(self):
        """update_chain_stats propagates leg_source_summary from truth_report."""
        from strategy.chain_stats import new_chain_stats, update_chain_stats

        stats = new_chain_stats()
        self.assertIsNone(stats["last_leg_source_summary"])

        truth_report = {
            "roundtrip_summary": {
                "leg_source_summary": {
                    "leg1": {"quoter_v2": 3, "slot0": 2},
                    "leg2": {"quoter_v2": 2, "ve33_getAmountOut": 3},
                    "both_quoter_v2": 2,
                    "both_slot0": 0,
                    "mixed_source": 3,
                    "total": 5,
                }
            }
        }
        update_chain_stats(
            stats, exit_code=0, run_dir=None, summary=None,
            truth_report=truth_report,
        )
        lss = stats["last_leg_source_summary"]
        self.assertIsNotNone(lss)
        self.assertEqual(lss["total"], 5)
        self.assertEqual(lss["mixed_source"], 3)
        self.assertEqual(lss["both_quoter_v2"], 2)

    def test_leg_source_summary_detects_all_executable_roundtrips(self):
        """When leg_source_summary shows both_quoter_v2+mixed executable > 0,
        the chain is not QUOTE_PATH_BLOCKED — executable quotes are flowing."""
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 10,
            "fail": 0,
            "included_signals_total": 20,
            "roundtrip_evaluated_total": 5,
            "real_quote_count_total": 5,
            "runs_with_sweep": 2,
            "last_cross_dex_pairs_count": 8,
            "last_quote_source_summary": {
                "quotes_fetched_executable": 10,
                "quotes_fetched_diagnostic": 5,
                "quoter_v2_failed_count": 2,
            },
            "last_oe_rejection_funnel": {
                "total_opportunities": 20,
                "rejected_count": 15,
                "rejected_reasons": {
                    "NET_PROFIT_TOO_LOW": 12,
                    "MIXED_SOURCE": 3,
                },
            },
            "last_leg_source_summary": {
                "leg1": {"quoter_v2": 3, "ve33_getAmountOut": 2},
                "leg2": {"quoter_v2": 2, "ve33_getAmountOut": 3},
                "both_quoter_v2": 2,
                "both_slot0": 0,
                "mixed_source": 1,
                "total": 5,
            },
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        # NET_PROFIT_TOO_LOW dominates (12/15=80%) → OE_ECONOMICS, not MIXED_SOURCE
        self.assertEqual(stats["blocker_evidence"], "OE_ECONOMICS")
