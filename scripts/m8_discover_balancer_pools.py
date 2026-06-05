#!/usr/bin/env python3
"""Build rolling Balancer pool index for M8.2 mirror resolve.

Verifies each pool_id via Vault.getPoolTokens(bytes32) and writes
data/runs/_rolling/m8_balancer_pool_index_latest.json.

Usage:
  py -3.11 scripts/m8_discover_balancer_pools.py --chain base \\
      --registry data/runs/_rolling/m8_pending_pairs.json \\
      --output data/runs/_rolling/m8_balancer_pool_index_latest.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = REPO_ROOT / "data/runs/_rolling/m8_balancer_pool_index_latest.json"
_METADATA = REPO_ROOT / "config/adapter_metadata.yaml"
_VAULT = "0xba12222222228d8ba445958a75a0704d566bf2c8"
_GET_POOL_TOKENS_SELECTOR = "f94d4668"
_SCHEMA = "m8_balancer_pool_index.1"


def _resolve_rpc() -> str:
    try:
        from core.env import load_root_dotenv

        load_root_dotenv()
        from core.rpc_urls import resolve_rpc_http

        url, _, _ = resolve_rpc_http(chain_id=8453, network="base")
        if url:
            return url
    except Exception:
        pass
    return os.environ.get("BASE_RPC", "https://base-rpc.publicnode.com")


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


def _decode_get_pool_tokens(hex_result: str) -> tuple[list[str], list[int]]:
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    words = [raw[i : i + 64] for i in range(0, len(raw), 64)]

    def _read_array(head_word_idx: int) -> list[str]:
        offset_bytes = int(words[head_word_idx], 16)
        base = offset_bytes // 32
        length = int(words[base], 16)
        return [words[base + 1 + k] for k in range(length)]

    token_words = _read_array(0)
    balance_words = _read_array(1)
    tokens = ["0x" + w[24:].lower() for w in token_words]
    balances = [int(w, 16) for w in balance_words]
    return tokens, balances


def _load_metadata_pools(chain: str) -> list[dict]:
    if not _METADATA.exists():
        return []
    raw = yaml.safe_load(_METADATA.read_text(encoding="utf-8")) or {}
    chain_pools = (raw.get("balancer") or {}).get(chain, {}).get("pools") or {}
    vault = str((raw.get("balancer") or {}).get("vault_address") or _VAULT).lower()
    out: list[dict] = []
    for pool_id, meta in chain_pools.items():
        if not isinstance(meta, dict):
            continue
        out.append(
            {
                "pool_id": str(pool_id).lower(),
                "pool_kind": meta.get("pool_kind", "stable"),
                "pool_address": str(meta.get("pool_address") or pool_id[:42]).lower(),
                "assets": [str(a).lower() for a in (meta.get("assets") or [])],
                "vault_address": vault,
                "source": "adapter_metadata",
            }
        )
    return out


def _registry_balancer_pools(registry_path: Path, chain: str) -> list[dict]:
    if not registry_path.exists():
        return []
    reg = json.loads(registry_path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for tok in (reg.get("tokens") or {}).values():
        for venue in (tok.get("venues") or {}).values():
            if venue.get("dex") != "balancer_vault":
                continue
            pool_addr = str(venue.get("pool") or "").lower()
            if not pool_addr.startswith("0x"):
                continue
            assets = sorted(
                a
                for a in (
                    str(venue.get("token0") or "").lower(),
                    str(venue.get("token1") or "").lower(),
                )
                if a.startswith("0x")
            )
            out.append(
                {
                    "pool_id": "",
                    "pool_address": pool_addr,
                    "pool_kind": "unknown",
                    "assets": assets,
                    "vault_address": _VAULT,
                    "source": "registry_venue",
                }
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="M8 Balancer pool index builder")
    ap.add_argument("--chain", default="base")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--output", default=str(_DEFAULT_OUTPUT))
    ap.add_argument("--rpc", default=None)
    args = ap.parse_args()

    rpc = args.rpc or _resolve_rpc()
    candidates = _load_metadata_pools(args.chain)
    if args.registry:
        candidates.extend(_registry_balancer_pools(Path(args.registry), args.chain))

    seen_ids: set[str] = set()
    verified: list[dict] = []
    for cand in candidates:
        pool_id = str(cand.get("pool_id") or "").lower()
        if not pool_id or len(pool_id) != 66:
            continue
        if pool_id in seen_ids:
            continue
        seen_ids.add(pool_id)
        calldata = "0x" + _GET_POOL_TOKENS_SELECTOR + pool_id[2:]
        try:
            result = _eth_call(rpc, cand.get("vault_address") or _VAULT, calldata)
            tokens, balances = _decode_get_pool_tokens(result)
        except Exception as exc:
            print(f"SKIP {pool_id[:18]}... verify failed: {exc}")
            continue
        if len(tokens) < 2:
            continue
        assets = sorted(t.lower() for t in tokens)
        verified.append(
            {
                "pool_id": pool_id,
                "pool_address": str(cand.get("pool_address") or pool_id[:42]).lower(),
                "vault_address": str(cand.get("vault_address") or _VAULT).lower(),
                "pool_kind": cand.get("pool_kind", "stable"),
                "assets": assets,
                "balances": balances,
                "probe_status": "QUOTE_OK_VAULT_VERIFY",
                "source": cand.get("source", "unknown"),
            }
        )
        print(f"OK {pool_id[:18]}... tokens={len(tokens)}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _SCHEMA,
        "generated_at_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chain": args.chain,
        "vault_address": _VAULT,
        "pools_verified": len(verified),
        "pools": verified,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(verified)} pools -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
