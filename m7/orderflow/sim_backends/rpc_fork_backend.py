"""
RPC Fork Simulation Backend — eth_call with state overrides.

E1.16: Zero-infrastructure simulation using production RPC.

Unlike Anvil (requires separate process) or Tenderly (requires credits),
this backend uses `eth_call` with the stateOverride parameter supported
by Geth, OP-Geth, dRPC, Alchemy, and other EVM nodes.

State overrides let us inject ERC-20 balances and allowances into the
simulation without modifying actual chain state — everything is read-only.

Environment:
  ARBY_SIM_BACKEND=rpc_fork    — selects this backend
  (no extra env vars needed: uses chain RPC from existing config)
"""

import logging
import os
from typing import Dict, Optional, Tuple

logger = logging.getLogger("m7.orderflow.sim_backends.rpc_fork")

# Common ERC-20 storage slots for balanceOf(address) mapping.
# Slot = keccak256(abi.encode(address, baseSlot))
_COMMON_BALANCE_SLOTS = [0, 1, 2, 3, 9, 51]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def is_rpc_fork_configured() -> bool:
    """Always True — uses production RPC which is already configured."""
    return True


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def _keccak256(data: bytes) -> bytes:
    """Ethereum keccak256 (NOT NIST SHA3-256)."""
    try:
        from web3 import Web3
        return bytes(Web3.keccak(data))
    except ImportError:
        pass
    try:
        from Crypto.Hash import keccak
        return keccak.new(data=data, digest_bits=256).digest()
    except ImportError:
        pass
    import hashlib
    try:
        return hashlib.new("keccak-256", data).digest()
    except ValueError:
        logger.warning("No keccak-256 available, sim may fail")
        return hashlib.new("sha3_256", data).digest()


def _compute_mapping_slot(key_addr: str, base_slot: int) -> str:
    """Compute Solidity mapping slot: keccak256(abi.encode(address, uint256))."""
    addr_bytes = bytes.fromhex(key_addr.lower().replace("0x", "").zfill(64))
    slot_bytes = base_slot.to_bytes(32, "big")
    return "0x" + _keccak256(addr_bytes + slot_bytes).hex()


def _compute_allowance_slot(owner: str, spender: str, base_slot: int) -> str:
    """Compute nested mapping slot for allowance[owner][spender]."""
    owner_bytes = bytes.fromhex(owner.lower().replace("0x", "").zfill(64))
    slot_bytes = base_slot.to_bytes(32, "big")
    inner = _keccak256(owner_bytes + slot_bytes)
    spender_bytes = bytes.fromhex(spender.lower().replace("0x", "").zfill(64))
    return "0x" + _keccak256(spender_bytes + inner).hex()


# ---------------------------------------------------------------------------
# State override builder
# ---------------------------------------------------------------------------

def _build_state_overrides(
    token_in_addr: str,
    holder: str,
    router: str,
    amount: int = 10**30,
) -> Dict:
    """Build eth_call stateOverride for ERC-20 balance + allowance seeding.

    Overrides ALL common balance slots and corresponding allowance slots
    so the simulation has sufficient balance regardless of token layout.
    """
    large_value = "0x" + amount.to_bytes(32, "big").hex()
    max_allowance = "0x" + (2**256 - 1).to_bytes(32, "big").hex()

    state_diff: Dict[str, str] = {}

    for base_slot in _COMMON_BALANCE_SLOTS:
        # Balance slot
        bal_slot = _compute_mapping_slot(holder, base_slot)
        state_diff[bal_slot] = large_value

        # Allowance slots: try allowance base = balance base + 1 (most common)
        for allowance_offset in [1, 0, 2]:
            allow_slot = _compute_allowance_slot(holder, router, base_slot + allowance_offset)
            state_diff[allow_slot] = max_allowance

    return {
        token_in_addr: {"stateDiff": state_diff}
    }


# ---------------------------------------------------------------------------
# RPC call helpers
# ---------------------------------------------------------------------------

def _get_rpc_url(chain: str) -> Optional[str]:
    """Get chain RPC URL via existing config."""
    try:
        from core.rpc_urls import get_rpc_url
        return get_rpc_url(chain)
    except ImportError:
        return None


