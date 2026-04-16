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
        # E1 widened coverage — should have at least len(_COMMON_BALANCE_SLOTS) balance
        # slots plus multiple allowance offsets.
        assert len(diff) >= len(_COMMON_BALANCE_SLOTS)

    def test_extra_balance_slots_from_env(self, monkeypatch):
        """E1: ARBY_SIM_EXTRA_BALANCE_SLOTS augments _COMMON_BALANCE_SLOTS."""
        from m7.orderflow.sim_backends.rpc_fork_backend import (
            _effective_balance_slots, _COMMON_BALANCE_SLOTS,
        )
        monkeypatch.setenv("ARBY_SIM_EXTRA_BALANCE_SLOTS", "200,201,202")
        slots = _effective_balance_slots()
        assert 200 in slots and 201 in slots and 202 in slots
        for base in _COMMON_BALANCE_SLOTS:
            assert base in slots

    def test_extra_balance_slots_invalid_env_ignored(self, monkeypatch):
        from m7.orderflow.sim_backends.rpc_fork_backend import (
            _effective_balance_slots, _COMMON_BALANCE_SLOTS,
        )
        monkeypatch.setenv("ARBY_SIM_EXTRA_BALANCE_SLOTS", "not-an-int")
        slots = _effective_balance_slots()
        assert slots == list(_COMMON_BALANCE_SLOTS)


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


