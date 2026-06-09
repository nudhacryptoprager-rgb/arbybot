#!/usr/bin/env python3
"""Build rolling Balancer pool index for M8.2 mirror resolve."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_OUTPUT = REPO_ROOT / "data/runs/_rolling/m8_balancer_pool_index_latest.json"
_SCHEMA = "m8_balancer_pool_index.1"


def _load_watchlist_tokens(path: str) -> set[str]:
    from m8.discovery.token_watchlist import load_watchlist

    wl = load_watchlist(path)
    return {t.lower() for t in (wl.get("tokens") or {}) if t.startswith("0x")}


def _connector_tokens_from_config() -> set[str]:
    import yaml

    cfg_path = REPO_ROOT / "config/exotic_base_anchor.yaml"
    if not cfg_path.exists():
        return set()
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    out: set[str] = set()
    for meta in (raw.get("tokens") or {}).values():
        if isinstance(meta, dict) and meta.get("address"):
            out.add(str(meta["address"]).lower())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="M8 Balancer pool index builder")
    ap.add_argument("--chain", default="base")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--watchlist", default="data/tmp/m8_token_watchlist_latest.json")
    ap.add_argument("--output", default=str(_DEFAULT_OUTPUT))
    ap.add_argument("--rpc", default=None)
    ap.add_argument("--no-graphql", action="store_true")
    ap.add_argument("--verify-vault", action="store_true", default=True)
    ap.add_argument("--quote-smoke", action="store_true")
    args = ap.parse_args()

    from m8.discovery.balancer_indexer import build_balancer_index, load_balancer_config
    from m8.discovery.specialized_index_rpc import resolve_productive_rpc

    rpc = args.rpc or resolve_productive_rpc(args.chain)
    if not rpc:
        print("ERROR: no RPC URL", file=sys.stderr)
        return 1
    cfg = load_balancer_config(args.chain)
    watchlist = _load_watchlist_tokens(args.watchlist)
    connectors = _connector_tokens_from_config()
    registry = Path(args.registry) if args.registry else None
    verified, metrics = build_balancer_index(
        chain=args.chain,
        rpc_url=rpc,
        watchlist_tokens=watchlist,
        connector_tokens=connectors,
        registry_path=registry,
        use_graphql=not args.no_graphql,
        verify_vault=args.verify_vault,
        quote_smoke=args.quote_smoke,
    )
    for row in verified:
        print(
            f"OK {row.get('pool_id','')[:18]}... tokens={len(row.get('assets') or [])} "
            f"probe={row.get('probe_status')}"
        )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _SCHEMA,
        "generated_at_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chain": args.chain,
        "vault_address": cfg["vault_address"],
        "pools_verified": len(verified),
        "metrics": metrics,
        "pools": verified,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(verified)} pools -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
