"""E1.35 audit-recommendations — unit tests for all 9 gate-improvement items.

P0.1: block_number forwarded to simulate_swap
P0.2: Tenderly auto-fallback on HTTP 4xx
P1.3: _ACCEPTED_FEES from DEX registry
P1.4: MIN_EVENT_SIZE_USD chain-aware
P1.5: post-sim freshness (block_lag_at_sim, freshness_violation)
P2.6: dedupe gas_cost scoring → guard via pre_computed_*
P2.7: chain-aware stale_gate (get_chain_stale_blocks)
P3.8: oracle sanity for oversized backruns
P3.9: USD-based get_min_profitable_size_usd
"""
import os
import pytest


# ---------------------------------------------------------------------------
# P0.1: block_number forwarded to simulate_swap
# ---------------------------------------------------------------------------

class TestBlockNumberForwarded:
    """P0.1: execution_gate passes event_block to simulate_swap."""

    def test_simulate_swap_receives_block_number(self, monkeypatch):
        from m7.orderflow.execution_gate import _attempt_simulation
        from m7.orderflow.simulation import SimulationResult
        from m7.orderflow.profit_guard import ProfitGuardResult
        import m7.orderflow.execution_gate as gate_mod

        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda: True)

        # Capture what simulate_swap receives
        captured = {}

        def fake_simulate_swap(**kw):
            captured.update(kw)
            return SimulationResult(success=True, gas_used=100_000)

        monkeypatch.setattr(gate_mod, "simulate_swap", fake_simulate_swap)

        class FakeResult:
            best_buy_venue = "uniswap_v3"
            best_buy_fee = 500
            actual_pair = "WETH/USDC"
            event_block = 12345678
            quote_block = 12345680
            backrun_token_in_address = "0xaaa"
            backrun_token_out_address = "0xbbb"
            amount_in_wei = 10 ** 18
            best_sell_venue = None

        # Patch _build_sim_tx_params to succeed
        monkeypatch.setattr(
            gate_mod,
            "_build_sim_tx_params",
            lambda r, chain: ({"to": "0x" + "00" * 20, "calldata": b"\x00", "value": 0}, None),
        )
        # Disable roundtrip
        monkeypatch.setenv("ARBY_ROUNDTRIP_SIM", "0")

        _attempt_simulation(FakeResult(), ProfitGuardResult(), chain="base")
        assert captured.get("block_number") == 12345678


# ---------------------------------------------------------------------------
# P0.2: Tenderly auto-fallback
# ---------------------------------------------------------------------------

class TestTenderlyAutoFallback:
    """P0.2: simulate_swap falls back to rpc_fork on HTTP 4xx."""

    def test_fallback_on_403(self, monkeypatch):
        from m7.orderflow import simulation as sim_mod
        from m7.orderflow.simulation import SimulationResult, simulate_swap

        monkeypatch.setattr(sim_mod, "get_simulation_backend", lambda **kw: "tenderly")
        monkeypatch.setattr(
            sim_mod,
            "_simulate_swap_tenderly",
            lambda **kw: SimulationResult(
                success=False, error="HTTP 403: insufficient credits"
            ),
        )
        monkeypatch.setenv("ARBY_SIM_FALLBACK", "rpc_fork")

        # Mock rpc_fork
        import m7.orderflow.sim_backends.rpc_fork_backend as rpc_mod
        monkeypatch.setattr(
            rpc_mod,
            "simulate_swap_rpc_fork",
            lambda **kw: SimulationResult(success=True, gas_used=150_000, backend="rpc_fork"),
        )

        result = simulate_swap(chain="base")
        assert result.success is True
        assert "rpc_fork" in (result.backend or "")

    def test_no_fallback_without_env(self, monkeypatch):
        from m7.orderflow import simulation as sim_mod
        from m7.orderflow.simulation import SimulationResult, simulate_swap

        monkeypatch.setattr(sim_mod, "get_simulation_backend", lambda **kw: "tenderly")
        monkeypatch.setattr(
            sim_mod,
            "_simulate_swap_tenderly",
            lambda **kw: SimulationResult(
                success=False, error="HTTP 403: insufficient credits"
            ),
        )
        monkeypatch.delenv("ARBY_SIM_FALLBACK", raising=False)

        result = simulate_swap(chain="base")
        assert result.success is False
        assert "403" in (result.error or "")


# ---------------------------------------------------------------------------
# P1.3: _ACCEPTED_FEES from DEX registry
# ---------------------------------------------------------------------------

