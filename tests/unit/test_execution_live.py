# PATH: tests/unit/test_execution_live.py
"""
R28.15 tests for live execution path.

Tests:
- PreTradeSimulator: DRY_RUN simulate, slippage, freshness, gas
- PreTradeSimulator: classify_revert
- DexDexExecutor: blocker checks, sync execute, ExecutionResult
- DexDexExecutor: execute_live (async, mocked provider)
"""

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from execution.simulator import (
    PreTradeSimulator,
    SimulatorConfig,
    SimulationBlocker,
    SimulationResult,
    classify_revert,
)
from execution.dex_dex_executor import (
    DexDexExecutor,
    ExecutorConfig,
    ExecutionBlocker,
    ExecutionResult,
    ExecutionMethod,
)
from execution.state_machine import TradeState


# --- Helper: fresh opportunity dict ---
def _make_opportunity(**overrides):
    opp = {
        "spread_id": "test_spread_001",
        "router_address": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
        "swap_calldata": "0xdb3e2198" + "0" * 64,
        "expected_out": "1000000",
        "gas_estimate": 200_000,
        "quote_timestamp_ms": int(time.time() * 1000),
        "simulation_passed": True,
        "expected_pnl_usd": "5.00",
        "token_out_price_usd": "1.0",
        "token_in_price_usd": "1.0",
        "token_out_decimals": 6,
        "token_in_decimals": 6,
        "paper_size_usd": "150",
        "eth_price_usd": "2500",
    }
    opp.update(overrides)
    return opp


# ============================================================
#  classify_revert
# ============================================================
class TestClassifyRevert:
    def test_execution_reverted(self):
        assert classify_revert("execution reverted") == "EXECUTION_REVERTED"

    def test_insufficient_liquidity(self):
        assert classify_revert("insufficient liquidity") == "INSUFFICIENT_LIQUIDITY"

    def test_price_slippage(self):
        assert classify_revert("too much price impact") == "PRICE_SLIPPAGE_REVERT"

    def test_deadline_expired(self):
        assert classify_revert("Transaction deadline has expired") == "DEADLINE_EXPIRED"

    def test_standard_error_selector(self):
        assert classify_revert("0x08c379a0abcdef") == "Error(string)"

    def test_panic_selector(self):
        assert classify_revert("0x4e487b71abcdef") == "Panic(uint256)"

    def test_empty_revert(self):
        assert classify_revert("0x") == "EMPTY_REVERT"

    def test_empty_string(self):
        assert classify_revert("") == "UNKNOWN_REVERT"

    def test_unknown(self):
        assert classify_revert("0xdeadbeef") == "UNKNOWN_REVERT"


# ============================================================
#  PreTradeSimulator.simulate (DRY_RUN, sync)
# ============================================================
class TestPreTradeSimulatorDryRun:
    def test_simulate_passes_fresh_opportunity(self):
        sim = PreTradeSimulator()
        opp = _make_opportunity(expected_out="1000", simulated_out="995")
        result = sim.simulate(opp)
        assert result.passed is True
        assert result.metadata["mode"] == "DRY_RUN"
        assert len(result.blockers) == 0

    def test_simulate_blocks_stale_quote(self):
        sim = PreTradeSimulator(SimulatorConfig(quote_freshness_ms=1000))
        opp = _make_opportunity(
            quote_timestamp_ms=int(time.time() * 1000) - 5000,
        )
        result = sim.simulate(opp)
        assert result.passed is False
        assert SimulationBlocker.QUOTE_STALE in result.blockers

    def test_simulate_blocks_high_gas(self):
        sim = PreTradeSimulator(SimulatorConfig(max_gas_estimate=100_000))
        opp = _make_opportunity(gas_estimate=200_000)
        result = sim.simulate(opp)
        assert result.passed is False
        assert SimulationBlocker.GAS_TOO_HIGH in result.blockers

    def test_simulate_blocks_high_slippage(self):
        sim = PreTradeSimulator(SimulatorConfig(max_slippage_bps=50))
        opp = _make_opportunity(expected_out="1000", simulated_out="900")
        result = sim.simulate(opp)
        assert result.passed is False
        assert SimulationBlocker.SLIPPAGE_EXCEEDED in result.blockers

    def test_slippage_computes_correct_bps(self):
        sim = PreTradeSimulator()
        # 1% slippage = 100 bps
        bps = sim._compute_slippage_bps(Decimal("1000"), Decimal("990"))
        assert bps == 100

    def test_zero_expected_returns_zero_slippage(self):
        sim = PreTradeSimulator()
        bps = sim._compute_slippage_bps(Decimal("0"), Decimal("100"))
        assert bps == 0

    def test_no_quote_ts_skips_freshness(self):
        """Opportunity without quote_timestamp_ms should skip freshness check."""
        sim = PreTradeSimulator()
        opp = _make_opportunity()
        del opp["quote_timestamp_ms"]
        result = sim.simulate(opp)
        assert result.passed is True

    def test_to_dict(self):
        sim = PreTradeSimulator()
        result = sim.simulate(_make_opportunity())
        d = result.to_dict()
        assert "passed" in d
        assert "slippage_bps" in d
        assert "mode" in d["metadata"]


