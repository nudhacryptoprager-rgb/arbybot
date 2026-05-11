"""E1.83 — Refresh pool_family_truth.json rolling artifact.

Queries on-chain DEX factories for the BASE_TARGET_PAIRS list and writes
``data/runs/_rolling/pool_family_truth.json``.  The bridge_runtime.py loads
this artifact on each cold cycle to populate factory_pool_count / factory_dex_count
per pair, enabling Step 8 guard (skip confirmed single-DEX pairs).

Usage (online, requires BASE_RPC env var or positional arg):
    py -3.11 scripts/refresh_factory_truth.py
    py -3.11 scripts/refresh_factory_truth.py https://mainnet.base.org

Usage (offline test — writes empty artifact with 0 pairs):
    ARBY_SKIP_RPC=1 py -3.11 scripts/refresh_factory_truth.py

Exit codes:
    0  — artifact written (may have 0 pools if ARBY_SKIP_RPC=1 or RPC errors)
    1  — fatal error (import failure, write error)
"""
from __future__ import annotations

import os
import sys

# Ensure repo root is on path when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    try:
        from m7.scouts.factory_scout import (
            BASE_TARGET_PAIRS,
            scan_factories_for_pairs,
            write_pool_family_truth,
            _POOL_FAMILY_TRUTH_PATH,
        )
    except ImportError as exc:
        print(f"[refresh_factory_truth] FATAL import error: {exc}", file=sys.stderr)
        return 1

    # Resolve RPC URL: CLI arg → BASE_RPC env → publicnode fallback.
    rpc_url = ""
    if len(sys.argv) > 1:
        rpc_url = sys.argv[1].strip()
    if not rpc_url:
        rpc_url = os.environ.get("BASE_RPC", "").strip()
    if not rpc_url:
        rpc_url = "https://mainnet.base.org"  # public fallback

    skip_rpc = os.environ.get("ARBY_SKIP_RPC", "0") == "1"
    if skip_rpc:
        print("[refresh_factory_truth] ARBY_SKIP_RPC=1 — writing empty artifact")
        entries = []
    else:
        print(f"[refresh_factory_truth] Scanning {len(BASE_TARGET_PAIRS)} pairs on base via {rpc_url}")
        try:
            entries = scan_factories_for_pairs(
                network="base",
                pairs=BASE_TARGET_PAIRS,
                rpc_url=rpc_url,
            )
        except Exception as exc:
            print(f"[refresh_factory_truth] scan error: {exc}", file=sys.stderr)
            entries = []

    try:
        write_pool_family_truth(entries, path=_POOL_FAMILY_TRUTH_PATH)
        print(f"[refresh_factory_truth] OK — {len(entries)} pools → {_POOL_FAMILY_TRUTH_PATH}")
    except Exception as exc:
        print(f"[refresh_factory_truth] write error: {exc}", file=sys.stderr)
        return 1

    # Print summary table.
    from m7.scouts.factory_scout import build_pool_family_truth
    truth = build_pool_family_truth(entries)
    if truth:
        print(f"\n{'Pair':<20} {'pools':>5} {'dexes':>6}  dex_set")
        print("-" * 60)
        for key, pft in sorted(truth.items()):
            print(f"{key:<20} {pft.pool_count:>5} {pft.dex_count:>6}  {sorted(pft.dex_set)}")
    else:
        print("[refresh_factory_truth] No pools found (SKIP_RPC or RPC errors)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