class TestAcceptedFeesFromRegistry:
    """P1.3: get_accepted_fees builds set from config/dexes.yaml."""

    def test_base_contains_standard_v3_fees(self):
        from m7.orderflow.execution_gate import get_accepted_fees, _reset_accepted_fees_cache
        _reset_accepted_fees_cache()
        fees = get_accepted_fees("base")
        # Standard V3
        assert 100 in fees
        assert 500 in fees
        assert 3000 in fees
        assert 10000 in fees
        # VE33 sentinels
        assert 0 in fees
        assert 1 in fees

    def test_arbitrum_contains_pancake_2500(self):
        from m7.orderflow.execution_gate import get_accepted_fees, _reset_accepted_fees_cache
        _reset_accepted_fees_cache()
        fees = get_accepted_fees("arbitrum_one")
        assert 2500 in fees  # PancakeSwap unique tier

    def test_cache_reuse(self):
        from m7.orderflow.execution_gate import get_accepted_fees, _reset_accepted_fees_cache
        _reset_accepted_fees_cache()
        fees1 = get_accepted_fees("base")
        fees2 = get_accepted_fees("base")
        assert fees1 is fees2  # same frozenset object

    def test_unknown_chain_fallback(self):
        from m7.orderflow.execution_gate import get_accepted_fees, _reset_accepted_fees_cache
        _reset_accepted_fees_cache()
        fees = get_accepted_fees("nonexistent_chain_xyz")
        # Fallback: standard V3 + VE33
        assert 100 in fees
        assert 500 in fees
        assert 0 in fees


# ---------------------------------------------------------------------------
# P1.4: MIN_EVENT_SIZE_USD chain-aware
# ---------------------------------------------------------------------------

class TestChainAwareMinEventSize:
    """P1.4: get_victim_min_size_usd is chain-aware."""

    def test_base_lower_than_arbitrum(self, monkeypatch):
        monkeypatch.delenv("ARBY_VICTIM_MIN_USD", raising=False)
        from m7.shared.constants import get_victim_min_size_usd
        base_min = get_victim_min_size_usd(chain="base")
        arb_min = get_victim_min_size_usd(chain="arbitrum_one")
        assert base_min == 100.0
        assert arb_min == 500.0
        assert base_min < arb_min

    def test_no_chain_uses_global_default(self, monkeypatch):
        monkeypatch.delenv("ARBY_VICTIM_MIN_USD", raising=False)
        from m7.shared.constants import get_victim_min_size_usd, MIN_EVENT_SIZE_USD
        assert get_victim_min_size_usd() == MIN_EVENT_SIZE_USD

    def test_env_override_wins_over_chain(self, monkeypatch):
        monkeypatch.setenv("ARBY_VICTIM_MIN_USD", "42")
        from m7.shared.constants import get_victim_min_size_usd
        assert get_victim_min_size_usd(chain="base") == 42.0

    def test_unknown_chain_falls_back(self, monkeypatch):
        monkeypatch.delenv("ARBY_VICTIM_MIN_USD", raising=False)
        from m7.shared.constants import get_victim_min_size_usd, MIN_EVENT_SIZE_USD
        assert get_victim_min_size_usd(chain="fantom") == MIN_EVENT_SIZE_USD

    def test_classify_event_viability_with_chain(self, monkeypatch):
        """classify_event_viability passes chain to get_victim_min_size_usd."""
        monkeypatch.delenv("ARBY_VICTIM_MIN_USD", raising=False)
        from m7.orderflow.pricing import classify_event_viability
        from m7.orderflow.contracts import OrderflowEvent

        ev = OrderflowEvent(
            event_id="test",
            tx_hash="0xabc",
            block_number=1,
            event_type="swap",
            chain="base",
            dex="uniswap_v3",
            pool_address="0x123",
            token_in="USDC",
            token_out="WETH",
            amount_in_wei=200 * 10**6,
            amount_out_wei=10**17,
            fee_tier=500,
            estimated_size_usd=200.0,   # < 500 (arb) but >= 100 (base)
            estimated_impact_bps=10.0,
            timestamp="2025-01-01T00:00:00Z",
        )
        # Without chain or with arbitrum → rejected (200 < 500)
        assert classify_event_viability(ev, chain="arbitrum_one") is not None
        # With base → accepted (200 >= 100)
        assert classify_event_viability(ev, chain="base") is None


# ---------------------------------------------------------------------------
# P1.5: post-sim freshness
# ---------------------------------------------------------------------------

