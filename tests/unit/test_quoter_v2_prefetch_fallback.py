"""R39x+1: Regression tests for QuoterV2 prefetch fallback RPC handling.

Verifies that:
1. read_quoter_v2 uses fallback_rpc_urls when primary is rate-limited (429)
2. Prefetch code path passes fallback URLs (structural contract)
"""

import ast
import inspect
import textwrap
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test 1: read_quoter_v2 tries fallback RPC after primary 429
# ---------------------------------------------------------------------------

def test_quoter_v2_uses_fallback_on_429():
    """When primary RPC returns 429, read_quoter_v2 should try fallback URLs."""
    from strategy.quote_rpc import read_quoter_v2, _cycle_quarantine

    # Clear quarantine
    _cycle_quarantine.clear()

    call_log = []

    def mock_w3(url, timeout=10):
        m = MagicMock()
        def mock_call(tx, block_identifier=None):
            call_log.append(url)
            if url == "http://primary.example.com":
                raise Exception("429 Too Many Requests")
            # Fallback succeeds — return valid ABI-encoded QuoterV2 response
            # amountOut=1000, sqrtPriceAfter=0, ticksCrossed=1, gasEstimate=100000
            return bytes.fromhex(
                "00000000000000000000000000000000000000000000000000000000000003e8"
                "0000000000000000000000000000000000000000000000000000000000000000"
                "0000000000000000000000000000000000000000000000000000000000000001"
                "00000000000000000000000000000000000000000000000000000000000186a0"
            )
        m.eth.call = mock_call
        return m

    with patch("strategy.quote_rpc._get_shared_w3", side_effect=mock_w3):
        with patch("strategy.quote_rpc.os.environ", {"ARBY_SKIP_RPC": "0"}):
            result = read_quoter_v2(
                quoter_address="0x" + "a1" * 20,
                token_in="0x" + "b1" * 20,
                token_out="0x" + "c1" * 20,
                amount_in=1000000,
                fee=500,
                rpc_url="http://primary.example.com",
                block_num=12345,
                fallback_rpc_urls=["http://fallback.example.com"],
            )

    # Primary was tried first, then fallback
    assert len(call_log) == 2
    assert call_log[0] == "http://primary.example.com"
    assert call_log[1] == "http://fallback.example.com"
    # Fallback succeeded
    assert result is not None
    assert result.get("amount_out") == 1000

    _cycle_quarantine.clear()


def test_quoter_v2_all_429_returns_rate_limited_sentinel():
    """When ALL RPCs return 429, read_quoter_v2 should return QUOTER_RATE_LIMITED."""
    from strategy.quote_rpc import (
        read_quoter_v2,
        QUOTER_RATE_LIMITED,
        _cycle_quarantine,
    )

    _cycle_quarantine.clear()

    def mock_w3(url, timeout=10):
        m = MagicMock()
        def mock_call(tx, block_identifier=None):
            raise Exception("429 Too Many Requests")
        m.eth.call = mock_call
        return m

    with patch("strategy.quote_rpc._get_shared_w3", side_effect=mock_w3):
        with patch("strategy.quote_rpc.os.environ", {"ARBY_SKIP_RPC": "0"}):
            result = read_quoter_v2(
                quoter_address="0x" + "a1" * 20,
                token_in="0x" + "b1" * 20,
                token_out="0x" + "c1" * 20,
                amount_in=1000000,
                fee=500,
                rpc_url="http://primary.example.com",
                block_num=12345,
                fallback_rpc_urls=["http://fallback.example.com"],
            )

    assert result is QUOTER_RATE_LIMITED
    _cycle_quarantine.clear()


# ---------------------------------------------------------------------------
# Test 2: Structural contract — prefetch code passes fallback_rpc_urls
# ---------------------------------------------------------------------------

def test_prefetch_quoter_v2_call_includes_fallback_rpc_urls():
    """The prefetch submit() for uniswap_v3 quoter_v2 must pass fallback URLs.

    This is a source-code structural test to prevent regression of R39x+1 fix.
    """
    src = inspect.getsource(
        __import__("strategy.quotes", fromlist=["collect_quotes"]).collect_quotes
    )
    tree = ast.parse(textwrap.dedent(src))

    # Find the prefetch submit call for read_quoter_v2
    # We look for: _pf_exec.submit(read_quoter_v2, ..., _fallback_rpc_urls, ...)
    found_fallback_in_prefetch = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Check if this is _pf_exec.submit(read_quoter_v2, ...)
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "submit"
                and len(node.args) >= 2
            ):
                # First arg should be read_quoter_v2
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Name) and first_arg.id == "read_quoter_v2":
                    # Check if _fallback_rpc_urls is in the remaining args
                    for arg in node.args[1:]:
                        if isinstance(arg, ast.Name) and arg.id == "_fallback_rpc_urls":
                            found_fallback_in_prefetch = True
                            break

    assert found_fallback_in_prefetch, (
        "Prefetch submit(read_quoter_v2, ...) must include _fallback_rpc_urls "
        "to survive 429 on primary RPC (R39x+1 fix)"
    )
