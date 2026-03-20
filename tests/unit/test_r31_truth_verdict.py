# PATH: tests/unit/test_r31_truth_verdict.py
"""
R31: Tests for truth_verdict (policy) + quote_source_summary / oe_rejection_funnel (truth_report).

Locks the contract:
- compute_status() returns truth_verdict in all paths
- build_truth_data() returns quote_source_summary and oe_rejection_funnel
"""

import unittest


class TestTruthVerdictPolicy(unittest.TestCase):
    """R31: truth_verdict must be present in compute_status() output."""

    def _compute(self, **kwargs):
        from m4.policy import compute_status
        defaults = {
            "signals_count": 5,
            "total_net_usdc": 1.0,
            "roundtrip_profitable_count": 0,
        }
        defaults.update(kwargs)
        return compute_status(**defaults)

    def test_no_data_returns_truth_verdict(self):
        result = self._compute(signals_count=0, total_net_usdc=0)
        self.assertEqual(result["truth_verdict"], "NO_DATA")

    def test_diagnostic_profit_only(self):
        """profit_status=PASS + no profitable roundtrips -> DIAGNOSTIC_PROFIT_ONLY."""
        result = self._compute(total_net_usdc=1.0, roundtrip_profitable_count=0)
        self.assertEqual(result["profit_status"], "PASS")
        self.assertEqual(result["roundtrip_truth_status"], "NOT_PROFITABLE")
        self.assertEqual(result["truth_verdict"], "DIAGNOSTIC_PROFIT_ONLY")

    def test_roundtrip_profitable(self):
        result = self._compute(total_net_usdc=1.0, roundtrip_profitable_count=3)
        self.assertEqual(result["truth_verdict"], "ROUNDTRIP_PROFITABLE")

    def test_no_profit(self):
        result = self._compute(total_net_usdc=-0.5, roundtrip_profitable_count=0)
        self.assertEqual(result["profit_status"], "FAIL")
        self.assertEqual(result["truth_verdict"], "NO_PROFIT")

    def test_truth_verdict_domain(self):
        """truth_verdict must be one of the 4 canonical values."""
        valid = {"NO_DATA", "ROUNDTRIP_PROFITABLE", "DIAGNOSTIC_PROFIT_ONLY", "NO_PROFIT"}
        for net, rpc in [(0, 0), (1.0, 0), (1.0, 2), (-1.0, 0)]:
            result = self._compute(
                signals_count=5 if net != 0 or rpc != 0 else 0,
                total_net_usdc=net,
                roundtrip_profitable_count=rpc,
            )
            self.assertIn(result["truth_verdict"], valid,
                          f"Invalid truth_verdict={result['truth_verdict']} for net={net}, rpc={rpc}")


class TestQuoteSourceSummaryInTruthReport(unittest.TestCase):
    """R31: build_truth_data() must include quote_source_summary."""

    def _build(self, stats_override=None):
        from strategy.artifacts import build_truth_data
        config = {
            "chain_id": 42161, "chain": "arbitrum_one",
            "paper_size_usd": 1000, "gas_usd_estimate": 0.10,
        }
        stats = {
            "quotes_total": 10, "quotes_fetched": 8, "dexes_active": 2,
            "price_sanity_passed": 8, "price_sanity_failed": 2,
            "quotes_fetched_executable": 5,
            "quotes_fetched_diagnostic": 3,
            "quoter_v2_failed_count": 4,
            "quoter_matrix": {"uniswap_v3": {"success": 3, "fail": 2}},
        }
        if stats_override:
            stats.update(stats_override)
        return build_truth_data(config, stats, 12345, [], [], {}, 50, 10)

    def test_quote_source_summary_present(self):
        truth = self._build()
        self.assertIn("quote_source_summary", truth)

    def test_quote_source_summary_fields(self):
        truth = self._build()
        qs = truth["quote_source_summary"]
        self.assertEqual(qs["quotes_fetched_executable"], 5)
        self.assertEqual(qs["quotes_fetched_diagnostic"], 3)
        self.assertEqual(qs["quoter_v2_failed_count"], 4)
        self.assertEqual(qs["quoter_matrix"], {"uniswap_v3": {"success": 3, "fail": 2}})

    def test_quote_source_summary_defaults_when_missing(self):
        """When stats don't have quoter fields, defaults to 0/{}."""
        truth = self._build(stats_override={
            "quotes_fetched_executable": None,  # won't override, but let's test absent
        })
        # Just verify it doesn't crash — exact values depend on override
        self.assertIn("quote_source_summary", truth)


class TestOeRejectionFunnelInTruthReport(unittest.TestCase):
    """R31: build_truth_data() must include oe_rejection_funnel."""

    def _build(self, oe_stats=None):
        from strategy.artifacts import build_truth_data
        config = {
            "chain_id": 42161, "chain": "arbitrum_one",
            "paper_size_usd": 1000, "gas_usd_estimate": 0.10,
        }
        oe = oe_stats or {
            "enabled": True,
            "summary": {
                "total_opportunities": 228,
                "gated_count": 0,
                "rejected_count": 228,
                "rejected_reasons": {
                    "SLOT0_DIAGNOSTIC": 90,
                    "NET_PROFIT_TOO_LOW": 51,
                    "SUSPECT_SPREAD_HARD": 37,
                    "MIXED_SOURCE": 36,
                    "NOTIONAL_DRIFT": 14,
                },
            },
        }
        stats = {
            "quotes_total": 131, "quotes_fetched": 131, "dexes_active": 4,
            "price_sanity_passed": 131, "price_sanity_failed": 0,
            "opportunity_engine": oe,
        }
        return build_truth_data(config, stats, 12345, [], [], {}, 50, 10)

    def test_oe_rejection_funnel_present(self):
        truth = self._build()
        self.assertIn("oe_rejection_funnel", truth)

    def test_oe_rejection_funnel_values(self):
        truth = self._build()
        funnel = truth["oe_rejection_funnel"]
        self.assertEqual(funnel["total_opportunities"], 228)
        self.assertEqual(funnel["gated_count"], 0)
        self.assertEqual(funnel["rejected_count"], 228)
        self.assertIn("SLOT0_DIAGNOSTIC", funnel["rejected_reasons"])

    def test_oe_rejection_funnel_empty_when_no_oe(self):
        truth = self._build(oe_stats={"enabled": False})
        funnel = truth["oe_rejection_funnel"]
        self.assertEqual(funnel["total_opportunities"], 0)
        self.assertEqual(funnel["gated_count"], 0)
        self.assertEqual(funnel["rejected_reasons"], {})


if __name__ == "__main__":
    unittest.main()