def _json_rpc(url: str, method: str, params: list, timeout: float = 10.0) -> Tuple[Optional[dict], Optional[str]]:
    """Send JSON-RPC request. Returns (result_dict, error_str)."""
    try:
        import httpx
    except ImportError:
        return None, "httpx not installed"

    try:
        resp = httpx.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        if "error" in data:
            msg = data["error"].get("message", str(data["error"]))[:200]
            return None, msg
        return data, None
    except Exception as e:
        return None, str(e)[:200]


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def simulate_swap_rpc_fork(
    chain: str = "base",
    from_address: str = "0x0000000000000000000000000000000000000000",
    to_address: str = "0x0000000000000000000000000000000000000000",
    calldata: bytes = b"",
    value_wei: int = 0,
    block_number: Optional[int] = None,
) -> "SimulationResult":
    """Simulate a swap via production RPC eth_call with state overrides.

    Uses the stateOverride parameter to inject ERC-20 balances and
    allowances for the sender, enabling real swap execution path
    simulation without modifying chain state.
    """
    from m7.orderflow.simulation import SimulationResult

    rpc_url = _get_rpc_url(chain)
    if not rpc_url:
        return SimulationResult(
            success=False,
            error="RPC_URL_NOT_AVAILABLE",
            backend="rpc_fork",
        )

    # Build tx object
    tx_obj: Dict = {
        "from": from_address,
        "to": to_address,
        "data": "0x" + calldata.hex() if calldata else "0x",
    }
    if value_wei:
        tx_obj["value"] = hex(value_wei)

    block_tag = "latest" if block_number is None else hex(block_number)

    # Build state overrides for ERC-20 balance seeding
    state_overrides: Dict = {}
    if len(calldata) >= 36 and from_address != "0x" + "0" * 40:
        try:
            token_in_hex = "0x" + calldata[4:36].hex().lstrip("0").zfill(40)
            state_overrides = _build_state_overrides(
                token_in_addr=token_in_hex,
                holder=from_address,
                router=to_address,
            )
        except Exception as e:
            logger.debug("State override build failed (non-fatal): %s", str(e)[:100])

    # eth_call with state overrides (3rd parameter)
    params = [tx_obj, block_tag]
    if state_overrides:
        params.append(state_overrides)

    data, call_err = _json_rpc(rpc_url, "eth_call", params)

    if call_err:
        revert_reason = None
        if "revert" in call_err.lower() or "execution reverted" in call_err.lower():
            revert_reason = call_err
        return SimulationResult(
            success=False,
            error=call_err,
            revert_reason=revert_reason,
            backend="rpc_fork",
        )

    output_hex = data.get("result", "0x") if data else "0x"

    # Gas estimation with state overrides (Geth 1.13+ supports this)
    gas = 0
    gas_params = [tx_obj]
    if state_overrides:
        gas_params.append(state_overrides)
    est_data, gas_err = _json_rpc(rpc_url, "eth_estimateGas", gas_params)
    if est_data and not gas_err:
        try:
            gas = int(est_data.get("result", "0x0"), 16)
        except (ValueError, TypeError):
            pass
    elif gas_err:
        # Retry without overrides (older nodes)
        est_data2, _ = _json_rpc(rpc_url, "eth_estimateGas", [tx_obj])
        if est_data2:
            try:
                gas = int(est_data2.get("result", "0x0"), 16)
            except (ValueError, TypeError):
                pass
        logger.debug("Gas estimate with overrides failed: %s", gas_err)

    # Parse output amount (first 32 bytes of return data)
    output_amount = 0
    if output_hex and len(output_hex) >= 66:
        try:
            output_amount = int(output_hex[2:66], 16)
        except ValueError:
            pass

    logger.info(
        "rpc_fork sim OK: chain=%s, gas=%d, output=%d",
        chain, gas, output_amount,
    )

    return SimulationResult(
        success=True,
        gas_used=gas,
        output_amount_wei=output_amount,
        backend="rpc_fork",
    )
