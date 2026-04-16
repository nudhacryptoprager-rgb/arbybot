"""
Simulation Backend Router — M7 execution pre-flight.

E1.12.1: Tenderly fork scaffolding.
E1.12.4A: Backend abstraction. Supports ARBY_SIM_BACKEND=tenderly|anvil.

The simulation gate sits between profit_guard_passed and submit_ready
in the execution funnel:
    scored → positive → route_viable → profit_guard_passed → sim_passed → submit_ready

Usage:
    from m7.orderflow.simulation import is_simulation_configured, simulate_swap

    if is_simulation_configured():
        result = simulate_swap(chain="base", tx_params={...})
        if result.success:
            # proceed to submit

Backend selection:
    ARBY_SIM_BACKEND=tenderly  (default, requires TENDERLY_* env vars)
    ARBY_SIM_BACKEND=anvil     (requires ARBY_ANVIL_RPC_URL or localhost:8545)
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("m7.orderflow.simulation")


# ---------------------------------------------------------------------------
# Backend constants
# ---------------------------------------------------------------------------
BACKEND_TENDERLY = "tenderly"
BACKEND_ANVIL = "anvil"
BACKEND_RPC_FORK = "rpc_fork"
_VALID_BACKENDS = {BACKEND_TENDERLY, BACKEND_ANVIL, BACKEND_RPC_FORK}


@dataclass
class SimulationResult:
    """Result of a fork simulation (backend-agnostic)."""
    success: bool
    gas_used: int = 0
    output_amount_wei: int = 0
    revert_reason: Optional[str] = None
    simulation_id: Optional[str] = None
    error: Optional[str] = None
    backend: Optional[str] = None
    # E1.27/D1: Raw wei values for offline profit analysis.
    # NOTE: Do NOT compute profit_bps from (output - input) unless token_in
    # and token_out have identical decimals. Single-leg swap between different
    # tokens (e.g. WETH→USDC) has no meaningful bps. Use round-trip sim or
    # compare with scored expected_output_wei instead.
    input_amount_wei: int = 0
    # E2: Round-trip sim fields (buy + sell leg). Because both legs compare
    # the SAME token (token_in → token_out → token_in), bps is semantically
    # valid. Note: sell leg uses UNMODIFIED pool state (eth_call is stateless
    # between sequential calls), so this is an upper-bound estimate that
    # ignores price impact from the buy leg.
    roundtrip_attempted: bool = False
    roundtrip_success: bool = False
    roundtrip_final_wei: int = 0           # token_in amount after both legs
    roundtrip_profit_wei: int = 0          # final - initial input
    roundtrip_profit_bps: float = 0.0      # 10000 * profit / input
    roundtrip_sell_gas_used: int = 0
    roundtrip_sell_revert_reason: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.success and self.revert_reason is None


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

def get_simulation_backend() -> str:
    """Return the active simulation backend name.

    Reads ARBY_SIM_BACKEND env var.  Defaults to "tenderly" for
    backward compatibility.
    """
    raw = os.environ.get("ARBY_SIM_BACKEND", BACKEND_TENDERLY).strip().lower()
    if raw in _VALID_BACKENDS:
        return raw
    logger.warning("Unknown ARBY_SIM_BACKEND=%r, falling back to tenderly", raw)
    return BACKEND_TENDERLY


def is_tenderly_configured() -> bool:
    """Check if Tenderly env vars are set (non-empty)."""
    return all(
        os.environ.get(k, "").strip()
        for k in ("TENDERLY_USER", "TENDERLY_PROJECT", "TENDERLY_ACCESS_KEY")
    )


def is_anvil_configured() -> bool:
    """Check if Anvil backend is reachable (env var or default localhost)."""
    from m7.orderflow.sim_backends.anvil_backend import is_anvil_configured as _anvil_ok
    return _anvil_ok()


def is_rpc_fork_configured() -> bool:
    """Check if rpc_fork backend is available (always True — uses production RPC)."""
    from m7.orderflow.sim_backends.rpc_fork_backend import is_rpc_fork_configured as _rpc_ok
    return _rpc_ok()


def is_simulation_configured() -> bool:
    """Generic readiness check for the currently selected backend."""
    backend = get_simulation_backend()
    if backend == BACKEND_ANVIL:
        return is_anvil_configured()
    if backend == BACKEND_RPC_FORK:
        return is_rpc_fork_configured()
    return is_tenderly_configured()


# ---------------------------------------------------------------------------
# Tenderly implementation (legacy, kept in-module for migration cycle)
# ---------------------------------------------------------------------------

def _get_tenderly_base_url() -> str:
    user = os.environ.get("TENDERLY_USER", "")
    project = os.environ.get("TENDERLY_PROJECT", "")
    return f"https://api.tenderly.co/api/v1/account/{user}/project/{project}"


def _simulate_swap_tenderly(
    chain: str = "base",
    from_address: str = "0x0000000000000000000000000000000000000000",
    to_address: str = "0x0000000000000000000000000000000000000000",
    calldata: bytes = b"",
    value_wei: int = 0,
    block_number: Optional[int] = None,
) -> SimulationResult:
    """Simulate via Tenderly fork API."""
    if not is_tenderly_configured():
        return SimulationResult(
            success=False,
            error="TENDERLY_NOT_CONFIGURED",
            backend=BACKEND_TENDERLY,
        )

    chain_id_map = {"base": 8453, "arbitrum_one": 42161, "optimism": 10}
    network_id = chain_id_map.get(chain, 8453)

    try:
        import httpx
    except ImportError:
        return SimulationResult(success=False, error="httpx not installed", backend=BACKEND_TENDERLY)

    base_url = _get_tenderly_base_url()
    access_key = os.environ.get("TENDERLY_ACCESS_KEY", "")

    payload = {
        "network_id": str(network_id),
        "from": from_address,
        "to": to_address,
        "input": "0x" + calldata.hex() if calldata else "0x",
        "value": str(value_wei),
        "save_if_fails": False,
        "simulation_type": "quick",
    }
    if block_number is not None:
        payload["block_number"] = block_number

    try:
        resp = httpx.post(
            f"{base_url}/simulate",
            json=payload,
            headers={
                "X-Access-Key": access_key,
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
        if resp.status_code != 200:
            return SimulationResult(
                success=False,
                error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                backend=BACKEND_TENDERLY,
            )

        data = resp.json()
        tx = data.get("transaction", {})
        status = tx.get("status", False)

        return SimulationResult(
            success=bool(status),
            gas_used=tx.get("gas_used", 0),
            simulation_id=data.get("simulation", {}).get("id"),
            revert_reason=tx.get("error_message") if not status else None,
            backend=BACKEND_TENDERLY,
        )
    except Exception as e:
        logger.warning("Tenderly simulation failed: %s", str(e)[:200])
        return SimulationResult(success=False, error=str(e)[:200], backend=BACKEND_TENDERLY)


# ---------------------------------------------------------------------------
# Public router
# ---------------------------------------------------------------------------

def simulate_swap(
    chain: str = "base",
    from_address: str = "0x0000000000000000000000000000000000000000",
    to_address: str = "0x0000000000000000000000000000000000000000",
    calldata: bytes = b"",
    value_wei: int = 0,
    block_number: Optional[int] = None,
) -> SimulationResult:
    """
    Simulate a swap transaction via the configured backend.

    Backend is determined by ARBY_SIM_BACKEND env var (default: tenderly).
    """
    backend = get_simulation_backend()

    if backend == BACKEND_ANVIL:
        from m7.orderflow.sim_backends.anvil_backend import simulate_swap_anvil
        return simulate_swap_anvil(
            chain=chain,
            from_address=from_address,
            to_address=to_address,
            calldata=calldata,
            value_wei=value_wei,
            block_number=block_number,
        )

    if backend == BACKEND_RPC_FORK:
        from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork
        return simulate_swap_rpc_fork(
            chain=chain,
            from_address=from_address,
            to_address=to_address,
            calldata=calldata,
            value_wei=value_wei,
            block_number=block_number,
        )

    return _simulate_swap_tenderly(
        chain=chain,
        from_address=from_address,
        to_address=to_address,
        calldata=calldata,
        value_wei=value_wei,
        block_number=block_number,
    )
