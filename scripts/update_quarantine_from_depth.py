"""Update M9 quarantine with toxic pools from a depth-enriched inventory.

Usage:
    py -3.11 scripts/update_quarantine_from_depth.py \
        --inventory data/tmp/m9_depth_enriched_bridge.json \
        --quarantine data/quarantine/m9_pool_depth_quarantine.json \
        --threshold 0.15
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Add toxic pools to M9 quarantine.")
    p.add_argument(
        "--inventory",
        default="data/tmp/m9_depth_enriched_bridge.json",
        help="Depth-enriched inventory JSON",
    )
    p.add_argument(
        "--quarantine",
        default="data/quarantine/m9_pool_depth_quarantine.json",
        help="Quarantine JSON to update",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.15,
        help="Price-impact threshold (fraction, e.g. 0.15 = 15%%). "
             "Pools exceeding this are added to quarantine.",
    )
    args = p.parse_args()

    inv_path = Path(args.inventory)
    q_path = Path(args.quarantine)

    if not inv_path.exists():
        print(f"ERROR: inventory not found: {inv_path}", file=sys.stderr)
        return 1

    enriched = json.loads(inv_path.read_text())
    routes = enriched.get("active_routes", [])

    q: dict
    if q_path.exists():
        q = json.loads(q_path.read_text())
    else:
        q = {
            "schema_version": "m9_pool_depth_quarantine.1",
            "generated_at_utc": "",
            "description": "Auto-generated quarantine",
            "quarantined_pools": [],
            "_notes": [],
        }

    existing_addrs = {
        e["pool_address"].lower() for e in q.get("quarantined_pools", [])
    }
    print(f"Existing quarantine: {len(existing_addrs)} pools")

    new_entries = []
    for r in routes:
        pi = r.get("price_impact_at_100usd")
        addr = (r.get("pool_address") or "").lower()
        if pi is None or not r.get("depth_probe_ok") or not addr:
            continue
        if abs(pi) > args.threshold and addr not in existing_addrs:
            pair_id = r.get("pair_id", "?")
            dex_id = r.get("dex_id", "?")
            new_entries.append(
                {
                    "pool_address": addr,
                    "pair_id": pair_id,
                    "dex_id": dex_id,
                    "fee": r.get("fee"),
                    "reject_reason": "TOXIC_PRICE_IMPACT",
                    "evidence": {
                        "price_impact_at_100usd": round(pi, 4),
                        "measured_at": "2026-05-28",
                        "rpc": "publicnode.com",
                    },
                    "note": (
                        f"{abs(pi)*100:.1f}% price impact at $100 probe. "
                        "Auto-added by update_quarantine_from_depth.py."
                    ),
                }
            )
            existing_addrs.add(addr)

    print(f"New toxic pools to add ({int(args.threshold*100)}% threshold): {len(new_entries)}")
    for e in new_entries:
        print(
            f"  {e['pair_id']:20s} {e['dex_id']:20s} "
            f"impact={e['evidence']['price_impact_at_100usd']*100:.1f}%"
        )

    q.setdefault("quarantined_pools", []).extend(new_entries)
    q["generated_at_utc"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    q_path.write_text(json.dumps(q, indent=2))
    print(f"Quarantine written: {len(q['quarantined_pools'])} total entries -> {q_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
