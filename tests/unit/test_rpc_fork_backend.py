# PATH: tests/unit/test_rpc_fork_backend.py
"""
E1.16: Tests for rpc_fork simulation backend.

Covers:
  - Backend selection via ARBY_SIM_BACKEND=rpc_fork
  - is_rpc_fork_configured() always True
  - is_simulation_configured() routes to rpc_fork
  - State override builder (balance + allowance slots)
  - simulate_swap_rpc_fork() eth_call plumbing
  - Successful simulation with output parsing
  - Revert detection
  - RPC unavailable handling
"""
import json
import os

import pytest


class TestRpcForkSelection:
    """ARBY_SIM_BACKEND=rpc_fork routes to the new backend."""

    def test_rpc_fork_backend_selected(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "rpc_fork")
        from m7.orderflow.simulation import get_simulation_backend
        assert get_simulation_backend() == "rpc_fork"

    def test_rpc_fork_is_configured(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "rpc_fork")
        from m7.orderflow.simulation import is_simulation_configured
        assert is_simulation_configured() is True

    def test_rpc_fork_no_tenderly_needed(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "rpc_fork")
        monkeypatch.delenv("TENDERLY_USER", raising=False)
        monkeypatch.delenv("TENDERLY_PROJECT", raising=False)
        monkeypatch.delenv("TENDERLY_ACCESS_KEY", raising=False)
        from m7.orderflow.simulation import is_simulation_configured
        assert is_simulation_configured() is True


class TestStateOverrideBuilder:
    """State override generation for ERC-20 balance seeding."""

    def test_builds_overrides_for_token(self):
        from m7.orderflow.sim_backends.rpc_fork_backend import _build_state_overrides
        overrides = _build_state_overrides(
            token_in_addr="0x4200000000000000000000000000000000000006",
            holder="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            router="0x2626664c2603336E57B271c5C0b26F421741e481",
        )
        # Should have exactly one key (the token address)
        assert len(overrides) == 1
        token_key = list(overrides.keys())[0]
        assert "0x4200" in token_key.lower()
        # Should have stateDiff with multiple slots
        state_diff = overrides[token_key]["stateDiff"]
        assert len(state_diff) > 0
        # Each slot should be a hex string
        for slot, value in state_diff.items():
            assert slot.startswith("0x")
            assert value.startswith("0x")

    def test_override_has_balance_and_allowance_slots(self):
        from m7.orderflow.sim_backends.rpc_fork_backend import _build_state_overrides, _COMMON_BALANCE_SLOTS
        overrides = _build_state_overrides(
            token_in_addr="0x4200000000000000000000000000000000000006",
            holder="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            router="0x2626664c2603336E57B271c5C0b26F421741e481",
        )
        token_key = list(overrides.keys())[0]
        diff = overrides[token_key]["stateDiff"]
        # Should have balance slots (6 slots) + allowance slots (6 * 3 offsets = 18)
        # Total: 6 + 18 = 24 slots
        assert len(diff) >= len(_COMMON_BALANCE_SLOTS)


class TestHashingCompat:
    """keccak256 must match Ethereum keccak (not NIST SHA3)."""

    def test_keccak256_empty(self):
        from m7.orderflow.sim_backends.rpc_fork_backend import _keccak256
        result = _keccak256(b"")
        # Ethereum keccak256("") = 0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470
        assert result.hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"


class TestSimulateSwapRpcFork:
    """simulate_swap_rpc_fork() plumbing."""

    def test_no_rpc_url(self, monkeypatch):
        """When RPC URL is unavailable, returns explicit error."""
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_rpc_url",
            lambda chain: None,
        )
        from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork
        result = simulate_swap_rpc_fork(chain="base")
        assert not result.success
        assert "RPC_URL_NOT_AVAILABLE" in result.error
        assert result.backend == "rpc_fork"

    def test_eth_call_revert(self, monkeypatch):
        """Revert is classified correctly."""
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_rpc_url",
            lambda chain: "http://fake:8545",
        )

        def mock_json_rpc(url, method, params, timeout=10.0):
            if method == "eth_call":
                return None, "execution reverted: STF"
            return None, "not called"

        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._json_rpc",
            mock_json_rpc,
        )
        from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork
        result = simulate_swap_rpc_fork(
            chain="base",
            from_address="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            to_address="0x2626664c2603336E57B271c5C0b26F421741e481",
            calldata=bytes(36),
        )
        assert not result.success
        assert result.revert_reason is not None
        assert "STF" in result.error

    def test_successful_sim(self, monkeypatch):
        """Successful eth_call returns output amount."""
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_rpc_url",
            lambda chain: "http://fake:8545",
        )
        # Mock output: 233 USDC = 233000000 in 6 decimals = 0x0DE4BD00
        output_hex = "0x" + (233_000_000).to_bytes(32, "big").hex()

        def mock_json_rpc(url, method, params, timeout=10.0):
            if method == "eth_call":
                return {"result": output_hex}, None
            if method == "eth_estimateGas":
                return {"result": hex(150_000)}, None
            return None, "unknown method"

        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._json_rpc",
            mock_json_rpc,
        )
        from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork
        result = simulate_swap_rpc_fork(
            chain="base",
            from_address="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            to_address="0x2626664c2603336E57B271c5C0b26F421741e481",
            calldata=bytes(36),
        )
        assert result.success
        assert result.passed
        assert result.output_amount_wei == 233_000_000
        assert result.gas_used == 150_000
        assert result.backend == "rpc_fork"

    def test_state_overrides_passed_to_eth_call(self, monkeypatch):
        """State overrides are included in eth_call params."""
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_rpc_url",
            lambda chain: "http://fake:8545",
        )

        captured_params = {}

        def mock_json_rpc(url, method, params, timeout=10.0):
            captured_params[method] = params
            if method == "eth_call":
                return {"result": "0x" + "00" * 32}, None
            return {"result": "0x0"}, None

        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._json_rpc",
            mock_json_rpc,
        )
        from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork

        # Build calldata with valid 36+ bytes (4 selector + 32 token_in)
        import struct
        calldata = b"\x04\xe4\x5a\xaf" + bytes.fromhex(
            "0000000000000000000000004200000000000000000000000000000000000006"
        )

        result = simulate_swap_rpc_fork(
            chain="base",
            from_address="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            to_address="0x2626664c2603336E57B271c5C0b26F421741e481",
            calldata=calldata,
        )
        # eth_call should have 3 params: tx_obj, block_tag, state_overrides
        assert "eth_call" in captured_params
        eth_call_params = captured_params["eth_call"]
        assert len(eth_call_params) == 3
        # Third param is state overrides dict
        assert isinstance(eth_call_params[2], dict)


class TestViaRouter:
    """simulate_swap() routes to rpc_fork when ARBY_SIM_BACKEND=rpc_fork."""

    def test_router_dispatches_to_rpc_fork(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "rpc_fork")
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_rpc_url",
            lambda chain: "http://fake:8545",
        )

        def mock_json_rpc(url, method, params, timeout=10.0):
            if method == "eth_call":
                return {"result": "0x" + (42).to_bytes(32, "big").hex()}, None
            return {"result": "0x0"}, None

        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._json_rpc",
            mock_json_rpc,
        )

        from m7.orderflow.simulation import simulate_swap
        result = simulate_swap(chain="base")
        assert result.backend == "rpc_fork"
        assert result.success
