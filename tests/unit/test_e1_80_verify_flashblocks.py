"""E1.80 Iter 6 — verify_flashblocks helper smoke tests."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from scripts import verify_flashblocks as vf


def test_missing_rpc_url_returns_2(monkeypatch):
    monkeypatch.delenv("ARBY_BASE_RPC_URL", raising=False)
    rc = vf.main(["--rpc-url", ""])
    assert rc == 2


def test_call_ok_returns_0(monkeypatch):
    # Stub http_post directly via the imported module after main runs it.
    import chains.flashblocks_http as fh

    def fake_post(url, payload, timeout_s):
        # Minimal valid JSON-RPC reply: empty logs list.
        return {"jsonrpc": "2.0", "id": 1, "result": []}

    monkeypatch.setattr(vf, "_http_post", fake_post)
    monkeypatch.setenv("ARBY_FLASHBLOCKS_HTTP_LANE", "1")

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = vf.main(["--rpc-url", "https://example.invalid", "--pool", "0xabc"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["stats"]["calls_ok"] == 1
    assert payload["logs_returned"] == 0


def test_call_failure_returns_1(monkeypatch):
    def fake_post(url, payload, timeout_s):
        raise RuntimeError("simulated transport error")

    monkeypatch.setattr(vf, "_http_post", fake_post)
    monkeypatch.setenv("ARBY_FLASHBLOCKS_HTTP_LANE", "1")

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = vf.main(["--rpc-url", "https://example.invalid", "--pool", "0xabc"])
    assert rc == 1
    payload = json.loads(buf.getvalue())
    assert payload["stats"]["calls_ok"] == 0
    assert payload["stats"]["calls_other_error"] >= 1
