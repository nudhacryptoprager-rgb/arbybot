#!/usr/bin/env python3
"""M8.2 on-chain factory/log mirror discovery (primary hot-path source)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def main() -> int:
    p = argparse.ArgumentParser(description="On-chain factory mirror scan for time-to-mirror hot path")
    p.add_argument("--chain", default="base")
    p.add_argument("--config", default="config/exotic_base_anchor.yaml")
    p.add_argument(
        "--token-subset-file",
        default="data/tmp/m8_time_to_mirror_expand_subset.json",
    )
    p.add_argument("--max-tokens", type=int, default=50)
    p.add_argument(
        "--hints-output",
        default="data/runs/_rolling/m8_external_pool_hints_latest.json",
    )
    p.add_argument(
        "--radar-output",
        default="data/runs/_rolling/m8_radar_pool_candidates_latest.json",
    )
    p.add_argument(
        "--scan-artifact",
        default="data/tmp/m8_onchain_factory_scan_latest.json",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-factory-log", action="store_true")
    args = p.parse_args()

    from m8.discovery.onchain_factory_mirror_discovery import run_mirror_discovery

    result = run_mirror_discovery(
        chain=args.chain,
        config_path=args.config,
        token_subset_path=args.token_subset_file,
        max_tokens=args.max_tokens,
        hints_path=args.hints_output,
        radar_path=args.radar_output,
        scan_artifact_path=args.scan_artifact,
        dry_run=args.dry_run,
        skip_factory_log=args.skip_factory_log,
    )
    print(
        f"onchain_factory={result.onchain_factory_candidates} "
        f"factory_log={result.factory_log_candidates} "
        f"first_pool={result.first_pool_found} "
        f"second_venue={result.second_venue_found} "
        f"verified_pools={result.verified_pool_count} "
        f"tokens={result.tokens_scanned}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
