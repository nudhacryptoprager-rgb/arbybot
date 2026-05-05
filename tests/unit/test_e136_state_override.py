"""E1.36 — Tests for shared state-override helpers and Tenderly state_objects.

P1: ``build_slot_map`` returns a plain ``{token: {slot: value}}`` dict.
P1: ``extract_token_in_from_calldata`` decodes V3 + Velodrome calldata.
P1: Tenderly sim payload carries ``state_objects`` when override is enabled.
P1: Opt-out via ARBY_SIM_DISABLE_STATE_OVERRIDE=1.
"""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

from m7.orderflow.sim_backends.rpc_fork_backend import (
    build_slot_map,
    extract_token_in_from_calldata,
    _build_state_overrides,
)


class TestBuildSlotMap:
    def test_returns_plain_dict(self):
        token = "0x" + "a" * 40
        holder = "0x" + "b" * 40
        router = "0x" + "c" * 40
        slot_map = build_slot_map(token, holder, router)
        assert isinstance(slot_map, dict)
        assert token.lower() in slot_map
        slots = slot_map[token.lower()]
        assert isinstance(slots, dict)
        # Each entry is hex slot -> hex value
        for k, v in slots.items():
            assert k.startswith("0x") and len(k) == 66
            assert v.startswith("0x") and len(v) == 66

    def test_balance_and_allowance_slots_present(self):
        token = "0x" + "a" * 40
        holder = "0x" + "b" * 40
        router = "0x" + "c" * 40
        slots = build_slot_map(token, holder, router)[token.lower()]
        # Balance slots: 14 entries. Allowance: 5 offsets × 14 = 70.
        # Plus overlaps → total ≥ 14 (balances only) and <= 14 * (1+5) = 84.
        assert 14 <= len(slots) <= 84

    def test_amount_embedded_in_value(self):
        token = "0x" + "a" * 40
        holder = "0x" + "b" * 40
        router = "0x" + "c" * 40
        slot_map = build_slot_map(token, holder, router, amount=10**18)
        # At least one entry should match 10^18 in hex (balance values).
        wanted = "0x" + (10**18).to_bytes(32, "big").hex()
        assert wanted in slot_map[token.lower()].values()


class TestExtractTokenIn:
    def test_v3_exact_input_single_v2(self):
        # Selector 0x04e45aaf + token_in padded to 32 bytes
        token = bytes.fromhex("dd" * 20)
        calldata = bytes.fromhex("04e45aaf") + b"\x00" * 12 + token + b"\x00" * 100
        got = extract_token_in_from_calldata(calldata)
        assert got is not None
        assert got.lower().endswith("dd" * 20)

    def test_v3_exact_input_single_v1(self):
        token = bytes.fromhex("ee" * 20)
        calldata = bytes.fromhex("414bf389") + b"\x00" * 12 + token + b"\x00" * 100
        got = extract_token_in_from_calldata(calldata)
        assert got is not None
        assert got.lower().endswith("ee" * 20)

    def test_too_short_returns_none(self):
        assert extract_token_in_from_calldata(b"\x00" * 20) is None

    def test_empty_returns_none(self):
        assert extract_token_in_from_calldata(b"") is None


class TestStateOverridesLegacyShape:
    def test_eth_call_statediff_envelope(self):
        token = "0x" + "a" * 40
        holder = "0x" + "b" * 40
        router = "0x" + "c" * 40
        overrides = _build_state_overrides(token, holder, router)
        assert token.lower() in overrides
        inner = overrides[token.lower()]
        assert "stateDiff" in inner
        assert isinstance(inner["stateDiff"], dict)
        assert len(inner["stateDiff"]) > 0


