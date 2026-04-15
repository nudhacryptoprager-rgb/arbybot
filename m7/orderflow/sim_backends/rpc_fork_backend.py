"""
RPC Fork Simulation Backend — eth_call with state overrides.

E1.16: Zero-infrastructure simulation using production RPC.
E1.20: Flashblocks pre-confirmed state (``pending`` block tag).

Unlike Anvil (requires separate process) or Tenderly (requires credits),
this backend uses `eth_call` with the stateOverride parameter supported
by Geth, OP-Geth, dRPC, Alchemy, and other EVM nodes.

State overrides let us inject ERC-20 balances and allowances into the
simulation without modifying actual chain state — everything is read-only.

E1.20 Flashblocks (Base only):
  When ARBY_FLASHBLOCKS_SIM=1, simulations on Base use the Flashblocks
  pre-confirmation endpoint (mainnet-preconf.base.org) with ``pending``
  block tag. This gives 1-2 blocks (2-4 seconds) of pre-confirmed state
  ahead of standard ``latest`` — an execution timing edge at zero cost.
  Falls back to standard RPC on failure.

Environment:
  ARBY_SIM_BACKEND=rpc_fork    — selects this backend
  ARBY_FLASHBLOCKS_SIM=1       — enable Flashblocks pending tag (Base only)
  ARBY_FLASHBLOCKS_HTTP        — override Flashblocks HTTP URL
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


# ---------------------------------------------------------------------------
# Flashblocks pre-confirmed state (E1.20)
# ---------------------------------------------------------------------------

# Chains that support Flashblocks pre-confirmation via ``pending`` block tag.
_FLASHBLOCKS_CHAINS = {"base"}


def _is_flashblocks_sim_enabled() -> bool:
    """True when ARBY_FLASHBLOCKS_SIM=1 (opt-in)."""
    return os.environ.get("ARBY_FLASHBLOCKS_SIM", "").strip() == "1"


def _get_flashblocks_http_url(chain: str) -> Optional[str]:
    """Resolve Flashblocks HTTP endpoint for *chain*.

    Priority: ARBY_FLASHBLOCKS_HTTP env > chains.yaml > None.
    Only returns a URL for chains in ``_FLASHBLOCKS_CHAINS``.
    """
    if chain not in _FLASHBLOCKS_CHAINS:
        return None
    try:
        from chains.flashblocks import get_flashblocks_http_url
        return get_flashblocks_http_url()
    except ImportError:
        pass
    return os.environ.get("ARBY_FLASHBLOCKS_HTTP")


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

    E1.20: When ARBY_FLASHBLOCKS_SIM=1 and chain is Base, uses the
    Flashblocks preconf endpoint with ``pending`` block tag for 1-2 blocks
    of pre-confirmed state (2-4 sec edge).  Falls back to standard RPC on
    failure.
    """
    from m7.orderflow.simulation import SimulationResult

    rpc_url = _get_rpc_url(chain)
    if not rpc_url:
        return SimulationResult(
            success=False,
            error="RPC_URL_NOT_AVAILABLE",
            backend="rpc_fork",
        )

    # E1.20: Resolve Flashblocks preconf endpoint for pending-state sim
    use_flashblocks = False
    flashblocks_url: Optional[str] = None
    if block_number is None and _is_flashblocks_sim_enabled():
        flashblocks_url = _get_flashblocks_http_url(chain)
        if flashblocks_url:
            use_flashblocks = True

    # Build tx object
    tx_obj: Dict = {
        "from": from_address,
        "to": to_address,
        "data": "0x" + calldata.hex() if calldata else "0x",
    }
    if value_wei:
        tx_obj["value"] = hex(value_wei)

    if block_number is not None:
        block_tag = hex(block_number)
    elif use_flashblocks:
        block_tag = "pending"
    else:
        block_tag = "latest"

    # Build state overrides for ERC-20 balance seeding
    # E1.18: Detect calldata type by selector to extract token_in correctly.
    # V3 (0x04e45aaf / 0x414bf389): token_in at calldata[4:36]
    # ve33 (0xcac88ea9): token_in in routes array (dynamic offset)
    state_overrides: Dict = {}
    if len(calldata) >= 36 and from_address != "0x" + "0" * 40:
        try:
            selector = calldata[:4]
            _VE33_SELECTOR = bytes.fromhex("cac88ea9")
            if selector == _VE33_SELECTOR and len(calldata) >= 260:
                # Velodrome: parse routes offset → routes[0].from
                # Layout: selector(4) + amountIn(32) + amountOutMin(32) +
                #   offset(32) + to(32) + deadline(32) + length(32) + route0.from(32)
                # offset value at bytes [68:100] points to routes data start
                # routes[0].from is at position: 4 + offset + 32 (length field)
                routes_offset = int.from_bytes(calldata[68:100], "big")
                route0_from_start = 4 + routes_offset + 32  # skip selector + offset + length
                token_in_hex = "0x" + calldata[route0_from_start:route0_from_start + 32].hex().lstrip("0").zfill(40)
            else:
                # V3: token_in is first parameter at calldata[4:36]
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

    # E1.20: Try Flashblocks preconf endpoint first (pending state edge),
    # fall back to standard RPC on any failure.
    sim_url = rpc_url
    backend_label = "rpc_fork"
    if use_flashblocks and flashblocks_url:
        data, call_err = _json_rpc(flashblocks_url, "eth_call", params)
        if call_err:
            logger.info(
                "Flashblocks preconf sim failed (%s), falling back to standard RPC",
                call_err[:80],
            )
            # Fall back: switch to standard RPC + latest block tag
            params[1] = "latest"
            data, call_err = _json_rpc(rpc_url, "eth_call", params)
        else:
            sim_url = flashblocks_url
            backend_label = "rpc_fork_preconf"
    else:
        data, call_err = _json_rpc(rpc_url, "eth_call", params)

    if call_err:
        revert_reason = None
        if "revert" in call_err.lower() or "execution reverted" in call_err.lower():
            revert_reason = call_err
        return SimulationResult(
            success=False,
            error=call_err,
            revert_reason=revert_reason,
            backend=backend_label,
        )

    output_hex = data.get("result", "0x") if data else "0x"

    # Gas estimation with state overrides (Geth 1.13+ supports this)
    # Use the same URL that succeeded for eth_call.
    gas = 0
    gas_params = [tx_obj]
    if state_overrides:
        gas_params.append(state_overrides)
    est_data, gas_err = _json_rpc(sim_url, "eth_estimateGas", gas_params)
    if est_data and not gas_err:
        try:
            gas = int(est_data.get("result", "0x0"), 16)
        except (ValueError, TypeError):
            pass
    elif gas_err:
        # Retry without overrides (older nodes)
        est_data2, _ = _json_rpc(sim_url, "eth_estimateGas", [tx_obj])
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
        "rpc_fork sim OK: chain=%s, gas=%d, output=%d, backend=%s",
        chain, gas, output_amount, backend_label,
    )

    return SimulationResult(
        success=True,
        gas_used=gas,
        output_amount_wei=output_amount,
        backend=backend_label,
    )
