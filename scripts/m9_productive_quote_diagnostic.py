#!/usr/bin/env python3
"""Productive M9 quote diagnostic for Balancer/Maverick (raw_http_probe path)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_OUT = "data/tmp/m9_productive_quote_diagnostic_latest.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="M9 productive distinct-pricing quote diagnostic")
    ap.add_argument("--chain", default="base")
    ap.add_argument("--max-routes", type=int, default=10)
    ap.add_argument("--output", default=_DEFAULT_OUT)
    ap.add_argument(
        "--index",
        choices=["balancer", "maverick", "both"],
        default="both",
    )
    args = ap.parse_args()

    from m8.discovery.specialized_index_rpc import resolve_productive_rpc
    from m8_1.stable_anchor.pairs import TokenInfo
    from m8_1.stable_anchor.pool_discovery import DexRoute
    from m9.graph_arb.productive_distinct_quote import (
        balancer_index_row_tokens,
        balancer_probe_amount_in,
    )
    from m9.graph_arb.raw_http_probe import probe_quote_raw_http

    rpc = resolve_productive_rpc(args.chain)
    if not rpc:
        print("ERROR: no RPC", file=sys.stderr)
        return 1

    samples = []
    productive_counts: dict[str, str] = {}

    def _probe_row(row: dict, *, adapter_type: str, dex_id: str) -> None:
        pool = str(row.get("pool_address") or row.get("pool_id") or "")
        bal_assets: list[str] | None = None
        if dex_id == "balancer_vault":
            token_a, token_b, bal_assets = balancer_index_row_tokens(row)
            amount = balancer_probe_amount_in(row, token_in=token_a)
        else:
            token_a = str(row.get("token_a") or row.get("token0_addr") or "")
            token_b = str(row.get("token_b") or row.get("token1_addr") or "")
            amount = 10_000
        if not token_a or not token_b or not pool:
            return
        route = DexRoute(
            dex_id=dex_id,
            adapter_type=adapter_type,
            quoter=pool if dex_id == "maverick_v2" else str(row.get("vault_address") or ""),
            fee=0,
            tick_spacing=0,
            curve_coin0_sym="",
            pool_id=row.get("pool_id"),
            vault_address=row.get("vault_address"),
            balancer_assets=bal_assets or None,
            token_in_index=1 if dex_id == "maverick_v2" else None,
        )
        result = probe_quote_raw_http(
            rpc,
            route,
            TokenInfo(address=token_a, symbol="A", decimals=18),
            TokenInfo(address=token_b, symbol="B", decimals=18),
            amount,
        )
        status = "QUOTE_OK_PRODUCTIVE" if result.ok else str(result.reject_reason or "FAIL")
        key = f"{dex_id}:{pool.lower()}"
        productive_counts[key] = status
        samples.append(
            {
                "dex_id": dex_id,
                "pool": pool,
                "ok": result.ok,
                "productive_quote_status": status,
                "amount_out": result.amount_out,
                "quote_target": result.quote_target,
                "quote_selector": result.quote_selector,
                "quote_abi_path": result.quote_abi_path,
                "quote_pool_id": result.quote_pool_id,
                "raw_error": result.raw_error,
            }
        )

    if args.index in ("balancer", "both"):
        bal_path = REPO_ROOT / "data/runs/_rolling/m8_balancer_pool_index_latest.json"
        if bal_path.exists():
            bal = json.loads(bal_path.read_text(encoding="utf-8"))
            for row in (bal.get("pools") or [])[: args.max_routes]:
                if str(row.get("quote_smoke_status", "")).startswith("QUOTE_OK"):
                    _probe_row(row, adapter_type="balancer_weighted", dex_id="balancer_vault")

    if args.index in ("maverick", "both"):
        mav_path = REPO_ROOT / "data/runs/_rolling/m8_maverick_pool_index_latest.json"
        if mav_path.exists():
            mav = json.loads(mav_path.read_text(encoding="utf-8"))
            pools = mav.get("pools") or mav.get("verified_pools") or []
            for row in pools[: args.max_routes]:
                if str(row.get("quote_smoke_status", "")).startswith("QUOTE_OK"):
                    _probe_row(row, adapter_type="maverick_v2", dex_id="maverick_v2")

    ok_n = sum(1 for s in samples if s.get("ok"))
    payload = {
        "chain": args.chain,
        "rpc_configured": bool(rpc),
        "samples": samples,
        "productive_quote_counts": productive_counts,
        "metrics": {
            "productive_samples": len(samples),
            "productive_quote_ok": ok_n,
            "productive_balancer_quoteable_routes": sum(
                1 for s in samples if s.get("dex_id") == "balancer_vault" and s.get("ok")
            ),
            "productive_maverick_quoteable_routes": sum(
                1 for s in samples if s.get("dex_id") == "maverick_v2" and s.get("ok")
            ),
        },
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["metrics"], indent=2))
    return 0 if ok_n > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
