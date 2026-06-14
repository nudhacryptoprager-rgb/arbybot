#!/usr/bin/env python3
"""Standalone mirror quote-smoke on M8.2 expansion same-pair routes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from m8.discovery.cross_dex_expand import load_yaml_config, write_artifact
from m8.discovery.mirror_quote_smoke import (
    aggregate_mirror_readiness_from_routes,
    smoke_mirror_same_pair_routes,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="M8.2 mirror same-pair quote smoke")
    ap.add_argument(
        "--expansion",
        default="data/runs/_rolling/m8_cross_dex_expansion_latest.json",
    )
    ap.add_argument("--config", default="config/exotic_base_anchor.yaml")
    ap.add_argument("--chain", default="base")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = Path(args.expansion)
    doc = json.loads(path.read_text(encoding="utf-8"))
    routes = list(doc.get("routes_admitted") or [])
    config = load_yaml_config(Path(args.config))
    smoke = smoke_mirror_same_pair_routes(
        routes,
        chain=args.chain,
        config=config,
        dry_run=bool(args.dry_run),
    )
    topology, quote, same_pair, debug = aggregate_mirror_readiness_from_routes(routes)
    summary = doc.setdefault("summary", {})
    summary["mirror_topology_ready_tokens"] = topology
    summary["mirror_quote_ready_tokens"] = quote
    summary["same_pair_mirror_tokens"] = same_pair
    summary["same_pair_mirror_ready_debug"] = debug
    summary["mirror_quote_smoke"] = smoke
    doc["routes_admitted"] = routes
    write_artifact(doc, path)
    print(json.dumps(smoke, indent=2))
    print(
        "mirror_topology_ready_tokens:",
        topology,
        "mirror_quote_ready_tokens:",
        quote,
    )
    return 0 if quote > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
