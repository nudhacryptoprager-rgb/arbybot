"""
Anvil Simulation Backend — local fork via Foundry Anvil.

E1.12.4A: Provides sim_passed path without Tenderly credits.

Anvil runs as a separate process (started by scripts/start_anvil_fork.py
or manually).  This module talks to it via standard JSON-RPC:
  - eth_call for swap simulation
  - eth_estimateGas for gas estimation
  - anvil_reset for fork lifecycle (optional)

Environment:
  ARBY_ANVIL_RPC_URL  — default http://127.0.0.1:8545

Design constraints (per E1.12.4 directives):
  - Anvil is terminal-stage ONLY (profit_guard → sim → submit_ready)
  - NOT in quote collection or hot scoring path
  - Reuses execution/preflight.py + execution/simulator.py contracts where possible
"""

import logging
import os
from typing import Optional

logger = logging.getLogger("m7.orderflow.sim_backends.anvil")

DEFAULT_ANVIL_RPC_URL = "http://127.0.0.1:8545"

# Chain ID map (same as simulation.py for consistency)
CHAIN_ID_MAP = {"base": 8453, "arbitrum_one": 42161, "optimism": 10}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def get_anvil_rpc_url() -> str:
    """Return the Anvil JSON-RPC URL from env or default."""
    return os.environ.get("ARBY_ANVIL_RPC_URL", DEFAULT_ANVIL_RPC_URL).strip()


def is_anvil_configured() -> bool:
    """Check if Anvil is supposed to be used.

    True when ARBY_SIM_BACKEND=anvil (checked by caller) and the URL is set
    or default localhost is assumed.  Does NOT probe the connection — use
    check_anvil_connection() for that.
    """
    url = get_anvil_rpc_url()
    return bool(url)


# ---------------------------------------------------------------------------
# Health probe
# ---------------------------------------------------------------------------

def check_anvil_connection() -> tuple:
    """Probe Anvil JSON-RPC for liveness.

    Returns:
        (ok: bool, client_version: str | None, error: str | None)
    """
    url = get_anvil_rpc_url()
    try:
        import httpx
    except ImportError:
        return False, None, "httpx not installed"

    try:
        resp = httpx.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": "web3_clientVersion", "params": []},
            timeout=5.0,
        )
        if resp.status_code != 200:
            return False, None, f"HTTP {resp.status_code}"
        data = resp.json()
        client = data.get("result", "")
        # Anvil responds with something like "anvil/v0.2.0"
        if "anvil" in client.lower():
            return True, client, None
        return False, client, f"not anvil: {client[:80]}"
    except Exception as e:
        return False, None, str(e)[:200]


# ---------------------------------------------------------------------------
# Fork lifecycle
# ---------------------------------------------------------------------------

def reset_anvil_fork(block_number: Optional[int] = None) -> bool:
    """Reset Anvil fork state via anvil_reset RPC.

    Args:
        block_number: If given, reset fork to this block.  Otherwise Anvil
                      uses its configured --fork-block-number or latest.

    Returns:
        True on success.
    """
    url = get_anvil_rpc_url()
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed — cannot reset Anvil fork")
        return False

    params: dict = {}
    if block_number is not None:
        params["forking"] = {"blockNumber": block_number}

    try:
        resp = httpx.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": "anvil_reset", "params": [params] if params else []},
            timeout=10.0,
        )
        if resp.status_code == 200 and "error" not in resp.json():
            logger.info("Anvil fork reset (block=%s)", block_number)
            return True
        logger.warning("Anvil reset failed: %s", resp.text[:200])
        return False
    except Exception as e:
        logger.warning("Anvil reset error: %s", str(e)[:200])
        return False


# ---------------------------------------------------------------------------
# Simulation via eth_call + eth_estimateGas
# ---------------------------------------------------------------------------

