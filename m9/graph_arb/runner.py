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
        default="data/tmp/m8_1_exotic_inventory_latest.json",
        help="Inventory artifact JSON path",
    )
    parser.add_argument(
        "--duration-minutes",
        type=float,
        default=1.0,
        help="Target scan duration in minutes",
    )
    parser.add_argument(
        "--cycles-limit",
        type=int,
        default=5000,
        help="Maximum cycles to find per sweep",
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
    from m9.graph_arb.builder import build_graph_from_inventory, graph_token_count, graph_edge_count, graph_route_count
    from m9.graph_arb.finder import find_cycles, analyze_topology, rank_cycles
    from m9.graph_arb.artifacts import build_artifact, write_artifact

    run_timestamp = _iso_now()
    started_at = time.monotonic()
    sweeps_completed = 0
    process_id = os.getpid()

    log.info("M9 graph-arb runner starting: chain=%s config=%s", args.chain, args.config)

    # Build graph
    try:
        adjacency = build_graph_from_inventory(
            inventory_path=args.inventory,
            config_path=args.config,
        )
    except Exception as exc:
        log.error("Failed to build graph: %s", exc)
        return EXIT_CONFIG_ERROR

    if not adjacency:
        log.error("Empty graph — check inventory path: %s", args.inventory)
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
            inventory_path=args.inventory,
            config_path=args.config,
            sweeps_completed=0,
            process_id=process_id,
            python_executable=sys.executable,
            venv_active=bool(os.environ.get("VIRTUAL_ENV")),
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
            inventory_path=args.inventory,
            config_path=args.config,
            sweeps_completed=sweeps_completed,
            process_id=process_id,
            python_executable=sys.executable,
            venv_active=bool(os.environ.get("VIRTUAL_ENV")),
        )
        write_artifact(artifact, args.artifact_path)
        return EXIT_NO_CYCLES

    if args.dry_run:
        log.info("Dry-run mode: skipping quoting")
        artifact = build_artifact(
            chain=args.chain,
            duration_minutes=args.duration_minutes,
            cycle_results=[],
            topology=topology,
            sizes_usd=tuple(args.sizes_usd),
            run_timestamp=run_timestamp,
            started_at_mono=started_at,
            elapsed_s=time.monotonic() - started_at,
            inventory_path=args.inventory,
            config_path=args.config,
            sweeps_completed=sweeps_completed,
            process_id=process_id,
            python_executable=sys.executable,
            venv_active=bool(os.environ.get("VIRTUAL_ENV")),
        )
        write_artifact(artifact, args.artifact_path)
        return EXIT_OK

    # Connect RPC
    w3 = _connect_rpc(args.chain)
    if w3 is None:
        log.warning("Could not connect to RPC for chain %s — quoting will fail", args.chain)

    # Quote cycles
    from m9.graph_arb.quoter import schedule_cycle_quotes
    cycle_results = schedule_cycle_quotes(
        ranked,
        w3=w3,
        sizes_usd=tuple(args.sizes_usd),
    )
    sweeps_completed = 1

    # Build and write artifact
    artifact = build_artifact(
        chain=args.chain,
        duration_minutes=args.duration_minutes,
        cycle_results=cycle_results,
        topology=topology,
        sizes_usd=tuple(args.sizes_usd),
        run_timestamp=run_timestamp,
        started_at_mono=started_at,
        elapsed_s=time.monotonic() - started_at,
        inventory_path=args.inventory,
        config_path=args.config,
        sweeps_completed=sweeps_completed,
        process_id=process_id,
        python_executable=sys.executable,
        venv_active=bool(os.environ.get("VIRTUAL_ENV")),
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
