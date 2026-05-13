"""M8 Phase 1 — Standalone smoke runner for new-pool factory event listener.

Purpose
-------
HTTP-polling loop that watches factory contracts on Base (or another EVM chain)
for PoolCreated / PairCreated log events, tracks a full event-processing funnel,
and writes a rolling artifact to ``data/runs/_rolling/new_pool_sniper_latest.json``.

Feature flag
-----------
``ARBY_SNIPER_ENABLE=1`` must be set; otherwise the script exits immediately
with a clear message (exit code 0 — not an error, intentional gate).

RPC URL resolution order
------------------------
1. ``--rpc-url`` CLI argument
2. ``BASE_RPC`` env var  (chain-specific, preferred)
3. ``ARBY_BASE_RPC_URL`` env var
4. Public fallback ``https://mainnet.base.org``

Offline mode (``--offline`` flag or ``ARBY_SNIPER_OFFLINE=1``)
--------------------------------------------------------------
Skips all RPC calls. Simulates one empty cycle so the funnel counters
and artifact writing path are exercised without a network connection.
Useful for offline CI and unit tests.

Commands
--------
  # Enable and run for 10 minutes on Base:
  ARBY_SNIPER_ENABLE=1 BASE_RPC=https://... py -3.11 scripts/sniper_smoke_run.py

  # Offline smoke (no RPC needed):
  ARBY_SNIPER_ENABLE=1 py -3.11 scripts/sniper_smoke_run.py --offline --duration-minutes 0

Self-test
---------
If ``verification_from_block`` and ``verification_to_block`` are set in
``config/new_pool_factories.yaml`` for a factory, the script runs a
self-test at startup: replays that block range via ``eth_getLogs`` and
checks that ≥1 event is parsed. Hard-fails (exit 3) if the self-test
fails for any factory that has verification blocks configured.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Ensure repo root is on sys.path (needed when run as script).
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.env import env_flag_enabled, load_root_dotenv
from core.logging import get_logger, setup_logging
from core.rpc_urls import public_fallback_for
from discovery.new_pool_listener import (
    FactoryConfig,
    NewPoolEvent,
    dedup_events,
    load_factory_config,
    make_event_id,
    parse_raw_log,
)
from monitoring.sniper_artifacts import (
    make_sniper_artifact,
    write_sniper_artifact,
    validate_sniper_artifact,
)
from monitoring.sniper_funnel import EventTrace, FunnelTracker

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ARTIFACT_WRITE_INTERVAL_S: float = 30.0
_MAX_BLOCKS_PER_CALL: int = 2000   # conservative RPC limit
_MAX_RECENT_EVENTS_IN_ARTIFACT: int = 20
_DEFAULT_CHAIN: str = "base"
_DEFAULT_BLOCKS_BACK: int = 50
_DEFAULT_POLL_INTERVAL_S: float = 30.0
_DEFAULT_DURATION_MIN: float = 10.0


# ---------------------------------------------------------------------------
# Raw log → plain dict normalisation
# ---------------------------------------------------------------------------

def _log_to_dict(raw: Any) -> Dict[str, Any]:
    """Convert a web3 AttributeDict (or any Mapping) to a plain dict.

    ``eth.get_logs`` returns ``AttributeDict`` objects; ``parse_raw_log``
    expects plain dicts or Mapping-compatible objects.  AttributeDict is a
    Mapping, so parsing works without normalisation — but we normalise for
    clean serialisation in debug logs.
    """
    try:
        d: Dict[str, Any] = {}
        for k in raw:
            v = raw[k]
            try:
                d[str(k)] = hex(v) if isinstance(v, int) and str(k) in ("blockNumber",) else v
            except Exception:
                d[str(k)] = str(v)
        return d
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# RPC helpers
# ---------------------------------------------------------------------------

def _resolve_rpc_url(chain: str, override: Optional[str]) -> str:
    """Return the RPC URL to use, in priority order.

    1. CLI override (``--rpc-url``)
    2. ``BASE_RPC`` (or chain-upper env) env var
    3. ``ARBY_BASE_RPC_URL`` / ``ARBY_{CHAIN}_RPC_URL``
    4. Public fallback from ``core.rpc_urls``
    """
    if override:
        return override
    chain_upper = chain.upper()
    for env_var in (
        f"{chain_upper}_RPC",
        f"ARBY_{chain_upper}_RPC_URL",
        "ARBY_RPC_URL",
    ):
        val = os.environ.get(env_var, "").strip()
        if val:
            return val
    fb = public_fallback_for(chain)
    if fb:
        return fb
    raise RuntimeError(
        f"No RPC URL available for chain={chain!r}. "
        f"Set {chain_upper}_RPC env var or pass --rpc-url."
    )


def _get_block_number(w3: Any) -> Optional[int]:
    try:
        return int(w3.eth.block_number)
    except Exception as exc:
        logger.warning(
            "eth_blockNumber failed",
            extra={"context": {"error": str(exc)[:120]}},
        )
        return None


def _get_logs_safe(
    w3: Any,
    params: Dict[str, Any],
) -> tuple[List[Any], bool]:
    """Call ``eth.get_logs(params)`` and return (logs, had_error)."""
    try:
        return list(w3.eth.get_logs(params)), False
    except Exception as exc:
        logger.warning(
            "eth_getLogs failed",
            extra={"context": {"params": str(params)[:200], "error": str(exc)[:120]}},
        )
        return [], True


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _run_self_test(
    w3: Any,
    configs: List[FactoryConfig],
    chain: str,
) -> bool:
    """Replay verification block ranges for each factory that has them set.

    Returns True if all testable factories pass (≥1 event parsed).
    Returns True when no factories have verification blocks (nothing to test).
    """
    testable = [
        cfg for cfg in configs
        if cfg.verification_from_block is not None and cfg.verification_to_block is not None
    ]
    if not testable:
        logger.info(
            "self_test skipped — no verification blocks configured",
            extra={"context": {"chain": chain, "factories_total": len(configs)}},
        )
        return True

    all_pass = True
    for cfg in testable:
        assert cfg.verification_from_block is not None
        assert cfg.verification_to_block is not None
        params: Dict[str, Any] = {
            "fromBlock": cfg.verification_from_block,
            "toBlock": cfg.verification_to_block,
            "address": w3.to_checksum_address(cfg.factory),
        }
        if cfg.topic0:
            params["topics"] = [cfg.topic0]

        logs, had_err = _get_logs_safe(w3, params)
        if had_err:
            logger.error(
                "self_test rpc_error",
                extra={"context": {"dex": cfg.dex, "factory": cfg.factory}},
            )
            all_pass = False
            continue

        parsed = [parse_raw_log(lg, cfg) for lg in logs]
        ok_count = sum(1 for e in parsed if e is not None)
        if ok_count == 0:
            logger.error(
                "self_test FAIL — no events parsed in verification range",
                extra={
                    "context": {
                        "dex": cfg.dex,
                        "factory": cfg.factory,
                        "from_block": cfg.verification_from_block,
                        "to_block": cfg.verification_to_block,
                        "raw_logs": len(logs),
                    }
                },
            )
            all_pass = False
        else:
            logger.info(
                "self_test PASS",
                extra={
                    "context": {
                        "dex": cfg.dex,
                        "factory": cfg.factory,
                        "events_parsed": ok_count,
                        "from_block": cfg.verification_from_block,
                        "to_block": cfg.verification_to_block,
                    }
                },
            )
    return all_pass


# ---------------------------------------------------------------------------
# Per-factory getLogs params builder
# ---------------------------------------------------------------------------

def _build_filter_params(
    w3: Any,
    cfg: FactoryConfig,
    from_block: int,
    to_block: int,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "fromBlock": from_block,
        "toBlock": to_block,
        "address": w3.to_checksum_address(cfg.factory),
    }
    if cfg.topic0:
        params["topics"] = [cfg.topic0]
    return params


# ---------------------------------------------------------------------------
# Build rolling artifact from funnel + recent events
# ---------------------------------------------------------------------------

def _build_and_write_artifact(
    funnel: FunnelTracker,
    recent_events: List[NewPoolEvent],
    started_at: str,
    elapsed_s: float,
    source: str,
    status: str,
    reasons: List[str],
) -> None:
    """Build, validate, and atomically write the rolling artifact."""
    metrics = funnel.snapshot()
    recent_list = [
        {
            "event_id": e.event_id,
            "chain": e.chain,
            "dex": e.dex,
            "factory": e.factory,
            "pool": e.pool,
            "token0": e.token0,
            "token1": e.token1,
            "block_number": e.block_number,
            "tx_hash": e.tx_hash,
        }
        for e in recent_events[-_MAX_RECENT_EVENTS_IN_ARTIFACT:]
    ]
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    artifact = make_sniper_artifact(
        metrics=metrics,
        status=status,
        reasons=reasons,
        source=source,
        freshness_s=round(elapsed_s, 1),
        generated_at_utc=now_utc,
        recent_events=recent_list,
    )
    violations = validate_sniper_artifact(artifact)
    if violations:
        logger.warning(
            "artifact_validation_violations",
            extra={"context": {"violations": violations}},
        )
    path = write_sniper_artifact(artifact)
    logger.info(
        "artifact_written",
        extra={
            "context": {
                "path": str(path),
                "status": status,
                "candidates_total": metrics["snipe_candidates_total"],
                "elapsed_s": round(elapsed_s, 1),
            }
        },
    )


# ---------------------------------------------------------------------------
# Offline simulation (no RPC)
# ---------------------------------------------------------------------------

def _run_offline_cycle(
    funnel: FunnelTracker,
    configs: List[FactoryConfig],
    chain: str,
    cycle_n: int,
) -> None:
    """Simulate a single poll cycle with zero real logs."""
    # We 'simulate' one RPC call per factory in the counter for visibility.
    for _cfg in configs:
        funnel.inc_rpc_call()
    funnel.complete_cycle()
    logger.info(
        "poll_cycle_offline",
        extra={
            "context": {
                "cycle": cycle_n,
                "chain": chain,
                "new_events": 0,
                "raw_logs": 0,
                "note": "offline mode — no real RPC",
            }
        },
    )


# ---------------------------------------------------------------------------
# Main polling loop (online)
# ---------------------------------------------------------------------------

def _run_online_loop(
    *,
    w3: Any,
    configs: List[FactoryConfig],
    chain: str,
    funnel: FunnelTracker,
    recent_events: List[NewPoolEvent],
    seen_ids: Set[str],
    poll_interval_s: float,
    blocks_back: int,
    duration_s: float,
    source: str,
) -> None:
    """Main online HTTP polling loop."""
    deadline = time.monotonic() + duration_s
    last_artifact_ts = time.monotonic()
    cycle_n = 0
    last_processed_block: Optional[int] = None

    while time.monotonic() < deadline:
        cycle_start = time.monotonic()
        cycle_n += 1

        current_block = _get_block_number(w3)
        if current_block is None:
            funnel.inc_rpc_error()
            logger.warning(
                "poll_cycle_skip — block_number unavailable",
                extra={"context": {"cycle": cycle_n}},
            )
            time.sleep(min(poll_interval_s, 5.0))
            continue

        if last_processed_block is None:
            from_block = max(0, current_block - blocks_back)
        else:
            from_block = last_processed_block + 1

        # Guard against going backwards (e.g. RPC jitter / re-org)
        from_block = min(from_block, current_block)
        # Chunk to max allowed range
        to_block = min(current_block, from_block + _MAX_BLOCKS_PER_CALL - 1)

        cycle_raw = 0
        cycle_new = 0

        for cfg in configs:
            params = _build_filter_params(w3, cfg, from_block, to_block)
            funnel.inc_rpc_call()
            logs, had_err = _get_logs_safe(w3, params)
            if had_err:
                funnel.inc_rpc_error()
                continue
            funnel.inc("raw_fetched", len(logs))
            cycle_raw += len(logs)

            for raw_log in logs:
                event = parse_raw_log(raw_log, cfg)
                if event is None:
                    funnel.inc("parse_failed")
                    continue
                funnel.inc("parse_ok")

                if event.event_id in seen_ids:
                    funnel.inc("dedup_dropped")
                    continue

                funnel.inc("dedup_new")
                seen_ids.add(event.event_id)

                # Phase 1: all dedup_new pass (honeypot filter in Phase 2)
                funnel.inc("filter_passed")
                funnel.inc("candidates_queued")
                cycle_new += 1

                recent_events.append(event)
                if len(recent_events) > _MAX_RECENT_EVENTS_IN_ARTIFACT * 5:
                    recent_events[:] = recent_events[-_MAX_RECENT_EVENTS_IN_ARTIFACT * 5:]

                trace = EventTrace(
                    event_id=event.event_id,
                    chain=event.chain,
                    dex=event.dex,
                    factory=event.factory,
                    pool=event.pool,
                    token0=event.token0,
                    token1=event.token1,
                    block_number=event.block_number,
                    received_ts=time.time(),
                    filter_passed=True,
                    candidate=True,
                )
                funnel.record_trace(trace)

                logger.info(
                    "new_pool_event",
                    extra={
                        "context": {
                            "event_id": event.event_id,
                            "chain": event.chain,
                            "dex": event.dex,
                            "pool": event.pool,
                            "token0": event.token0,
                            "token1": event.token1,
                            "block_number": event.block_number,
                            "tx_hash": event.tx_hash,
                        }
                    },
                )

        last_processed_block = to_block
        funnel.complete_cycle()

        elapsed_since_artifact = time.monotonic() - last_artifact_ts
        if elapsed_since_artifact >= _ARTIFACT_WRITE_INTERVAL_S:
            snap = funnel.snapshot()
            elapsed_total = snap["elapsed_s"]
            status = "ACTIVE" if snap["snipe_candidates_total"] > 0 else "EMPTY"
            reasons = [] if snap["snipe_candidates_total"] > 0 else ["NO_EVENTS_YET"]
            _build_and_write_artifact(
                funnel=funnel,
                recent_events=recent_events,
                started_at="",
                elapsed_s=elapsed_total,
                source=source,
                status=status,
                reasons=reasons,
            )
            last_artifact_ts = time.monotonic()

        logger.info(
            "poll_cycle",
            extra={
                "context": {
                    "cycle": cycle_n,
                    "chain": chain,
                    "block_range": f"{from_block}-{to_block}",
                    "raw_logs": cycle_raw,
                    "new_events": cycle_new,
                    "total_candidates": funnel.snapshot()["snipe_candidates_total"],
                }
            },
        )

        # Sleep the remainder of the poll interval
        cycle_elapsed = time.monotonic() - cycle_start
        sleep_s = max(0.0, poll_interval_s - cycle_elapsed)
        if sleep_s > 0:
            time.sleep(sleep_s)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point.  Returns OS exit code (0=ok, 1=error, 3=self-test fail)."""
    load_root_dotenv()

    # ------------------------------------------------------------------
    # Feature flag gate — intentional early exit (not an error)
    # ------------------------------------------------------------------
    if not env_flag_enabled("ARBY_SNIPER_ENABLE"):
        print(
            "[sniper_smoke_run] ARBY_SNIPER_ENABLE is not set or is '0'. "
            "Set ARBY_SNIPER_ENABLE=1 to run the sniper listener. Exiting."
        )
        return 0

    # ------------------------------------------------------------------
    # Parse args
    # ------------------------------------------------------------------
    parser = argparse.ArgumentParser(
        description="M8 Phase 1 — New-pool factory event smoke runner.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--chain", default=_DEFAULT_CHAIN,
        help="Chain to listen on (e.g. 'base').",
    )
    parser.add_argument(
        "--duration-minutes", type=float, default=_DEFAULT_DURATION_MIN,
        metavar="N",
        help="How long to run (minutes). 0 = single cycle then exit.",
    )
    parser.add_argument(
        "--poll-interval-s", type=float, default=_DEFAULT_POLL_INTERVAL_S,
        metavar="S",
        help="Seconds between eth_getLogs polls.",
    )
    parser.add_argument(
        "--blocks-back", type=int, default=_DEFAULT_BLOCKS_BACK,
        metavar="N",
        help="How many historical blocks to fetch on first cycle.",
    )
    parser.add_argument(
        "--rpc-url", default=None,
        help="Override RPC URL (ignores env vars).",
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="Offline mode: skip real RPC, simulate empty cycles.",
    )
    parser.add_argument(
        "--log-json", action="store_true",
        help="Emit JSON-formatted log lines (for file capture).",
    )
    parser.add_argument(
        "--skip-self-test", action="store_true",
        help="Skip startup self-test (verification block replay).",
    )
    args = parser.parse_args(argv)

    # Offline via ENV as well
    offline = args.offline or env_flag_enabled("ARBY_SNIPER_OFFLINE")

    # ------------------------------------------------------------------
    # Logging setup
    # ------------------------------------------------------------------
    setup_logging(json_format=args.log_json)

    logger.info(
        "sniper_startup",
        extra={
            "context": {
                "chain": args.chain,
                "duration_minutes": args.duration_minutes,
                "poll_interval_s": args.poll_interval_s,
                "blocks_back": args.blocks_back,
                "offline": offline,
            }
        },
    )

    # ------------------------------------------------------------------
    # Load factory configs
    # ------------------------------------------------------------------
    try:
        configs = load_factory_config(chain_filter=args.chain)
    except Exception as exc:
        logger.error(
            "factory_config_load_failed",
            extra={"context": {"error": str(exc)}},
        )
        return 1

    if not configs:
        logger.error(
            "factory_config_empty",
            extra={"context": {"chain": args.chain}},
        )
        return 1

    logger.info(
        "factory_config_loaded",
        extra={
            "context": {
                "chain": args.chain,
                "factories": [c.factory for c in configs],
                "dexes": [c.dex for c in configs],
            }
        },
    )

    # ------------------------------------------------------------------
    # Warn about factories with unverified topic0 (topic0_verified=False)
    # ------------------------------------------------------------------
    unverified_topic_factories = [
        c.dex for c in configs
        if c.topic0 is not None and not c.topic0_verified
    ]
    null_topic_factories = [
        c.dex for c in configs if c.topic0 is None
    ]
    if unverified_topic_factories:
        logger.warning(
            "topic0_unverified — topic0 computed but not confirmed from contract ABI; "
            "online filtering may miss events or filter wrong logs",
            extra={"context": {"unverified_dexes": unverified_topic_factories}},
        )
    if null_topic_factories:
        logger.warning(
            "topic0_null — these factories will fetch all events (no topic0 filter); "
            "expect higher RPC load",
            extra={"context": {"null_topic_dexes": null_topic_factories}},
        )

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    funnel = FunnelTracker()
    recent_events: List[NewPoolEvent] = []
    seen_ids: Set[str] = set()
    source = f"sniper_smoke_run/{args.chain}"
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t0 = time.monotonic()

    # ------------------------------------------------------------------
    # Online-only: build web3 + self-test
    # ------------------------------------------------------------------
    w3: Any = None
    if not offline:
        try:
            rpc_url = _resolve_rpc_url(args.chain, args.rpc_url)
        except RuntimeError as exc:
            logger.error(str(exc))
            return 1

        try:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(rpc_url))
        except Exception as exc:
            logger.error(
                "web3_init_failed",
                extra={"context": {"rpc_url": rpc_url, "error": str(exc)}},
            )
            return 1

        if not args.skip_self_test:
            self_test_ok = _run_self_test(w3, configs, args.chain)
            if not self_test_ok:
                logger.error("self_test_FAILED — aborting run (use --skip-self-test to bypass)")
                return 3

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    duration_s = args.duration_minutes * 60.0
    # Treat 0 duration as "one cycle then exit"; use a small positive value.
    if duration_s <= 0:
        duration_s = 0.001

    try:
        if offline:
            # Single offline cycle (enough for smoke / CI)
            _run_offline_cycle(funnel, configs, args.chain, cycle_n=1)
            # Extra cycles if duration > poll_interval
            extra_cycles = max(0, int(duration_s / max(args.poll_interval_s, 1.0)) - 1)
            for n in range(2, extra_cycles + 2):
                _run_offline_cycle(funnel, configs, args.chain, cycle_n=n)
        else:
            _run_online_loop(
                w3=w3,
                configs=configs,
                chain=args.chain,
                funnel=funnel,
                recent_events=recent_events,
                seen_ids=seen_ids,
                poll_interval_s=args.poll_interval_s,
                blocks_back=args.blocks_back,
                duration_s=duration_s,
                source=source,
            )
    except KeyboardInterrupt:
        logger.info("sniper interrupted by user (KeyboardInterrupt)")

    # ------------------------------------------------------------------
    # Final artifact write
    # ------------------------------------------------------------------
    snap = funnel.snapshot()
    elapsed_s = snap["elapsed_s"]
    if snap["snipe_candidates_total"] > 0:
        status = "ACTIVE"
        reasons: List[str] = []
    elif snap["rpc_errors"] > 0 and snap["cycles_completed"] == 0:
        status = "ERROR"
        reasons = ["RPC_UNAVAILABLE"]
    else:
        status = "EMPTY"
        reasons = ["NO_EVENTS_YET"]

    # Append topic-quality warnings to reasons so they appear in artifact.
    for dex_name in unverified_topic_factories:
        reasons.append(f"TOPIC_UNVERIFIED:{dex_name}")
    for dex_name in null_topic_factories:
        reasons.append(f"TOPIC_NULL:{dex_name}")

    _build_and_write_artifact(
        funnel=funnel,
        recent_events=recent_events,
        started_at=started_at,
        elapsed_s=elapsed_s,
        source=source,
        status=status,
        reasons=reasons,
    )

    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------
    for line in funnel.funnel_table_lines():
        print(line)

    logger.info(
        "sniper_shutdown",
        extra={
            "context": {
                "status": status,
                "elapsed_s": elapsed_s,
                "candidates_total": snap["snipe_candidates_total"],
                "cycles_completed": snap["cycles_completed"],
            }
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