class TestE120FlashblocksPreconf:
    """E1.20: Flashblocks pre-confirmed state via ``pending`` block tag."""

    def test_flashblocks_disabled_by_default(self, monkeypatch):
        """Without ARBY_FLASHBLOCKS_SIM=1, uses standard rpc_fork."""
        monkeypatch.delenv("ARBY_FLASHBLOCKS_SIM", raising=False)
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_rpc_url",
            lambda chain: "http://standard:8545",
        )

        captured = {}

        def mock_json_rpc(url, method, params, timeout=10.0):
            if method == "eth_call":
                captured["url"] = url
                captured["block_tag"] = params[1]
                return {"result": "0x" + "00" * 32}, None
            return {"result": "0x0"}, None

        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._json_rpc",
            mock_json_rpc,
        )
        from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork
        result = simulate_swap_rpc_fork(chain="base")
        assert result.backend == "rpc_fork"
        assert captured["url"] == "http://standard:8545"
        assert captured["block_tag"] == "latest"

    def test_flashblocks_enabled_uses_pending(self, monkeypatch):
        """ARBY_FLASHBLOCKS_SIM=1 → preconf URL + ``pending`` block tag."""
        monkeypatch.setenv("ARBY_FLASHBLOCKS_SIM", "1")
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_rpc_url",
            lambda chain: "http://standard:8545",
        )
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_flashblocks_http_url",
            lambda chain: "https://mainnet-preconf.base.org",
        )

        captured = {}

        def mock_json_rpc(url, method, params, timeout=10.0):
            if method == "eth_call":
                captured["url"] = url
                captured["block_tag"] = params[1]
                return {"result": "0x" + "00" * 32}, None
            return {"result": "0x0"}, None

        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._json_rpc",
            mock_json_rpc,
        )
        from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork
        result = simulate_swap_rpc_fork(chain="base")
        assert result.backend == "rpc_fork_preconf"
        assert captured["url"] == "https://mainnet-preconf.base.org"
        assert captured["block_tag"] == "pending"

    def test_flashblocks_fallback_on_failure(self, monkeypatch):
        """When Flashblocks endpoint fails, falls back to standard RPC."""
        monkeypatch.setenv("ARBY_FLASHBLOCKS_SIM", "1")
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_rpc_url",
            lambda chain: "http://standard:8545",
        )
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_flashblocks_http_url",
            lambda chain: "https://mainnet-preconf.base.org",
        )

        call_log = []

        def mock_json_rpc(url, method, params, timeout=10.0):
            call_log.append((url, method, params[1] if len(params) > 1 else None))
            if method == "eth_call" and "preconf" in url:
                return None, "HTTP 429: rate limited"
            if method == "eth_call":
                return {"result": "0x" + (100).to_bytes(32, "big").hex()}, None
            return {"result": "0x0"}, None

        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._json_rpc",
            mock_json_rpc,
        )
        from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork
        result = simulate_swap_rpc_fork(chain="base")
        assert result.success
        # First call = preconf (fails), second call = standard (succeeds)
        assert len([c for c in call_log if c[1] == "eth_call"]) == 2
        assert call_log[0][0] == "https://mainnet-preconf.base.org"
        assert call_log[0][2] == "pending"
        assert call_log[1][0] == "http://standard:8545"
        assert call_log[1][2] == "latest"
        # Backend label reflects fallback
        assert result.backend == "rpc_fork"

    def test_flashblocks_not_on_arbitrum(self, monkeypatch):
        """ARBY_FLASHBLOCKS_SIM=1 has no effect on non-Base chains."""
        monkeypatch.setenv("ARBY_FLASHBLOCKS_SIM", "1")
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_rpc_url",
            lambda chain: "http://arb:8545",
        )

        captured = {}

        def mock_json_rpc(url, method, params, timeout=10.0):
            if method == "eth_call":
                captured["url"] = url
                captured["block_tag"] = params[1]
                return {"result": "0x" + "00" * 32}, None
            return {"result": "0x0"}, None

        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._json_rpc",
            mock_json_rpc,
        )
        from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork
        result = simulate_swap_rpc_fork(chain="arbitrum_one")
        assert result.backend == "rpc_fork"
        assert captured["url"] == "http://arb:8545"
        assert captured["block_tag"] == "latest"

    def test_flashblocks_skipped_when_explicit_block(self, monkeypatch):
        """Explicit block_number disables Flashblocks pending."""
        monkeypatch.setenv("ARBY_FLASHBLOCKS_SIM", "1")
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_rpc_url",
            lambda chain: "http://standard:8545",
        )

        captured = {}

        def mock_json_rpc(url, method, params, timeout=10.0):
            if method == "eth_call":
                captured["url"] = url
                captured["block_tag"] = params[1]
                return {"result": "0x" + "00" * 32}, None
            return {"result": "0x0"}, None

        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._json_rpc",
            mock_json_rpc,
        )
        from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork
        result = simulate_swap_rpc_fork(chain="base", block_number=44739000)
        assert result.backend == "rpc_fork"
        assert captured["url"] == "http://standard:8545"
        assert captured["block_tag"] == hex(44739000)

    def test_is_flashblocks_sim_enabled_flag(self, monkeypatch):
        from m7.orderflow.sim_backends.rpc_fork_backend import _is_flashblocks_sim_enabled
        monkeypatch.delenv("ARBY_FLASHBLOCKS_SIM", raising=False)
        assert _is_flashblocks_sim_enabled() is False
        monkeypatch.setenv("ARBY_FLASHBLOCKS_SIM", "0")
        assert _is_flashblocks_sim_enabled() is False
        monkeypatch.setenv("ARBY_FLASHBLOCKS_SIM", "1")
        assert _is_flashblocks_sim_enabled() is True


# ---------------------------------------------------------------------------
# E1.27/D1: Raw sim input/output amounts (profit_bps removed due to decimals bug)
# ---------------------------------------------------------------------------

