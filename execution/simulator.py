# PATH: execution/simulator.py
"""
ARBY M4 Pre-Trade Simulation Gate.

PRE-TRADE SIMULATION CONTRACT:
==============================

Purpose:
  Before executing a trade, simulate it to verify:
  1. Quotes are still valid (freshness check)
  2. Expected output is within acceptable slippage (eth_call)
  3. Gas estimate is reasonable (estimateGas / adapter gas)
  4. No obvious revert reasons (revert classification)
  5. Route is viable (pool liquidity check)

Interface:
  simulate(opportunity) → SimulationResult        [sync, DRY_RUN]
  simulate_rpc(opportunity, provider) → SimResult  [async, real eth_call]

Blocking criteria:
  - QUOTE_STALE: quote older than freshness threshold
  - SLIPPAGE_EXCEEDED: simulated output < min acceptable
  - GAS_TOO_HIGH: gas estimate exceeds max
  - REVERT_PREDICTED: simulation detected revert
  - POOL_DEPLETED: insufficient liquidity
  - RPC_ERROR: provider call failed

==============================

R28.15: Real implementation with eth_call simulation, slippage bounds,
revert classification, and route viability checks.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from core.time import now_ms
from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SimulationResult:
    """Result of pre-trade simulation."""
    passed: bool
    expected_out: Decimal = Decimal("0")
    simulated_out: Decimal = Decimal("0")
    slippage_bps: int = 0
    gas_estimate: int = 0
    blockers: List[str] = field(default_factory=list)
    revert_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "expected_out": str(self.expected_out),
            "simulated_out": str(self.simulated_out),
            "slippage_bps": self.slippage_bps,
            "gas_estimate": self.gas_estimate,
            "blockers": self.blockers,
            "revert_reason": self.revert_reason,
            "metadata": self.metadata,
        }


class SimulationBlocker:
    """Standard simulation blocker codes."""
    QUOTE_STALE = "QUOTE_STALE"
    SLIPPAGE_EXCEEDED = "SLIPPAGE_EXCEEDED"
    GAS_TOO_HIGH = "GAS_TOO_HIGH"
    REVERT_PREDICTED = "REVERT_PREDICTED"
    POOL_DEPLETED = "POOL_DEPLETED"
    RPC_ERROR = "RPC_ERROR"


# Known revert signatures for classification
REVERT_SIGNATURES: Dict[str, str] = {
    "0x08c379a0": "Error(string)",           # Standard revert
    "0x4e487b71": "Panic(uint256)",           # Solidity panic
    "0x": "EMPTY_REVERT",                     # Empty revert data
}


def classify_revert(revert_data: str) -> str:
    """Classify a revert reason from RPC error or return data."""
    if not revert_data:
        return "UNKNOWN_REVERT"
    lower = revert_data.lower()
    if "execution reverted" in lower:
        return "EXECUTION_REVERTED"
    if "insufficient" in lower and "liquidity" in lower:
        return "INSUFFICIENT_LIQUIDITY"
    if "spl" in lower or "price" in lower:
        return "PRICE_SLIPPAGE_REVERT"
    if "expired" in lower or "deadline" in lower:
        return "DEADLINE_EXPIRED"
    # Check exact empty revert
    if lower == "0x":
        return "EMPTY_REVERT"
    # Check known selectors (first 4 bytes = 10 chars including 0x)
    if len(lower) >= 10:
        selector = lower[:10]
        for sig, name in REVERT_SIGNATURES.items():
            if sig != "0x" and selector == sig:
                return name
    return "UNKNOWN_REVERT"


@dataclass
class SimulatorConfig:
    """Configuration for pre-trade simulator."""
    max_slippage_bps: int = 100
    max_gas_estimate: int = 500_000
    quote_freshness_ms: int = 3000


class PreTradeSimulator:
    """
    Pre-trade simulation gate.

    Simulates trades before execution to catch issues early.

    Usage:
      # DRY_RUN mode (sync, no RPC):
      sim = PreTradeSimulator()
      result = sim.simulate(opportunity)

      # REAL mode (async, needs RPCProvider):
      result = await sim.simulate_rpc(opportunity, provider)
    """

    def __init__(self, config: Optional[SimulatorConfig] = None):
        self.config = config or SimulatorConfig()

    def _check_quote_freshness(self, opportunity: Dict[str, Any]) -> Optional[str]:
        """Check if the quote is still fresh enough to trade on."""
        quote_ts = opportunity.get("quote_timestamp_ms")
        if quote_ts is None:
            return None  # No timestamp → skip check (backwards compat)
        age_ms = now_ms() - int(quote_ts)
        if age_ms > self.config.quote_freshness_ms:
            return f"Quote is {age_ms}ms old, max allowed {self.config.quote_freshness_ms}ms"
        if age_ms < 0:
            return f"Quote timestamp is in the future by {-age_ms}ms"
        return None

    def _compute_slippage_bps(
        self, expected: Decimal, simulated: Decimal
    ) -> int:
        """Compute slippage in bps: (expected - simulated) / expected * 10000."""
        if expected <= 0:
            return 0
        diff = expected - simulated
        return int(diff * 10000 / expected)

    def simulate(self, opportunity: Dict[str, Any]) -> SimulationResult:
        """
        Simulate a trade opportunity (DRY_RUN mode — no RPC).

        Checks:
          1. Quote freshness
          2. Gas estimate bounds (from quote metadata)
          3. Slippage bounds (if both expected/simulated_out in opportunity)

        Returns:
            SimulationResult with pass/fail and details.
        """
        blockers: List[str] = []
        revert_reason: Optional[str] = None

        # 1. Quote freshness check
        freshness_err = self._check_quote_freshness(opportunity)
        if freshness_err:
            blockers.append(SimulationBlocker.QUOTE_STALE)
            return SimulationResult(
                passed=False,
                blockers=blockers,
                revert_reason=freshness_err,
                metadata={"mode": "DRY_RUN"},
            )

        # 2. Extract expected output
        expected_out = Decimal(str(opportunity.get("expected_out", "0")))

        # 3. Gas estimate check (from quote metadata)
        gas_est = int(opportunity.get("gas_estimate", 0))
        if gas_est > self.config.max_gas_estimate:
            blockers.append(SimulationBlocker.GAS_TOO_HIGH)

        # 4. Slippage check (if simulated_out already available from adapter)
        simulated_out = Decimal(str(opportunity.get("simulated_out", "0")))
        slippage_bps = 0
        if expected_out > 0 and simulated_out > 0:
            slippage_bps = self._compute_slippage_bps(expected_out, simulated_out)
            if slippage_bps > self.config.max_slippage_bps:
                blockers.append(SimulationBlocker.SLIPPAGE_EXCEEDED)

        passed = len(blockers) == 0
        return SimulationResult(
            passed=passed,
            expected_out=expected_out,
            simulated_out=simulated_out,
            slippage_bps=slippage_bps,
            gas_estimate=gas_est,
            blockers=blockers,
            revert_reason=revert_reason,
            metadata={"mode": "DRY_RUN"},
        )

    async def simulate_rpc(
        self,
        opportunity: Dict[str, Any],
        provider: Any,
    ) -> SimulationResult:
        """
        Simulate a trade using real RPC eth_call.

        This performs an actual on-chain simulation by calling the router
        contract via eth_call to verify the swap would succeed.

        Args:
            opportunity: Opportunity dict with:
                - router_address: str (swap router)
                - swap_calldata: str (encoded swap tx data)
                - expected_out: str/Decimal (expected output amount)
                - gas_estimate: int (from adapter)
                - quote_timestamp_ms: int (when quote was fetched)
            provider: RPCProvider instance for eth_call

        Returns:
            SimulationResult with real simulation data.
        """
        blockers: List[str] = []
        revert_reason: Optional[str] = None

        # 1. Quote freshness check
        freshness_err = self._check_quote_freshness(opportunity)
        if freshness_err:
            blockers.append(SimulationBlocker.QUOTE_STALE)
            return SimulationResult(
                passed=False,
                blockers=blockers,
                revert_reason=freshness_err,
                metadata={"mode": "SIMULATE_RPC"},
            )

        expected_out = Decimal(str(opportunity.get("expected_out", "0")))
        router_address = opportunity.get("router_address", "")
        swap_calldata = opportunity.get("swap_calldata", "")

        if not router_address or not swap_calldata:
            return SimulationResult(
                passed=False,
                blockers=[SimulationBlocker.RPC_ERROR],
                revert_reason="Missing router_address or swap_calldata",
                metadata={"mode": "SIMULATE_RPC"},
            )

        # 2. Call eth_call to simulate swap
        simulated_out = Decimal("0")
        gas_estimate = int(opportunity.get("gas_estimate", 0))
        try:
            response = await provider.eth_call(
                to=router_address,
                data=swap_calldata,
                block="latest",
            )

            # Decode output — for exactInputSingle the return is (uint256 amountOut)
            if response.result and len(response.result) >= 66:
                raw_amount = int(response.result[:66], 16)
                simulated_out = Decimal(str(raw_amount))
            else:
                blockers.append(SimulationBlocker.REVERT_PREDICTED)
                revert_reason = classify_revert(response.result or "")

        except Exception as e:
            err_str = str(e)
            revert_reason = classify_revert(err_str)
            logger.warning(
                "Pre-trade simulation eth_call failed",
                extra={"context": {
                    "router": router_address,
                    "error": err_str,
                    "revert_class": revert_reason,
                }},
            )
            blockers.append(SimulationBlocker.REVERT_PREDICTED)
            return SimulationResult(
                passed=False,
                expected_out=expected_out,
                blockers=blockers,
                revert_reason=revert_reason,
                metadata={"mode": "SIMULATE_RPC"},
            )

        # 3. Slippage check
        slippage_bps = self._compute_slippage_bps(expected_out, simulated_out)
        if expected_out > 0 and slippage_bps > self.config.max_slippage_bps:
            blockers.append(SimulationBlocker.SLIPPAGE_EXCEEDED)

        # 4. Gas check
        if gas_estimate > self.config.max_gas_estimate:
            blockers.append(SimulationBlocker.GAS_TOO_HIGH)

        # 5. Pool depletion check (simulated output is 0 or negligible)
        if expected_out > 0 and simulated_out == 0:
            blockers.append(SimulationBlocker.POOL_DEPLETED)

        passed = len(blockers) == 0
        return SimulationResult(
            passed=passed,
            expected_out=expected_out,
            simulated_out=simulated_out,
            slippage_bps=slippage_bps,
            gas_estimate=gas_estimate,
            blockers=blockers,
            revert_reason=revert_reason,
            metadata={"mode": "SIMULATE_RPC"},
        )

    async def batch_simulate_rpc(
        self,
        opportunities: List[Dict[str, Any]],
        provider: Any,
    ) -> List[SimulationResult]:
        """Simulate multiple opportunities via RPC (sequential)."""
        results = []
        for opp in opportunities:
            result = await self.simulate_rpc(opp, provider)
            results.append(result)
        return results
