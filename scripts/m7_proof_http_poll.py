"""HTTP-poll proof lane runner (E1.52).

Standalone entry point — does NOT depend on WebSocket. Suitable for
proof-of-concept canaries on free-tier RPC providers that 429 on
``eth_subscribe newHeads``.

Usage::

    py -3.11 scripts/m7_proof_http_poll.py --chain base --duration 600
    py -3.11 scripts/m7_proof_http_poll.py --duration 60 --poll 1.5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from repo root without install
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from m7.orderflow.mode_http_poll import run_http_poll_proof  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="M7 HTTP-only proof lane")
    parser.add_argument("--chain", default="base", help="Chain key (default: base)")
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Total proof window duration in seconds (default: 60)",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=1.5,
        help="Poll interval seconds between eth_blockNumber calls (default: 1.5)",
    )
    parser.add_argument(
        "--rpc",
        default=None,
        help="Explicit HTTP RPC URL (default: resolve from core.rpc_urls)",
    )
    parser.add_argument(
        "--artifact",
        default=None,
        help=(
            "Override path for the rolling proof artifact (default: "
            "data/runs/_rolling/m7_proof_latest.json)"
        ),
    )
    args = parser.parse_args(argv)

    artifact_path = Path(args.artifact) if args.artifact else None

    print(f"[m7_proof] starting chain={args.chain} duration={args.duration}s poll={args.poll}s")
    artifact = run_http_poll_proof(
        chain=args.chain,
        duration_s=args.duration,
        poll_interval_s=args.poll,
        rpc_url=args.rpc,
        artifact_path=artifact_path,
    )

    # Print compact summary
    summary = {
        "iterations": artifact["window"]["iterations"],
        "blocks_seen": artifact["window"]["blocks_seen"],
        "last_block": artifact["window"]["last_block_number"],
        "v3_logs": artifact["logs"]["v3_swap_total"],
        "v2_logs": artifact["logs"]["v2_sync_total"],
        "errors": artifact["logs"]["errors_total"],
        "v3_updates": artifact["pool_price_state"]["v3_updates_total"],
        "v2_updates": artifact["pool_price_state"]["v2_updates_total"],
        "pools_tracked": artifact["pool_price_state"]["pools_tracked"],
        "verdict_partial": artifact["verdict_partial"],
    }
    print("[m7_proof] summary:", json.dumps(summary, indent=2))

    # Exit code reflects partial verdict: 0 = at least one pool state landed
    pp = artifact["pool_price_state"]
    if (pp["v3_updates_total"] + pp["v2_updates_total"]) > 0:
        return 0
    if artifact["logs"]["v3_swap_total"] + artifact["logs"]["v2_sync_total"] > 0:
        # Logs received but registry didn't update → decoder failure
        return 2
    return 1  # No logs at all


if __name__ == "__main__":
    raise SystemExit(main())
