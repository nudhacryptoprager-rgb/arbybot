"""
Tenderly Fork Simulation — Scaffolding for M7 execution pre-flight.

E1.12.1: Scaffolding only. Actual API calls require TENDERLY_ACCESS_KEY.

The simulation gate sits between profit_guard_passed and submit_ready
in the execution funnel:
    scored → positive → route_viable → profit_guard_passed → sim_passed → submit_ready

Usage:
    from m7.orderflow.simulation import is_tenderly_configured, simulate_swap

    if is_tenderly_configured():
        result = simulate_swap(chain="base", tx_params={...})
        if result.success:
            # proceed to submit
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("m7.orderflow.simulation")


@dataclass
class SimulationResult:
    """Result of a Tenderly fork simulation."""
    success: bool
    gas_used: int = 0
    output_amount_wei: int = 0
    revert_reason: Optional[str] = None
    simulation_id: Optional[str] = None
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.success and self.revert_reason is None


def is_tenderly_configured() -> bool:
    """Check if Tenderly env vars are set (non-empty)."""
    return all(
        os.environ.get(k, "").strip()
        for k in ("TENDERLY_USER", "TENDERLY_PROJECT", "TENDERLY_ACCESS_KEY")
    )


def _get_tenderly_base_url() -> str:
    user = os.environ.get("TENDERLY_USER", "")
    project = os.environ.get("TENDERLY_PROJECT", "")
    return f"https://api.tenderly.co/api/v1/account/{user}/project/{project}"


def simulate_swap(
    chain: str = "base",
    from_address: str = "0x0000000000000000000000000000000000000000",
    to_address: str = "0x0000000000000000000000000000000000000000",
    calldata: bytes = b"",
    value_wei: int = 0,
    block_number: Optional[int] = None,
) -> SimulationResult:
    """
    Simulate a swap transaction via Tenderly fork API.

    Args:
        chain: Chain name (base, arbitrum_one, etc.)
        from_address: Sender address
        to_address: Target contract address
        calldata: Transaction calldata
        value_wei: ETH value to send
        block_number: Block to simulate at (latest if None)

    Returns:
        SimulationResult with success/failure details
    """
    if not is_tenderly_configured():
        return SimulationResult(
            success=False,
            error="TENDERLY_NOT_CONFIGURED",
        )

    chain_id_map = {"base": 8453, "arbitrum_one": 42161, "optimism": 10}
    network_id = chain_id_map.get(chain, 8453)

    try:
        import httpx
    except ImportError:
        return SimulationResult(success=False, error="httpx not installed")

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
            )

        data = resp.json()
        tx = data.get("transaction", {})
        status = tx.get("status", False)

        return SimulationResult(
            success=bool(status),
            gas_used=tx.get("gas_used", 0),
            simulation_id=data.get("simulation", {}).get("id"),
            revert_reason=tx.get("error_message") if not status else None,
        )
    except Exception as e:
        logger.warning("Tenderly simulation failed: %s", str(e)[:200])
        return SimulationResult(success=False, error=str(e)[:200])
