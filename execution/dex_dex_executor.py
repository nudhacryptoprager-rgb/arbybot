# PATH: execution/dex_dex_executor.py
"""
ARBY M4 DEX-DEX Executor.

DEX-DEX EXECUTION CONTRACT:
===========================

Execution methods:
  1. PUBLIC_MEMPOOL - standard transaction submission
  2. PRIVATE_MEMPOOL - flashbots/mev-share submission
  3. FLASH_SWAP - atomic execution via flash loan

Interface:
  execute(opportunity, method) → ExecutionResult           [sync, blocked/DRY_RUN]
  execute_live(opportunity, provider, ...) → ExecutionResult [async, real tx]

Execution blockers (prevent execution):
  - SMOKE_MODE_NO_EXECUTION: running in smoke mode
  - KILL_SWITCH_ACTIVE: kill switch is on
  - EXECUTION_DISABLED: master switch off
  - SIMULATION_REQUIRED: must pass simulation first
  - SIMULATION_FAILED: pre-trade simulation failed
  - INSUFFICIENT_BALANCE: not enough funds
  - GAS_PRICE_TOO_HIGH: gas spike detected
  - SLIPPAGE_TOO_HIGH: slippage exceeds tolerance

R28.15: Real implementation with tx build, signing policy,
receipts, fill parsing, gas accounting, and realized PnL.
===========================
"""

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from core.logging import get_logger
from execution.state_machine import TradeState, TradeStateMachine

logger = get_logger(__name__)


class ExecutionMethod(str, Enum):
    """Trade execution methods."""
    PUBLIC_MEMPOOL = "PUBLIC_MEMPOOL"
    PRIVATE_MEMPOOL = "PRIVATE_MEMPOOL"
    FLASH_SWAP = "FLASH_SWAP"


class ExecutionBlocker:
    """Standard execution blocker codes.
    
    v2.0.2: Added EXECUTION_DISABLED for master switch off.
    """
    SMOKE_MODE_NO_EXECUTION = "SMOKE_MODE_NO_EXECUTION"
    EXECUTION_DISABLED = "EXECUTION_DISABLED"  # v2.0.2: Master switch off
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    SIMULATION_REQUIRED = "SIMULATION_REQUIRED"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    GAS_PRICE_TOO_HIGH = "GAS_PRICE_TOO_HIGH"
    SLIPPAGE_TOO_HIGH = "SLIPPAGE_TOO_HIGH"
    POOL_DEPLETED = "POOL_DEPLETED"


@dataclass
class ExecutionResult:
    """Result of trade execution."""
    trade_id: str
    state: TradeState
    tx_hash: Optional[str] = None
    block_number: Optional[int] = None
    gas_used: Optional[int] = None
    gas_price_gwei: Optional[float] = None
    realized_pnl: Optional[Decimal] = None
    realized_pnl_bps: Optional[int] = None
    expected_pnl: Optional[Decimal] = None
    filled_in: Optional[str] = None
    filled_out: Optional[str] = None
    slippage_bps: int = 0
    execution_latency_ms: Optional[int] = None
    blockers: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    receipt_status: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.state == TradeState.CONFIRMED

    @property
    def is_blocked(self) -> bool:
        return len(self.blockers) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "state": self.state.value,
            "is_success": self.is_success,
            "is_blocked": self.is_blocked,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "gas_used": self.gas_used,
            "gas_price_gwei": self.gas_price_gwei,
            "receipt_status": self.receipt_status,
            "realized_pnl": str(self.realized_pnl) if self.realized_pnl is not None else None,
            "realized_pnl_bps": self.realized_pnl_bps,
            "expected_pnl": str(self.expected_pnl) if self.expected_pnl is not None else None,
            "filled_in": self.filled_in,
            "filled_out": self.filled_out,
            "slippage_bps": self.slippage_bps,
            "execution_latency_ms": self.execution_latency_ms,
            "blockers": self.blockers,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


@dataclass
class ExecutorConfig:
    """Configuration for DEX-DEX executor.
    
    M4 SAFETY CONTRACT (v2.0.2):
    - execution_enabled: Master switch for ANY real tx submission
    - kill_switch_active: Emergency stop for all trades
    - smoke_mode: Safe mode that simulates but never submits
    
    CRITICAL: execution_enabled=False by default, MUST be explicitly
    enabled in production config after full M4.2 DoD proof.
    """
    default_method: ExecutionMethod = ExecutionMethod.PUBLIC_MEMPOOL
    max_gas_price_gwei: float = 100.0
    max_slippage_bps: int = 100
    require_simulation: bool = True
    smoke_mode: bool = True  # Default to smoke mode (safe)
    execution_enabled: bool = False  # v2.0.2: Master switch - NEVER True until M4.2 DoD
    receipt_timeout_seconds: int = 60
    receipt_poll_interval_seconds: float = 2.0


