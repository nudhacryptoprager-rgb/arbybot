"""Tests for block timestamp resolver shared module."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from m8.discovery.block_timestamp_resolver import resolve_block_timestamps


def test_resolve_block_timestamps_empty_input():
    """Empty block set returns empty dict without RPC calls."""
    result = resolve_block_timestamps(set(), chain="base")
    assert result == {}


def test_resolve_block_timestamps_skip_rpc():
    """ARBY_SKIP_RPC=1 returns empty dict."""
    with patch.dict("os.environ", {"ARBY_SKIP_RPC": "1"}, clear=False):
        result = resolve_block_timestamps({100}, chain="base")
    assert result == {}


def test_resolve_block_timestamps_returns_iso_format():
    """Block numbers are converted to ISO-8601 timestamps."""
    block_num = 47019463
    block_ts = 1748000000

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"result": {"timestamp": hex(block_ts)}}
    ).encode("utf-8")
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp), patch(
        "core.rpc_urls.get_rpc_url", return_value="http://rpc.test"
    ), patch("core.env.load_root_dotenv"), patch.dict(
        "os.environ", {"ARBY_SKIP_RPC": "0"}, clear=False
    ):
        result = resolve_block_timestamps({block_num}, chain="base")

    assert block_num in result
    ts = result[block_num]
    assert ts.endswith("Z")
    assert len(ts) == 20  # YYYY-MM-DDTHH:MM:SSZ


def test_resolve_block_timestamps_no_rpc_url():
    """No RPC URL available returns empty dict."""
    with patch("core.rpc_urls.get_rpc_url", return_value=None), patch(
        "core.env.load_root_dotenv"
    ), patch.dict("os.environ", {"ARBY_SKIP_RPC": "0"}, clear=False):
        result = resolve_block_timestamps({100}, chain="base")
    assert result == {}


def test_resolve_block_timestamps_rpc_error_silently_dropped():
    """RPC errors are silently dropped (caller treats missing as stale)."""
    with patch("urllib.request.urlopen", side_effect=Exception("RPC error")), patch(
        "core.rpc_urls.get_rpc_url", return_value="http://rpc.test"
    ), patch("core.env.load_root_dotenv"), patch.dict(
        "os.environ", {"ARBY_SKIP_RPC": "0"}, clear=False
    ):
        result = resolve_block_timestamps({100}, chain="base")
    assert result == {}


def test_resolve_block_timestamps_multiple_blocks():
    """Multiple blocks resolved in a single call."""
    blocks = {100, 200, 300}
    timestamps = {100: 1748000000, 200: 1748000100, 300: 1748000200}

    def mock_urlopen_side_effect(req, timeout=None):
        payload = json.loads(req.data.decode("utf-8"))
        block_hex = payload["params"][0]
        block_num = int(block_hex, 16)
        ts = timestamps.get(block_num)
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"result": {"timestamp": hex(ts)}}
        ).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch(
        "urllib.request.urlopen", side_effect=mock_urlopen_side_effect
    ), patch("core.rpc_urls.get_rpc_url", return_value="http://rpc.test"), patch(
        "core.env.load_root_dotenv"
    ), patch.dict("os.environ", {"ARBY_SKIP_RPC": "0"}, clear=False):
        result = resolve_block_timestamps(blocks, chain="base")

    assert len(result) == 3
    assert 100 in result
    assert 200 in result
    assert 300 in result
