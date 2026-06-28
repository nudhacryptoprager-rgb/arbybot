#!/usr/bin/env python3
"""Refresh M8.2 external pool hints from DexScreener / GeckoTerminal / The Graph.

Reads watchlist tokens, writes a single rolling artifact:
  data/runs/_rolling/m8_external_pool_hints_latest.json

Hints are **not** M9 truth — on-chain verify happens here and in cross_dex_expand.
"""
from __future__ import annotations

import argparse
import json
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
    "thegraph_token_api": "m8.discovery.thegraph_token_api_hints",
    "coingecko_onchain": "m8.discovery.coingecko_onchain_hints",
    "coinmarketcap_dex": "m8.discovery.radar_providers",
    "dexpaprika": "m8.discovery.radar_providers",
    "moralis": "m8.discovery.radar_providers",
    "codex_defined": "m8.discovery.radar_providers",
}

_RADAR_FETCH_FN = {
    "coinmarketcap_dex": "fetch_coinmarketcap_dex_hints",
    "dexpaprika": "fetch_dexpaprika_hints",
    "moralis": "fetch_moralis_hints",
    "codex_defined": "fetch_codex_defined_hints",
}


def _fetch_source(source: str, token: str, *, chain: str):
    import importlib

    mod = importlib.import_module(_SOURCE_FETCHERS[source])
    if source == "geckoterminal":
        return mod.fetch_token_pool_hints(token, chain=chain)
    if source == "coingecko_onchain":
        return mod.fetch_token_pool_hints(token, chain=chain)
    if source in _RADAR_FETCH_FN:
        return getattr(mod, _RADAR_FETCH_FN[source])(token, chain=chain)
    return mod.fetch_token_hints(token, chain=chain)


