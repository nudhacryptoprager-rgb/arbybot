#!/usr/bin/env python3
"""Build rolling Maverick V2 pool index for M8.2 mirror resolve."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_OUTPUT = REPO_ROOT / "data/runs/_rolling/m8_maverick_pool_index_latest.json"
_SCHEMA = "m8_maverick_pool_index.1"


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
    for sym, meta in (raw.get("tokens") or {}).items():
        if isinstance(meta, dict) and meta.get("address"):
            out.add(str(meta["address"]).lower())
    return out


def _load_previous_pools(out_path: Path) -> list[dict]:
    if not out_path.exists():
        return []
    try:
        raw = json.loads(out_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    pools = raw.get("pools") or []
    return pools if isinstance(pools, list) else []


def main() -> int:
    ap = argparse.ArgumentParser(description="M8 Maverick pool index builder")
    ap.add_argument("--chain", default="base")
    ap.add_argument("--registry", required=True)
    ap.add_argument("--watchlist", default="data/tmp/m8_token_watchlist_latest.json")
    ap.add_argument("--external-hints", default="data/runs/_rolling/m8_external_pool_hints_latest.json")
    ap.add_argument("--output", default=str(_DEFAULT_OUTPUT))
    ap.add_argument("--rpc", default=None)
    ap.add_argument("--scan-factory-logs", action="store_true")
    ap.add_argument("--no-factory-pagination", action="store_true")
    ap.add_argument("--verify-factory", action="store_true", default=True)
    ap.add_argument("--quote-smoke", action="store_true")
    args = ap.parse_args()

    from m8.discovery.maverick_indexer import build_maverick_index
    from m8.discovery.specialized_index_rpc import resolve_productive_rpc

    rpc = args.rpc or resolve_productive_rpc(args.chain)
    if not rpc:
        print("ERROR: no RPC URL", file=sys.stderr)
        return 1
    watchlist = _load_watchlist_tokens(args.watchlist)
    connectors = _connector_tokens_from_config()
    out_path = Path(args.output)
    previous_pools = _load_previous_pools(out_path)
    hints_path = Path(args.external_hints)
    external_hints = None
    if hints_path.exists():
        external_hints = json.loads(hints_path.read_text(encoding="utf-8"))

    print(
        f"maverick lookup budget: watchlist={len(watchlist)} connectors={len(connectors)} "
        f"previous_pools={len(previous_pools)}",
        flush=True,
    )
    verified, metrics = build_maverick_index(
        chain=args.chain,
        rpc_url=rpc,
        watchlist_tokens=watchlist,
        connector_tokens=connectors,
        registry_path=Path(args.registry),
        external_hints_artifact=external_hints,
        scan_factory_logs=args.scan_factory_logs,
        scan_factory_pagination=not args.no_factory_pagination,
        verify_factory=args.verify_factory,
        quote_smoke=args.quote_smoke,
    )
    for row in verified:
        print(
            f"OK {row.get('pool_address','')[:14]}... "
            f"{row.get('token_a','')[:10]}/{row.get('token_b','')[:10]} "
            f"probe={row.get('probe_status')}"
        )

    pools_out = verified
    carried_forward = 0
    if not verified and previous_pools:
        pools_out = previous_pools
        carried_forward = len(previous_pools)
        metrics = {
            **metrics,
            "previous_pools_carried_forward": carried_forward,
            "discovery_failed_reason": metrics.get(
                "discovery_failed_reason", "ZERO_VERIFIED_POOLS"
            ),
        }
        print(
            f"WARN: zero verified pools; carrying forward {carried_forward} previous pools",
            flush=True,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _SCHEMA,
        "generated_at_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chain": args.chain,
        "pools_indexed": len(pools_out),
        "metrics": metrics,
        "pools": pools_out,
    }
    if carried_forward:
        payload["previous_pools_carried_forward"] = carried_forward
        payload["discovery_failed_reason"] = metrics.get("discovery_failed_reason")
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(pools_out)} pools -> {out_path}")
    print(f"metrics: {metrics}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
