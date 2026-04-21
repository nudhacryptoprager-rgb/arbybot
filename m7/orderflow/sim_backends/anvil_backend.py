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

E1.14: ERC-20 balance seeding via anvil_setStorageAt + approval for sim.
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
# ERC-20 balance seeding for simulation (E1.14)
# ---------------------------------------------------------------------------

# Standard ERC-20 slot patterns for balanceOf(address) and allowance(owner,spender)
# Most tokens (OpenZeppelin-based) use slot keccak256(abi.encode(address, slotIndex)).
# Common balance slots: 0 (OZ ERC20), 1 (some), 2, 9 (USDC proxy).
_COMMON_BALANCE_SLOTS = [0, 1, 2, 3, 9, 51]


def _keccak256(data: bytes) -> bytes:
    """Ethereum keccak256 hash (NOT SHA3-256)."""
    try:
        from Crypto.Hash import keccak
        return keccak.new(data=data, digest_bits=256).digest()
    except ImportError:
        pass
    try:
        # pysha3 / pycryptodome fallback
        import sha3
        return sha3.keccak_256(data).digest()
    except ImportError:
        pass
    try:
        # web3 has keccak
        from web3 import Web3
        return Web3.keccak(data)
    except ImportError:
        pass
    # Last resort: hashlib on Python 3.11+ with OpenSSL 3.x may have keccak
    import hashlib
    try:
        h = hashlib.new("keccak-256", data)
        return h.digest()
    except ValueError:
        # Fall back to sha3_256 — will likely produce wrong slots
        logger.warning("No keccak-256 available, falling back to sha3_256 (may not work for storage slot computation)")
        return hashlib.new("sha3_256", data).digest()


def _compute_mapping_slot(key_addr: str, base_slot: int) -> str:
    """Compute Solidity mapping slot: keccak256(abi.encode(address, uint256))."""
    addr_bytes = bytes.fromhex(key_addr.lower().replace("0x", "").zfill(64))
    slot_bytes = base_slot.to_bytes(32, "big")
    return "0x" + _keccak256(addr_bytes + slot_bytes).hex()


def _compute_allowance_slot(owner: str, spender: str, base_slot: int) -> str:
    """Compute nested mapping slot for allowance[owner][spender].

    Solidity storage for mapping(address => mapping(address => uint256)):
      inner_slot = keccak256(abi.encode(owner, base_slot))
      actual_slot = keccak256(abi.encode(spender, inner_slot))
    """
    owner_bytes = bytes.fromhex(owner.lower().replace("0x", "").zfill(64))
    slot_bytes = base_slot.to_bytes(32, "big")
    inner = _keccak256(owner_bytes + slot_bytes)

    spender_bytes = bytes.fromhex(spender.lower().replace("0x", "").zfill(64))
    return "0x" + _keccak256(spender_bytes + inner).hex()


def _anvil_set_storage(token_addr: str, slot: str, value: str) -> bool:
    """Set storage slot via anvil_setStorageAt."""
    url = get_anvil_rpc_url()
    try:
        import httpx

        resp = httpx.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "anvil_setStorageAt",
                "params": [token_addr, slot, value],
            },
            timeout=5.0,
        )
        data = resp.json()
        return "error" not in data
    except Exception as e:
        logger.debug("anvil_setStorageAt failed: %s", str(e)[:100])
        return False


def _anvil_get_balance_of(token_addr: str, owner: str) -> int:
    """Read ERC-20 balanceOf via eth_call."""
    url = get_anvil_rpc_url()
    # balanceOf(address) selector = 0x70a08231
    calldata = "0x70a08231" + owner.lower().replace("0x", "").zfill(64)
    try:
        import httpx

        resp = httpx.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_call",
                "params": [{"to": token_addr, "data": calldata}, "latest"],
            },
            timeout=5.0,
        )
        data = resp.json()
        result_hex = data.get("result", "0x0")
        if result_hex and len(result_hex) >= 3:
            return int(result_hex, 16)
        return 0
    except Exception:
        return 0