class TestPostSimFreshness:
    """P1.5: SimulationResult records freshness telemetry."""

    def test_freshness_fields_default(self):
        from m7.orderflow.simulation import SimulationResult
        sr = SimulationResult(success=True)
        assert sr.sim_block_number is None
        assert sr.event_block_number is None
        assert sr.block_lag_at_sim is None
        assert sr.freshness_violation is False

    def test_attempt_simulation_sets_freshness(self, monkeypatch):
        from m7.orderflow.execution_gate import _attempt_simulation
        from m7.orderflow.simulation import SimulationResult
        from m7.orderflow.profit_guard import ProfitGuardResult
        import m7.orderflow.execution_gate as gate_mod

        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda: True)
        monkeypatch.setattr(
            gate_mod,
            "_build_sim_tx_params",
            lambda r, chain: ({"to": "0x" + "00" * 20, "calldata": b"\x00", "value": 0}, None),
        )
        monkeypatch.setattr(
            gate_mod,
            "simulate_swap",
            lambda **kw: SimulationResult(success=True, gas_used=100_000),
        )
        monkeypatch.setenv("ARBY_ROUNDTRIP_SIM", "0")

        class FakeResult:
            best_buy_venue = "uniswap_v3"
            best_buy_fee = 500
            actual_pair = "WETH/USDC"
            event_block = 100
            quote_block = 103
            backrun_token_in_address = "0xaaa"
            backrun_token_out_address = "0xbbb"
            amount_in_wei = 10 ** 18
            best_sell_venue = None

        sim = _attempt_simulation(FakeResult(), ProfitGuardResult(), chain="base")
        assert sim.event_block_number == 100
        assert sim.sim_block_number == 103
        assert sim.block_lag_at_sim == 3
        # Base stale_blocks = 3, lag = 3 → exactly at threshold, not violated
        assert sim.freshness_violation is False

    def test_freshness_violation_when_stale(self, monkeypatch):
        from m7.orderflow.execution_gate import _attempt_simulation
        from m7.orderflow.simulation import SimulationResult
        from m7.orderflow.profit_guard import ProfitGuardResult
        import m7.orderflow.execution_gate as gate_mod

        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda: True)
        monkeypatch.setattr(
            gate_mod,
            "_build_sim_tx_params",
            lambda r, chain: ({"to": "0x" + "00" * 20, "calldata": b"\x00", "value": 0}, None),
        )
        monkeypatch.setattr(
            gate_mod,
            "simulate_swap",
            lambda **kw: SimulationResult(success=True, gas_used=100_000),
        )
        monkeypatch.setenv("ARBY_ROUNDTRIP_SIM", "0")

        class FakeResult:
            best_buy_venue = "uniswap_v3"
            best_buy_fee = 500
            actual_pair = "WETH/USDC"
            event_block = 100
            quote_block = 105  # lag=5 > base stale=3
            backrun_token_in_address = "0xaaa"
            backrun_token_out_address = "0xbbb"
            amount_in_wei = 10 ** 18
            best_sell_venue = None

        sim = _attempt_simulation(FakeResult(), ProfitGuardResult(), chain="base")
        assert sim.block_lag_at_sim == 5
        assert sim.freshness_violation is True


# ---------------------------------------------------------------------------
# P2.6: dedupe gas_cost scoring → guard
# ---------------------------------------------------------------------------

class TestDedupeGasCost:
    """P2.6: check_profit_guard uses pre_computed_gas_{bps,cost_wei} when set."""

    def test_precomputed_gas_reused(self):
        from m7.orderflow.profit_guard import check_profit_guard
        # Set up a scenario where the pre-computed gas is absurdly high
        # to prove it's actually used (instead of re-computed from chain).
        result = check_profit_guard(
            buy_amount_wei=10 ** 18,
            sell_amount_wei=10 ** 18 + 10 ** 16,  # 1% gross
            backrun_size_wei=10 ** 18,
            chain="base",
            pre_computed_gas_bps=5000.0,
            pre_computed_gas_cost_wei=10 ** 17,
        )
        # Gas is so high (5000 bps = 50%) that it should eat all profit
        assert result.gas_bps == 5000.0
        assert result.gas_cost_wei == 10 ** 17
        assert result.passed is False

    def test_without_precomputed_falls_back(self):
        from m7.orderflow.profit_guard import check_profit_guard
        result = check_profit_guard(
            buy_amount_wei=10 ** 18,
            sell_amount_wei=10 ** 18 + 10 ** 16,
            backrun_size_wei=10 ** 18,
            chain="base",
        )
        # Without pre-computed, uses estimate_gas_cost(base, ...) which
        # yields very low gas_bps (~0.15 floor). Profit should pass.
        assert result.passed is True
        assert result.gas_bps < 50  # way less than 5000


