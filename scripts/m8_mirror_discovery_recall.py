#!/usr/bin/env python3
"""Run M8.2 mirror discovery max-recall lane (DexScreener all dexId, classify, verify supported)."""
from __future__ import annotations

import argparse
import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def main() -> int:
    p = argparse.ArgumentParser(description="M8 mirror discovery max-recall")
    p.add_argument("--chain", default="base")
    p.add_argument(
        "--token-subset-file",
        default="data/tmp/m8_time_to_mirror_expand_subset.json",
    )
    p.add_argument("--max-tokens", type=int, default=150)
    p.add_argument(
        "--output",
        default="data/tmp/m8_mirror_discovery_recall_latest.json",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--use-cache",
        action="store_true",
        help="Reuse DexScreener cache (default: live fetch for max recall diversity)",
    )
    p.add_argument(
        "--write-supported-hints",
        action="store_true",
        help="Also write supported+verified hints to rolling artifact",
    )
    args = p.parse_args()

    from pathlib import Path

    from m8.discovery.mirror_discovery_recall import (
        run_mirror_discovery_recall,
        run_mirror_discovery_recall_from_subset,
        run_mirror_selection_pass,
        write_mirror_discovery_recall,
        _load_token_list,
        _load_yaml_config,
        DEFAULT_CONFIG_PATH,
    )

    subset = Path(args.token_subset_file)
    tokens = _load_token_list(subset, max_tokens=args.max_tokens)
    cfg = _load_yaml_config(DEFAULT_CONFIG_PATH)
    hints, payload = run_mirror_discovery_recall(
        tokens,
        chain=args.chain,
        config=cfg,
        dry_run=args.dry_run or os.environ.get("ARBY_SKIP_RPC") == "1",
        use_cache=bool(args.use_cache),
    )
    write_mirror_discovery_recall(payload, output_path=Path(args.output))
    if args.write_supported_hints:
        sel = run_mirror_selection_pass(payload, hints=hints)
        print(json.dumps(sel, indent=2), flush=True)
    print(
        f"mirror_discovery_recall: all_dex={payload.get('all_dex_mirrors_total')} "
        f"supported={payload.get('supported_mirrors_total')} "
        f"pool_exists={payload.get('recall_verified_pool_exists_total')} "
        f"selection_fresh={payload.get('selection_verified_fresh_total')} "
        f"stale_backlog={len(payload.get('stale_mirror_backlog') or [])} "
        f"rca_blocker={payload.get('verify_rca', {}).get('primary_blocker_selection')} "
        f"-> {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