def seed_erc20_balance(
    token_addr: str, holder: str, amount: int, spender: Optional[str] = None
) -> bool:
    """Seed ERC-20 balance on Anvil fork by brute-forcing common storage slots.

    Tries _COMMON_BALANCE_SLOTS to find which slot controls balanceOf(holder).
    Sets balance to `amount` and optionally sets unlimited allowance for `spender`.

    Returns True if balance was successfully set.
    """
    large_value = "0x" + amount.to_bytes(32, "big").hex()

    for base_slot in _COMMON_BALANCE_SLOTS:
        slot = _compute_mapping_slot(holder, base_slot)
        _anvil_set_storage(token_addr, slot, large_value)

        # Verify
        actual = _anvil_get_balance_of(token_addr, holder)
        if actual >= amount:
            logger.debug(
                "Seeded %s balance for %s at slot %d (balance=%d)",
                token_addr[:10],
                holder[:10],
                base_slot,
                actual,
            )
            # Set approval if spender given
            if spender:
                _seed_approval(token_addr, holder, spender, base_slot)
            return True

    logger.debug("Failed to seed balance for token %s (tried %d slots)", token_addr[:10], len(_COMMON_BALANCE_SLOTS))
    return False


def _seed_approval(
    token_addr: str, owner: str, spender: str, balance_base_slot: int
) -> bool:
    """Set unlimited allowance for spender by trying common allowance slots.

    Allowance mapping is typically at balance_slot + 1, but can vary.
    """
    max_uint = "0x" + "ff" * 32
    # Common: allowance slot = balance slot + 1
    for allowance_offset in [1, 0, 2, 3]:
        allowance_base = balance_base_slot + allowance_offset
        slot = _compute_allowance_slot(owner, spender, allowance_base)
        _anvil_set_storage(token_addr, slot, max_uint)

    return True


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


def get_anvil_block_number() -> Optional[int]:
    """Return current Anvil local head block, or None on failure.

    Step 9: used to detect static-fork drift — if the requested event_block
    is higher than the local head, Anvil has no state for it and eth_call
    raises BlockOutOfRangeError.
    """
    url = get_anvil_rpc_url()
    try:
        import httpx
    except ImportError:
        return None
    try:
        resp = httpx.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []},
            timeout=5.0,
        )
        data = resp.json()
        if "error" in data:
            return None
        res = data.get("result")
        if isinstance(res, str) and res.startswith("0x"):
            return int(res, 16)
    except Exception:
        return None
    return None


def _resolve_anvil_block_tag(block_number: Optional[int]) -> tuple:
    """Step 9: clamp block_number to local Anvil head to prevent drift.

    ARBY_ANVIL_CLAMP_BLOCK (default "1"): when the requested block_number
    exceeds the local Anvil head, replace it with "latest" so eth_call
    uses the fork state we actually have instead of raising
    BlockOutOfRangeError.

    Returns:
        (block_tag, clamped_flag, local_head)

    block_tag is the value to pass as eth_call params[1].
    clamped_flag is True when a drift was detected and the tag was
    replaced with "latest".
    """
    clamp_enabled = os.environ.get("ARBY_ANVIL_CLAMP_BLOCK", "1").strip() == "1"
    if block_number is None:
        return "latest", False, None
    if not clamp_enabled:
        return hex(block_number), False, None

    local_head = get_anvil_block_number()
    if local_head is None:
        # Cannot probe local head — fall back to "latest" to stay safe.
        return "latest", True, None
    if block_number > local_head:
        logger.info(
            "anvil block clamp: requested=%d > local_head=%d → using latest",
            block_number, local_head,
        )
        return "latest", True, local_head
    return hex(block_number), False, local_head


