#!/usr/bin/env python3
"""Run incremental factory-log event stream lane for time-to-mirror hot path."""
from __future__ import annotations

import argparse
import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def main() -> int:
    p = argparse.ArgumentParser(description="M8 event stream lane (factory log poll)")
    p.add_argument("--chain", default="base")
    p.add_argument(
        "--token-subset-file",
        default="data/tmp/m8_time_to_mirror_expand_subset.json",
    )
    p.add_argument("--max-tokens", type=int, default=50)
    p.add_argument("--max-blocks", type=int, default=500)
    p.add_argument(
        "--webhook-payload",
        default=None,
        help="Optional Alchemy custom webhook JSON file to ingest",
    )
    p.add_argument(
        "--output",
        default="data/tmp/m8_event_stream_lane_latest.json",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    from pathlib import Path

    from m8.discovery.event_stream_lane import run_event_stream_lane

    payload = run_event_stream_lane(
        chain=args.chain,
        subset_path=Path(args.token_subset_file),
        max_tokens=args.max_tokens,
        max_blocks=args.max_blocks,
        output_path=Path(args.output),
        webhook_payload_path=Path(args.webhook_payload) if args.webhook_payload else None,
        dry_run=args.dry_run or os.environ.get("ARBY_SKIP_RPC") == "1",
    )
    print(
        f"event_stream_lane: events={payload.get('events_emitted')} "
        f"pending={payload.get('pending_count')} -> {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
