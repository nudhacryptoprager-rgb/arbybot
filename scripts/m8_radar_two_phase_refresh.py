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
    p.add_argument(
        "--config",
        default="config/exotic_base_anchor.yaml",
        help="M8 config for fresh_delta / wide_recall lane policy",
    )
    p.add_argument(
        "--lane-mode",
        choices=("fresh_first", "wide_only", "legacy"),
        default="fresh_first",
        help="fresh_first: fresh_delta then wide_recall; legacy: flat watchlist order",
    )
    p.add_argument(
        "--secondary-provider-timeout-s",
        type=int,
        default=12,
        help="Provider timeout for GeckoTerminal/TheGraph secondary phase",
    )
    p.add_argument(
        "--coingecko-provider-timeout-s",
        type=int,
        default=45,
        help="Provider timeout for CoinGecko onchain fallback phase",
    )
    args = p.parse_args()

    py = sys.executable
    boot = [py, "scripts/bootstrap_productive_rpc_env.py", "--", py, "-u"]

    token_subset_file: str | None = None
    if args.lane_mode != "legacy":
        import yaml

        from m8.discovery.fresh_delta_lane import build_radar_token_list
        from m8.discovery.token_watchlist import load_watchlist, save_watchlist

        wl_path = _REPO / args.watchlist
        watchlist = load_watchlist(str(wl_path))
        config = yaml.safe_load((_REPO / args.config).read_text(encoding="utf-8")) or {}
        selected, lane_meta = build_radar_token_list(
            watchlist,
            config=config,
            max_tokens=args.max_tokens,
            fresh_first=args.lane_mode == "fresh_first",
        )
        save_watchlist(watchlist, str(wl_path))
        subset_path = _REPO / "data/tmp/m8_fresh_delta_token_subset.json"
        subset_path.parent.mkdir(parents=True, exist_ok=True)
        subset_path.write_text(
            json.dumps({"tokens": selected, "lane_meta": lane_meta}, indent=2),
            encoding="utf-8",
        )
        token_subset_file = str(subset_path)
        print(
            f"lane_mode={args.lane_mode} fresh_delta={lane_meta.get('fresh_delta_count')} "
            f"wide_recall={lane_meta.get('wide_recall_count')} total={len(selected)}",
            flush=True,
        )

    phase1_cmd = boot + [
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
    ]
    if token_subset_file:
        phase1_cmd.extend(["--token-subset-file", token_subset_file])

    # Phase 1: DexScreener fast radar (no verify)
    rc = _run(
        phase1_cmd,
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
            secondary_out = str(_REPO / "data/tmp/m8_secondary_hints_merge_staging.json")
            secondary_staging = Path(secondary_out)
            rc_secondary = _run(
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
                    secondary_out,
                    "--checkpoint-path",
                    "data/tmp/m8_hint_refresh_checkpoint_secondary.json",
                    "--provider-timeout-s",
                    str(int(args.secondary_provider_timeout_s)),
                    "--sleep-ms",
                    "80",
                    "--fetch-async",
                    "--skip-route-liveness",
                    "--no-resume",
                ],
                label="phase3_secondary",
            )
            if rc_secondary != 0:
                print(
                    f"phase3_secondary failed rc={rc_secondary}; skipping hint merge",
                    flush=True,
                )
            elif secondary_staging.is_file():
                from m8.discovery.hint_artifact_merge import merge_hint_artifact_files

                merge_hint_artifact_files(
                    _REPO / HINTS_OUT,
                    secondary_staging,
                    _REPO / HINTS_OUT,
                    chain="base",
                )
                try:
                    secondary_staging.unlink()
                except OSError:
                    pass

    if not args.skip_coingecko:
        subset_file = _REPO / "data/tmp/m8_coingecko_fallback_subset.json"
        subset_file.write_text(
            json.dumps({"tokens": []}),
            encoding="utf-8",
        )
        coingecko_staging = _REPO / "data/tmp/m8_coingecko_hints_merge_staging.json"
        rc_cg = _run(
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
                "--output",
                str(coingecko_staging),
                "--checkpoint-path",
                "data/tmp/m8_hint_refresh_checkpoint_cg.json",
                "--provider-timeout-s",
                str(int(args.coingecko_provider_timeout_s)),
                "--sleep-ms",
                "250",
                "--fetch-async",
                "--skip-route-liveness",
                "--no-resume",
            ],
            label="phase4_coingecko_canary",
        )
        if rc_cg != 0:
            print(f"phase4_coingecko_canary failed rc={rc_cg}; skipping merge", flush=True)
        elif coingecko_staging.is_file():
            from m8.discovery.hint_artifact_merge import merge_hint_artifact_files

            merge_hint_artifact_files(
                _REPO / HINTS_OUT,
                coingecko_staging,
                _REPO / HINTS_OUT,
                chain="base",
            )
            try:
                coingecko_staging.unlink()
            except OSError:
                pass

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
