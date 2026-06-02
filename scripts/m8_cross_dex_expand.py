#!/usr/bin/env python3
"""M8.2 cross-DEX expansion — find pools across all configured Base DEXes for M8 tokens."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

log = logging.getLogger("m8_cross_dex_expand")


def main() -> int:
    p = argparse.ArgumentParser(description="M8.2 cross-DEX pool expansion")
    p.add_argument("--chain", default="base")
    p.add_argument("--config", default="config/exotic_base_anchor.yaml")
    p.add_argument(
        "--input",
        default="data/runs/_rolling/m8_pending_pairs.json",
        help="M8.2 pending-pair registry JSON",
    )
    p.add_argument(
        "--anchor",
        default="data/runs/_rolling/m8_1_stable_anchor_latest.json",
        help="M8.1 stable anchor artifact (optional pairs)",
    )
    p.add_argument(
        "--output",
        default="data/runs/_rolling/m8_cross_dex_expansion_latest.json",
    )
    p.add_argument("--dry-run", action="store_true", help="Registry venues only; no factory RPC")
    p.add_argument("--max-pairs", type=int, default=None, help="Cap token/anchor pairs (debug)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from pathlib import Path

    from m8.discovery.cross_dex_expand import expand_cross_dex, load_yaml_config, write_artifact

    config_path = Path(args.config)
    config = load_yaml_config(config_path)

    registry = None
    if Path(args.input).exists():
        with open(args.input, encoding="utf-8") as fh:
            registry = json.load(fh)
    else:
        log.warning("Registry not found: %s", args.input)

    anchor_artifact = None
    if Path(args.anchor).exists():
        with open(args.anchor, encoding="utf-8") as fh:
            anchor_artifact = json.load(fh)

    artifact = expand_cross_dex(
        chain=args.chain,
        config=config,
        registry=registry,
        anchor_artifact=anchor_artifact,
        dry_run=args.dry_run,
        max_pairs=args.max_pairs,
    )
    artifact["config_path"] = str(config_path).replace("\\", "/")
    artifact["input_registry_path"] = args.input

    if not args.dry_run:
        write_artifact(artifact, Path(args.output))
        log.info("Written: %s", args.output)
    else:
        log.info("Dry-run complete (artifact not written)")

    s = artifact["summary"]
    log.info(
        "tokens_in=%d multi_venue=%d routes_admitted=%d dry_run=%s",
        s["tokens_in"],
        s["multi_venue_tokens"],
        s["routes_admitted_count"],
        s["dry_run"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
