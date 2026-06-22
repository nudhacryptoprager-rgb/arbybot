"""M8.3 token risk preflight tests."""
from __future__ import annotations

from unittest.mock import MagicMock

from m8.metadata.token_risk import build_token_risk_metadata, risk_warnings_for_token


def test_token_risk_non_erc20_no_code():
    risk = build_token_risk_metadata(
        "0xdead000000000000000000000000000000000001",
        w3=None,
        code_length=0,
        error_code="NO_CODE",
        decimals_resolved=False,
    )
    assert risk["is_contract"] is False
    assert risk["non_erc20_reason"] == "NO_CODE"
    assert risk["erc20_methods_ok"] is False
    assert risk["token_behavior_flags"]["pausable_like_selectors"] is False


def test_token_risk_proxy_detected_in_bytecode():
    w3 = MagicMock()
    # EIP-1167 minimal proxy pattern stub
    impl = "0x" + "a" * 40
    code_hex = "363d3d373d3d3d363d73" + impl[2:] + "57fd5bf3" + ("00" * 20)
    w3.eth.get_code.return_value = bytes.fromhex(code_hex)
    w3.to_checksum_address.side_effect = lambda a: a

    risk = build_token_risk_metadata(
        "0xbeef000000000000000000000000000000000002",
        w3=w3,
        decimals_resolved=True,
    )
    assert risk["proxy_detected"] is True
    assert risk["implementation"] == impl
    assert "PROXY_DETECTED" in risk_warnings_for_token(risk)


def test_token_risk_erc20_ok():
    risk = build_token_risk_metadata(
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        w3=None,
        code_length=1234,
        error_code=None,
        decimals_resolved=True,
    )
    assert risk["erc20_methods_ok"] is True
    assert risk["non_erc20_reason"] is None
