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

    # E1.35 P1.5: freshness telemetry.
    # * ``sim_block_number`` — block against which the sim was executed
    #   (None when backend does not expose it, e.g. Tenderly quick).
    # * ``event_block_number`` — event.block_number at sim time.
    # * ``block_lag_at_sim`` — sim_block − event_block when both known.
    # Consumers (execution_gate) use this to reject stale submits.
    sim_block_number: Optional[int] = None
    event_block_number: Optional[int] = None
    block_lag_at_sim: Optional[int] = None
    freshness_violation: bool = False

    @property
    def passed(self) -> bool:
        return self.success and self.revert_reason is None


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

# E1.34 P0.1: Profile-specific env override.
# When profile="discovery", ARBY_SIM_BACKEND_DISC takes precedence over
# ARBY_SIM_BACKEND. This lets operators flip DISC lane to rpc_fork/anvil
# (no credit limits, no HTTP 403) while keeping PROD on Tenderly.
_PROFILE_ENV = {
    "discovery": "ARBY_SIM_BACKEND_DISC",
    "disc": "ARBY_SIM_BACKEND_DISC",
    "prod": "ARBY_SIM_BACKEND_PROD",
    "production": "ARBY_SIM_BACKEND_PROD",
}


def get_simulation_backend(profile: Optional[str] = None) -> str:
    """Return the active simulation backend name.

    E1.34 P0.1: Profile-aware selection.
    - If ``profile`` is given (e.g. "discovery"/"prod") and its profile-specific
      env var (``ARBY_SIM_BACKEND_DISC`` / ``ARBY_SIM_BACKEND_PROD``) is set
      to a valid backend, that wins.
    - Otherwise falls back to ``ARBY_SIM_BACKEND``.
    - Default: ``rpc_fork`` (Tenderly is opt-in via ARBY_SIM_BACKEND=tenderly).

    Unknown profile-env values log a warning and fall through to the generic
    ``ARBY_SIM_BACKEND`` selector (not silently dropped to tenderly).
    """
    if profile:
        env_name = _PROFILE_ENV.get(profile.strip().lower())
        if env_name:
            override = os.environ.get(env_name, "").strip().lower()
            if override:
                if override in _VALID_BACKENDS:
                    return override
                logger.warning(
                    "Unknown %s=%r, falling back to ARBY_SIM_BACKEND", env_name, override
                )
    raw = os.environ.get("ARBY_SIM_BACKEND", BACKEND_RPC_FORK).strip().lower()
    if raw in _VALID_BACKENDS:
        return raw
    logger.warning("Unknown ARBY_SIM_BACKEND=%r, falling back to rpc_fork", raw)
    return BACKEND_RPC_FORK


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


def is_simulation_configured(profile: Optional[str] = None) -> bool:
    """Generic readiness check for the currently selected backend.

    E1.34 P0.1: Accepts optional ``profile`` (passed through to
    :func:`get_simulation_backend`) so callers in DISC vs PROD lanes
    validate the right backend.
    """
    backend = get_simulation_backend(profile=profile)
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

    # E1.36 P1: inject ERC-20 balance + allowance overrides into Tenderly
    # simulation.  Without these, the sim EOA has 0 balance and STF reverts
    # every swap.  Uses the same slot-map builder as rpc_fork_backend.
    # Opt-out via ARBY_SIM_DISABLE_STATE_OVERRIDE=1 for debugging.
    if (
        os.environ.get("ARBY_SIM_DISABLE_STATE_OVERRIDE", "").strip() != "1"
        and len(calldata) >= 36
        and from_address != "0x" + "0" * 40
    ):
        try:
            from m7.orderflow.sim_backends.rpc_fork_backend import (
                build_slot_map,
                extract_token_in_from_calldata,
            )
            _token_in = extract_token_in_from_calldata(calldata)
            if _token_in:
                _slot_map = build_slot_map(
                    token_in_addr=_token_in,
                    holder=from_address,
                    router=to_address,
                )
                # Tenderly format: state_objects.<addr>.storage.<slot> = value
                payload["state_objects"] = {
                    _addr: {"storage": _slots}
                    for _addr, _slots in _slot_map.items()
                }
        except Exception as _so_exc:
            logger.debug("Tenderly state_objects build skipped: %s", str(_so_exc)[:100])

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

        # P0 (2026-04-20): Run Tenderly's raw ``error_message`` through the
        # unified revert decoder so histogram keys converge with rpc_fork
        # backend (e.g. "STF", "PRICE_LIMIT", "SLIPPAGE") rather than
        # leaving free-form strings that fragment the distribution.
        _raw_err = tx.get("error_message") if not status else None
        if _raw_err:
            try:
                from m7.orderflow.sim_backends.rpc_fork_backend import _decode_revert_reason
                _revert = _decode_revert_reason(_raw_err)
            except Exception:
                _revert = str(_raw_err)[:200]
        else:
            _revert = None

        return SimulationResult(
            success=bool(status),
            gas_used=tx.get("gas_used", 0),
            simulation_id=data.get("simulation", {}).get("id"),
            revert_reason=_revert,
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

    E1.35 P0.1: when the primary backend is ``tenderly`` and the call
    fails with an HTTP 4xx response (e.g. 403 "insufficient credits"),
    and ``ARBY_SIM_FALLBACK=rpc_fork`` is set, automatically retry once
    against the rpc_fork backend. This keeps PROD alive without operator
    intervention while Tenderly quota is being refilled.
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

    result = _simulate_swap_tenderly(
        chain=chain,
        from_address=from_address,
        to_address=to_address,
        calldata=calldata,
        value_wei=value_wei,
        block_number=block_number,
    )

    # E1.35 P0.1: auto-fallback on Tenderly quota/auth failures.
    _fallback = os.environ.get("ARBY_SIM_FALLBACK", "").strip().lower()
    if (
        not result.passed
        and _fallback == BACKEND_RPC_FORK
        and result.error
        and ("HTTP 4" in result.error or "HTTP 5" in result.error)
    ):
        logger.warning(
            "Tenderly backend error (%s) — falling back to rpc_fork",
            (result.error or "?")[:80],
        )
        try:
            from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork
            fb_result = simulate_swap_rpc_fork(
                chain=chain,
                from_address=from_address,
                to_address=to_address,
                calldata=calldata,
                value_wei=value_wei,
                block_number=block_number,
            )
            fb_result.backend = f"{BACKEND_RPC_FORK}:fallback_from_tenderly"
            return fb_result
        except Exception as exc:
            logger.warning("Fallback to rpc_fork also failed: %s", str(exc)[:120])

    return result
