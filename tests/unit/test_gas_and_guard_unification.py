from __future__ import annotations

from m7.orderflow.contracts import BackrunResult, OrderflowEvent
from m7.orderflow.profit_guard import annotate_profit_guard_results, check_profit_guard
from m7.orderflow.pricing import estimate_gas_cost_bps
from m7.shared.constants import estimate_gas_cost, get_min_profitable_size_wei


class TestUnifiedGasEstimation:
    def test_estimate_gas_cost_base_small_size_is_dynamic(self):
        gas_bps, gas_cost_wei = estimate_gas_cost("base", 10**16)
        assert gas_bps >= 0.5
        assert gas_cost_wei > 0

    def test_min_profitable_size_scales_by_decimals(self):
        eth_min = get_min_profitable_size_wei("base", 18)
        usdc_min = get_min_profitable_size_wei("base", 6)
        assert eth_min >= 10**15
        assert usdc_min >= 10**3
        assert eth_min > usdc_min

    def test_offline_estimate_gas_cost_bps_respects_chain(self):
        event = OrderflowEvent(
            event_id="ev1",
            event_type="swap",
            chain="base",
            block_number=1,
            tx_hash="0x1",
            token_in="WETH",
            token_out="USDC",
            amount_in_wei=10**18,
            amount_out_wei=2_000 * 10**6,
            dex="uniswap_v3",
            pool_address="0xpool",
            fee_tier=3000,
            estimated_size_usd=3500.0,
            estimated_impact_bps=10.0,
            timestamp="2026-04-15T00:00:00Z",
        )
        base_bps = estimate_gas_cost_bps(event, chain="base")
        arb_bps = estimate_gas_cost_bps(event, chain="arbitrum_one")
        assert base_bps < arb_bps


class TestGuardRejectTelemetry:
    def test_profit_guard_returns_reject_reason(self):
        guard = check_profit_guard(
            buy_amount_wei=10**16,
            sell_amount_wei=10**16,
            backrun_size_wei=10**16,
            chain="base",
        )
        assert guard.passed is False
        assert guard.reject_reason == "ENDING_BALANCE_NOT_GT_STARTING"

    def test_annotate_profit_guard_writes_reject_reason_back(self):
        result = BackrunResult(
            event_id="ev2",
            event_source="live",
            event_type="swap",
            post_trade_state_used="live",
            backrun_direction="buy",
            amount_in_wei=10**16,
            gross_pnl_wei=0,
            best_backrun_net_bps=1.0,
            route_viable=True,
            size_valid_for_token=True,
        )
        passed = annotate_profit_guard_results([result], chain="base")
        assert passed == []
        assert result.profit_guard_passed is False
        assert result.guard_reject_reason == "ENDING_BALANCE_NOT_GT_STARTING"