def main() -> int:
    p = argparse.ArgumentParser(description="M8.2 external pool hint refresh")
    p.add_argument("--chain", default="base")
    p.add_argument(
        "--sources",
        default="dexscreener,geckoterminal,thegraph,thegraph_token_api",
        help="Comma-separated: dexscreener,geckoterminal,thegraph,thegraph_token_api",
    )
    p.add_argument(
        "--watchlist",
        default="data/tmp/m8_token_watchlist_latest.json",
        help="Required for canonical mode; M8-derived token universe only",
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Cap watchlist tokens processed (ignored when --token-subset-file fully defines list)",
    )
    p.add_argument(
        "--exploration",
        action="store_true",
        help="Non-canonical mode without watchlist (hints not for production bridge)",
    )
    p.add_argument(
        "--output",
        default="data/runs/_rolling/m8_external_pool_hints_latest.json",
    )
    p.add_argument(
        "--merge-existing-output",
        action="store_true",
        help="Merge with existing --output artifact instead of replacing verified hints",
    )
    p.add_argument(
        "--token-concurrency",
        type=int,
        default=1,
        help="Bounded parallel token fetches (DexScreener rate-limited globally)",
    )
    p.add_argument("--sleep-ms", type=int, default=120, help="Pause between token API calls")
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
    p.add_argument(
        "--new-pools-backfill",
        action="store_true",
        help="GeckoTerminal networks/new_pools filtered to watchlist tokens",
    )
    p.add_argument(
        "--new-pools-pages",
        type=int,
        default=3,
        help="Pages of GeckoTerminal new_pools when --new-pools-backfill",
    )
    p.add_argument(
        "--radar-output",
        default="data/runs/_rolling/m8_radar_pool_candidates_latest.json",
        help="Raw radar candidates artifact (hint-only, no canonical claims)",
    )
    p.add_argument(
        "--skip-route-liveness",
        action="store_true",
        help="Skip 0x/1inch/Uniswap external_route_liveness probes",
    )
    p.add_argument(
        "--skip-defillama-weights",
        action="store_true",
        help="Skip DeFiLlama DEX scan-order weights",
    )
    p.add_argument(
        "--fetch-async",
        action="store_true",
        default=os.environ.get("ARBY_HINT_FETCH_ASYNC", "0").strip().lower()
        in ("1", "true", "yes"),
        help="Fetch all sources per token in parallel",
    )
    p.add_argument(
        "--verify-async-workers",
        type=int,
        default=int(os.environ.get("ARBY_HINT_VERIFY_ASYNC_WORKERS", "4")),
        help="Parallel on-chain verify workers per token batch",
    )
    p.add_argument(
        "--use-multicall",
        action="store_true",
        default=os.environ.get("ARBY_HINT_USE_MULTICALL", "0").strip().lower()
        in ("1", "true", "yes"),
        help="Parallel bytecode pre-pass (thread pool eth_getCode; not aggregate3 verify)",
    )
    p.add_argument(
        "--ws-head",
        action="store_true",
        default=os.environ.get("ARBY_HINT_WS_HEAD", "0").strip().lower()
        in ("1", "true", "yes"),
        help="Pin verify context to latest WS newHeads block",
    )
    p.add_argument("--verbose", action="store_true")
    p.add_argument(
        "--retry-single-venue",
        action="store_true",
        default=True,
        help="Extra fetch passes for tokens seen on only one DEX (default on)",
    )
    p.add_argument(
        "--no-retry-single-venue",
        action="store_false",
        dest="retry_single_venue",
        help="Disable single-venue retry passes",
    )
    p.add_argument(
        "--retry-max",
        type=int,
        default=2,
        help="Max extra passes per single-venue token",
    )
    p.add_argument(
        "--retry-backoff-ms",
        type=int,
        default=250,
        help="Backoff between single-venue retry passes",
    )
    p.add_argument(
        "--checkpoint-path",
        default="data/tmp/m8_hint_refresh_checkpoint.json",
        help="Resume/save progress while refreshing large watchlists",
    )
    p.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore existing checkpoint and start from token 0",
    )
    p.add_argument(
        "--checkpoint-every",
        type=int,
        default=25,
        help="Flush checkpoint every N tokens",
    )
    p.add_argument(
        "--provider-timeout-s",
        type=float,
        default=45.0,
        help="Per-source fetch timeout (seconds)",
    )
    p.add_argument(
        "--radar-fast",
        action="store_true",
        help="DexScreener-only fast radar (verify none, low sleep, no single-venue retry)",
    )
    p.add_argument(
        "--load-radar-input",
        default=None,
        help="Load candidates from radar artifact; skip fetch (use with verify subset)",
    )
    p.add_argument(
        "--verify-subset-only",
        action="store_true",
        help="With --load-radar-input: verify only multi-venue / signal subset",
    )
    p.add_argument(
        "--token-subset-file",
        default=None,
        help="JSON list of token addresses to fetch (secondary/fallback lane)",
    )
    p.add_argument(
        "--pipeline-mode",
        default="full",
        choices=("full", "radar_fast", "verify_subset", "secondary", "audit_nightly"),
        help="Operational pipeline mode label for metrics",
    )
    args = p.parse_args()

    if args.radar_fast:
        args.sources = "dexscreener"
        args.verify_mode = "none"
        args.pipeline_mode = "radar_fast"
        if args.sleep_ms == 120:
            args.sleep_ms = 20
        args.retry_single_venue = False
        args.fetch_async = True
        args.skip_route_liveness = True
        args.skip_defillama_weights = True

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    import json
    from pathlib import Path

    from m8.discovery.hint_refresh_lock import (
        acquire_hint_refresh_lock,
        release_hint_refresh_lock,
    )

    try:
        acquire_hint_refresh_lock(
            checkpoint_path=args.checkpoint_path,
            output_path=args.output,
            chain=args.chain,
            sources=[s.strip() for s in args.sources.split(",") if s.strip()],
        )
    except RuntimeError as exc:
        log.error("%s", exc)
        return 3

    try:
        return _run_hint_refresh(args)
    finally:
        release_hint_refresh_lock(args.checkpoint_path)


