#!/usr/bin/env python3
"""M9 graph topology diagnostic — components, edge loss, cycle potential by length.

Separates M8.2 handoff breadth from M9 graph builder / cycle closure blockers.

Usage:
  py -3.11 scripts/m9_graph_topology_diagnostic.py \\
    --inventory data/tmp/m9_bridge_inventory_graph_handoff_latest.json \\
    --cycle-lengths 2,3,4

  py -3.11 scripts/m9_graph_topology_diagnostic.py \\
    --expansion data/runs/_rolling/m8_cross_dex_expansion_latest.json \\
    --bridge data/tmp/m9_bridge_inventory_graph_handoff_latest.json \\
    --cycle-lengths 2,3,4
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_INVENTORY = "data/tmp/m9_bridge_inventory_graph_handoff_latest.json"
_DEFAULT_EXPANSION = "data/runs/_rolling/m8_cross_dex_expansion_latest.json"
_DEFAULT_CONFIG = "config/exotic_base_anchor.yaml"
_DEFAULT_OUTPUT = "data/tmp/m9_graph_topology_diagnostic_latest.json"


def _parse_cycle_lengths(raw: str) -> tuple[int, ...]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(int(p) for p in parts) or (2, 3, 4)


def main() -> int:
    ap = argparse.ArgumentParser(description="M9 graph topology / cycle closure diagnostic")
    ap.add_argument("--inventory", default=_DEFAULT_INVENTORY)
    ap.add_argument(
        "--expansion",
        default=None,
        help="Full M8.2 expansion artifact for before/after bridge comparison",
    )
    ap.add_argument(
        "--bridge",
        default=None,
        help="Bridge inventory for comparison (defaults to --inventory)",
    )
    ap.add_argument("--config", default=_DEFAULT_CONFIG)
    ap.add_argument("--cycle-lengths", default="2,3,4")
    ap.add_argument("--output", default=_DEFAULT_OUTPUT)
    ap.add_argument(
        "--lane",
        choices=("discovery", "productive", "both"),
        default="both",
        help="Graph build lane(s) to analyze",
    )
    args = ap.parse_args()

    from m9.graph_arb.topology_diagnostic import run_topology_diagnostic

    lengths = _parse_cycle_lengths(args.cycle_lengths)
    lanes = ("discovery", "productive") if args.lane == "both" else (args.lane,)
    bridge_path = args.bridge or args.inventory
    report = run_topology_diagnostic(
        inventory_path=bridge_path,
        config_path=args.config,
        cycle_lengths=lengths,
        lanes=lanes,
        expansion_path=args.expansion,
        bridge_inventory_path=bridge_path if args.expansion else None,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    prod = (report.get("lanes") or {}).get("productive", {}).get("topology", {})
    disc = (report.get("lanes") or {}).get("discovery", {}).get("topology", {})
    compare = report.get("expansion_vs_bridge") or {}
    print(
        json.dumps(
            {
                "active_routes": report.get("active_routes_count"),
                "cycles_found_topology": report.get("cycles_found_topology"),
                "cycles_productive": prod.get("cycles_by_length"),
                "cycles_discovery": disc.get("cycles_by_length"),
                "expansion_vs_bridge": {
                    "full_expansion_routes": compare.get("full_expansion_routes"),
                    "bridge_active_routes": compare.get("bridge_active_routes"),
                    "cycles_3_4_before": compare.get("cycles_by_length_3_4_before_bridge"),
                    "cycles_3_4_after": compare.get("cycles_by_length_3_4_after_bridge"),
                    "cycles_lost_3_4": compare.get("cycles_lost_3_4_by_bridge_selection"),
                },
                "blocker_hint": report.get("blocker_hint"),
            },
            indent=2,
        )
    )
    print("written:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
