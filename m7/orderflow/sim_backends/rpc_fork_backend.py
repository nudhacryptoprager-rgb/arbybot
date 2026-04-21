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
# E1: Widened coverage — added slots used by proxy upgradeable tokens
# (USDC proxy=9, DAI=2), Solmate (slot 0), OpenZeppelin (slot 0/3),
# and custom meme tokens (slots 5/6/7/101/104/151).
_COMMON_BALANCE_SLOTS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 51, 101, 104, 151]

# E1: Allow runtime extension via env (comma-separated ints)
_EXTRA_SLOTS_ENV = "ARBY_SIM_EXTRA_BALANCE_SLOTS"


def _effective_balance_slots() -> list:
    """Union _COMMON_BALANCE_SLOTS with ARBY_SIM_EXTRA_BALANCE_SLOTS env."""
    extra_raw = os.environ.get(_EXTRA_SLOTS_ENV, "").strip()
    if not extra_raw:
        return list(_COMMON_BALANCE_SLOTS)
    try:
        extra = [int(s.strip()) for s in extra_raw.split(",") if s.strip()]
        return sorted(set(_COMMON_BALANCE_SLOTS) | set(extra))
    except ValueError:
        return list(_COMMON_BALANCE_SLOTS)


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

def build_slot_map(
    token_in_addr: str,
    holder: str,
    router: str,
    amount: int = 10**30,
) -> Dict[str, Dict[str, str]]:
    """Return a plain ``{token_addr: {slot_hex: value_hex}}`` mapping.

    Backend-agnostic helper — caller wraps it into its own format
    (``stateDiff`` for eth_call, ``state_objects.storage`` for Tenderly,
    ``anvil_setStorageAt`` RPC for local Anvil).

    Covers all balance-slots in ``_effective_balance_slots()`` and for
    each tries allowance offsets {+1, +0, +2, +3, +4} so proxy/dense/
    upgradeable ERC-20 layouts are all seeded in one call.
    """
    large_value = "0x" + amount.to_bytes(32, "big").hex()
    max_allowance = "0x" + (2**256 - 1).to_bytes(32, "big").hex()

    slots: Dict[str, str] = {}
    for base_slot in _effective_balance_slots():
        bal_slot = _compute_mapping_slot(holder, base_slot)
        slots[bal_slot] = large_value
        for allowance_offset in [1, 0, 2, 3, 4]:
            allow_slot = _compute_allowance_slot(holder, router, base_slot + allowance_offset)
            slots[allow_slot] = max_allowance

    return {token_in_addr.lower(): slots}


def extract_token_in_from_calldata(calldata: bytes) -> Optional[str]:
    """Recover ``token_in`` address from swap calldata.

    Supports Uniswap V3 ``exactInputSingle`` (selectors 0x04e45aaf and
    0x414bf389) and Velodrome V2 ``swapExactTokensForTokens`` (selector
    0xcac88ea9).  Returns ``None`` for unrecognised calldata.
    """
    if len(calldata) < 36:
        return None
    try:
        selector = calldata[:4]
        _VE33_SELECTOR = bytes.fromhex("cac88ea9")
        if selector == _VE33_SELECTOR and len(calldata) >= 260:
            routes_offset = int.from_bytes(calldata[68:100], "big")
            route0_from_start = 4 + routes_offset + 32
            addr_bytes = calldata[route0_from_start:route0_from_start + 32]
        else:
            addr_bytes = calldata[4:36]
        return "0x" + addr_bytes.hex().lstrip("0").zfill(40)
    except Exception:
        return None


def _build_state_overrides(
    token_in_addr: str,
    holder: str,
    router: str,
    amount: int = 10**30,
) -> Dict:
    """Build eth_call stateOverride for ERC-20 balance + allowance seeding.

    Wraps :func:`build_slot_map` into the standard eth_call ``stateDiff``
    envelope.
    """
    slot_map = build_slot_map(token_in_addr, holder, router, amount=amount)
    # Convert to {token: {stateDiff: {...}}}
    return {addr: {"stateDiff": slots} for addr, slots in slot_map.items()}


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
    """Send JSON-RPC request. Returns (result_dict, error_str).

    Returns the HTTP status code embedded in the error string when non-200,
    so callers can detect 429 and attempt fallback.
    """
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
            err_obj = data["error"]
            msg = err_obj.get("message", str(err_obj))[:200]
            # E1.32/C2-extended: Many RPCs (Alchemy, Infura, publicnode) place
            # the revert payload in ``error.data`` (bare hex) while the message
            # stays generic "execution reverted". Combine both so the decoder
            # can reach Error(string)/Panic/custom-selector data.
            raw_data = err_obj.get("data")
            if raw_data:
                if isinstance(raw_data, dict):
                    raw_data = raw_data.get("data") or raw_data.get("originalError", {}).get("data") or ""
                if isinstance(raw_data, str) and raw_data.startswith("0x") and len(raw_data) > 2:
                    # Preserve original message, append payload so the decoder
                    # sees "execution reverted: 0x..." even when the RPC split them.
                    if "0x" not in msg:
                        msg = f"{msg}: {raw_data[:400]}"
            return None, msg[:600]
        return data, None
    except Exception as e:
        return None, str(e)[:200]