# ============================================================
#  DexDexExecutor blocker checks
# ============================================================
class TestDexDexExecutorBlockers:
    def test_kill_switch_blocks(self):
        ex = DexDexExecutor(kill_switch_active=True)
        opp = _make_opportunity()
        result = ex.execute(opp)
        assert result.is_blocked
        assert ExecutionBlocker.KILL_SWITCH_ACTIVE in result.blockers

    def test_execution_disabled_blocks(self):
        ex = DexDexExecutor(
            config=ExecutorConfig(execution_enabled=False, smoke_mode=False),
            kill_switch_active=False,
        )
        opp = _make_opportunity()
        result = ex.execute(opp)
        assert result.is_blocked
        assert ExecutionBlocker.EXECUTION_DISABLED in result.blockers

    def test_smoke_mode_blocks(self):
        ex = DexDexExecutor(
            config=ExecutorConfig(smoke_mode=True, execution_enabled=True),
            kill_switch_active=False,
        )
        opp = _make_opportunity()
        result = ex.execute(opp)
        assert result.is_blocked
        assert ExecutionBlocker.SMOKE_MODE_NO_EXECUTION in result.blockers

    def test_simulation_required_blocks(self):
        ex = DexDexExecutor(
            config=ExecutorConfig(
                smoke_mode=False, execution_enabled=True, require_simulation=True,
            ),
            kill_switch_active=False,
        )
        opp = _make_opportunity(simulation_passed=False)
        result = ex.execute(opp)
        assert result.is_blocked
        assert ExecutionBlocker.SIMULATION_REQUIRED in result.blockers

    def test_no_blockers_when_fully_enabled(self):
        ex = DexDexExecutor(
            config=ExecutorConfig(
                smoke_mode=False, execution_enabled=True, require_simulation=False,
            ),
            kill_switch_active=False,
        )
        opp = _make_opportunity()
        result = ex.execute(opp)
        assert not result.is_blocked
        assert result.state == TradeState.PENDING

    def test_kill_switch_activate_kills_trades(self):
        ex = DexDexExecutor(
            config=ExecutorConfig(
                smoke_mode=False, execution_enabled=True, require_simulation=False,
            ),
            kill_switch_active=False,
        )
        opp = _make_opportunity()
        ex.execute(opp)  # Creates a trade
        ex.activate_kill_switch("test")
        assert ex.kill_switch_active is True

    def test_deactivate_kill_switch(self):
        ex = DexDexExecutor(kill_switch_active=True)
        ex.deactivate_kill_switch()
        assert ex.kill_switch_active is False


