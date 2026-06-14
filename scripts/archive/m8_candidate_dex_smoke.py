#!/usr/bin/env python3
"""Targeted on-chain smoke for M8.2 P0 candidate DEX lanes (iZiSwap, QuickSwap Algebra)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_exotic_config() -> dict:
    from m8.discovery.cross_dex_expand import load_yaml_config

    return load_yaml_config(REPO_ROOT / "config" / "exotic_base_anchor.yaml")


def main() -> int:
    ap = argparse.ArgumentParser(description="M8.2 candidate DEX factory/resolver smoke")
    ap.add_argument("--chain", default="base")
    ap.add_argument(
        "--pairs",
        default="WETH/USDC",
        help="Comma-separated exotic/anchor symbol pairs",
    )
    ap.add_argument("--output", default="data/tmp/m8_candidate_dex_smoke_latest.json")
    args = ap.parse_args()

    if os.environ.get("ARBY_SKIP_RPC") == "1":
        print("ARBY_SKIP_RPC=1 — smoke skipped")
        return 0

    from discovery.pool_resolver import get_pool_resolver
    from m8.discovery.cross_dex_expand import _resolve_via_factory

    config = _load_exotic_config()
    resolver = get_pool_resolver(args.chain)
    tokens = config.get("tokens") or {}

    results = []
    for pair in [p.strip() for p in args.pairs.split(",") if p.strip()]:
        exotic_sym, anchor_sym = pair.split("/", 1)
        exotic_addr = str((tokens.get(exotic_sym) or {}).get("address") or "").lower()
        anchor_addr = str((tokens.get(anchor_sym) or {}).get("address") or "").lower()
        for dex_id in ("iziswap_base", "quickswap_algebra"):
            pool, reason = _resolve_via_factory(
                args.chain,
                dex_id,
                exotic_sym,
                anchor_sym,
                exotic_address=exotic_addr,
                anchor_address=anchor_addr,
                dry_run=False,
                resolver=resolver,
                config=config,
            )
            results.append({
                "dex_id": dex_id,
                "pair": pair,
                "pool_address": (pool or {}).get("pool_address"),
                "reason": reason,
                "ok": pool is not None,
            })
            print(f"{dex_id} {pair}: {reason} pool={((pool or {}).get('pool_address') or '-')}")

    artifact = {
        "schema_version": "m8_candidate_dex_smoke.1",
        "chain": args.chain,
        "results": results,
        "pass_count": sum(1 for r in results if r["ok"]),
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print("written:", out)
    return 0 if artifact["pass_count"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
