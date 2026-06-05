#!/usr/bin/env python3
"""Build rolling Maverick V2 pool index for M8.2 mirror resolve.

Indexes Maverick venues from the M8 pending registry (and optional metadata).
Quote smoke is marked INDEXED_FROM_REGISTRY until a dedicated probe is wired.

Usage:
  py -3.11 scripts/m8_discover_maverick_pools.py --chain base \\
      --registry data/runs/_rolling/m8_pending_pairs.json \\
      --output data/runs/_rolling/m8_maverick_pool_index_latest.json
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
_DEFAULT_OUTPUT = REPO_ROOT / "data/runs/_rolling/m8_maverick_pool_index_latest.json"
_METADATA = REPO_ROOT / "config/adapter_metadata.yaml"
_TOKEN_A_SELECTOR = "0dfe1681"  # tokenA()
_SCHEMA = "m8_maverick_pool_index.1"


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


def _fetch_token_a(rpc_url: str, pool_addr: str) -> str:
    result = _eth_call(rpc_url, pool_addr, "0x" + _TOKEN_A_SELECTOR)
    raw = result[2:] if result.startswith("0x") else result
    return ("0x" + raw[-40:]).lower()


def _load_metadata_pools(chain: str) -> list[dict]:
    if not _METADATA.exists():
        return []
    raw = yaml.safe_load(_METADATA.read_text(encoding="utf-8")) or {}
    chain_pools = (raw.get("maverick") or {}).get(chain, {}).get("pools") or {}
    out: list[dict] = []
    for pool_addr, meta in chain_pools.items():
        if not isinstance(meta, dict):
            continue
        token_a = str(meta.get("token_a") or "").lower()
        if not token_a:
            continue
        out.append(
            {
                "pool_address": str(pool_addr).lower(),
                "token_a": token_a,
                "token_b": str(meta.get("token_b") or "").lower(),
                "probe_status": meta.get("probe_status", "QUOTE_OK_CONFIG"),
                "source": "adapter_metadata",
            }
        )
    return out


def _registry_maverick_pools(registry_path: Path) -> list[dict]:
    if not registry_path.exists():
        return []
    reg = json.loads(registry_path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for tok in (reg.get("tokens") or {}).values():
        for venue in (tok.get("venues") or {}).values():
            if venue.get("dex") != "maverick_v2":
                continue
            pool_addr = str(venue.get("pool") or "").lower()
            t0 = str(venue.get("token0") or "").lower()
            t1 = str(venue.get("token1") or "").lower()
            if not pool_addr.startswith("0x"):
                continue
            out.append(
                {
                    "pool_address": pool_addr,
                    "token_a": t0,
                    "token_b": t1,
                    "probe_status": "INDEXED_FROM_REGISTRY",
                    "source": "registry_venue",
                }
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="M8 Maverick pool index builder")
    ap.add_argument("--chain", default="base")
    ap.add_argument("--registry", required=True)
    ap.add_argument("--output", default=str(_DEFAULT_OUTPUT))
    ap.add_argument("--rpc", default=None)
    ap.add_argument("--probe-token-a", action="store_true", help="eth_call tokenA() per pool")
    args = ap.parse_args()

    rpc = args.rpc or _resolve_rpc()
    candidates = _load_metadata_pools(args.chain)
    candidates.extend(_registry_maverick_pools(Path(args.registry)))

    seen: set[str] = set()
    indexed: list[dict] = []
    for cand in candidates:
        pool_addr = str(cand.get("pool_address") or "").lower()
        if not pool_addr or pool_addr in seen:
            continue
        seen.add(pool_addr)
        token_a = str(cand.get("token_a") or "").lower()
        token_b = str(cand.get("token_b") or "").lower()
        if args.probe_token_a or not token_a:
            try:
                token_a = _fetch_token_a(rpc, pool_addr)
            except Exception as exc:
                print(f"SKIP {pool_addr[:14]}... tokenA failed: {exc}")
                continue
        if token_a and token_b and token_a > token_b:
            token_a, token_b = token_b, token_a
        if not token_a or not token_b:
            print(f"SKIP {pool_addr[:14]}... missing token pair")
            continue
        probe = str(cand.get("probe_status") or "INDEXED_FROM_REGISTRY")
        if probe == "INDEXED_FROM_REGISTRY":
            probe = "MAVERICK_INDEXED_NOT_QUOTE_PROBED"
        indexed.append(
            {
                "pool_address": pool_addr,
                "token_a": token_a,
                "token_b": token_b,
                "probe_status": probe,
                "source": cand.get("source", "unknown"),
            }
        )
        print(f"OK {pool_addr[:14]}... {token_a[:10]} / {token_b[:10]}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _SCHEMA,
        "generated_at_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chain": args.chain,
        "pools_indexed": len(indexed),
        "pools": indexed,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(indexed)} pools -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