# Alternative public HTTP endpoints for sim fallback on 429.
_SIM_FALLBACK_HTTP: Dict[str, str] = {
    "base": "https://base-rpc.publicnode.com",
    "arbitrum_one": "https://arbitrum-one-rpc.publicnode.com",
}


# ---------------------------------------------------------------------------
# E1.27/C2: Revert reason decoder
# ---------------------------------------------------------------------------

def _decode_revert_reason(raw_error: str) -> str:
    """Decode Solidity revert reason from RPC error message.

    RPC nodes embed revert data in error messages in various formats:
      - "execution reverted: Too little received"  (human-readable)
      - "execution reverted: 0x08c379a0..."        (ABI-encoded Error(string))
      - "execution reverted"                        (no data)
    """
    # E1.32: Known custom-error selectors surfaced by common routers.
    # Mapping selector (4 bytes, hex w/ 0x) → stable classification tag.
    _CUSTOM_ERROR_SELECTORS = {
        # Uniswap V3 SwapRouter / PositionManager
        "0xf4d678b8": "INSUFFICIENT_OUTPUT_AMOUNT",   # Too little received
        "0x39d35496": "PRICE_LIMIT",                   # SPL (sqrtPriceLimit)
        "0x3994d14e": "AMOUNT_SPECIFIED_ZERO",
        "0xc45a0155": "POOL_NOT_INITIALIZED",
        # ERC20 SafeTransferFrom / Permit2
        "0xf4059071": "STF",                           # safeTransferFrom failed
        "0xe450d38c": "INSUFFICIENT_BALANCE",
        "0x13e45317": "INSUFFICIENT_ALLOWANCE",
        # Aerodrome / Velodrome router
        "0x7c41cbe1": "INSUFFICIENT_OUTPUT_AMOUNT",
        "0x749b5939": "INVALID_PATH",
        # P0 (2026-04-20): Common Uniswap/Permit2/router custom errors
        "0xfb8f41b2": "INSUFFICIENT_ALLOWANCE",         # ERC20InsufficientAllowance
        "0xe602df05": "INSUFFICIENT_ALLOWANCE",         # ERC20: insufficient allowance
        "0xea553b34": "DEADLINE_EXPIRED",               # TransactionDeadlinePassed
        "0x48f5c3ed": "DEADLINE_EXPIRED",               # Expired
        "0xf4844814": "UNAUTHORIZED",
        "0x9996b315": "UNAUTHORIZED",
        "0x8f4eb604": "INVALID_SIGNATURE",
        "0xbfb22adf": "PERMIT_EXPIRED",
        "0x8baa579f": "INVALID_SIGNATURE",
    }

    # E1.32: Known inline substrings (case-insensitive) → tag.
    # Ordered: most-specific first. Very-short tags checked separately below
    # as exact tokens to avoid false matches (e.g. "as" inside "class").
    _INLINE_PATTERNS = [
        ("too little received", "SLIPPAGE"),
        ("too much requested", "SLIPPAGE"),
        ("insufficient_output_amount", "SLIPPAGE"),
        ("insufficient output amount", "SLIPPAGE"),
        ("minimum_output_amount", "SLIPPAGE"),
        ("sqrtpricelimit", "PRICE_LIMIT"),
        ("price_limit", "PRICE_LIMIT"),
        ("transferhelper::safetransferfrom", "STF"),
        ("safetransferfrom", "STF"),
        ("transfer_from_failed", "STF"),
        ("erc20: transfer amount exceeds allowance", "INSUFFICIENT_ALLOWANCE"),
        ("insufficient allowance", "INSUFFICIENT_ALLOWANCE"),
        ("erc20: transfer amount exceeds balance", "INSUFFICIENT_BALANCE"),
        ("insufficient balance", "INSUFFICIENT_BALANCE"),
        ("transaction too old", "DEADLINE_EXPIRED"),
        ("deadline exceeded", "DEADLINE_EXPIRED"),
        ("expired", "DEADLINE_EXPIRED"),
        ("insufficient_liquidity", "INSUFFICIENT_LIQUIDITY"),
        ("insufficient liquidity", "INSUFFICIENT_LIQUIDITY"),
        ("pool not initialized", "POOL_NOT_INITIALIZED"),
        ("reentrancy", "REENTRANCY"),
    ]

    # Standalone short tokens that are themselves valid Uniswap/Aerodrome
    # revert strings. Checked as exact (whitespace or end-bounded) to avoid
    # substring false positives.
    _EXACT_TOKEN_TAGS = {
        "stf": "STF",
        "spl": "PRICE_LIMIT",
        "lok": "POOL_LOCKED",
        "as": "POOL_NOT_INITIALIZED",
        "ai": "AMOUNT_IN_ZERO",
        "ao": "AMOUNT_OUT_ZERO",
        "l": "INSUFFICIENT_LIQUIDITY",
        "ti": "TOKEN_INVALID",
    }

    # Case 1: Already human-readable after "execution reverted: "
    _prefix = "execution reverted: "
    idx = raw_error.lower().find(_prefix.lower())
    if idx >= 0:
        after = raw_error[idx + len(_prefix):].strip()
        if after and not after.startswith("0x"):
            # Try inline pattern match for known error strings.
            low = after.lower()
            # Exact-token match first (whole message IS the token).
            tok = low.strip(" .\"'`")
            if tok in _EXACT_TOKEN_TAGS:
                return f"REVERT:{_EXACT_TOKEN_TAGS[tok]}"
            for pat, tag in _INLINE_PATTERNS:
                if pat in low:
                    return f"REVERT:{tag}"
            return f"REVERT:{after[:200]}"
        # Case 2: ABI-encoded Error(string) — selector 0x08c379a0
        if after.startswith("0x08c379a0") and len(after) >= 138:
            try:
                hex_data = after[2:]  # strip 0x
                # Error(string): selector(8) + offset(64) + length(64) + data
                str_len = int(hex_data[72:136], 16)
                str_bytes = bytes.fromhex(hex_data[136:136 + str_len * 2])
                decoded = str_bytes.decode("utf-8", errors="replace").strip()
                if decoded:
                    low = decoded.lower()
                    tok = low.strip(" .\"'`")
                    if tok in _EXACT_TOKEN_TAGS:
                        return f"REVERT:{_EXACT_TOKEN_TAGS[tok]}"
                    for pat, tag in _INLINE_PATTERNS:
                        if pat in low:
                            return f"REVERT:{tag}"
                    return f"REVERT:{decoded[:200]}"
            except Exception:
                pass
        # Case 3: ABI-encoded Panic(uint256) — selector 0x4e487b71
        if after.startswith("0x4e487b71") and len(after) >= 74:
            try:
                panic_code = int(after[10:74], 16)
                _PANIC_CODES = {
                    0x00: "generic",
                    0x01: "assert_failed",
                    0x11: "overflow",
                    0x12: "div_by_zero",
                    0x21: "enum_conversion",
                    0x22: "storage_encoding",
                    0x31: "pop_empty",
                    0x32: "index_out_of_bounds",
                    0x41: "too_much_memory",
                    0x51: "zero_init_fn_ptr",
                }
                desc = _PANIC_CODES.get(panic_code, f"code_{panic_code}")
                return f"PANIC:{desc}"
            except Exception:
                pass
        # E1.32: Case 4 — custom error selector (4 bytes).
        if after.startswith("0x") and len(after) >= 10:
            selector = after[:10].lower()
            tag = _CUSTOM_ERROR_SELECTORS.get(selector)
            if tag:
                return f"REVERT:{tag}"
        if after:
            return f"REVERT:hex:{after[:200]}"

    # E1.32: Case 5 — no "execution reverted: " prefix, but message itself
    # contains a known pattern or bare hex payload.
    low = raw_error.lower()
    for pat, tag in _INLINE_PATTERNS:
        if pat in low:
            return f"REVERT:{tag}"
    # Bare hex payload embedded anywhere
    import re as _re
    m = _re.search(r"0x[0-9a-fA-F]{8,}", raw_error)
    if m:
        hex_blob = m.group(0).lower()
        selector = hex_blob[:10]
        tag = _CUSTOM_ERROR_SELECTORS.get(selector)
        if tag:
            return f"REVERT:{tag}"
        if hex_blob.startswith("0x08c379a0") and len(hex_blob) >= 138:
            # Try Error(string) even when not prefixed
            try:
                hex_data = hex_blob[2:]
                str_len = int(hex_data[72:136], 16)
                str_bytes = bytes.fromhex(hex_data[136:136 + str_len * 2])
                decoded = str_bytes.decode("utf-8", errors="replace").strip()
                if decoded:
                    inner = decoded.lower()
                    tok = inner.strip(" .\"'`")
                    if tok in _EXACT_TOKEN_TAGS:
                        return f"REVERT:{_EXACT_TOKEN_TAGS[tok]}"
                    for pat, tag in _INLINE_PATTERNS:
                        if pat in inner:
                            return f"REVERT:{tag}"
                    return f"REVERT:{decoded[:200]}"
            except Exception:
                pass
        return f"REVERT:hex:{hex_blob[:200]}"
    # P0 (2026-04-20): fallback surfaces short fingerprint of raw_error so
    # histogram buckets stay diagnosable even when no pattern matches.
    _trim = (raw_error or "").strip().replace("\n", " ")[:200]
    if _trim:
        logger.warning("REVERT:unknown | raw_error=%s", raw_error)
        return f"REVERT:unknown:{_trim}"
    logger.warning("REVERT:unknown | raw_error is empty or None")
    return "REVERT:unknown"


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
    # E1.36 P1: Helper moved to extract_token_in_from_calldata() (shared
    # with Tenderly backend).
    state_overrides: Dict = {}
    if len(calldata) >= 36 and from_address != "0x" + "0" * 40:
        try:
            token_in_hex = extract_token_in_from_calldata(calldata)
            if token_in_hex:
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

    # E1.23: Fallback to alternative public RPC on 429 rate limit.
    if call_err and "HTTP 429" in call_err:
        fallback_url = _SIM_FALLBACK_HTTP.get(chain)
        if fallback_url and fallback_url != rpc_url:
            logger.info(
                "rpc_fork 429 on primary, retrying sim via fallback (%s)",
                fallback_url.split("//")[-1][:40],
            )
            params[1] = "latest"  # ensure standard block tag
            data, call_err = _json_rpc(fallback_url, "eth_call", params)
            if not call_err:
                sim_url = fallback_url

    if call_err:
        revert_reason = None
        if "revert" in call_err.lower() or "execution reverted" in call_err.lower():
            revert_reason = _decode_revert_reason(call_err)
        # E1: Diagnostic logging for STF reverts — shows which token/router/pool
        # is failing safeTransferFrom despite state overrides. Helps identify
        # non-standard token layouts that need explicit slot mapping.
        if revert_reason and "STF" in revert_reason:
            _tin = state_overrides and list(state_overrides.keys())[0] or "?"
            logger.warning(
                "rpc_fork STF revert: token_in=%s router=%s from=%s amount=%d",
                _tin[:42], to_address[:18], from_address[:18],
                int.from_bytes(calldata[4:36], "big") if len(calldata) >= 36 else 0,
            )
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

    # E1.27/D1: Extract input_amount from calldata. Note: profit_bps cannot be
    # computed from single-leg sim because token_in and token_out have different
    # decimals. We report raw values only; caller must compare against scored
    # expected output or do round-trip sim to derive profit.
    input_amount = 0
    if len(calldata) >= 36:
        try:
            selector = calldata[:4]
            _VE33_SEL = bytes.fromhex("cac88ea9")
            _V2_SEL = bytes.fromhex("04e45aaf")   # SwapRouter02 exactInputSingle
            _V1_SEL = bytes.fromhex("414bf389")   # SwapRouter  exactInputSingle (legacy)
            if selector == _VE33_SEL:
                input_amount = int.from_bytes(calldata[4:36], "big")
            elif selector == _V1_SEL and len(calldata) >= 196:
                input_amount = int.from_bytes(calldata[4 + 160:4 + 192], "big")
            elif len(calldata) >= 164:
                input_amount = int.from_bytes(calldata[4 + 128:4 + 160], "big")
        except Exception:
            pass

    logger.info(
        "rpc_fork sim OK: chain=%s, gas=%d, input_wei=%d, output_wei=%d, backend=%s",
        chain, gas, input_amount, output_amount, backend_label,
    )

    return SimulationResult(
        success=True,
        gas_used=gas,
        output_amount_wei=output_amount,
        input_amount_wei=input_amount,
        backend=backend_label,
    )