class TestSimProfitExtraction:
    """D1: raw input_amount_wei and output_amount_wei are captured correctly."""

    def test_v2_profit_calculated(self, monkeypatch):
        """V2 exactInputSingle: input_amount_wei decoded from calldata."""
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_rpc_url",
            lambda chain: "http://fake:8545",
        )
        _sel_v2 = bytes.fromhex("04e45aaf")
        _amount_in = 1_000_000  # 1 USDC (6 dec)
        _calldata = (
            _sel_v2
            + b"\x00" * 32  # tokenIn
            + b"\x00" * 32  # tokenOut
            + b"\x00" * 32  # fee
            + b"\x00" * 32  # recipient
            + _amount_in.to_bytes(32, "big")  # amountIn
            + b"\x00" * 32  # amountOutMin
            + b"\x00" * 32  # sqrtPriceLimit
        )
        output_hex = "0x" + (1_005_000).to_bytes(32, "big").hex()

        def mock_json_rpc(url, method, params, timeout=10.0):
            if method == "eth_call":
                return {"result": output_hex}, None
            if method == "eth_estimateGas":
                return {"result": hex(150_000)}, None
            return None, "unknown"

        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._json_rpc",
            mock_json_rpc,
        )
        from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork
        result = simulate_swap_rpc_fork(
            chain="base",
            from_address="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            to_address="0x2626664c2603336E57B271c5C0b26F421741e481",
            calldata=_calldata,
        )
        assert result.success
        assert result.input_amount_wei == 1_000_000
        assert result.output_amount_wei == 1_005_000
        # D1: sim_profit_bps fields removed due to cross-decimals bug.
        assert not hasattr(result, "sim_profit_bps")

    def test_negative_profit(self, monkeypatch):
        """Negative profit (output < input) reported honestly."""
        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._get_rpc_url",
            lambda chain: "http://fake:8545",
        )
        _sel_v2 = bytes.fromhex("04e45aaf")
        _amount_in = 1_000_000
        _calldata = (
            _sel_v2
            + b"\x00" * 128  # 4 params * 32 bytes
            + _amount_in.to_bytes(32, "big")
            + b"\x00" * 64  # 2 more params
        )
        output_hex = "0x" + (990_000).to_bytes(32, "big").hex()

        def mock_json_rpc(url, method, params, timeout=10.0):
            if method == "eth_call":
                return {"result": output_hex}, None
            if method == "eth_estimateGas":
                return {"result": hex(150_000)}, None
            return None, "unknown"

        monkeypatch.setattr(
            "m7.orderflow.sim_backends.rpc_fork_backend._json_rpc",
            mock_json_rpc,
        )
        from m7.orderflow.sim_backends.rpc_fork_backend import simulate_swap_rpc_fork
        result = simulate_swap_rpc_fork(
            chain="base",
            from_address="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            to_address="0x2626664c2603336E57B271c5C0b26F421741e481",
            calldata=_calldata,
        )
        assert result.success
        assert result.input_amount_wei == 1_000_000
        assert result.output_amount_wei == 990_000


# ---------------------------------------------------------------------------
# E1.27/C2: Revert reason decoding
# ---------------------------------------------------------------------------

class TestRevertReasonDecoding:
    """C2: _decode_revert_reason parses Solidity Error/Panic from RPC errors."""

    def test_human_readable_revert(self):
        from m7.orderflow.sim_backends.rpc_fork_backend import _decode_revert_reason
        result = _decode_revert_reason("execution reverted: Too little received")
        assert result == "REVERT:Too little received"

    def test_stf_revert(self):
        from m7.orderflow.sim_backends.rpc_fork_backend import _decode_revert_reason
        result = _decode_revert_reason("execution reverted: STF")
        assert result == "REVERT:STF"

    def test_abi_encoded_error_string(self):
        from m7.orderflow.sim_backends.rpc_fork_backend import _decode_revert_reason
        hex_data = (
            "08c379a0"
            + "0000000000000000000000000000000000000000000000000000000000000020"
            + "0000000000000000000000000000000000000000000000000000000000000003"
            + "5354460000000000000000000000000000000000000000000000000000000000"
        )
        raw = f"execution reverted: 0x{hex_data}"
        result = _decode_revert_reason(raw)
        assert result == "REVERT:STF"

    def test_panic_overflow(self):
        from m7.orderflow.sim_backends.rpc_fork_backend import _decode_revert_reason
        hex_data = "4e487b71" + "0000000000000000000000000000000000000000000000000000000000000011"
        raw = f"execution reverted: 0x{hex_data}"
        result = _decode_revert_reason(raw)
        assert result == "PANIC:overflow"

    def test_bare_revert(self):
        from m7.orderflow.sim_backends.rpc_fork_backend import _decode_revert_reason
        result = _decode_revert_reason("execution reverted")
        assert result == "REVERT:unknown"


