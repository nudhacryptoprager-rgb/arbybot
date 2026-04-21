# PATH: tests/unit/test_anvil_backend.py
"""
E1.12.4A: Tests for Anvil simulation backend + backend router.

Covers:
  - Backend selection via ARBY_SIM_BACKEND
  - is_anvil_configured() / is_simulation_configured() routing
  - simulate_swap_anvil() eth_call + estimateGas plumbing
  - check_anvil_connection() health probe
  - Error normalization (revert vs generic)
  - SimulationResult.backend field
"""

import json
import os

import pytest


class TestBackendSelection:
    """ARBY_SIM_BACKEND env var controls which backend is active."""

    def test_default_is_tenderly(self, monkeypatch):
        monkeypatch.delenv("ARBY_SIM_BACKEND", raising=False)
        from m7.orderflow.simulation import get_simulation_backend
        assert get_simulation_backend() == "tenderly"

    def test_anvil_backend_selected(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "anvil")
        from m7.orderflow.simulation import get_simulation_backend
        assert get_simulation_backend() == "anvil"

    def test_unknown_backend_falls_to_tenderly(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "geth_debug")
        from m7.orderflow.simulation import get_simulation_backend
        assert get_simulation_backend() == "tenderly"

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "ANVIL")
        from m7.orderflow.simulation import get_simulation_backend
        assert get_simulation_backend() == "anvil"


class TestIsSimulationConfigured:
    """is_simulation_configured() delegates to backend-specific checks."""

    def test_tenderly_backend_delegates(self, monkeypatch):
        monkeypatch.delenv("ARBY_SIM_BACKEND", raising=False)
        # Without Tenderly env vars, should return False
        monkeypatch.delenv("TENDERLY_USER", raising=False)
        monkeypatch.delenv("TENDERLY_PROJECT", raising=False)
        monkeypatch.delenv("TENDERLY_ACCESS_KEY", raising=False)
        from m7.orderflow.simulation import is_simulation_configured
        assert is_simulation_configured() is False

    def test_tenderly_backend_configured(self, monkeypatch):
        monkeypatch.delenv("ARBY_SIM_BACKEND", raising=False)
        monkeypatch.setenv("TENDERLY_USER", "user")
        monkeypatch.setenv("TENDERLY_PROJECT", "proj")
        monkeypatch.setenv("TENDERLY_ACCESS_KEY", "key123")
        from m7.orderflow.simulation import is_simulation_configured
        assert is_simulation_configured() is True

    def test_anvil_backend_delegates(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "anvil")
        # Anvil is always "configured" when URL is set (default localhost)
        from m7.orderflow.simulation import is_simulation_configured
        assert is_simulation_configured() is True


class TestAnvilConfigured:
    """is_anvil_configured() checks URL presence."""

    def test_default_url_is_configured(self):
        from m7.orderflow.sim_backends.anvil_backend import is_anvil_configured
        assert is_anvil_configured() is True

    def test_custom_url(self, monkeypatch):
        monkeypatch.setenv("ARBY_ANVIL_RPC_URL", "http://10.0.0.5:8546")
        from m7.orderflow.sim_backends.anvil_backend import get_anvil_rpc_url
        assert get_anvil_rpc_url() == "http://10.0.0.5:8546"


class TestCheckAnvilConnection:
    """check_anvil_connection() probes JSON-RPC."""

    def test_connection_refused(self, monkeypatch):
        # Use a port that almost certainly has no listener
        monkeypatch.setenv("ARBY_ANVIL_RPC_URL", "http://127.0.0.1:19999")
        from m7.orderflow.sim_backends.anvil_backend import check_anvil_connection
        ok, client, err = check_anvil_connection()
        assert ok is False
        assert err is not None

    def test_non_anvil_client(self, monkeypatch):
        """If a server responds but isn't Anvil, ok=False."""
        import httpx
        from unittest.mock import patch, MagicMock

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "Geth/v1.10.0"}

        with patch("httpx.post", return_value=fake_resp):
            from m7.orderflow.sim_backends.anvil_backend import check_anvil_connection
            ok, client, err = check_anvil_connection()
            assert ok is False
            assert "not anvil" in (err or "")

    def test_anvil_client_ok(self, monkeypatch):
        """If Anvil responds, ok=True."""
        from unittest.mock import patch, MagicMock

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "anvil/v0.2.0"}

        with patch("httpx.post", return_value=fake_resp):
            from m7.orderflow.sim_backends.anvil_backend import check_anvil_connection
            ok, client, err = check_anvil_connection()
            assert ok is True
            assert client == "anvil/v0.2.0"
            assert err is None


