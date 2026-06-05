#!/usr/bin/env python3
"""Probe token contract deployment blocks for M8/M9 bridge or registry tokens."""
from __future__ import annotations

import argparse
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _load_tokens_from_bridge(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for route in data.get("active_routes") or data.get("routes") or []:
        for key in ("token0_addr", "token1_addr"):
            addr = (route.get(key) or "").lower()
            if not addr or addr in seen:
                continue
            seen.add(addr)
            rows.append({
                "address": addr,
                "symbol": route.get(key.replace("_addr", ""), ""),
                "source": route.get("source", ""),
            })
    return rows


def _load_tokens_from_registry(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    rows: list[dict[str, str]] = []
    for addr, tok in (data.get("tokens") or {}).items():
        rows.append({
            "address": addr.lower(),
            "symbol": str(tok.get("symbol") or ""),
            "token_first_seen_ts": tok.get("first_seen_ts"),
            "source": "m8_pending_pairs",
        })
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description="Probe token contract creation blocks")
    p.add_argument("--chain", default="base")
    p.add_argument(
        "--inventory",
        default="data/runs/_rolling/m9_bridge_inventory_latest.json",
        help="Bridge inventory JSON (active_routes)",
    )
    p.add_argument(
        "--registry",
        default=None,
        help="Optional m8_pending_pairs.json; merged with bridge exotic tokens",
    )
    p.add_argument(
        "--output",
        default="data/tmp/m8_token_contract_age_latest.json",
    )
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args()

    from core.rpc_urls import apply_productive_rpc_env, resolve_productive_http_rpc
    from m8.discovery.token_contract_age import probe_token_creation_block
    from web3 import Web3

    apply_productive_rpc_env(chain=args.chain)
    rpc_url = resolve_productive_http_rpc(args.chain)
    if not rpc_url:
        print("ERROR: no HTTP RPC for chain", args.chain, file=sys.stderr)
        return 1
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))

    tokens = _load_tokens_from_bridge(args.inventory)
    if args.registry:
        reg = _load_tokens_from_registry(args.registry)
        known = {t["address"] for t in tokens}
        tokens.extend(t for t in reg if t["address"] not in known)
    tokens = tokens[: args.limit]

    latest = int(w3.eth.block_number)
    results = []
    for tok in tokens:
        addr = tok["address"]
        creation = probe_token_creation_block(w3, addr, latest_block=latest)
        results.append({
            **tok,
            "token_creation_block": creation,
            "probe_latest_block": latest,
        })

    out = {
        "schema_version": "m8_token_contract_age.1",
        "chain": args.chain,
        "inventory_path": args.inventory.replace("\\", "/"),
        "probe_latest_block": latest,
        "tokens_probed": len(results),
        "tokens": results,
    }
    out_path = os.path.join(_REPO_ROOT, args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"Wrote {args.output} ({len(results)} tokens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
