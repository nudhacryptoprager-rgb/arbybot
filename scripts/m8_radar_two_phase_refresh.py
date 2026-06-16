#!/usr/bin/env python3
"""DexScreener-first two-phase radar: fast sweep → selective verify → secondary fallback."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
RADAR_OUT = "data/runs/_rolling/m8_radar_pool_candidates_latest.json"
HINTS_OUT = "data/runs/_rolling/m8_external_pool_hints_latest.json"


def _run(cmd: list[str], *, label: str) -> int:
    print(f"\n=== {label} ===", flush=True)
    print(" ".join(cmd), flush=True)
    t0 = time.monotonic()
    rc = subprocess.call(cmd, cwd=str(_REPO))
    print(f"{label} exit={rc} elapsed_s={time.monotonic()-t0:.1f}", flush=True)
    return int(rc)


def main() -> int:
    p = argparse.ArgumentParser(description="M8.2 DexScreener-first two-phase refresh")
    p.add_argument("--max-tokens", type=int, default=300)
    p.add_argument("--watchlist", default="data/tmp/m8_token_watchlist_latest.json")
    p.add_argument("--skip-secondary", action="store_true")
    p.add_argument("--skip-coingecko", action="store_true")
    p.add_argument("--skip-acceptance", action="store_true")
    args = p.parse_args()

    py = sys.executable
    boot = [py, "scripts/bootstrap_productive_rpc_env.py", "--", py, "-u"]

    # Phase 1: DexScreener fast radar (no verify)
    rc = _run(
        boot
        + [
            "scripts/m8_external_pool_hint_refresh.py",
            "--chain",
            "base",
            "--radar-fast",
            "--watchlist",
            args.watchlist,
            "--max-tokens",
            str(args.max_tokens),
            "--radar-output",
            RADAR_OUT,
            "--checkpoint-path",
            "data/tmp/m8_hint_refresh_checkpoint_ds_radar.json",
            "--provider-timeout-s",
            "8",
            "--sleep-ms",
            "20",
            "--no-resume",
            "--no-retry-single-venue",
        ],
        label="phase1_radar_fast",
    )
    if rc != 0:
        return rc

    # Phase 2: verify subset from radar artifact
    rc = _run(
        boot
        + [
            "scripts/m8_external_pool_hint_refresh.py",
            "--chain",
            "base",
            "--sources",
            "dexscreener",
            "--pipeline-mode",
            "verify_subset",
            "--load-radar-input",
            RADAR_OUT,
            "--verify-subset-only",
            "--verify-mode",
            "specialized",
            "--output",
            HINTS_OUT,
            "--checkpoint-path",
            "data/tmp/m8_hint_refresh_checkpoint_ds_verify.json",
            "--fetch-async",
            "--use-multicall",
            "--ws-head",
            "--verify-async-workers",
            "6",
            "--skip-route-liveness",
            "--skip-defillama-weights",
            "--no-resume",
        ],
        label="phase2_verify_subset",
    )
    if rc != 0:
        return rc

    if not args.skip_secondary:
        radar = json.loads((_REPO / RADAR_OUT).read_text(encoding="utf-8"))
        from m8.discovery.pool_hints import PoolHint
        from m8.discovery.radar_fast_pipeline import (
            tokens_for_secondary_sources,
        )

        hints = [PoolHint.from_dict(h) for h in (radar.get("candidates") or [])]
        wl = json.loads((_REPO / args.watchlist).read_text(encoding="utf-8"))
        all_tokens = list((wl.get("tokens") or {}).keys())[: args.max_tokens]
        secondary = tokens_for_secondary_sources(all_tokens, hints)[:50]
        subset_file = _REPO / "data/tmp/m8_secondary_token_subset.json"
        subset_file.parent.mkdir(parents=True, exist_ok=True)
        subset_file.write_text(json.dumps({"tokens": secondary}), encoding="utf-8")
        if secondary:
            _run(
                boot
                + [
                    "scripts/m8_external_pool_hint_refresh.py",
                    "--chain",
                    "base",
                    "--sources",
                    "geckoterminal,thegraph_token_api",
                    "--pipeline-mode",
                    "secondary",
                    "--watchlist",
                    args.watchlist,
                    "--token-subset-file",
                    str(subset_file),
                    "--verify-mode",
                    "specialized",
                    "--output",
                    HINTS_OUT,
                    "--checkpoint-path",
                    "data/tmp/m8_hint_refresh_checkpoint_secondary.json",
                    "--provider-timeout-s",
                    "12",
                    "--sleep-ms",
                    "80",
                    "--fetch-async",
                    "--skip-route-liveness",
                    "--no-resume",
                ],
                label="phase3_secondary",
            )

    if not args.skip_coingecko:
        subset_file = _REPO / "data/tmp/m8_coingecko_fallback_subset.json"
        subset_file.write_text(
            json.dumps({"tokens": []}),
            encoding="utf-8",
        )
        _run(
            boot
            + [
                "scripts/m8_external_pool_hint_refresh.py",
                "--chain",
                "base",
                "--sources",
                "coingecko_onchain",
                "--pipeline-mode",
                "secondary",
                "--watchlist",
                args.watchlist,
                "--max-tokens",
                "50",
                "--verify-mode",
                "specialized",
                "--checkpoint-path",
                "data/tmp/m8_hint_refresh_checkpoint_cg.json",
                "--provider-timeout-s",
                "45",
                "--sleep-ms",
                "250",
                "--fetch-async",
                "--skip-route-liveness",
                "--no-resume",
            ],
            label="phase4_coingecko_canary",
        )

    if not args.skip_acceptance:
        rc = _run(
            [py, "scripts/m8_2_acceptance_report.py", "--strict"],
            label="m8_2_acceptance",
        )
        if rc != 0:
            return rc

    hpath = _REPO / HINTS_OUT
    if hpath.is_file():
        m = json.loads(hpath.read_text(encoding="utf-8")).get("metrics") or {}
        print("\n=== pipeline summary ===", flush=True)
        print(
            json.dumps(
                {
                    k: m.get(k)
                    for k in (
                        "pipeline_mode",
                        "radar_fast_tokens",
                        "radar_candidates",
                        "verify_subset_size",
                        "radar_to_verify_rate",
                        "verified_yield",
                        "provider_timing",
                        "fetch_async",
                        "bytecode_parallel_prepass",
                    )
                },
                indent=2,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