# ============================================================
#  DexDexExecutor.execute_live (async, mocked provider)
# ============================================================
class TestDexDexExecutorLive:
    def _make_provider(self, gas_price=10_000_000_000, nonce=5, receipt=None):
        provider = AsyncMock()
        provider.chain_id = 42161
        provider.get_gas_price = AsyncMock(return_value=(gas_price, 0))
        provider.get_transaction_count = AsyncMock(return_value=nonce)
        provider.get_transaction_receipt = AsyncMock(return_value=receipt)
        return provider

    def _make_receipt(self, status=1, gas_used=150_000, block_number=100):
        """Build a mock receipt dict with hex or int fields."""
        return {
            "status": hex(status),
            "gasUsed": hex(gas_used),
            "blockNumber": hex(block_number),
            "logs": [],
        }

    @pytest.mark.asyncio
    async def test_live_blocked_by_kill_switch(self):
        ex = DexDexExecutor(kill_switch_active=True)
        provider = self._make_provider()
        sign_and_send = AsyncMock()
        result = await ex.execute_live(
            _make_opportunity(), provider, "0xsigner", sign_and_send,
        )
        assert result.is_blocked
        assert ExecutionBlocker.KILL_SWITCH_ACTIVE in result.blockers
        sign_and_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_live_gas_too_high(self):
        ex = DexDexExecutor(
            config=ExecutorConfig(
                smoke_mode=False, execution_enabled=True,
                require_simulation=False, max_gas_price_gwei=5.0,
            ),
            kill_switch_active=False,
        )
        # 10 gwei > max 5 gwei
        provider = self._make_provider(gas_price=10_000_000_000)
        sign_and_send = AsyncMock()
        result = await ex.execute_live(
            _make_opportunity(), provider, "0xsigner", sign_and_send,
        )
        assert result.state == TradeState.SIM_FAILED
        assert ExecutionBlocker.GAS_PRICE_TOO_HIGH in result.blockers
        sign_and_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_live_successful_execution(self):
        receipt = self._make_receipt(status=1, gas_used=150_000, block_number=42)
        ex = DexDexExecutor(
            config=ExecutorConfig(
                smoke_mode=False, execution_enabled=True,
                require_simulation=False, max_gas_price_gwei=50.0,
                receipt_timeout_seconds=5, receipt_poll_interval_seconds=0.01,
            ),
            kill_switch_active=False,
        )
        provider = self._make_provider(gas_price=10_000_000_000, nonce=7, receipt=receipt)
        sign_and_send = AsyncMock(return_value="0xdeadbeef")
        result = await ex.execute_live(
            _make_opportunity(), provider, "0xsigner", sign_and_send,
        )
        assert result.state == TradeState.CONFIRMED
        assert result.is_success is True
        assert result.tx_hash == "0xdeadbeef"
        assert result.gas_used == 150_000
        assert result.block_number == 42
        assert result.receipt_status == 1
        assert result.execution_latency_ms is not None
        assert result.execution_latency_ms >= 0
        sign_and_send.assert_called_once()
        # Check tx_dict passed to sign_and_send
        tx_dict = sign_and_send.call_args[0][0]
        assert tx_dict["nonce"] == 7
        assert tx_dict["chainId"] == 42161

    @pytest.mark.asyncio
    async def test_live_reverted_tx(self):
        receipt = self._make_receipt(status=0, gas_used=50_000, block_number=43)
        ex = DexDexExecutor(
            config=ExecutorConfig(
                smoke_mode=False, execution_enabled=True,
                require_simulation=False, max_gas_price_gwei=50.0,
                receipt_timeout_seconds=5, receipt_poll_interval_seconds=0.01,
            ),
            kill_switch_active=False,
        )
        provider = self._make_provider(gas_price=5_000_000_000, nonce=1, receipt=receipt)
        sign_and_send = AsyncMock(return_value="0xaabb")
        result = await ex.execute_live(
            _make_opportunity(), provider, "0xsigner", sign_and_send,
        )
        assert result.state == TradeState.FAILED
        assert result.is_success is False
        assert result.tx_hash == "0xaabb"
        assert result.receipt_status == 0
        assert result.error_message == "TX_REVERTED"

    @pytest.mark.asyncio
    async def test_live_sign_failure(self):
        ex = DexDexExecutor(
            config=ExecutorConfig(
                smoke_mode=False, execution_enabled=True,
                require_simulation=False, max_gas_price_gwei=50.0,
            ),
            kill_switch_active=False,
        )
        provider = self._make_provider(gas_price=5_000_000_000, nonce=1)
        sign_and_send = AsyncMock(side_effect=RuntimeError("key not found"))
        result = await ex.execute_live(
            _make_opportunity(), provider, "0xsigner", sign_and_send,
        )
        assert result.state == TradeState.FAILED
        assert "key not found" in result.error_message

    @pytest.mark.asyncio
    async def test_live_receipt_timeout(self):
        ex = DexDexExecutor(
            config=ExecutorConfig(
                smoke_mode=False, execution_enabled=True,
                require_simulation=False, max_gas_price_gwei=50.0,
                receipt_timeout_seconds=0,  # immediate timeout
                receipt_poll_interval_seconds=0.01,
            ),
            kill_switch_active=False,
        )
        provider = self._make_provider(gas_price=5_000_000_000, nonce=1, receipt=None)
        sign_and_send = AsyncMock(return_value="0x111")
        result = await ex.execute_live(
            _make_opportunity(), provider, "0xsigner", sign_and_send,
        )
        assert result.state == TradeState.FAILED
        assert result.tx_hash == "0x111"
        assert "timeout" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_live_nonce_failure(self):
        ex = DexDexExecutor(
            config=ExecutorConfig(
                smoke_mode=False, execution_enabled=True,
                require_simulation=False, max_gas_price_gwei=50.0,
            ),
            kill_switch_active=False,
        )
        provider = self._make_provider(gas_price=5_000_000_000)
        provider.get_transaction_count = AsyncMock(side_effect=RuntimeError("RPC down"))
        sign_and_send = AsyncMock()
        result = await ex.execute_live(
            _make_opportunity(), provider, "0xsigner", sign_and_send,
        )
        assert result.state == TradeState.KILLED
        assert "RPC down" in result.error_message
        sign_and_send.assert_not_called()


