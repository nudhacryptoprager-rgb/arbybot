"""Shared RPC helpers for specialized pool indexers."""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, List, Optional


def resolve_productive_rpc(chain: str = "base") -> str:
    try:
        from core.env import load_root_dotenv
        from core.rpc_urls import apply_productive_rpc_env, resolve_productive_http_rpc

        load_root_dotenv()
        env = apply_productive_rpc_env(chain)
        url = resolve_productive_http_rpc(chain, env=env)
        if url:
            return url
        return str(env.get("BASE_RPC_PRIMARY") or env.get("BASE_RPC") or "")
    except Exception:
        return os.environ.get("BASE_RPC", "")


def eth_call(rpc_url: str, to: str, data: str, *, timeout_s: float = 20.0) -> str:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if body.get("error"):
        raise RuntimeError(str(body["error"]))
    return str(body.get("result") or "0x")


def eth_get_logs(
    rpc_url: str,
    *,
    address: str,
    topics: List[str],
    from_block: int,
    to_block: int,
    timeout_s: float = 30.0,
) -> List[Dict[str, Any]]:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getLogs",
            "params": [
                {
                    "fromBlock": hex(from_block),
                    "toBlock": hex(to_block),
                    "address": address,
                    "topics": topics,
                }
            ],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if body.get("error"):
        raise RuntimeError(str(body["error"]))
    rows = body.get("result") or []
    return rows if isinstance(rows, list) else []


def eth_block_number(rpc_url: str) -> int:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
    ).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return int(body.get("result") or "0x0", 16)


def selector(sig: str) -> str:
    from web3 import Web3

    return Web3.keccak(text=sig).hex()[:8]
