#!/usr/bin/env python3
"""Print rolling sniper artifact metrics for runtime soak monitoring."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ARTIFACT = Path(__file__).resolve().parents[1] / "data/runs/_rolling/new_pool_sniper_latest.json"


def main() -> int:
    if not _ARTIFACT.exists():
        print(f"MISSING {_ARTIFACT}")
        return 1
    data = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    m = data.get("metrics") or {}
    status = data.get("status", "?")
    gen = data.get("generated_at_utc", "?")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"=== sniper monitor @ {now} ===")
    print(f"artifact_generated_at_utc: {gen}")
    print(f"status: {status}")
    keys = [
        "snipe_candidates_total",
        "raw_fetched",
        "rpc_errors",
        "rpc_calls_made",
        "cycles_completed",
        "elapsed_s",
        "sniper_rpc_provider",
        "sniper_rpc_secondary_provider",
        "sniper_rpc_failover_count",
        "getlogs_400_count",
        "getlogs_429_count",
        "getlogs_chunk_size",
        "listener_mode",
        "ws_provider",
        "http_fallback_provider",
    ]
    for k in keys:
        if k in m:
            print(f"  {k}: {m[k]}")
    hist = m.get("rpc_error_histogram") or {}
    if hist:
        print(f"  rpc_error_histogram: {hist}")
    reasons = data.get("reasons") or []
    if reasons:
        print(f"  reasons: {reasons[:5]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
