"""M9 graph-arb runner — CLI entry point for the shadow scanner."""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Process lock file
_LOCK_FILE = "data/tmp/m9_runner.lock"

# Exit codes
EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_NO_CYCLES = 2
EXIT_ALL_QUOTES_FAILED = 3


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _setup_logging(verbose: bool = False) -> None:
    import logging
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _get_provider_throttle_snapshot() -> "dict | None":
    """Return current provider_throttle snapshot, or None if unavailable."""
    try:
        from core.provider_throttle import provider_throttle
        return provider_throttle.snapshot()
    except Exception:
        return None


def _connect_rpc(chain: str) -> "object | None":
    """Attempt to connect to the chain RPC. Returns Web3 instance or None."""
    try:
        from core.rpc_urls import get_rpc_url  # type: ignore[import]
        from web3 import Web3  # type: ignore[import]

        url = get_rpc_url(chain)
        w3 = Web3(Web3.HTTPProvider(url))
        if w3.is_connected():
            return w3
        return None
    except Exception:
        return None


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="M9 graph-arb shadow scanner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--chain", default="base", help="Chain identifier")
    parser.add_argument(
        "--config",
        default="config/exotic_base_anchor.yaml",
        help="M8_1 config YAML path",
    )
    parser.add_argument(
        "--inventory",
        default=None,
        help=(
            "Inventory artifact JSON path. "
            "If omitted, uses shadow inventory with gap edges if available, "
            "else m8_1 exotic inventory fallback."
        ),
    )
    parser.add_argument(
        "--duration-minutes",
        type=float,
        default=1.0,
        help="Wall-clock scan duration in minutes (hard deadline)",
    )
    parser.add_argument(
        "--cycles-limit",
        type=int,
        default=5000,
        help="Maximum cycles to find per topology sweep",
    )
    parser.add_argument(
        "--max-cycles-per-sweep",
        type=int,
        default=200,
        help="Maximum cycles to quote per sweep iteration (deadline loop)",
    )
    parser.add_argument(
        "--quote-timeout-s",
        type=float,
        default=10.0,
        help="Per-cycle quote timeout in seconds",
    )
    parser.add_argument(
        "--sizes-usd",
        nargs="+",
        type=float,
        default=[1000.0, 5000.0, 10000.0],
        help="Quote sizes in USD",
    )
    parser.add_argument(
        "--artifact-path",
        default="data/runs/_rolling/m9_graph_latest.json",
        help="Rolling artifact output path",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Build graph only, skip quoting")
    parser.add_argument(
        "--quote-workers",
        type=int,
        default=4,
        help=(
            "Number of parallel quote worker threads. "
            "Reduce to 1-2 when using dRPC free tier to avoid HTTP 429."
        ),
    )
    parser.add_argument(
        "--quote-backend",
        default="direct_http",
        choices=["direct_http", "raw_http", "anvil_fork"],
        help=(
            "Quote backend: "
            "'direct_http' (web3 + eth_chainId, 2 HTTP/probe), "
            "'raw_http' (direct JSON-RPC, 1 HTTP/probe, recommended for 429 fix), "
            "'anvil_fork' (local fork at http://127.0.0.1:8545, no rate limits)."
        ),
    )
    parser.add_argument(
        "--ws-freshness-url",
        default=None,
        help=(
            "WebSocket URL for newHeads freshness monitor (e.g. wss://mainnet.base.org). "
            "Optional — falls back to env BASE_WSS if not set."
        ),
    )

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    import logging
    log = logging.getLogger(__name__)

    # Acquire process lock
    lock_path = Path(_LOCK_FILE)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        log.warning("Lock file exists at %s — another runner may be active", _LOCK_FILE)

    lock_path.write_text(str(os.getpid()))

    try:
        return _run(args, log)
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def _run(args: argparse.Namespace, log: "logging.Logger") -> int:
    import logging
    from m9.graph_arb.builder import (
        build_graph_from_inventory, graph_token_count, graph_edge_count, graph_route_count,
        extract_inventory_stats, best_inventory_path,
    )
    from m9.graph_arb.finder import find_cycles, analyze_topology, rank_cycles
    from m9.graph_arb.artifacts import build_artifact, write_artifact

    run_timestamp = _iso_now()
    started_at = time.monotonic()
    sweeps_completed = 0
    process_id = os.getpid()

    # Prefer merged shadow inventory if available
    inventory_path = best_inventory_path(preferred=args.inventory)
    log.info(
        "M9 graph-arb runner starting: chain=%s config=%s inventory=%s",
        args.chain, args.config, inventory_path,
    )

    # Extract inventory stats (Funnel A + reject taxonomy) before building graph
    inv_stats = extract_inventory_stats(inventory_path)
    funnel_a = inv_stats.get("funnel_a")
    inventory_reject_histogram = inv_stats.get("reject_histogram") or None

    # Build graph
    try:
        adjacency = build_graph_from_inventory(
            inventory_path=inventory_path,
            config_path=args.config,
        )
    except Exception as exc:
        log.error("Failed to build graph: %s", exc)
        return EXIT_CONFIG_ERROR

    if not adjacency:
        log.error("Empty graph — check inventory path: %s", inventory_path)
        from m9.graph_arb.models import GraphTopology
        topology = GraphTopology(
            token_count=0, edge_count=0, route_count=0,
            hub_tokens=[], dead_end_tokens=[],
            missing_edges_for_3cycle=[], adjacency_summary={},
        )
        artifact = build_artifact(
            chain=args.chain,
            duration_minutes=args.duration_minutes,
            cycle_results=[],
            topology=topology,
            sizes_usd=tuple(args.sizes_usd),
            run_timestamp=run_timestamp,
            started_at_mono=started_at,
            elapsed_s=time.monotonic() - started_at,
            inventory_path=inventory_path,
            config_path=args.config,
            sweeps_completed=0,
            process_id=process_id,
            python_executable=sys.executable,
            venv_active=bool(os.environ.get("VIRTUAL_ENV")),
            funnel_a=funnel_a,
            inventory_reject_histogram=inventory_reject_histogram,
        )
        write_artifact(artifact, args.artifact_path)
        return EXIT_CONFIG_ERROR

    # Find cycles
    log.info("Finding cycles (limit=%d)...", args.cycles_limit)
    cycles = find_cycles(adjacency, max_cycles=args.cycles_limit)
    topology = analyze_topology(adjacency, cycles)
    ranked = rank_cycles(cycles)

    log.info("Found %d cycles across %d tokens", len(cycles), topology.token_count)

    if not cycles:
        artifact = build_artifact(
            chain=args.chain,
            duration_minutes=args.duration_minutes,
            cycle_results=[],
            topology=topology,
            sizes_usd=tuple(args.sizes_usd),
            run_timestamp=run_timestamp,
            started_at_mono=started_at,
            elapsed_s=time.monotonic() - started_at,
            inventory_path=inventory_path,
            config_path=args.config,
            sweeps_completed=sweeps_completed,
            process_id=process_id,
            python_executable=sys.executable,
            venv_active=bool(os.environ.get("VIRTUAL_ENV")),
            funnel_a=funnel_a,
            inventory_reject_histogram=inventory_reject_histogram,
        )
        write_artifact(artifact, args.artifact_path)
        return EXIT_NO_CYCLES

    if args.dry_run:
        log.info("Dry-run mode: skipping quoting (topology cycles_found=%d)", len(cycles))
        artifact = build_artifact(
            chain=args.chain,
            duration_minutes=args.duration_minutes,
            cycle_results=[],
            topology=topology,
            sizes_usd=tuple(args.sizes_usd),
            run_timestamp=run_timestamp,
            started_at_mono=started_at,
            elapsed_s=time.monotonic() - started_at,
            inventory_path=inventory_path,
            config_path=args.config,
            sweeps_completed=sweeps_completed,
            process_id=process_id,
            python_executable=sys.executable,
            venv_active=bool(os.environ.get("VIRTUAL_ENV")),
            # Preserve topology cycle count even though quote results are empty
            cycles_found_topology=len(cycles),
            funnel_a=funnel_a,
            inventory_reject_histogram=inventory_reject_histogram,
        )
        write_artifact(artifact, args.artifact_path)
        return EXIT_OK

    # Connect RPC
    w3 = _connect_rpc(args.chain)
    if w3 is None:
        log.warning("Could not connect to RPC for chain %s — quoting will fail", args.chain)

    # Resolve RPC URL for raw_http / anvil_fork backends
    rpc_url: "str | None" = None
    try:
        from core.rpc_urls import get_rpc_url
        rpc_url = get_rpc_url(args.chain)
    except Exception as exc:
        log.warning("Could not resolve rpc_url for chain %s: %s", args.chain, exc)

    # Start optional WS freshness monitor
    ws_url = getattr(args, "ws_freshness_url", None) or os.environ.get("BASE_WSS")
    ws_monitor = None
    if ws_url:
        try:
            from m9.graph_arb.ws_monitor import start_ws_monitor
            ws_monitor = start_ws_monitor(ws_url)
            log.info("WS freshness monitor started: %s", ws_url)
        except Exception as exc:
            log.debug("WS monitor start failed: %s", exc)

    # Deadline-aware quote loop: run sweeps until wall-clock deadline expires.
    # Each sweep quotes a batch of max_cycles_per_sweep cycles, then writes a
    # partial artifact so the rolling artifact stays fresh even mid-soak.
    from m9.graph_arb.quoter import schedule_cycle_quotes
    deadline = started_at + args.duration_minutes * 60.0
    max_per_sweep = getattr(args, "max_cycles_per_sweep", 200)
    cycle_count = len(ranked)
    all_results: list = []
    sweep_num = 0

    while time.monotonic() < deadline:
        start_idx = (sweep_num * max_per_sweep) % cycle_count
        end_idx = min(start_idx + max_per_sweep, cycle_count)
        batch = ranked[start_idx:end_idx]
        if not batch:
            # cycle_count < max_per_sweep — all cycles covered in one sweep
            if sweep_num > 0:
                break
        new_results = schedule_cycle_quotes(
            batch,
            w3=w3,
            sizes_usd=tuple(args.sizes_usd),
            timeout_s=getattr(args, "quote_timeout_s", 10.0),
            max_workers=getattr(args, "quote_workers", 4),
            quote_backend=getattr(args, "quote_backend", "direct_http"),
            rpc_url=rpc_url,
        )
        all_results.extend(new_results)
        sweeps_completed += 1
        sweep_num += 1

        # Write partial artifact after every sweep so rolling stays current
        elapsed_so_far = time.monotonic() - started_at
        _pt_snap = _get_provider_throttle_snapshot()
        _ws_snap = ws_monitor.snapshot() if ws_monitor is not None else None
        partial = build_artifact(
            chain=args.chain,
            duration_minutes=args.duration_minutes,
            cycle_results=all_results,
            topology=topology,
            sizes_usd=tuple(args.sizes_usd),
            run_timestamp=run_timestamp,
            started_at_mono=started_at,
            elapsed_s=elapsed_so_far,
            inventory_path=inventory_path,
            config_path=args.config,
            sweeps_completed=sweeps_completed,
            process_id=process_id,
            python_executable=sys.executable,
            venv_active=bool(os.environ.get("VIRTUAL_ENV")),
            funnel_a=funnel_a,
            inventory_reject_histogram=inventory_reject_histogram,
            quote_backend=getattr(args, "quote_backend", "direct_http"),
            quote_workers=getattr(args, "quote_workers", 4),
            provider_throttle_snapshot=_pt_snap,
            ws_freshness=_ws_snap,
        )
        write_artifact(partial, args.artifact_path)
        positive_so_far = sum(1 for qr in all_results if qr.gross_bps > 0)
        log.info(
            "Sweep %d done: %d new, %d total, %d positive, elapsed=%.1fs/%.0fs",
            sweeps_completed, len(new_results), len(all_results),
            positive_so_far, elapsed_so_far, args.duration_minutes * 60,
        )

        if time.monotonic() >= deadline:
            break

    cycle_results = all_results

    # Collect final infra telemetry
    _pt_snap_final = _get_provider_throttle_snapshot()
    _ws_snap_final = ws_monitor.snapshot() if ws_monitor is not None else None
    if ws_monitor is not None:
        ws_monitor.stop()

    # Build and write final artifact with full elapsed_s
    artifact = build_artifact(
        chain=args.chain,
        duration_minutes=args.duration_minutes,
        cycle_results=cycle_results,
        topology=topology,
        sizes_usd=tuple(args.sizes_usd),
        run_timestamp=run_timestamp,
        started_at_mono=started_at,
        elapsed_s=time.monotonic() - started_at,
        inventory_path=inventory_path,
        config_path=args.config,
        sweeps_completed=sweeps_completed,
        process_id=process_id,
        python_executable=sys.executable,
        venv_active=bool(os.environ.get("VIRTUAL_ENV")),
        funnel_a=funnel_a,
        inventory_reject_histogram=inventory_reject_histogram,
        quote_backend=getattr(args, "quote_backend", "direct_http"),
        quote_workers=getattr(args, "quote_workers", 4),
        provider_throttle_snapshot=_pt_snap_final,
        ws_freshness=_ws_snap_final,
    )
    write_artifact(artifact, args.artifact_path)

    positive = sum(1 for qr in cycle_results if qr.gross_bps > 0)
    log.info(
        "Sweep complete: %d cycles quoted, %d positive gross, artifact written to %s",
        len(cycle_results),
        positive,
        args.artifact_path,
    )

    if not cycle_results:
        return EXIT_ALL_QUOTES_FAILED

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