def _eth_call_anvil(
    from_address: str,
    to_address: str,
    calldata: bytes,
    value_wei: int = 0,
    block_number: Optional[int] = None,
) -> tuple:
    """Raw eth_call via Anvil.

    Step 9: when ``block_number`` exceeds local Anvil head, the tag is
    clamped to "latest" (controlled by ARBY_ANVIL_CLAMP_BLOCK, default on).
    The returned error also normalises ``BlockOutOfRangeError`` spellings
    into a stable prefix so rollups can histogram them cleanly.

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

    block_tag, _clamped, _local_head = _resolve_anvil_block_tag(block_number)

    try:
        resp = httpx.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [tx_obj, block_tag]},
            timeout=10.0,
        )
        data = resp.json()
        if "error" in data:
            err_msg = data["error"].get("message", str(data["error"]))[:200]
            low = err_msg.lower()
            # Step 9 fallback: if the endpoint still complained about an
            # out-of-range block (e.g., clamp was disabled or local_head
            # probe raced a reorg), retry once with "latest".
            if ("blockoutofrange" in low or "block out of range" in low
                    or "beyond the latest" in low) and block_tag != "latest":
                logger.info(
                    "anvil eth_call BlockOutOfRange on tag=%s → retrying latest",
                    block_tag,
                )
                resp2 = httpx.post(
                    url,
                    json={
                        "jsonrpc": "2.0", "id": 1, "method": "eth_call",
                        "params": [tx_obj, "latest"],
                    },
                    timeout=10.0,
                )
                data2 = resp2.json()
                if "error" in data2:
                    err2 = data2["error"].get("message", str(data2["error"]))[:200]
                    return "", f"eth_call: {err2}"
                return data2.get("result", "0x"), None
            return "", f"eth_call: {err_msg}"
        return data.get("result", "0x"), None
    except Exception as e:
        return "", str(e)[:200]


def refresh_anvil_fork_if_stale(
    chain: str = "base",
    max_drift_blocks: int = 120,
    offset: int = 5,
    upstream_url: Optional[str] = None,
) -> tuple:
    """Step 9: re-fork Anvil when its local head drifts too far behind the
    upstream chain.

    This is the long-running counterpart of :func:`_resolve_anvil_block_tag`:
    clamping keeps single sims from failing, but without a periodic reset
    the local state grows stale against the live chain. Calling this from
    a supervisor loop every few minutes keeps the fork roughly in sync.

    Args:
        chain: Chain key — only used for the default upstream lookup via
            ``ARBY_FORK_RPC_URL`` / chain-env fallback.
        max_drift_blocks: Minimum drift before we bother resetting.
        offset: Target = upstream_head - offset (avoids reorg races).
        upstream_url: Override the upstream RPC URL (mainly for tests).

    Returns:
        (refreshed: bool, diagnostic: dict)
    """
    diag: dict = {"chain": chain, "reset": False}
    upstream = upstream_url or os.environ.get("ARBY_FORK_RPC_URL", "").strip()
    if not upstream:
        # Fallback to chain-scoped legacy env
        env_map = {
            "base": ("BASE_RPC_URL", "BASE_RPC"),
            "arbitrum_one": ("ARBITRUM_RPC_URL", "ARBITRUM_RPC"),
            "optimism": ("OPTIMISM_RPC_URL", "OPTIMISM_RPC"),
        }
        for key in env_map.get(chain, ()):
            val = os.environ.get(key, "").strip()
            if val:
                upstream = val
                break
    if not upstream:
        diag["reason"] = "NO_UPSTREAM_URL"
        return False, diag

    try:
        import httpx
    except ImportError:
        diag["reason"] = "NO_HTTPX"
        return False, diag

    # Probe upstream head
    try:
        resp = httpx.post(
            upstream,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []},
            timeout=10.0,
        )
        payload = resp.json()
        head_hex = payload.get("result")
        upstream_head = int(head_hex, 16) if isinstance(head_hex, str) else None
    except Exception as e:
        diag["reason"] = f"UPSTREAM_PROBE_FAILED:{str(e)[:100]}"
        return False, diag

    if upstream_head is None:
        diag["reason"] = "NO_UPSTREAM_HEAD"
        return False, diag

    local_head = get_anvil_block_number()
    diag["local_head"] = local_head
    diag["upstream_head"] = upstream_head
    if local_head is None:
        diag["reason"] = "NO_LOCAL_HEAD"
        return False, diag

    drift = upstream_head - local_head
    diag["drift"] = drift
    if drift < max_drift_blocks:
        diag["reason"] = "DRIFT_OK"
        return False, diag

    target_block = max(1, upstream_head - max(0, offset))
    diag["target_block"] = target_block
    ok = reset_anvil_fork(block_number=target_block)
    diag["reset"] = ok
    diag["reason"] = "RESET_OK" if ok else "RESET_FAILED"
    return ok, diag


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

    # E1.14: Seed ERC-20 balance for from_address before simulation.
    # Extract token_in from calldata (first 32 bytes after 4-byte selector)
    # and seed a large balance + approval for the router (to_address).
    if len(calldata) >= 36 and from_address != "0x0000000000000000000000000000000000000000":
        try:
            token_in_hex = "0x" + calldata[4:36].hex().lstrip("0").zfill(40)
            # Seed 10^30 of the token (enough for any realistic sim)
            seed_amount = 10**30
            seeded = seed_erc20_balance(token_in_hex, from_address, seed_amount, spender=to_address)
            if seeded:
                logger.debug("Seeded token %s for sim from %s", token_in_hex[:10], from_address[:10])
        except Exception as e:
            logger.debug("Balance seeding failed (non-fatal): %s", str(e)[:100])

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
