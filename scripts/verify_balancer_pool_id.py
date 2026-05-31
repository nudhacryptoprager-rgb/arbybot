#!/usr/bin/env python3
"""Verify a Balancer V2 pool_id on-chain before adding it to adapter_metadata.yaml.

The M8/8.1 → M9 bridge quotes Balancer pools via ``Vault.queryBatchSwap``,
which requires a 32-byte ``pool_id`` and the correct token ordering.  A wrong
pool_id silently reverts (QUOTE_REVERT) or, worse, decodes phantom output.
This helper calls ``Vault.getPoolTokens(bytes32)`` via a raw JSON-RPC
``eth_call`` and prints the on-chain tokens + balances so the operator can
confirm the pool_id and token order before activating the pool.

Usage
-----
  $env:BASE_RPC="https://base.publicnode.com"
  py -3.11 scripts/verify_balancer_pool_id.py \
      --pool-id 0x5332584890d6e415a6dc910254d6430b8aab7e69000200000000000000000103

  # Optionally assert expected tokens are present (order-independent):
  py -3.11 scripts/verify_balancer_pool_id.py --pool-id 0x... \
      --expect 0x4200000000000000000000000000000000000006 \
      --expect 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913

Exit codes
----------
  0  pool_id resolved (and, if --expect given, all expected tokens present)
  1  RPC / decode error, or expected tokens missing
  2  bad arguments
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

# Balancer Vault (same address on all EVM chains)
_VAULT = "0xBA12222222228d8Ba445958a75a0704d566BF2C8"
# keccak256("getPoolTokens(bytes32)")[:4]
_GET_POOL_TOKENS_SELECTOR = "f94d4668"


def _eth_call(rpc_url: str, to: str, data: str) -> str:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
    }
    resp = httpx.post(rpc_url, json=payload, timeout=20.0)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"eth_call error: {body['error']}")
    return body["result"]


def _decode_get_pool_tokens(hex_result: str) -> "tuple[list[str], list[int]]":
    """Decode getPoolTokens → (tokens, balances).

    ABI return: (address[] tokens, uint256[] balances, uint256 lastChangeBlock).
    The two dynamic arrays are referenced by head offsets.
    """
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 64 * 3:
        raise ValueError(f"getPoolTokens response too short: {len(raw)} hex chars")
    words = [raw[i : i + 64] for i in range(0, len(raw), 64)]

    def _read_array(head_word_idx: int) -> "list[str]":
        offset_bytes = int(words[head_word_idx], 16)
        base = offset_bytes // 32  # word index of the array length
        length = int(words[base], 16)
        return [words[base + 1 + k] for k in range(length)]

    token_words = _read_array(0)
    balance_words = _read_array(1)
    tokens = ["0x" + w[24:] for w in token_words]
    balances = [int(w, 16) for w in balance_words]
    return tokens, balances


def _resolve_rpc(cli_rpc: "str | None") -> str:
    if cli_rpc:
        return cli_rpc
    for env_key in ("BASE_RPC", "ARBITRUM_RPC", "RPC_URL", "ETH_RPC_URL"):
        val = os.environ.get(env_key)
        if val:
            return val
    raise SystemExit(
        "No RPC URL: pass --rpc or set BASE_RPC / ARBITRUM_RPC / RPC_URL"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify a Balancer V2 pool_id on-chain")
    ap.add_argument("--pool-id", required=True, help="32-byte pool id (0x + 64 hex)")
    ap.add_argument("--rpc", default=None, help="RPC URL (else BASE_RPC/ARBITRUM_RPC env)")
    ap.add_argument("--vault", default=_VAULT, help="Vault address (default: canonical)")
    ap.add_argument(
        "--expect",
        action="append",
        default=[],
        help="Expected token address (repeatable); checked order-independent",
    )
    args = ap.parse_args()

    pool_id = args.pool_id.lower()
    if not pool_id.startswith("0x") or len(pool_id) != 66:
        print(f"ERROR: pool_id must be 0x + 64 hex chars, got {args.pool_id!r}")
        return 2

    rpc_url = _resolve_rpc(args.rpc)
    calldata = "0x" + _GET_POOL_TOKENS_SELECTOR + pool_id[2:]

    try:
        result = _eth_call(rpc_url, args.vault, calldata)
        tokens, balances = _decode_get_pool_tokens(result)
    except Exception as exc:  # noqa: BLE001 — CLI surfaces any failure
        print(f"FAIL: getPoolTokens reverted or undecodable: {exc}")
        print("  → pool_id likely wrong, pool not registered, or wrong chain/vault.")
        return 1

    if not tokens:
        print("FAIL: pool registered but has 0 tokens (paused/empty?).")
        return 1

    print(f"pool_id : {pool_id}")
    print(f"vault   : {args.vault}")
    print(f"tokens  : {len(tokens)}")
    for tok, bal in zip(tokens, balances):
        print(f"  - {tok}  balance={bal}")

    print(
        "\nadapter_metadata.yaml snippet (assets order MUST match the list above):"
    )
    print(f"  pool_id: \"{pool_id}\"")
    print("  assets:")
    for tok in tokens:
        print(f"    - \"{tok}\"")

    expected = {a.lower() for a in args.expect}
    if expected:
        present = {t.lower() for t in tokens}
        missing = expected - present
        if missing:
            print("\nFAIL: expected tokens not in pool: " + ", ".join(sorted(missing)))
            return 1
        print("\nOK: all expected tokens present.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