# ============================================================
#  ExecutionResult contract
# ============================================================
class TestExecutionResult:
    def test_to_dict_complete(self):
        r = ExecutionResult(
            trade_id="t1",
            state=TradeState.CONFIRMED,
            tx_hash="0xabc",
            gas_used=100_000,
            realized_pnl=Decimal("1.50"),
            realized_pnl_bps=100,
        )
        d = r.to_dict()
        assert d["trade_id"] == "t1"
        assert d["state"] == "CONFIRMED"
        assert d["is_success"] is True
        assert d["is_blocked"] is False
        assert d["realized_pnl"] == "1.50"
        assert d["realized_pnl_bps"] == 100
        assert d["tx_hash"] == "0xabc"

    def test_blocked_result(self):
        r = ExecutionResult(
            trade_id="t2",
            state=TradeState.PENDING,
            blockers=["KILL_SWITCH_ACTIVE"],
        )
        assert r.is_blocked is True
        assert r.is_success is False

    def test_none_pnl_serializes_as_none(self):
        r = ExecutionResult(trade_id="t3", state=TradeState.FAILED)
        d = r.to_dict()
        assert d["realized_pnl"] is None
        assert d["realized_pnl_bps"] is None

    def test_get_trade_status(self):
        ex = DexDexExecutor(
            config=ExecutorConfig(
                smoke_mode=False, execution_enabled=True, require_simulation=False,
            ),
            kill_switch_active=False,
        )
        opp = _make_opportunity()
        ex.execute(opp)
        status = ex.get_trade_status(opp["spread_id"])
        assert status is not None
        assert "state" in status


# ============================================================
#  Swap fill parsing (static method)
# ============================================================
class TestSwapFillParsing:
    def test_parse_swap_fills_from_v3_event(self):
        """Test parsing Uniswap V3 Swap event log."""
        # amount0 = 1000000 (positive), amount1 = -2000000000000000000 (negative)
        amount0 = 1000000
        amount1 = -2000000000000000000
        # Encode as int256 (two's complement for negative)
        a0_hex = format(amount0, "064x")
        a1_hex = format(amount1 & (2**256 - 1), "064x")
        # sqrtPriceX96, liquidity, tick fill remaining data
        extra = "0" * 192  # 3 more uint values
        data = "0x" + a0_hex + a1_hex + extra

        receipt = {
            "logs": [{
                "topics": ["0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"],
                "data": data,
            }],
        }
        filled_in, filled_out = DexDexExecutor._parse_swap_fills(receipt)
        assert filled_in == str(amount0)
        assert filled_out == str(amount1)

    def test_parse_swap_fills_no_logs(self):
        receipt = {"logs": []}
        filled_in, filled_out = DexDexExecutor._parse_swap_fills(receipt)
        assert filled_in is None
        assert filled_out is None

    def test_parse_swap_fills_no_swap_event(self):
        receipt = {
            "logs": [{
                "topics": ["0x0000000000000000000000000000000000000000000000000000000000000001"],
                "data": "0x" + "0" * 128,
            }],
        }
        filled_in, filled_out = DexDexExecutor._parse_swap_fills(receipt)
        assert filled_in is None
        assert filled_out is None