class TestSimulateSwapAnvil:
    """simulate_swap_anvil() eth_call + gas estimation."""

    def test_unreachable_anvil(self, monkeypatch):
        monkeypatch.setenv("ARBY_ANVIL_RPC_URL", "http://127.0.0.1:19999")
        from m7.orderflow.sim_backends.anvil_backend import simulate_swap_anvil
        result = simulate_swap_anvil(chain="base", calldata=b"\x01\x02")
        assert result.success is False
        assert "ANVIL_UNREACHABLE" in (result.error or "")
        assert result.backend == "anvil"

    def test_eth_call_revert(self, monkeypatch):
        """eth_call reverts → success=False + revert_reason set."""
        from unittest.mock import patch, MagicMock

        call_count = [0]

        def fake_post(url, json=None, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            resp.status_code = 200
            method = json.get("method", "")
            if method == "web3_clientVersion":
                resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "anvil/v0.2.0"}
            elif method == "eth_call":
                resp.json.return_value = {
                    "jsonrpc": "2.0", "id": 1,
                    "error": {"code": 3, "message": "execution reverted: INSUFFICIENT_OUTPUT"}
                }
            else:
                resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "0x0"}
            return resp

        with patch("httpx.post", side_effect=fake_post):
            from m7.orderflow.sim_backends.anvil_backend import simulate_swap_anvil
            result = simulate_swap_anvil(chain="base", calldata=b"\xab\xcd")
            assert result.success is False
            assert result.revert_reason is not None
            assert "reverted" in result.revert_reason.lower()
            assert result.backend == "anvil"

    def test_successful_simulation(self, monkeypatch):
        """Happy path: eth_call ok + gas estimate ok."""
        from unittest.mock import patch, MagicMock

        def fake_post(url, json=None, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            method = json.get("method", "")
            if method == "web3_clientVersion":
                resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "anvil/v0.2.0"}
            elif method == "eth_call":
                # Return 1000 wei as output (padded to 32 bytes)
                hex_val = "0x" + hex(1000)[2:].zfill(64)
                resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": hex_val}
            elif method == "eth_estimateGas":
                resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": hex(150000)}
            else:
                resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "0x0"}
            return resp

        with patch("httpx.post", side_effect=fake_post):
            from m7.orderflow.sim_backends.anvil_backend import simulate_swap_anvil
            result = simulate_swap_anvil(chain="base", calldata=b"\xab\xcd")
            assert result.success is True
            assert result.gas_used == 150000
            assert result.output_amount_wei == 1000
            assert result.backend == "anvil"
            assert result.revert_reason is None


class TestSimulationResultBackendField:
    """SimulationResult includes backend provenance."""

    def test_backend_field_exists(self):
        from m7.orderflow.simulation import SimulationResult
        r = SimulationResult(success=True, backend="anvil")
        assert r.backend == "anvil"

    def test_default_backend_none(self):
        from m7.orderflow.simulation import SimulationResult
        r = SimulationResult(success=True)
        assert r.backend is None


class TestSimulateSwapRouter:
    """simulate_swap() routes to correct backend."""

    def test_tenderly_route_default(self, monkeypatch):
        monkeypatch.delenv("ARBY_SIM_BACKEND", raising=False)
        monkeypatch.delenv("TENDERLY_USER", raising=False)
        monkeypatch.delenv("TENDERLY_PROJECT", raising=False)
        monkeypatch.delenv("TENDERLY_ACCESS_KEY", raising=False)
        from m7.orderflow.simulation import simulate_swap
        result = simulate_swap(chain="base")
        assert result.error == "TENDERLY_NOT_CONFIGURED"
        assert result.backend == "tenderly"

    def test_anvil_route(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "anvil")
        monkeypatch.setenv("ARBY_ANVIL_RPC_URL", "http://127.0.0.1:19999")
        from m7.orderflow.simulation import simulate_swap
        result = simulate_swap(chain="base")
        assert result.success is False
        assert result.backend == "anvil"


