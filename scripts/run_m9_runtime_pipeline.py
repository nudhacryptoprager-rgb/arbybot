#!/usr/bin/env python3
"""One-shot M9 runtime validation: depth → bridge → diagnostic → soak metrics."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _dedicated_http_rpc() -> str:
    from core.env import load_root_dotenv

    load_root_dotenv()
    from core.rpc_urls import apply_productive_rpc_env, resolve_productive_http_rpc

    try:
        return resolve_productive_http_rpc("base")
    except RuntimeError:
        pass
    env = apply_productive_rpc_env("base")
    return env["BASE_RPC_PRIMARY"]


def main() -> int:
    rpc = _dedicated_http_rpc()
    env = os.environ.copy()
    env["BASE_RPC"] = rpc
    env.setdefault("ARBY_PRODUCTIVE_REQUIRE_DEPTH", "1")
    env.setdefault("ARBY_DEPTH_USE_MULTICALL", "1")
    env.setdefault("ARBY_M9_MAX_CYCLES_PER_ADAPTER", "8")
    env.setdefault("ARBY_RPC_RPS_LIMIT", "6")

    inv = _REPO / "data/runs/_rolling/m9_bridge_inventory_latest.json"
    steps_pre = [
        [sys.executable, str(_REPO / "scripts/m9_enrich_verified_depth.py"), "--verbose"],
    ]
    steps = [
        [
            sys.executable,
            str(_REPO / "scripts/m9_enrich_bridge_depth.py"),
            "--chain",
            "base",
            "--inventory",
            str(inv),
            "--verbose",
        ],
        [
            sys.executable,
            str(_REPO / "scripts/m9_bridge_build.py"),
            "--config",
            "config/exotic_base_anchor.yaml",
            "--base-inv",
            str(inv),
            "--output",
            str(inv),
            "--registry",
            "data/runs/_rolling/m8_pending_pairs.json",
        ],
        [
            sys.executable,
            str(_REPO / "scripts/m9_enrich_bridge_depth.py"),
            "--chain",
            "base",
            "--inventory",
            str(inv),
            "--verbose",
        ],
        [
            sys.executable,
            str(_REPO / "scripts/m9_quote_route_diagnostic.py"),
            "--limit",
            "50",
            "--lane",
            "productive",
        ],
    ]
    for cmd in steps_pre + steps:
        print("RUN:", " ".join(cmd[2:4]), flush=True)
        rc = subprocess.call(cmd, cwd=str(_REPO), env=env)
        if rc != 0:
            print(f"FAILED rc={rc}: {cmd[1]}", flush=True)
            return rc

    # Inventory stats
    data = json.loads(inv.read_text(encoding="utf-8"))
    routes = data.get("active_routes", [])
    with_depth = sum(1 for r in routes if r.get("effective_depth_usd") is not None)
    with_pq = sum(1 for r in routes if r.get("pool_quality_state"))
    print(
        f"INVENTORY: active={len(routes)} with_depth={with_depth} "
        f"pool_quality_state={with_pq}",
        flush=True,
    )
    hist = (data.get("bridge_source_metrics") or {}).get("pool_quality_histogram", {})
    print(f"pool_quality_histogram={hist}", flush=True)

    from m9.graph_arb.pool_quality import annotate_routes_pool_quality

    annotate_routes_pool_quality(routes)
    inv.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    with_pq2 = sum(1 for r in routes if r.get("pool_quality_state"))
    print(f"after_reannotate pool_quality_state={with_pq2}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
