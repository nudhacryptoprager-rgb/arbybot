"""Unit tests for hint_verify_batch and hint_refresh_lock."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from m8.discovery.hint_refresh_lock import (
    acquire_hint_refresh_lock,
    lock_path_for,
    release_hint_refresh_lock,
)
from m8.discovery.hint_verify_batch import pin_block_from_ws, verify_hints_async
from m8.discovery.pool_hints import PoolHint


def test_pin_block_from_ws_parses_head(monkeypatch):
    class _FakeWS:
        def __init__(self, *_a, **_k):
            self._step = 0

        def send(self, _msg):
            return None

        def recv(self):
            self._step += 1
            if self._step == 1:
                return json.dumps({"id": 1, "result": "0xsub"})
            return json.dumps(
                {"params": {"result": {"number": "0x2d307bf"}}}
            )

        def close(self):
            return None

    monkeypatch.setitem(
        __import__("sys").modules,
        "websocket",
        MagicMock(create_connection=_FakeWS),
    )
    with patch("core.rpc_urls.resolve_rpc_ws", return_value=("wss://x", "drpc", {})):
        block = pin_block_from_ws("base", timeout_s=2.0)
    assert block == 0x2D307BF


@patch("m8.discovery.hint_verify_batch.verify_hint_onchain")
def test_verify_hints_async_workers(mock_verify):
    mock_verify.side_effect = lambda h, **_: h
    hints = [
        PoolHint(
            source="dexscreener",
            chain="base",
            dex_id="uniswap_v3",
            pool_address=f"0xpool{i:040d}",
            token0_addr="0xa",
            token1_addr="0xb",
        )
        for i in range(4)
    ]
    out = verify_hints_async(
        hints,
        chain="base",
        verify_mode="specialized",
        workers=4,
        use_multicall=False,
    )
    assert len(out) == 4
    assert mock_verify.call_count == 4


def test_hint_refresh_lock_blocks_second_live_pid(tmp_path, monkeypatch):
    ck = tmp_path / "ck.json"
    out = tmp_path / "out.json"
    monkeypatch.setattr(
        "m8.discovery.hint_refresh_lock._pid_alive",
        lambda pid: pid == 9999,
    )
    lock = lock_path_for(str(ck))
    lock.write_text(json.dumps({"pid": 9999}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="already running"):
        acquire_hint_refresh_lock(
            checkpoint_path=str(ck),
            output_path=str(out),
            chain="base",
            sources=["dexscreener"],
        )


def test_hint_refresh_lock_release_own_pid(tmp_path, monkeypatch):
    ck = tmp_path / "ck.json"
    monkeypatch.setattr("m8.discovery.hint_refresh_lock._pid_alive", lambda _pid: False)
    acquire_hint_refresh_lock(
        checkpoint_path=str(ck),
        output_path=str(tmp_path / "out.json"),
        chain="base",
        sources=["dexscreener"],
    )
    assert lock_path_for(str(ck)).is_file()
    release_hint_refresh_lock(str(ck))
    assert not lock_path_for(str(ck)).is_file()