# ---------------------------------------------------------------------------
# P2.7: chain-aware stale_gate
# ---------------------------------------------------------------------------

class TestChainAwareStaleGate:
    """P2.7: get_chain_stale_blocks returns chain-appropriate thresholds."""

    def test_arbitrum_higher_threshold(self):
        from m7.shared.constants import get_chain_stale_blocks
        assert get_chain_stale_blocks("arbitrum_one") == 20

    def test_base_threshold(self):
        from m7.shared.constants import get_chain_stale_blocks
        assert get_chain_stale_blocks("base") == 3

    def test_unknown_chain_default(self):
        from m7.shared.constants import get_chain_stale_blocks
        assert get_chain_stale_blocks("fantom") == 2  # _DEFAULT_STALE_BLOCKS

    def test_empty_chain(self):
        from m7.shared.constants import get_chain_stale_blocks
        assert get_chain_stale_blocks("") == 2


# ---------------------------------------------------------------------------
# P3.8: oracle sanity for oversized backruns
# ---------------------------------------------------------------------------

class TestOracleSanity:
    """P3.8: check_oracle_sanity rejects large notionals with price deviation."""

    def test_below_threshold_passes(self):
        from m7.orderflow.oracle_sanity import check_oracle_sanity
        result = check_oracle_sanity(notional_usd=5000.0, implied_price=100.0, oracle_price=200.0)
        assert result.passed is True
        assert result.reason == "BELOW_THRESHOLD"

    def test_above_threshold_within_tolerance(self):
        from m7.orderflow.oracle_sanity import check_oracle_sanity
        result = check_oracle_sanity(
            notional_usd=15_000.0,
            implied_price=3500.0,
            oracle_price=3510.0,
        )
        assert result.passed is True

    def test_above_threshold_exceeds_tolerance(self):
        from m7.orderflow.oracle_sanity import check_oracle_sanity
        result = check_oracle_sanity(
            notional_usd=50_000.0,
            implied_price=3500.0,
            oracle_price=3000.0,  # ~16.7% deviation = 1667 bps >> 50
        )
        assert result.passed is False
        assert result.reason == "ORACLE_DEVIATION"
        assert result.deviation_bps > 1000

    def test_no_oracle_passes(self):
        from m7.orderflow.oracle_sanity import check_oracle_sanity
        result = check_oracle_sanity(notional_usd=50_000.0, oracle_price=None)
        assert result.passed is True
        assert result.reason == "ORACLE_UNAVAILABLE"

    def test_no_implied_passes(self):
        from m7.orderflow.oracle_sanity import check_oracle_sanity
        result = check_oracle_sanity(
            notional_usd=50_000.0, implied_price=None, oracle_price=3500.0,
        )
        assert result.passed is True
        assert result.reason == "IMPLIED_MISSING"

    def test_env_override_threshold(self, monkeypatch):
        from m7.orderflow.oracle_sanity import check_oracle_sanity
        monkeypatch.setenv("ARBY_ORACLE_SANITY_MIN_USD", "1000")
        result = check_oracle_sanity(
            notional_usd=5000.0,
            implied_price=3500.0,
            oracle_price=3000.0,
        )
        # Now 5000 > 1000 threshold, and 16.7% deviation → fail
        assert result.passed is False


# ---------------------------------------------------------------------------
# P3.9: USD-based get_min_profitable_size_usd
# ---------------------------------------------------------------------------

class TestMinProfitableSizeUsd:
    """P3.9: get_min_profitable_size_usd converts wei → USD."""

    def test_base_cheaper_than_arbitrum(self):
        from m7.shared.constants import get_min_profitable_size_usd
        base_usd = get_min_profitable_size_usd("base")
        arb_usd = get_min_profitable_size_usd("arbitrum_one")
        assert base_usd < arb_usd  # Base gas is cheaper

    def test_positive_result(self):
        from m7.shared.constants import get_min_profitable_size_usd
        val = get_min_profitable_size_usd("base")
        assert val > 0

    def test_custom_eth_price(self):
        from m7.shared.constants import get_min_profitable_size_usd
        cheap = get_min_profitable_size_usd("base", eth_price_usd=1000.0)
        expensive = get_min_profitable_size_usd("base", eth_price_usd=5000.0)
        assert expensive > cheap