def _run_hint_refresh(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    from m8.discovery.hint_verifier import empty_verification_metrics
    from m8.discovery.pool_hints import (
        BRIDGE_ELIGIBLE_HINT_STATUSES,
        PoolHint,
        TimedSource,
        build_artifact,
        dedupe_hints,
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

    tokens: list[str] = []
    wl: dict = {}
    if not args.exploration:
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
        if not tokens:
            log.error(
                "Canonical hint refresh requires --watchlist with M8 tokens "
                "(or use --exploration for non-canonical runs)"
            )
            return 1
    else:
        log.warning("EXPLORATION hint refresh: not for canonical M9 bridge")

    wl_tokens = (wl.get("tokens") or {}) if not args.exploration else {}

    def _venue_count(token_addr: str) -> int:
        venues = (wl_tokens.get(token_addr.lower()) or {}).get("venues") or {}
        dexes = {
            str(v.get("dex") or v.get("dex_id") or "")
            for v in venues.values()
            if v.get("dex") or v.get("dex_id")
        }
        return len(dexes)

    if not args.exploration:
        tokens = sorted(tokens, key=lambda t: (_venue_count(t), t))

    if args.token_subset_file:
        subset_path = Path(args.token_subset_file)
        if subset_path.is_file():
            subset_doc = json.loads(subset_path.read_text(encoding="utf-8"))
            if isinstance(subset_doc, list):
                tokens = [str(t).lower() for t in subset_doc]
            else:
                tokens = [str(t).lower() for t in (subset_doc.get("tokens") or [])]
            if args.max_tokens is not None:
                tokens = tokens[: args.max_tokens]
            log.info("Token subset file: %d tokens", len(tokens))

    log.info(
        "Refreshing hints for %d watchlist tokens (pipeline=%s)",
        len(tokens),
        args.pipeline_mode,
    )

    from m8.discovery.radar_fast_pipeline import ProviderTiming

    provider_timing: dict[str, ProviderTiming] = {
        s: ProviderTiming() for s in sources
    }

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed

    checkpoint_path = Path(args.checkpoint_path)
    hints_sidecar = checkpoint_path.with_suffix(checkpoint_path.suffix + ".hints.json")
    completed_indices: set[int] = set()
    all_hints: list[PoolHint] = []
    if not args.no_resume and checkpoint_path.is_file():
        try:
            ck = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if ck.get("watchlist") == args.watchlist and ck.get("chain") == args.chain:
                completed_indices = {
                    int(i) for i in (ck.get("completed_indices") or []) if str(i).isdigit()
                }
                legacy_next = ck.get("next_token_index")
                if legacy_next is not None and not completed_indices:
                    completed_indices = set(range(int(legacy_next)))
                if hints_sidecar.is_file():
                    side = json.loads(hints_sidecar.read_text(encoding="utf-8"))
                    all_hints = [PoolHint.from_dict(h) for h in (side.get("hints") or [])]
                    log.info(
                        "Resuming hint refresh: completed=%d/%d hints=%d",
                        len(completed_indices),
                        int(ck.get("tokens_total") or 0),
                        len(all_hints),
                    )
                else:
                    log.warning(
                        "Checkpoint with %d completed indices but hints sidecar missing; restarting",
                        len(completed_indices),
                    )
                    completed_indices = set()
        except Exception as exc:
            log.warning("Checkpoint load failed (starting fresh): %s", exc)

    def _contiguous_frontier(done: set[int]) -> int:
        i = 0
        while i in done:
            i += 1
        return i

    def _write_checkpoint(done: set[int]) -> None:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(
            json.dumps(
                {
                    "watchlist": args.watchlist,
                    "chain": args.chain,
                    "completed_indices": sorted(done),
                    "contiguous_frontier": _contiguous_frontier(done),
                    "tokens_total": len(tokens),
                    "hints_collected": len(all_hints),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        hints_sidecar.write_text(
            json.dumps({"hints": [h.to_dict() for h in all_hints]}, indent=2),
            encoding="utf-8",
        )

    timer = TimedSource()
    second_pool_hints = 0
    verification_metrics = empty_verification_metrics()
    source_pool_counts: dict[str, int] = {}
    per_source_verified_yield: dict[str, int] = {}
    single_venue_retries = 0
    raw_radar_hints: list[PoolHint] = []

    defillama_weights: dict = {}
    if not args.skip_defillama_weights:
        from m8.discovery.defillama_dex_priority import fetch_dex_priority_weights

        t0 = time.monotonic()
        defillama_weights = fetch_dex_priority_weights(args.chain)
        timer.latency_s["defillama_dex_priority"] = round(time.monotonic() - t0, 4)

    route_liveness: list = []
    if not args.skip_route_liveness:
        from m8.discovery.external_route_liveness import run_external_route_liveness_probes

        t0 = time.monotonic()
        route_liveness = run_external_route_liveness_probes(
            chain=args.chain,
            timeout_s=min(8.0, float(args.provider_timeout_s)),
        )
        timer.latency_s["external_route_liveness"] = round(time.monotonic() - t0, 4)

    verify_block: int | None = None
    if args.ws_head:
        from m8.discovery.hint_verify_batch import pin_block_from_ws

        verify_block = pin_block_from_ws(args.chain)
        if verify_block is not None:
            os.environ["ARBY_HINT_VERIFY_BLOCK"] = str(verify_block)
            log.info("WS head pinned for verify: block=%s", verify_block)
        else:
            log.warning("WS head pin failed; continuing without pinned block")

    def _verify_batch(batch: list[PoolHint]) -> list[PoolHint]:
        if verify_mode == "none" or not batch:
            return batch
        if args.verify_async_workers > 1 or args.use_multicall:
            from m8.discovery.hint_verify_batch import verify_hints_async

            return verify_hints_async(
                batch,
                chain=args.chain,
                verify_mode=verify_mode,
                metrics=verification_metrics,
                workers=max(1, int(args.verify_async_workers)),
                use_multicall=bool(args.use_multicall),
                block_num=verify_block,
            )
        return [
            verify_hint_onchain(
                h,
                chain=args.chain,
                verify_mode=verify_mode,
                metrics=verification_metrics,
            )
            for h in batch
        ]

    if args.load_radar_input:
        from m8.discovery.radar_fast_pipeline import (
            build_verify_subset_tokens,
            filter_hints_for_tokens,
            pipeline_metrics,
        )

        radar_doc = json.loads(Path(args.load_radar_input).read_text(encoding="utf-8"))
        raw_hints = [PoolHint.from_dict(h) for h in (radar_doc.get("candidates") or [])]
        subset = build_verify_subset_tokens(raw_hints)
        verify_hints = (
            filter_hints_for_tokens(raw_hints, subset)
            if args.verify_subset_only
            else list(raw_hints)
        )
        log.info(
            "Verify-from-radar: candidates=%d subset_tokens=%d verify_hints=%d",
            len(raw_hints),
            len(subset),
            len(verify_hints),
        )
        verified = _verify_batch(verify_hints)
        all_hints = dedupe_hints(verified)
        for h in all_hints:
            if h.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES:
                per_source_verified_yield[h.source] = int(
                    per_source_verified_yield.get(h.source, 0)
                ) + 1
        pipe_m = pipeline_metrics(
            radar_fast_tokens=len(tokens),
            radar_candidates=len(raw_hints),
            verify_subset_size=len(subset),
            verified_count=sum(
                1 for h in all_hints if h.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES
            ),
            provider_timing=provider_timing,
            verified_yield_by_source=per_source_verified_yield,
        )
        metrics = {
            "hint_tokens_checked": len(tokens),
            "pipeline_mode": args.pipeline_mode,
            **pipe_m,
            "verify_mode": verify_mode,
            "fetch_async": bool(args.fetch_async),
            "use_multicall": bool(args.use_multicall),
            "bytecode_parallel_prepass": bool(args.use_multicall),
            "ws_head_block": verify_block,
        }
        artifact = build_artifact(
            chain=args.chain,
            sources=sources,
            hints=all_hints,
            metrics=metrics,
        )
        write_hints_artifact(artifact, args.output)
        log.info("Written %s verified=%d", args.output, pipe_m.get("verified_yield"))
        return 0

    if args.new_pools_backfill:
        from m8.discovery.geckoterminal_hints import fetch_new_pools_backfill

        t0 = time.monotonic()
        backfill = fetch_new_pools_backfill(
            set(tokens),
            network=args.chain,
            chain=args.chain,
            max_pages=args.new_pools_pages,
        )
        timer.latency_s["geckoterminal_new_pools"] = round(time.monotonic() - t0, 4)
        log.info("new_pools_backfill pools=%d", len(backfill))
        for h in backfill:
            raw_radar_hints.append(PoolHint.from_dict(h.to_dict()))
        verified_backfill = _verify_batch(backfill)
        for h in verified_backfill:
            all_hints.append(h)
            source_pool_counts["geckoterminal_new_pools"] = (
                int(source_pool_counts.get("geckoterminal_new_pools", 0)) + 1
            )

    def _fetch_one_source(source: str, token: str) -> list[PoolHint]:
        t0 = time.monotonic()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(
                    lambda s=source, t=token: _fetch_source(s, t, chain=args.chain),
                )
                out = list(fut.result(timeout=max(1.0, float(args.provider_timeout_s))))
            provider_timing[source].record(time.monotonic() - t0)
            if source == "dexscreener":
                from m8.discovery.dexscreener_hints import last_fetch_timing

                ft = last_fetch_timing()
                if ft.get("error"):
                    provider_timing[source].record(0, error=True)
            return out
        except FuturesTimeout:
            provider_timing[source].record(
                time.monotonic() - t0, timeout=True
            )
            log.warning(
                "source=%s token=%s timed out after %.1fs",
                source,
                token[:10],
                args.provider_timeout_s,
            )
            return []
        except Exception as exc:
            provider_timing[source].record(time.monotonic() - t0, error=True)
            log.warning("source=%s token=%s failed: %s", source, token[:10], exc)
            return []

    import threading

    state_lock = threading.Lock()

    def _fetch_token_sources(token: str, venue_count: int) -> None:
        nonlocal second_pool_hints, single_venue_retries
        passes = 1
        if args.retry_single_venue and venue_count < 2:
            passes = max(1, int(args.retry_max) + 1)
        for pass_idx in range(passes):
            if pass_idx > 0:
                with state_lock:
                    single_venue_retries += 1
                if args.retry_backoff_ms:
                    time.sleep(args.retry_backoff_ms / 1000.0)
            token_batch: list[PoolHint] = []
            if args.fetch_async and len(sources) > 1:
                with ThreadPoolExecutor(max_workers=len(sources)) as pool:
                    futs = {
                        pool.submit(_fetch_one_source, source, token): source
                        for source in sources
                    }
                    for fut in as_completed(futs):
                        source = futs[fut]
                        batch = fut.result()
                        with state_lock:
                            for h in batch:
                                raw_radar_hints.append(PoolHint.from_dict(h.to_dict()))
                                h.focus_token = token
                                token_batch.append(h)
                                source_pool_counts[source] = int(
                                    source_pool_counts.get(source, 0)
                                ) + 1
            else:
                for source in sources:
                    batch = _fetch_one_source(source, token)
                    with state_lock:
                        for h in batch:
                            raw_radar_hints.append(PoolHint.from_dict(h.to_dict()))
                            h.focus_token = token
                            token_batch.append(h)
                            source_pool_counts[source] = int(
                                source_pool_counts.get(source, 0)
                            ) + 1
            verified = _verify_batch(token_batch)
            with state_lock:
                for h in verified:
                    all_hints.append(h)
                    if h.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES:
                        per_source_verified_yield[h.source] = int(
                            per_source_verified_yield.get(h.source, 0)
                        ) + 1
                        if venue_count < 2:
                            second_pool_hints += 1

    token_concurrency = max(1, int(args.token_concurrency or 1))
    pending_indices = [i for i in range(len(tokens)) if i not in completed_indices]

    def _process_token_at_index(i: int, token: str) -> int:
        if i in completed_indices:
            return i
        token = token.lower()
        venue_count = _venue_count(token)
        _fetch_token_sources(token, venue_count)
        with state_lock:
            completed_indices.add(i)
            if args.checkpoint_every and len(completed_indices) % int(args.checkpoint_every) == 0:
                _write_checkpoint(completed_indices)
                log.info(
                    "Checkpoint saved: completed %d/%d tokens",
                    len(completed_indices),
                    len(tokens),
                )
        return i

    if token_concurrency <= 1:
        for i in pending_indices:
            _process_token_at_index(i, tokens[i])
            if args.sleep_ms and i + 1 < len(tokens):
                time.sleep(args.sleep_ms / 1000.0)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=token_concurrency) as pool:
            futs = {
                pool.submit(_process_token_at_index, i, tokens[i]): i
                for i in pending_indices
            }
            for fut in as_completed(futs):
                fut.result()

    if checkpoint_path.is_file():
        try:
            checkpoint_path.unlink()
        except OSError:
            pass
    if hints_sidecar.is_file():
        try:
            hints_sidecar.unlink()
        except OSError:
            pass

    deduped = dedupe_hints(all_hints)
    second_venue_hist: dict[str, int] = {}
    for h in deduped:
        if h.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES:
            second_venue_hist[h.source] = int(second_venue_hist.get(h.source, 0)) + 1

    from m8.discovery.radar_layer import (
        build_radar_candidates_artifact,
        write_radar_candidates_artifact,
    )
    from m8.discovery.radar_fast_pipeline import build_verify_subset_tokens, pipeline_metrics
    from m8.discovery.radar_providers import radar_provider_metrics

    subset_size = len(build_verify_subset_tokens(deduped))
    pipe_m = pipeline_metrics(
        radar_fast_tokens=len(tokens),
        radar_candidates=len(raw_radar_hints) or len(deduped),
        verify_subset_size=subset_size,
        verified_count=sum(
            1 for h in deduped if h.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES
        ),
        provider_timing=provider_timing,
        verified_yield_by_source=per_source_verified_yield,
    )

    radar_artifact = build_radar_candidates_artifact(
        chain=args.chain,
        sources=sources + (["geckoterminal_new_pools"] if args.new_pools_backfill else []),
        hints=raw_radar_hints,
        metrics={
            "hint_tokens_checked": len(tokens),
            "defillama_dex_scan_weights": defillama_weights.get("dex_scan_weights") or {},
            "defillama_status": defillama_weights.get("status"),
            "external_route_liveness": route_liveness,
        },
    )
    write_radar_candidates_artifact(radar_artifact, args.radar_output)
    log.info(
        "Radar candidates written %s pools=%d",
        args.radar_output,
        radar_artifact["metrics"].get("candidates_total", 0),
    )

    if args.pipeline_mode == "radar_fast" or (
        args.radar_fast and verify_mode == "none"
    ):
        log.info(
            "Radar-fast complete: skipping canonical hints write (verify phase required)"
        )
        return 0

    radar_metrics = radar_provider_metrics(
        source_pool_counts,
        per_source_verified_yield,
        sources_requested=sources,
    )
    metrics = {
        "hint_tokens_checked": len(tokens),
        "second_pool_hints_found": second_pool_hints,
        "hint_source_latency_s": timer.latency_s,
        "hint_freshness_s": dict(timer.latency_s),
        "hint_source_pool_counts": source_pool_counts,
        "per_source_verified_yield": per_source_verified_yield,
        "single_venue_retry_passes": single_venue_retries,
        "second_venue_source": second_venue_hist,
        "verify_mode": verify_mode,
        "pipeline_mode": args.pipeline_mode,
        **pipe_m,
        "fetch_async": bool(args.fetch_async),
        "verify_async_workers": int(args.verify_async_workers),
        "bytecode_parallel_prepass": bool(args.use_multicall),
        "use_multicall": bool(args.use_multicall),
        "use_multicall_note": (
            "legacy alias; parallel eth_getCode pre-pass, not full aggregate3 verify"
        ),
        "ws_head_block": verify_block,
        "new_pools_backfill": bool(args.new_pools_backfill),
        "radar_candidates_path": args.radar_output,
        "radar_reason_counts": radar_artifact["metrics"].get("radar_reason_counts") or {},
        "defillama_dex_scan_weights": defillama_weights.get("dex_scan_weights") or {},
        "external_route_liveness": route_liveness,
        **radar_metrics,
        **verification_metrics,
    }
    artifact = build_artifact(
        chain=args.chain,
        sources=sources + (["geckoterminal_new_pools"] if args.new_pools_backfill else []),
        hints=all_hints,
        metrics=metrics,
    )
    if args.merge_existing_output:
        from m8.discovery.hint_artifact_merge import load_hint_artifact, merge_hint_artifacts

        prior = load_hint_artifact(args.output)
        artifact = merge_hint_artifacts(
            prior,
            artifact,
            chain=args.chain,
            sources=list(artifact.get("sources") or sources),
        )
    write_hints_artifact(artifact, args.output)
    m = artifact["metrics"]
    log.info(
        "Written %s tokens=%d pools=%d verified=%d tcr=%s reject=%s",
        args.output,
        m.get("hint_tokens_checked", 0),
        m.get("hint_pools_seen", 0),
        m.get("verified_second_pool_count", 0),
        m.get("transition_candidate_rate"),
        m.get("verification_reject_histogram", {}),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
