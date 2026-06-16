#!/usr/bin/env python3
"""A/B compare RPC-only vs radar-assisted M8.2 expansion funnel metrics."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _funnel_slice(
    *,
    label: str,
    hints: Optional[Dict[str, Any]],
    radar: Optional[Dict[str, Any]],
    expansion: Optional[Dict[str, Any]],
    duration_s: Optional[float] = None,
) -> Dict[str, Any]:
    from m8.discovery.radar_layer import build_radar_funnel

    funnel = build_radar_funnel(radar=radar, hints=hints, expansion=expansion)
    hm = (hints or {}).get("metrics") or {}
    rm = (radar or {}).get("metrics") or {}
    exp_s = (expansion or {}).get("summary") or {}
    return {
        "label": label,
        "duration_s": duration_s,
        "radar_seen": funnel["radar_seen"],
        "onchain_verified": funnel["onchain_verified"],
        "bridge_eligible": funnel["bridge_eligible"],
        "m9_handoff_routes": funnel["m9_handoff"].get("routes_admitted_count"),
        "verified_yield": funnel.get("per_source_verified_yield") or {},
        "stale_hint_rate": hm.get("stale_hint_rate")
        or (expansion or {}).get("radar_metrics", {}).get("stale_hint_rate"),
        "hint_source_pool_counts": hm.get("hint_source_pool_counts")
        or rm.get("hint_source_pool_counts"),
        "handoff_lane": exp_s.get("handoff_lane"),
        "handoff_ready": exp_s.get("handoff_ready"),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="M8.2 radar-assisted expansion A/B")
    p.add_argument(
        "--hints",
        default="data/runs/_rolling/m8_external_pool_hints_latest.json",
    )
    p.add_argument(
        "--radar",
        default="data/runs/_rolling/m8_radar_pool_candidates_latest.json",
    )
    p.add_argument(
        "--expansion",
        default="data/runs/_rolling/m8_cross_dex_expansion_latest.json",
    )
    p.add_argument(
        "--output",
        default="data/tmp/m8_radar_expansion_ab_latest.json",
    )
    p.add_argument(
        "--run-hint-refresh",
        action="store_true",
        help="Run a small radar-assisted hint refresh before compare",
    )
    p.add_argument("--max-tokens", type=int, default=5)
    p.add_argument("--sleep-ms", type=int, default=80)
    args = p.parse_args()

    refresh_duration: Optional[float] = None
    if args.run_hint_refresh:
        t0 = time.monotonic()
        cmd = [
            sys.executable,
            str(_REPO_ROOT / "scripts/m8_external_pool_hint_refresh.py"),
            "--max-tokens",
            str(args.max_tokens),
            "--sleep-ms",
            str(args.sleep_ms),
            "--verify-mode",
            "light",
            "--skip-route-liveness",
        ]
        subprocess.run(cmd, cwd=str(_REPO_ROOT), check=False)
        refresh_duration = round(time.monotonic() - t0, 2)

    hints = _load(_REPO_ROOT / args.hints)
    radar = _load(_REPO_ROOT / args.radar)
    expansion = _load(_REPO_ROOT / args.expansion)

    radar_assisted = _funnel_slice(
        label="radar_assisted",
        hints=hints,
        radar=radar,
        expansion=expansion,
        duration_s=refresh_duration,
    )
    rpc_only = _funnel_slice(
        label="rpc_only_baseline",
        hints=None,
        radar=None,
        expansion=expansion,
    )

    payload = {
        "schema_version": "m8_radar_expansion_ab.1",
        "comparison": {
            "radar_assisted": radar_assisted,
            "rpc_only": rpc_only,
            "delta_onchain_verified": (
                int(radar_assisted["onchain_verified"] or 0)
                - int(rpc_only["onchain_verified"] or 0)
            ),
            "delta_bridge_eligible": (
                int(radar_assisted["bridge_eligible"] or 0)
                - int(rpc_only["bridge_eligible"] or 0)
            ),
        },
        "note": (
            "rpc_only uses expansion artifact without hint/radar overlay; "
            "radar_assisted uses current hint+radar artifacts"
        ),
    }
    out = _REPO_ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["comparison"], indent=2))
    print("written:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
