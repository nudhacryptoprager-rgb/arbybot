#!/usr/bin/env python3
"""Stamp productive quote / maverick probes on handoff bridge inventory."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULT_INV = REPO / "data/tmp/m9_bridge_inventory_graph_handoff_latest.json"


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", default=str(DEFAULT_INV))
    args = ap.parse_args()

    from m8.discovery.distinct_pricing_lane import (
        enrich_balancer_routes_from_index,
        stamp_maverick_quote_amounts_from_debug,
        stamp_productive_quote_status_from_artifacts,
    )
    from m9.graph_arb.builder import productive_dex_ids_from_config
    from m9.graph_arb.expansion_admission import refresh_expansion_productive_admit

    inv_path = Path(args.inventory)
    doc = json.loads(inv_path.read_text(encoding="utf-8"))
    routes = list(doc.get("active_routes") or [])
    metrics = doc.setdefault("bridge_source_metrics", {})
    metrics.update(enrich_balancer_routes_from_index(routes))
    metrics.update(stamp_maverick_quote_amounts_from_debug(routes))
    metrics.update(stamp_productive_quote_status_from_artifacts(routes, repo_root=REPO))
    prod_dexes = productive_dex_ids_from_config("config/exotic_base_anchor.yaml")
    for route in routes:
        refresh_expansion_productive_admit(route, prod_dexes)
    inv_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    summary = {
        "routes": len(routes),
        "productive_quote_ok": sum(
            1
            for r in routes
            if str(r.get("productive_quote_status") or "").startswith("QUOTE_OK")
        ),
        "maverick_probe_stamped": sum(
            1 for r in routes if r.get("maverick_probe_by_token_in")
        ),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
