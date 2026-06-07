#!/usr/bin/env python3
"""Refresh M8.2 external pool hints from DexScreener / GeckoTerminal / The Graph.

Reads watchlist tokens, writes a single rolling artifact:
  data/runs/_rolling/m8_external_pool_hints_latest.json

Hints are **not** M9 truth — on-chain verify happens here and in cross_dex_expand.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

log = logging.getLogger("m8_external_pool_hint_refresh")

_SOURCE_FETCHERS = {
    "dexscreener": "m8.discovery.dexscreener_hints",
    "geckoterminal": "m8.discovery.geckoterminal_hints",
    "thegraph": "m8.discovery.graph_hints",
}


def _fetch_source(source: str, token: str, *, chain: str):
    import importlib

    mod = importlib.import_module(_SOURCE_FETCHERS[source])
    if source == "geckoterminal":
        return mod.fetch_token_pool_hints(token, chain=chain)
    return mod.fetch_token_hints(token, chain=chain)


def main() -> int:
    p = argparse.ArgumentParser(description="M8.2 external pool hint refresh")
    p.add_argument("--chain", default="base")
    p.add_argument(
        "--sources",
        default="dexscreener,geckoterminal,thegraph",
        help="Comma-separated: dexscreener,geckoterminal,thegraph",
    )
    p.add_argument(
        "--watchlist",
        default="data/tmp/m8_token_watchlist_latest.json",
    )
    p.add_argument(
        "--output",
        default="data/runs/_rolling/m8_external_pool_hints_latest.json",
    )
    p.add_argument("--max-tokens", type=int, default=None)
    p.add_argument("--sleep-ms", type=int, default=250, help="Pause between token API calls")
    p.add_argument(
        "--verify-mode",
        choices=("none", "light", "specialized"),
        default="specialized",
        help="On-chain verification mode (default specialized for acceptance)",
    )
    p.add_argument(
        "--verify-onchain",
        action="store_true",
        help="Deprecated alias for --verify-mode specialized",
    )
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    import json
    from pathlib import Path

    from m8.discovery.hint_verifier import empty_verification_metrics
    from m8.discovery.pool_hints import (
        BRIDGE_ELIGIBLE_HINT_STATUSES,
        PoolHint,
        TimedSource,
        build_artifact,
        verify_hint_onchain,
        write_hints_artifact,
    )
    from m8.discovery.token_watchlist import load_watchlist

    verify_mode = args.verify_mode
    if args.verify_onchain and verify_mode == "specialized":
        verify_mode = "specialized"

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    for s in sources:
        if s not in _SOURCE_FETCHERS:
            log.error("Unknown source: %s", s)
            return 2

    wl = load_watchlist(args.watchlist)
    tokens = list((wl.get("tokens") or {}).keys())
    if args.max_tokens is not None:
        tokens = tokens[: args.max_tokens]
    if not tokens and Path(args.watchlist).exists():
        reg_path = "data/runs/_rolling/m8_pending_pairs.json"
        if Path(reg_path).exists():
            reg = json.loads(Path(reg_path).read_text(encoding="utf-8"))
            tokens = list((reg.get("tokens") or {}).keys())
            if args.max_tokens is not None:
                tokens = tokens[: args.max_tokens]

    timer = TimedSource()
    all_hints: list[PoolHint] = []
    second_pool_hints = 0
    verification_metrics = empty_verification_metrics()

    for i, token in enumerate(tokens):
        token = token.lower()
        venue_count = len(
            {
                v.get("dex")
                for v in ((wl.get("tokens") or {}).get(token) or {}).get("venues", {}).values()
                if v.get("dex")
            }
        )
        for source in sources:
            try:
                batch = timer.run(
                    f"{source}",
                    lambda s=source, t=token: _fetch_source(s, t, chain=args.chain),
                )
            except Exception as exc:
                log.warning("source=%s token=%s failed: %s", source, token[:10], exc)
                batch = []
            for h in batch:
                h.focus_token = token
                if verify_mode != "none":
                    h = verify_hint_onchain(
                        h,
                        chain=args.chain,
                        verify_mode=verify_mode,
                        metrics=verification_metrics,
                    )
                all_hints.append(h)
                if venue_count < 2 and h.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES:
                    second_pool_hints += 1
        if args.sleep_ms and i + 1 < len(tokens):
            time.sleep(args.sleep_ms / 1000.0)

    metrics = {
        "hint_tokens_checked": len(tokens),
        "second_pool_hints_found": second_pool_hints,
        "hint_source_latency_s": timer.latency_s,
        "verify_mode": verify_mode,
        **verification_metrics,
    }
    artifact = build_artifact(
        chain=args.chain,
        sources=sources,
        hints=all_hints,
        metrics=metrics,
    )
    write_hints_artifact(artifact, args.output)
    m = artifact["metrics"]
    log.info(
        "Written %s tokens=%d pools=%d verified=%d v4_verified=%s reject=%s",
        args.output,
        m.get("hint_tokens_checked", 0),
        m.get("hint_pools_seen", 0),
        m.get("verified_second_pool_count", 0),
        m.get("v4_poolid_verified", 0),
        m.get("verification_reject_histogram", {}),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