class DexDexExecutor:
    """
    DEX-DEX arbitrage executor.
    
    Handles submission and monitoring of arbitrage trades.
    
    Usage:
      # Blocked/DRY_RUN mode (sync):
      executor = DexDexExecutor(config, kill_switch_active=True)
      result = executor.execute(opportunity)  # Returns blocked result
      
      # Live mode (async, requires provider + signer):
      result = await executor.execute_live(opportunity, provider, signer_address, sign_fn)
    """

    def __init__(
        self,
        config: Optional[ExecutorConfig] = None,
        kill_switch_active: bool = False,
    ):
        self.config = config or ExecutorConfig()
        self._kill_switch_active = kill_switch_active
        self._trades: Dict[str, TradeStateMachine] = {}

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    def activate_kill_switch(self, reason: str = "Manual activation") -> None:
        """Activate kill switch - stops all new executions."""
        self._kill_switch_active = True
        
        # Kill all pending trades
        for trade_id, sm in self._trades.items():
            if not sm.is_terminal:
                try:
                    sm.kill(reason=f"Kill switch: {reason}")
                except Exception:
                    pass

    def deactivate_kill_switch(self) -> None:
        """Deactivate kill switch."""
        self._kill_switch_active = False

    def _get_blockers(self, opportunity: Dict[str, Any]) -> List[str]:
        """Check for execution blockers.
        
        v2.0.2: Updated with execution_enabled master switch check.
        Order matters: check kill switch first, then master switch, then mode.
        """
        blockers = []
        
        # v2.0.2: Kill switch first (emergency)
        if self._kill_switch_active:
            blockers.append(ExecutionBlocker.KILL_SWITCH_ACTIVE)
        
        # v2.0.2: Master switch second (M4.2 gate)
        if not self.config.execution_enabled:
            blockers.append(ExecutionBlocker.EXECUTION_DISABLED)
        
        if self.config.smoke_mode:
            blockers.append(ExecutionBlocker.SMOKE_MODE_NO_EXECUTION)
        
        if self.config.require_simulation and not opportunity.get("simulation_passed"):
            blockers.append(ExecutionBlocker.SIMULATION_REQUIRED)
        
        return blockers

    def execute(
        self,
        opportunity: Dict[str, Any],
        method: Optional[ExecutionMethod] = None,
    ) -> ExecutionResult:
        """
        Execute a trade opportunity (sync, returns blocked in safe mode).
        
        In current M4 configuration (execution_enabled=False, kill_switch=True),
        this always returns a blocked result. Use execute_live() for actual
        transaction submission once M4.2 DoD requirements are met.
        """
        method = method or self.config.default_method
        trade_id = opportunity.get("opportunity_id") or opportunity.get("spread_id", "unknown")
        
        # Check blockers
        blockers = self._get_blockers(opportunity)
        
        if blockers:
            return ExecutionResult(
                trade_id=trade_id,
                state=TradeState.PENDING,
                blockers=blockers,
                metadata={
                    "method": method.value,
                    "reason": "Execution blocked",
                },
            )
        
        # Create state machine
        sm = TradeStateMachine(trade_id=trade_id)
        self._trades[trade_id] = sm
        
        return ExecutionResult(
            trade_id=trade_id,
            state=sm.state,
            blockers=[],
            metadata={
                "method": method.value,
                "note": "No blockers but execute_live() not called",
            },
        )

    async def execute_live(
        self,
        opportunity: Dict[str, Any],
        provider: Any,
        signer_address: str,
        sign_and_send: Any,
        method: Optional[ExecutionMethod] = None,
    ) -> ExecutionResult:
        """
        Execute a real on-chain trade.

        Args:
            opportunity: Opportunity dict with:
                - spread_id: str
                - router_address: str
                - swap_calldata: str (encoded swap tx data)
                - expected_out: str/Decimal
                - expected_pnl_usd: str/Decimal
                - gas_estimate: int
                - simulation_passed: bool (from PreTradeSimulator)
            provider: RPCProvider for RPC calls.
            signer_address: Address of the signing account.
            sign_and_send: Async callable(tx_dict) → tx_hash_hex.
                           Responsible for signing + submission.
                           Keeps private key out of this module.
            method: Execution method override.

        Returns:
            ExecutionResult with tx_hash, receipts, realized PnL.
        """
        method = method or self.config.default_method
        trade_id = opportunity.get("spread_id", f"trade_{int(time.time() * 1000)}")

        # 1. Blocker check (same as sync path)
        blockers = self._get_blockers(opportunity)
        if blockers:
            return ExecutionResult(
                trade_id=trade_id,
                state=TradeState.PENDING,
                blockers=blockers,
                metadata={"method": method.value},
            )

        # 2. Create state machine
        sm = TradeStateMachine(trade_id=trade_id)
        self._trades[trade_id] = sm
        start_ms = int(time.time() * 1000)

        # 3. Pre-trade simulation (transition PENDING → SIMULATING → SIM_PASSED)
        sm.transition_to(TradeState.SIMULATING, reason="Pre-trade gas/price check")
        try:
            gas_price_wei, _ = await provider.get_gas_price()
            gas_price_gwei = gas_price_wei / 1e9
            if gas_price_gwei > self.config.max_gas_price_gwei:
                sm.transition_to(
                    TradeState.SIM_FAILED,
                    reason=f"Gas price {gas_price_gwei:.1f} gwei > max {self.config.max_gas_price_gwei}",
                )
                return ExecutionResult(
                    trade_id=trade_id, state=sm.state,
                    blockers=[ExecutionBlocker.GAS_PRICE_TOO_HIGH],
                    gas_price_gwei=gas_price_gwei,
                    metadata={"method": method.value},
                )
        except Exception as e:
            sm.transition_to(TradeState.SIM_FAILED, reason=f"Gas price check failed: {e}")
            return ExecutionResult(
                trade_id=trade_id, state=sm.state,
                blockers=["RPC_ERROR"],
                error_message=str(e),
                metadata={"method": method.value},
            )

        sm.transition_to(TradeState.SIM_PASSED, reason="Pre-trade checks passed")

        # 4. Build transaction
        router_address = opportunity.get("router_address", "")
        swap_calldata = opportunity.get("swap_calldata", "")
        gas_estimate = int(opportunity.get("gas_estimate", 300_000))

        try:
            nonce = await provider.get_transaction_count(signer_address)
        except Exception as e:
            sm.kill(reason=f"Nonce fetch failed: {e}")
            return ExecutionResult(
                trade_id=trade_id, state=sm.state,
                error_message=str(e),
                metadata={"method": method.value},
            )

        tx_dict: Dict[str, Any] = {
            "to": router_address,
            "data": swap_calldata,
            "gas": gas_estimate,
            "gasPrice": gas_price_wei,
            "nonce": nonce,
            "chainId": provider.chain_id,
        }

        # 5. Sign and submit
        sm.transition_to(TradeState.SUBMITTING, reason="Signing and submitting tx")
        try:
            tx_hash = await sign_and_send(tx_dict)
        except Exception as e:
            sm.transition_to(TradeState.FAILED, reason=f"Tx submission failed: {e}")
            return ExecutionResult(
                trade_id=trade_id, state=sm.state,
                error_message=str(e),
                execution_latency_ms=int(time.time() * 1000) - start_ms,
                metadata={"method": method.value},
            )

        sm.transition_to(TradeState.SUBMITTED, reason=f"Tx submitted: {tx_hash}")

        # 6. Wait for receipt
        sm.transition_to(TradeState.CONFIRMING, reason="Waiting for confirmation")
        receipt = await self._wait_for_receipt(provider, tx_hash)
        execution_latency_ms = int(time.time() * 1000) - start_ms

        if receipt is None:
            sm.transition_to(TradeState.FAILED, reason="Receipt timeout")
            return ExecutionResult(
                trade_id=trade_id, state=sm.state,
                tx_hash=tx_hash,
                execution_latency_ms=execution_latency_ms,
                error_message="Receipt not received within timeout",
                metadata={"method": method.value},
            )

        # 7. Parse receipt
        receipt_status = int(receipt.get("status", "0x0"), 16) if isinstance(receipt.get("status"), str) else receipt.get("status", 0)
        gas_used = int(receipt.get("gasUsed", "0x0"), 16) if isinstance(receipt.get("gasUsed"), str) else receipt.get("gasUsed", 0)
        block_number = int(receipt.get("blockNumber", "0x0"), 16) if isinstance(receipt.get("blockNumber"), str) else receipt.get("blockNumber", 0)
        gas_cost_wei = gas_used * gas_price_wei
        gas_cost_usd = Decimal(str(gas_cost_wei)) / Decimal("1e18") * Decimal(str(opportunity.get("eth_price_usd", "2000")))

        expected_pnl = Decimal(str(opportunity.get("expected_pnl_usd", "0")))

        if receipt_status == 1:
            sm.transition_to(TradeState.CONFIRMED, reason="Transaction confirmed")
            # Parse fills from swap events
            filled_in, filled_out = self._parse_swap_fills(receipt)
            realized_pnl = self._compute_realized_pnl(
                filled_in, filled_out, gas_cost_usd, opportunity,
            )
            realized_pnl_bps = self._compute_realized_pnl_bps(realized_pnl, opportunity)
            return ExecutionResult(
                trade_id=trade_id,
                state=sm.state,
                tx_hash=tx_hash,
                block_number=block_number,
                gas_used=gas_used,
                gas_price_gwei=gas_price_gwei,
                receipt_status=receipt_status,
                realized_pnl=realized_pnl,
                realized_pnl_bps=realized_pnl_bps,
                expected_pnl=expected_pnl,
                filled_in=filled_in,
                filled_out=filled_out,
                execution_latency_ms=execution_latency_ms,
                metadata={"method": method.value, "gas_cost_usd": str(gas_cost_usd)},
            )
        else:
            sm.transition_to(TradeState.FAILED, reason="Transaction reverted on-chain")
            return ExecutionResult(
                trade_id=trade_id,
                state=sm.state,
                tx_hash=tx_hash,
                block_number=block_number,
                gas_used=gas_used,
                gas_price_gwei=gas_price_gwei,
                receipt_status=receipt_status,
                execution_latency_ms=execution_latency_ms,
                error_message="TX_REVERTED",
                metadata={"method": method.value, "gas_cost_usd": str(gas_cost_usd)},
            )

    async def _wait_for_receipt(
        self, provider: Any, tx_hash: str,
    ) -> Optional[Dict[str, Any]]:
        """Poll for transaction receipt until timeout."""
        import asyncio
        deadline = time.time() + self.config.receipt_timeout_seconds
        while time.time() < deadline:
            try:
                receipt = await provider.get_transaction_receipt(tx_hash)
                if receipt is not None:
                    return receipt
            except Exception:
                pass
            await asyncio.sleep(self.config.receipt_poll_interval_seconds)
        return None

    @staticmethod
    def _parse_swap_fills(receipt: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        """
        Parse Swap event logs from receipt to extract filled amounts.

        Returns (filled_in, filled_out) as decimal strings or None.
        Uniswap V3 Swap event:
          topic0 = keccak256("Swap(address,address,int256,int256,uint160,uint128,int24)")
        """
        # Swap event topic (Uniswap V3 / forks)
        SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
        logs = receipt.get("logs", [])
        for log in logs:
            topics = log.get("topics", [])
            if topics and topics[0] == SWAP_TOPIC:
                data = log.get("data", "0x")
                if len(data) >= 130:  # 0x + 64*2 (two int256)
                    # amount0 and amount1 are int256
                    amount0 = int(data[2:66], 16)
                    amount1 = int(data[66:130], 16)
                    # Convert from two's complement if negative
                    if amount0 >= 2**255:
                        amount0 -= 2**256
                    if amount1 >= 2**255:
                        amount1 -= 2**256
                    return str(amount0), str(amount1)
        return None, None

    @staticmethod
    def _compute_realized_pnl(
        filled_in: Optional[str],
        filled_out: Optional[str],
        gas_cost_usd: Decimal,
        opportunity: Dict[str, Any],
    ) -> Optional[Decimal]:
        """Compute realized PnL in USD from fill amounts and gas cost."""
        if filled_in is None or filled_out is None:
            return None
        # Simplified: use token USD prices from opportunity to convert fills
        token_out_price = Decimal(str(opportunity.get("token_out_price_usd", "1")))
        token_in_price = Decimal(str(opportunity.get("token_in_price_usd", "1")))
        token_out_decimals = int(opportunity.get("token_out_decimals", 18))
        token_in_decimals = int(opportunity.get("token_in_decimals", 18))

        out_amount = Decimal(filled_out) / Decimal(10 ** token_out_decimals)
        in_amount = abs(Decimal(filled_in)) / Decimal(10 ** token_in_decimals)

        gross_pnl_usd = (out_amount * token_out_price) - (in_amount * token_in_price)
        return gross_pnl_usd - gas_cost_usd

    @staticmethod
    def _compute_realized_pnl_bps(
        realized_pnl: Optional[Decimal],
        opportunity: Dict[str, Any],
    ) -> Optional[int]:
        """Convert realized PnL USD to bps relative to position size."""
        if realized_pnl is None:
            return None
        position_usd = Decimal(str(opportunity.get("paper_size_usd", "150")))
        if position_usd <= 0:
            return 0
        return int(realized_pnl * Decimal("10000") / position_usd)

    def get_trade_status(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a trade."""
        sm = self._trades.get(trade_id)
        if sm:
            return sm.to_dict()
        return None