class TestTenderlyStateObjects:
    """Verify the Tenderly path injects state_objects into the payload."""

    @patch("httpx.post")
    def test_state_objects_sent_to_tenderly(self, mock_post, monkeypatch):
        monkeypatch.setenv("TENDERLY_USER", "u")
        monkeypatch.setenv("TENDERLY_PROJECT", "p")
        monkeypatch.setenv("TENDERLY_ACCESS_KEY", "k")
        monkeypatch.delenv("ARBY_SIM_DISABLE_STATE_OVERRIDE", raising=False)
        # Explicitly request Tenderly (no longer the default)
        monkeypatch.setenv("ARBY_SIM_BACKEND", "tenderly")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "transaction": {"status": True, "gas_used": 120000},
            "simulation": {"id": "sim_x"},
        }
        mock_post.return_value = mock_resp

        from m7.orderflow.simulation import simulate_swap

        # Valid V3 calldata: selector + token_in (32) + rest
        token = bytes.fromhex("ab" * 20)
        calldata = bytes.fromhex("04e45aaf") + b"\x00" * 12 + token + b"\x00" * 100
        result = simulate_swap(
            chain="base",
            from_address="0x" + "11" * 20,
            to_address="0x" + "22" * 20,
            calldata=calldata,
        )

        assert result.passed
        # Inspect payload
        args, kwargs = mock_post.call_args
        payload = kwargs.get("json") or args[1]
        assert "state_objects" in payload, f"payload keys: {list(payload)}"
        so = payload["state_objects"]
        assert len(so) >= 1
        # storage dict present under at least one token address
        first_addr = next(iter(so))
        assert "storage" in so[first_addr]
        assert len(so[first_addr]["storage"]) > 0

    @patch("httpx.post")
    def test_opt_out_disables_state_objects(self, mock_post, monkeypatch):
        monkeypatch.setenv("TENDERLY_USER", "u")
        monkeypatch.setenv("TENDERLY_PROJECT", "p")
        monkeypatch.setenv("TENDERLY_ACCESS_KEY", "k")
        monkeypatch.setenv("ARBY_SIM_DISABLE_STATE_OVERRIDE", "1")
        monkeypatch.delenv("ARBY_SIM_BACKEND", raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"transaction": {"status": True}, "simulation": {}}
        mock_post.return_value = mock_resp

        from m7.orderflow.simulation import simulate_swap

        token = bytes.fromhex("ab" * 20)
        calldata = bytes.fromhex("04e45aaf") + b"\x00" * 12 + token + b"\x00" * 100
        simulate_swap(
            chain="base",
            from_address="0x" + "11" * 20,
            to_address="0x" + "22" * 20,
            calldata=calldata,
        )
        args, kwargs = mock_post.call_args
        payload = kwargs.get("json") or args[1]
        assert "state_objects" not in payload

    @patch("httpx.post")
    def test_zero_from_address_skips_overrides(self, mock_post, monkeypatch):
        monkeypatch.setenv("TENDERLY_USER", "u")
        monkeypatch.setenv("TENDERLY_PROJECT", "p")
        monkeypatch.setenv("TENDERLY_ACCESS_KEY", "k")
        monkeypatch.delenv("ARBY_SIM_DISABLE_STATE_OVERRIDE", raising=False)
        monkeypatch.delenv("ARBY_SIM_BACKEND", raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"transaction": {"status": True}, "simulation": {}}
        mock_post.return_value = mock_resp

        from m7.orderflow.simulation import simulate_swap

        token = bytes.fromhex("ab" * 20)
        calldata = bytes.fromhex("04e45aaf") + b"\x00" * 12 + token + b"\x00" * 100
        simulate_swap(
            chain="base",
            from_address="0x" + "00" * 20,
            to_address="0x" + "22" * 20,
            calldata=calldata,
        )
        args, kwargs = mock_post.call_args
        payload = kwargs.get("json") or args[1]
        assert "state_objects" not in payload


class TestAnvilRunnerScriptExists:
    """Patch 2 — verify the anvil runner entrypoint is discoverable."""

    def test_script_file_present(self):
        import pathlib
        root = pathlib.Path(__file__).parent.parent.parent
        script = root / "scripts" / "start_anvil_fork.py"
        assert script.exists(), f"Missing {script}"

    def test_script_has_cli_entrypoint(self):
        import pathlib
        root = pathlib.Path(__file__).parent.parent.parent
        script = root / "scripts" / "start_anvil_fork.py"
        body = script.read_text(encoding="utf-8")
        assert "def main()" in body
        assert "--chain" in body
        assert "--port" in body
        assert "--fork-url" in body
