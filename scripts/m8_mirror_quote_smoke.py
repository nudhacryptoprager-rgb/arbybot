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
    DEFAULT_MIRROR_CHECKPOINT_PATH,
    aggregate_mirror_readiness_from_routes,
    build_mirror_token_details,
    classify_mirror_smoke_exit,
    load_token_subset_from_path,
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
    ap.add_argument(
        "--force-retry",
        action="store_true",
        help="Re-run quote smoke on routes with QUOTE_FAIL / QUOTE_SKIP statuses",
    )
    ap.add_argument(
        "--pipeline-mode",
        action="store_true",
        help="Require productive non-public RPC (start.py time_to_mirror lane)",
    )
    ap.add_argument(
        "--checkpoint-path",
        default=DEFAULT_MIRROR_CHECKPOINT_PATH,
        help="Progress artifact for orchestrator heartbeat",
    )
    ap.add_argument(
        "--token-subset-file",
        default=None,
        help="Limit smoke to focus tokens listed in subset JSON or pending queue",
    )
    args = ap.parse_args()

    path = Path(args.expansion)
    doc = json.loads(path.read_text(encoding="utf-8"))
    routes = list(doc.get("routes_admitted") or [])
    config = load_yaml_config(Path(args.config))
    subset = None
    if args.token_subset_file:
        subset_path = Path(args.token_subset_file)
        if subset_path.is_file():
            subset_doc = json.loads(subset_path.read_text(encoding="utf-8"))
            if not (subset_doc.get("tokens") or []):
                smoke = {
                    "attempted": 0,
                    "quote_ok": 0,
                    "quote_fail": 0,
                    "reason": "NO_TRANSITION_SUBSET",
                    "exit_class": "no_quote_ready",
                    "exit_code": 2,
                    "token_subset_file": str(subset_path),
                }
                summary = doc.setdefault("summary", {})
                summary["mirror_quote_smoke"] = smoke
                write_artifact(doc, path)
                print(json.dumps(smoke, indent=2))
                return 2
        subset = load_token_subset_from_path(args.token_subset_file)
    smoke = smoke_mirror_same_pair_routes(
        routes,
        chain=args.chain,
        config=config,
        dry_run=bool(args.dry_run),
        force_retry=bool(args.force_retry),
        pipeline_mode=bool(args.pipeline_mode),
        checkpoint_path=args.checkpoint_path,
        token_subset=subset,
    )
    topology, quote, same_pair, debug = aggregate_mirror_readiness_from_routes(routes)
    mirror_tokens = build_mirror_token_details(routes)
    summary = doc.setdefault("summary", {})
    summary["mirror_topology_ready_tokens"] = topology
    summary["mirror_quote_ready_tokens"] = quote
    summary["same_pair_mirror_tokens"] = same_pair
    summary["same_pair_mirror_ready_debug"] = debug
    summary["mirror_quote_smoke"] = smoke
    summary["mirror_tokens"] = mirror_tokens
    doc["mirror_tokens"] = mirror_tokens
    doc["routes_admitted"] = routes
    write_artifact(doc, path)
    print(json.dumps(smoke, indent=2))
    print(
        "mirror_topology_ready_tokens:",
        topology,
        "mirror_quote_ready_tokens:",
        quote,
    )
    if args.dry_run:
        return 0
    exit_code, _exit_class = classify_mirror_smoke_exit(
        quote_ok=int(smoke.get("quote_ok") or 0),
        reason=str(smoke.get("reason") or "OK"),
    )
    if smoke.get("exit_code") is not None:
        return int(smoke["exit_code"])
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
