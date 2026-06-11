"""E1.80 Iter 6 — Flashblocks operational verification helper.

Pings the configured RPC endpoint with a single ``eth_getLogs`` call using
``fromBlock=toBlock=pending`` (or ``latest`` when ``ARBY_FLASHBLOCKS_USE_LATEST=1``)
against a small set of pool addresses, and reports whether
``flashblocks_http_calls_ok`` would advance.

Exit codes:
  0 — call returned a 200/JSON-RPC dict, ``calls_ok`` advanced.
  1 — call attempted but failed (transport, RPC error, or breaker open).
  2 — disabled (``ARBY_FLASHBLOCKS_HTTP_LANE!=1``) or missing config.

Usage:
  py -3.11 scripts/verify_flashblocks.py --rpc-url $env:ARBY_BASE_RPC_URL \
      --pool 0x...  [--pool 0x...]  [--latest]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _http_post(url: str, payload: dict, timeout_s: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rpc-url", default=os.environ.get("ARBY_BASE_RPC_URL", ""))
    p.add_argument("--pool", action="append", default=[])
    p.add_argument("--timeout-s", type=float, default=5.0)
    p.add_argument("--latest", action="store_true",
                   help="Use 'latest' block tag (works on Alchemy/dRPC).")
    args = p.parse_args(argv)

    if not args.rpc_url:
        print("verify_flashblocks: missing --rpc-url / ARBY_BASE_RPC_URL", file=sys.stderr)
        return 2
    if not args.pool:
        # WETH/USDC Aerodrome CL on Base — high-volume default for sanity.
        args.pool = ["0xb2cc224c1c9feE385f8ad6a55b4d94E92359DC59"]

    # Force-enable flag + optional latest override for this process only.
    os.environ["ARBY_FLASHBLOCKS_HTTP_LANE"] = "1"
    if args.latest:
        os.environ["ARBY_FLASHBLOCKS_USE_LATEST"] = "1"

    # Import after env so module-level reads pick up the gate.
    from chains import flashblocks_http as fh

    fh.reset_stats()
    logs = fh.fetch_pending_pool_logs(
        rpc_url=args.rpc_url,
        addresses=args.pool,
        http_post=_http_post,
        timeout_s=args.timeout_s,
    )
    s: dict[str, Any] = fh.stats()
    print(json.dumps({
        "rpc_url": args.rpc_url[:60] + ("..." if len(args.rpc_url) > 60 else ""),
        "pools": args.pool,
        "block_tag": "latest" if args.latest else "pending",
        "logs_returned": len(logs),
        "stats": s,
    }, indent=2))
    return 0 if s.get("calls_ok", 0) > 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
