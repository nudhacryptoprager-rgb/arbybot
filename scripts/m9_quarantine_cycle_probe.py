#!/usr/bin/env python3
"""Compare productive cycle counts under quarantine modes (offline graph probe)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _cycle_probe(
    *,
    inventory: str,
    config: str,
    cycle_lengths: tuple[int, ...],
    quarantine_mode: str,
) -> dict:
    from m9.graph_arb.builder import build_graph_from_inventory
    from m9.graph_arb.finder import find_cycles
    from m9.graph_arb.diagnostic_quarantine import build_quarantine_plan
    from m9.graph_arb.pool_depth_filter import load_quarantined_pool_addresses
    from m9.graph_arb.runner import _connect_rpc, resolve_revert_quarantine_addresses

    os.environ["ARBY_M9_DIAGNOSTIC_QUARANTINE_MODE"] = quarantine_mode

    depth_hard = set(load_quarantined_pool_addresses())
    revert_path = REPO_ROOT / "data/tmp/m9_revert_quarantine.json"
    phantom_path = REPO_ROOT / "data/tmp/m9_phantom_quarantine.json"
    diag_path = REPO_ROOT / "data/runs/_rolling/m9_quote_route_diagnostic_latest.json"

    def _load(p: Path):
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    inv = json.loads(Path(inventory).read_text(encoding="utf-8"))
    inv_routes = inv.get("active_routes") or []
    revert_data = _load(revert_path)
    plan = build_quarantine_plan(
        depth_hard_pools=depth_hard,
        revert_data=revert_data,
        revert_path=str(revert_path),
        phantom_data=_load(phantom_path),
        phantom_path=str(phantom_path),
        diagnostic_data=_load(diag_path),
        diagnostic_path=str(diag_path),
        legacy_revert_pools=resolve_revert_quarantine_addresses(
            revert_data or {}, inv_routes
        )
        if revert_data
        else None,
    )

    w3 = _connect_rpc("base")
    pre_adj = build_graph_from_inventory(
        inventory_path=inventory,
        config_path=config,
        require_factory_verified=True,
        exclude_pool_addresses=depth_hard or None,
        lane="productive",
        w3=w3,
    )
    adj = build_graph_from_inventory(
        inventory_path=inventory,
        config_path=config,
        require_factory_verified=True,
        exclude_pool_addresses=plan.hard_exclude or None,
        soft_quarantine_pools=plan.soft_tag,
        lane="productive",
        w3=w3,
    )

    def _by_len(adjacency):
        cycles = find_cycles(adjacency, cycle_lengths=cycle_lengths, max_cycles=5000)
        out = {str(n): 0 for n in cycle_lengths}
        seen = {str(n): set() for n in cycle_lengths}
        for c in cycles:
            ln = str(len(c.edges))
            if ln in seen:
                seen[ln].add(c.cycle_id)
        for k, v in seen.items():
            out[k] = len(v)
        return out, len(cycles), len({c.cycle_id for c in cycles})

    pre_by, pre_total, pre_unique = _by_len(pre_adj)
    post_by, post_total, post_unique = _by_len(adj)

    from m9.graph_arb.builder import get_last_graph_build_stats

    stats = get_last_graph_build_stats()
    return {
        "quarantine_mode": quarantine_mode,
        "quarantine_breakdown": plan.breakdown,
        "cycles_before_quarantine": pre_unique,
        "cycles_before_quarantine_by_length": pre_by,
        "cycles_after_quarantine": post_unique,
        "cycles_after_quarantine_by_length": post_by,
        "graph_build_metrics": {
            k: stats.get(k)
            for k in (
                "routes_after_admission",
                "routes_after_quarantine",
                "edges_built",
                "edge_build_skip_histogram",
            )
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="M9 quarantine cycle probe")
    ap.add_argument(
        "--inventory",
        default="data/tmp/m9_bridge_inventory_graph_handoff_latest.json",
    )
    ap.add_argument("--config", default="config/exotic_base_anchor.yaml")
    ap.add_argument("--cycle-lengths", default="2,3,4")
    ap.add_argument("--output", default="data/tmp/m9_quarantine_cycle_probe_latest.json")
    args = ap.parse_args()

    lengths = tuple(sorted({int(x) for x in args.cycle_lengths.split(",") if x.strip()}))
    modes = ("off", "production")
    report = {
        "inventory": args.inventory,
        "cycle_lengths": list(lengths),
        "modes": {},
    }
    for mode in modes:
        report["modes"][mode] = _cycle_probe(
            inventory=args.inventory,
            config=args.config,
            cycle_lengths=lengths,
            quarantine_mode=mode,
        )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("written:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