# ---------------------------------------------------------------------------
# E2: Round-trip simulation fields on SimulationResult
# ---------------------------------------------------------------------------

class TestRoundTripFields:
    """E2: SimulationResult carries round-trip (buy+sell) fields."""

    def test_default_roundtrip_fields(self):
        from m7.orderflow.simulation import SimulationResult
        r = SimulationResult(success=True)
        assert r.roundtrip_attempted is False
        assert r.roundtrip_success is False
        assert r.roundtrip_final_wei == 0
        assert r.roundtrip_profit_wei == 0
        assert r.roundtrip_profit_bps == 0.0
        assert r.roundtrip_sell_revert_reason is None

    def test_profitable_roundtrip_bps_positive(self):
        from m7.orderflow.simulation import SimulationResult
        r = SimulationResult(
            success=True,
            input_amount_wei=1_000_000,
            output_amount_wei=500_000,
            roundtrip_attempted=True,
            roundtrip_success=True,
            roundtrip_final_wei=1_005_000,
            roundtrip_profit_wei=5_000,
            roundtrip_profit_bps=50.0,
        )
        assert r.roundtrip_profit_bps > 0
        assert r.roundtrip_final_wei > r.input_amount_wei

    def test_sell_leg_builder_fee_check(self):
        """E2: _build_sell_leg_tx_params rejects unsupported fees."""
        from dataclasses import dataclass
        from m7.orderflow.execution_gate import _build_sell_leg_tx_params

        @dataclass
        class _FakeResult:
            best_sell_venue: str = "uniswap_v3"
            best_sell_fee: int = 2655  # non-standard Algebra dynamic
            best_buy_fee: int = 2655
            backrun_token_in_address: str = "0x4200000000000000000000000000000000000006"
            backrun_token_out_address: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

        tx, err = _build_sell_leg_tx_params(_FakeResult(), 1_000_000, chain="base")
        assert tx is None
        assert err is not None and "UNSUPPORTED" in err

    def test_sell_leg_builder_zero_input(self):
        from dataclasses import dataclass
        from m7.orderflow.execution_gate import _build_sell_leg_tx_params

        @dataclass
        class _FakeResult:
            best_sell_venue: str = "uniswap_v3"
            best_sell_fee: int = 500

        tx, err = _build_sell_leg_tx_params(_FakeResult(), 0, chain="base")
        assert tx is None and err == "SELL_INPUT_ZERO"


# ---------------------------------------------------------------------------
# E3: Rollup migration drops deprecated sim_profit_bps keys
# ---------------------------------------------------------------------------

class TestRollupMigration:
    def test_deprecated_keys_stripped(self, tmp_path, monkeypatch):
        import json as _json
        import m7.orderflow.runtime_io as _rio
        import m7.orderflow.hot_runtime_artifacts as _hra

        _rollup = tmp_path / "hot_rollup.json"
        _rollup.write_text(_json.dumps({
            "last_updated": "2026-04-16T00:00:00Z",
            "windows_seen": 5,
            "_sim_profit_bps_all": [-9999.9, -10000.0],
            "sim_profit_bps_best": -9999.9,
            "sim_profit_bps_worst": -10000.0,
            "sim_profit_bps_median": -9999.95,
            "sim_profitable_count": 0,
        }))

        monkeypatch.setattr(_rio, "_HOT_ROLLUP_PATH", str(_rollup))
        monkeypatch.setattr(_rio, "_SESSION_ID", "test-session")
        _hra._update_hot_rollup(
            chain="base", events_count=0,
            fast_results=None, guard_results=None,
            bridge_diagnostics=None, ws_live_stats=None,
        )
        data = _json.loads(_rollup.read_text())
        for k in [
            "_sim_profit_bps_all",
            "sim_profit_bps_best",
            "sim_profit_bps_worst",
            "sim_profit_bps_median",
            "sim_profitable_count",
        ]:
            assert k not in data