def estimate_gas_anvil(
    from_address: str,
    to_address: str,
    calldata: bytes,
    value_wei: int = 0,
) -> tuple:
    """Estimate gas for a transaction via Anvil eth_estimateGas.

    Returns:
        (gas: int, error: str | None)
    """
    url = get_anvil_rpc_url()
    try:
        import httpx
    except ImportError:
        return 0, "httpx not installed"

    tx_obj = {
        "from": from_address,
        "to": to_address,
        "data": "0x" + calldata.hex() if calldata else "0x",
    }
    if value_wei:
        tx_obj["value"] = hex(value_wei)

    try:
        resp = httpx.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_estimateGas", "params": [tx_obj]},
            timeout=10.0,
        )
        data = resp.json()
        if "error" in data:
            err_msg = data["error"].get("message", str(data["error"]))[:200]
            return 0, f"estimateGas: {err_msg}"
        gas = int(data.get("result", "0x0"), 16)
        return gas, None
    except Exception as e:
        return 0, str(e)[:200]


def _eth_call_anvil(
    from_address: str,
    to_address: str,
    calldata: bytes,
    value_wei: int = 0,
    block_number: Optional[int] = None,
) -> tuple:
    """Raw eth_call via Anvil.

    Returns:
        (output_hex: str, error: str | None)
    """
    url = get_anvil_rpc_url()
    try:
        import httpx
    except ImportError:
        return "", "httpx not installed"

    tx_obj = {
        "from": from_address,
        "to": to_address,
        "data": "0x" + calldata.hex() if calldata else "0x",
    }
    if value_wei:
        tx_obj["value"] = hex(value_wei)

    block_tag = "latest" if block_number is None else hex(block_number)

    try:
        resp = httpx.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [tx_obj, block_tag]},
            timeout=10.0,
        )
        data = resp.json()
        if "error" in data:
            err_msg = data["error"].get("message", str(data["error"]))[:200]
            return "", f"eth_call: {err_msg}"
        return data.get("result", "0x"), None
    except Exception as e:
        return "", str(e)[:200]


def simulate_swap_anvil(
    chain: str = "base",
    from_address: str = "0x0000000000000000000000000000000000000000",
    to_address: str = "0x0000000000000000000000000000000000000000",
    calldata: bytes = b"",
    value_wei: int = 0,
    block_number: Optional[int] = None,
) -> "SimulationResult":
    """Simulate a swap via Anvil local fork (eth_call + estimateGas).

    Returns a SimulationResult (imported from simulation.py to avoid
    circular deps at module level).
    """
    from m7.orderflow.simulation import SimulationResult, BACKEND_ANVIL

    if not is_anvil_configured():
        return SimulationResult(
            success=False,
            error="ANVIL_NOT_CONFIGURED",
            backend=BACKEND_ANVIL,
        )

    # Health check (fast, cached per-call for now)
    ok, client, conn_err = check_anvil_connection()
    if not ok:
        return SimulationResult(
            success=False,
            error=f"ANVIL_UNREACHABLE: {conn_err}",
            backend=BACKEND_ANVIL,
        )

    # eth_call to simulate the transaction
    output_hex, call_err = _eth_call_anvil(
        from_address=from_address,
        to_address=to_address,
        calldata=calldata,
        value_wei=value_wei,
        block_number=block_number,
    )

    if call_err:
        # Classify revert vs generic error
        revert_reason = None
        if "revert" in call_err.lower() or "execution reverted" in call_err.lower():
            revert_reason = call_err
        return SimulationResult(
            success=False,
            error=call_err,
            revert_reason=revert_reason,
            backend=BACKEND_ANVIL,
        )

    # Gas estimation
    gas, gas_err = estimate_gas_anvil(
        from_address=from_address,
        to_address=to_address,
        calldata=calldata,
        value_wei=value_wei,
    )

    if gas_err:
        # eth_call passed but gas estimation failed — still success with warning
        logger.warning("Anvil gas estimate failed (eth_call OK): %s", gas_err)

    # Parse output amount if available (first 32 bytes = uint256)
    output_amount = 0
    if output_hex and len(output_hex) >= 66:  # 0x + 64 hex chars
        try:
            output_amount = int(output_hex[2:66], 16)
        except ValueError:
            pass

    return SimulationResult(
        success=True,
        gas_used=gas,
        output_amount_wei=output_amount,
        backend=BACKEND_ANVIL,
    )