class TestResetAnvilFork:
    """reset_anvil_fork() lifecycle control."""

    def test_reset_success(self, monkeypatch):
        from unittest.mock import patch, MagicMock

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": True}

        with patch("httpx.post", return_value=fake_resp):
            from m7.orderflow.sim_backends.anvil_backend import reset_anvil_fork
            assert reset_anvil_fork() is True

    def test_reset_with_block(self, monkeypatch):
        from unittest.mock import patch, MagicMock

        last_payload = {}

        def capture_post(url, json=None, **kwargs):
            last_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": True}
            return resp

        with patch("httpx.post", side_effect=capture_post):
            from m7.orderflow.sim_backends.anvil_backend import reset_anvil_fork
            assert reset_anvil_fork(block_number=12345678) is True
            assert last_payload["method"] == "anvil_reset"


class TestCheckSimulationBackendConnection:
    """strategy/infra.py check_simulation_backend_connection()."""

    def test_tenderly_fallthrough(self, monkeypatch):
        monkeypatch.delenv("ARBY_SIM_BACKEND", raising=False)
        monkeypatch.delenv("TENDERLY_ACCESS_KEY", raising=False)
        from strategy.infra import check_simulation_backend_connection
        enabled, ok, err = check_simulation_backend_connection()
        assert enabled is False

    def test_anvil_backend_check(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "anvil")
        monkeypatch.setenv("ARBY_ANVIL_RPC_URL", "http://127.0.0.1:19999")
        from strategy.infra import check_simulation_backend_connection
        enabled, ok, err = check_simulation_backend_connection()
        assert enabled is True
        assert ok is False  # No anvil running on 19999


