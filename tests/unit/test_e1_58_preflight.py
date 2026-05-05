"""Unit tests for E1.58 fix step #2: m7.orderflow.preflight.

These tests lock the public contract: function signatures, return
shapes, and PREFLIGHT_* reason strings.  They use simple stub objects
so no RPC or web3 install dependency leaks into the offline suite.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from m7.orderflow import preflight as pf


# --- helpers ----------------------------------------------------------------


class _StubBalanceOf:
    def __init__(self, value: int):
        self._value = value

    def call(self) -> int:
        return self._value


class _StubAllowance:
    def __init__(self, value: int):
        self._value = value

    def call(self) -> int:
        return self._value


class _StubFunctions:
    def __init__(self, *, balance: int = 0, allowance: int = 0):
        self._balance = balance
        self._allowance = allowance

    def balanceOf(self, _owner):
        return _StubBalanceOf(self._balance)

    def allowance(self, _owner, _spender):
        return _StubAllowance(self._allowance)


class _StubContract:
    def __init__(self, *, balance: int = 0, allowance: int = 0):
        self.functions = _StubFunctions(balance=balance, allowance=allowance)


class _StubEth:
    def __init__(
        self,
        *,
        code_map=None,
        balance_map=None,
        contract_balance: int = 0,
        contract_allowance: int = 0,
        get_code_raises: bool = False,
    ):
        self._code_map = code_map or {}
        self._balance_map = balance_map or {}
        self._contract_balance = contract_balance
        self._contract_allowance = contract_allowance
        self._get_code_raises = get_code_raises

    def get_code(self, address):
        if self._get_code_raises:
            raise RuntimeError("simulated rpc failure")
        return self._code_map.get(address, b"")

    def get_balance(self, address):
        return self._balance_map.get(address, 0)

    def contract(self, *, address, abi):
        return _StubContract(
            balance=self._contract_balance,
            allowance=self._contract_allowance,
        )


class _StubW3:
    def __init__(self, eth: _StubEth):
        self.eth = eth


# --- is_enabled -------------------------------------------------------------


def test_is_enabled_default_off(monkeypatch):
    monkeypatch.delenv("ARBY_EXECUTION_PREFLIGHT", raising=False)
    assert pf.is_enabled() is False


def test_is_enabled_explicit_on(monkeypatch):
    monkeypatch.setenv("ARBY_EXECUTION_PREFLIGHT", "1")
    assert pf.is_enabled() is True


def test_is_enabled_explicit_zero(monkeypatch):
    monkeypatch.setenv("ARBY_EXECUTION_PREFLIGHT", "0")
    assert pf.is_enabled() is False


# --- check_router_exists ----------------------------------------------------


def test_check_router_exists_with_code():
    code = bytes.fromhex("60806040")  # arbitrary non-empty bytecode
    w3 = _StubW3(_StubEth(code_map={"0xrouter": _Hex(code)}))
    ok, reason = pf.check_router_exists(w3, "0xrouter")
    assert ok is True
    assert reason == ""


def test_check_router_exists_no_code():
    w3 = _StubW3(_StubEth(code_map={"0xrouter": _Hex(b"")}))
    ok, reason = pf.check_router_exists(w3, "0xrouter")
    assert ok is False
    assert reason == "PREFLIGHT_ROUTER_NO_CODE"


def test_check_router_exists_missing_address():
    w3 = _StubW3(_StubEth())
    ok, reason = pf.check_router_exists(w3, "")
    assert ok is False
    assert reason == "PREFLIGHT_ROUTER_MISSING"


def test_check_router_exists_rpc_error():
    w3 = _StubW3(_StubEth(get_code_raises=True))
    ok, reason = pf.check_router_exists(w3, "0xrouter")
    assert ok is False
    assert reason.startswith("PREFLIGHT_ROUTER_RPC_ERROR:")


class _Hex(bytes):
    """bytes subclass with a .hex() method that mimics HexBytes."""

    def hex(self) -> str:  # type: ignore[override]
        return "0x" + bytes(self).hex()


# --- check_balance ----------------------------------------------------------


def test_check_balance_zero_amount_passes():
    ok, reason = pf.check_balance(_StubW3(_StubEth()), "0xtoken", "0xowner", 0)
    assert ok is True
    assert reason == ""


def test_check_balance_missing_owner():
    ok, reason = pf.check_balance(_StubW3(_StubEth()), "0xtoken", "", 100)
    assert ok is False
    assert reason == "PREFLIGHT_OWNER_MISSING"


def test_check_balance_native_sufficient():
    w3 = _StubW3(_StubEth(balance_map={"0xowner": 10**18}))
    ok, reason = pf.check_balance(w3, "", "0xowner", 10**17)
    assert ok is True


def test_check_balance_native_insufficient():
    w3 = _StubW3(_StubEth(balance_map={"0xowner": 100}))
    ok, reason = pf.check_balance(w3, None, "0xowner", 1000)
    assert ok is False
    assert reason.startswith("PREFLIGHT_BALANCE_INSUFFICIENT:")


def test_check_balance_erc20_sufficient():
    w3 = _StubW3(_StubEth(contract_balance=5000))
    ok, reason = pf.check_balance(w3, "0xtoken", "0xowner", 1000)
    assert ok is True


def test_check_balance_erc20_insufficient():
    w3 = _StubW3(_StubEth(contract_balance=10))
    ok, reason = pf.check_balance(w3, "0xtoken", "0xowner", 1000)
    assert ok is False
    assert "PREFLIGHT_BALANCE_INSUFFICIENT:10<1000" == reason


# --- check_allowance --------------------------------------------------------


def test_check_allowance_zero_amount_passes():
    ok, reason = pf.check_allowance(
        _StubW3(_StubEth()), "0xtoken", "0xowner", "0xrouter", 0
    )
    assert ok is True


def test_check_allowance_native_skipped():
    # native coin → no allowance needed
    ok, reason = pf.check_allowance(
        _StubW3(_StubEth()), "", "0xowner", "0xrouter", 1000
    )
    assert ok is True


def test_check_allowance_sufficient():
    w3 = _StubW3(_StubEth(contract_allowance=5000))
    ok, _ = pf.check_allowance(w3, "0xtoken", "0xowner", "0xrouter", 1000)
    assert ok is True


def test_check_allowance_insufficient():
    w3 = _StubW3(_StubEth(contract_allowance=10))
    ok, reason = pf.check_allowance(w3, "0xtoken", "0xowner", "0xrouter", 1000)
    assert ok is False
    assert reason == "PREFLIGHT_ALLOWANCE_INSUFFICIENT:10<1000"


def test_check_allowance_missing_party():
    ok, reason = pf.check_allowance(_StubW3(_StubEth()), "0xtoken", "", "0xrouter", 1000)
    assert ok is False
    assert reason == "PREFLIGHT_ALLOWANCE_MISSING_PARTY"


# --- run_preflight ----------------------------------------------------------


def test_run_preflight_w3_none():
    blockers = pf.run_preflight(
        None, router="0xrouter", token_in="0xtoken", owner="0xowner", amount_wei=1000
    )
    assert blockers == ["PREFLIGHT_W3_UNAVAILABLE"]


def test_run_preflight_all_pass_erc20():
    code = _Hex(bytes.fromhex("60806040"))
    w3 = _StubW3(
        _StubEth(
            code_map={"0xrouter": code},
            contract_balance=10_000,
            contract_allowance=10_000,
        )
    )
    blockers = pf.run_preflight(
        w3, router="0xrouter", token_in="0xtoken", owner="0xowner", amount_wei=500
    )
    assert blockers == []


def test_run_preflight_router_missing():
    w3 = _StubW3(_StubEth())
    blockers = pf.run_preflight(
        w3, router=None, token_in="0xtoken", owner="0xowner", amount_wei=500
    )
    assert "PREFLIGHT_ROUTER_MISSING" in blockers


def test_run_preflight_chains_router_balance_allowance_failures():
    # router: empty code → fails; balance: 0 → fails; allowance: 0 → fails
    w3 = _StubW3(
        _StubEth(
            code_map={"0xrouter": _Hex(b"")},
            contract_balance=0,
            contract_allowance=0,
        )
    )
    blockers = pf.run_preflight(
        w3, router="0xrouter", token_in="0xtoken", owner="0xowner", amount_wei=1000
    )
    assert "PREFLIGHT_ROUTER_NO_CODE" in blockers
    assert any(b.startswith("PREFLIGHT_BALANCE_INSUFFICIENT:") for b in blockers)
    assert any(b.startswith("PREFLIGHT_ALLOWANCE_INSUFFICIENT:") for b in blockers)
    # stable order: router, balance, allowance
    assert blockers[0] == "PREFLIGHT_ROUTER_NO_CODE"


def test_run_preflight_zero_amount_flagged():
    code = _Hex(bytes.fromhex("60806040"))
    w3 = _StubW3(_StubEth(code_map={"0xrouter": code}))
    blockers = pf.run_preflight(
        w3, router="0xrouter", token_in="0xtoken", owner="0xowner", amount_wei=0
    )
    assert "PREFLIGHT_AMOUNT_ZERO" in blockers