class TestStep9BlockClamp:
    """Step 9: Anvil fork drift mitigation.

    Guarantees that an event_block beyond the local Anvil head does NOT
    raise BlockOutOfRangeError but is clamped to "latest" so fresh sim
    attempts can still execute against the available fork state.
    """

    def test_clamp_when_requested_block_exceeds_local_head(self, monkeypatch):
        monkeypatch.setenv("ARBY_ANVIL_CLAMP_BLOCK", "1")
        monkeypatch.setenv("ARBY_ANVIL_RPC_URL", "http://test-clamp:8545")
        from m7.orderflow.sim_backends.anvil_backend import _resolve_anvil_block_tag
        from unittest.mock import patch, MagicMock

        fake = MagicMock()
        fake.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": hex(100)}
        with patch("httpx.post", return_value=fake):
            tag, clamped, local_head = _resolve_anvil_block_tag(200)
        assert tag == "latest"
        assert clamped is True
        assert local_head == 100

    def test_no_clamp_when_block_within_local_head(self, monkeypatch):
        monkeypatch.setenv("ARBY_ANVIL_CLAMP_BLOCK", "1")
        monkeypatch.setenv("ARBY_ANVIL_RPC_URL", "http://test-clamp:8545")
        from m7.orderflow.sim_backends.anvil_backend import _resolve_anvil_block_tag
        from unittest.mock import patch, MagicMock

        fake = MagicMock()
        fake.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": hex(500)}
        with patch("httpx.post", return_value=fake):
            tag, clamped, local_head = _resolve_anvil_block_tag(400)
        assert tag == hex(400)
        assert clamped is False
        assert local_head == 500

    def test_clamp_disabled_preserves_hex_tag(self, monkeypatch):
        monkeypatch.setenv("ARBY_ANVIL_CLAMP_BLOCK", "0")
        from m7.orderflow.sim_backends.anvil_backend import _resolve_anvil_block_tag
        tag, clamped, _ = _resolve_anvil_block_tag(12345)
        assert tag == hex(12345)
        assert clamped is False

    def test_eth_call_retries_latest_on_block_out_of_range(self, monkeypatch):
        """_eth_call_anvil must transparently retry with "latest" when the
        server rejects the exact block tag (e.g., clamp disabled + reorg)."""
        monkeypatch.setenv("ARBY_ANVIL_CLAMP_BLOCK", "0")
        from unittest.mock import patch, MagicMock

        calls = []

        def fake_post(url, json=None, **kwargs):
            calls.append(json.get("params", [None, None])[1])
            resp = MagicMock()
            resp.status_code = 200
            if calls[-1] == "latest":
                resp.json.return_value = {
                    "jsonrpc": "2.0", "id": 1, "result": "0x" + "01" * 32
                }
            else:
                resp.json.return_value = {
                    "jsonrpc": "2.0", "id": 1,
                    "error": {"code": -32000, "message": "BlockOutOfRangeError"},
                }
            return resp

        with patch("httpx.post", side_effect=fake_post):
            from m7.orderflow.sim_backends.anvil_backend import _eth_call_anvil
            out, err = _eth_call_anvil(
                from_address="0x" + "00" * 20,
                to_address="0x" + "11" * 20,
                calldata=b"\xab\xcd",
                value_wei=0,
                block_number=999_999_999,
            )
        assert err is None, f"unexpected err={err}"
        assert out.startswith("0x")
        assert "latest" in calls  # retry happened

    def test_refresh_anvil_fork_if_stale_resets_when_drift_exceeds(self, monkeypatch):
        monkeypatch.setenv("ARBY_ANVIL_RPC_URL", "http://test-refresh:8545")
        monkeypatch.setenv("ARBY_FORK_RPC_URL", "http://upstream/base")
        from unittest.mock import patch, MagicMock

        reset_calls = []

        def fake_post(url, json=None, **kwargs):
            method = (json or {}).get("method", "")
            resp = MagicMock()
            resp.status_code = 200
            if method == "eth_blockNumber" and "upstream" in url:
                resp.json.return_value = {"result": hex(1000)}
            elif method == "eth_blockNumber":
                resp.json.return_value = {"result": hex(700)}  # local head
            elif method == "anvil_reset":
                reset_calls.append((json or {}).get("params"))
                resp.json.return_value = {"result": True}
            else:
                resp.json.return_value = {"result": "0x0"}
            return resp

        with patch("httpx.post", side_effect=fake_post):
            from m7.orderflow.sim_backends.anvil_backend import refresh_anvil_fork_if_stale
            ok, diag = refresh_anvil_fork_if_stale(
                chain="base",
                max_drift_blocks=100,
                offset=5,
                upstream_url="http://upstream/base",
            )
        assert ok is True
        assert diag["drift"] == 300
        assert diag["target_block"] == 995
        assert reset_calls, "anvil_reset must be called when drift > threshold"

    def test_refresh_anvil_fork_skips_when_drift_small(self, monkeypatch):
        monkeypatch.setenv("ARBY_ANVIL_RPC_URL", "http://test-refresh:8545")
        monkeypatch.setenv("ARBY_FORK_RPC_URL", "http://upstream/base")
        from unittest.mock import patch, MagicMock

        def fake_post(url, json=None, **kwargs):
            method = (json or {}).get("method", "")
            resp = MagicMock()
            resp.status_code = 200
            if method == "eth_blockNumber" and "upstream" in url:
                resp.json.return_value = {"result": hex(1000)}
            elif method == "eth_blockNumber":
                resp.json.return_value = {"result": hex(990)}
            else:
                resp.json.return_value = {"result": True}
            return resp

        with patch("httpx.post", side_effect=fake_post):
            from m7.orderflow.sim_backends.anvil_backend import refresh_anvil_fork_if_stale
            ok, diag = refresh_anvil_fork_if_stale(
                chain="base",
                max_drift_blocks=50,
                offset=5,
                upstream_url="http://upstream/base",
            )
        assert ok is False
        assert diag["reason"] == "DRIFT_OK"
