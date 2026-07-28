"""Long-lived continuous broker service with heartbeat and graceful shutdown."""
from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.continuous_broker import run_broker_round
from core.continuous_pipeline import ContinuousOrchestrator


@dataclass
class BrokerServiceState:
    rounds: int = 0
    jobs_processed: int = 0
    ingest_emitted: int = 0
    m9_quote_results: int = 0
    last_heartbeat_utc: str = ""


def _heartbeat_path(session_id: str) -> Path:
    return Path("data/tmp/continuous_broker_heartbeat") / f"{session_id}.json"


def write_heartbeat(session_id: str, state: BrokerServiceState) -> None:
    path = _heartbeat_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "session_id": session_id,
        "rounds": state.rounds,
        "jobs_processed": state.jobs_processed,
        "ingest_emitted": state.ingest_emitted,
        "m9_quote_results": state.m9_quote_results,
        "last_heartbeat_utc": state.last_heartbeat_utc,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run_broker_service(
    orchestrator: ContinuousOrchestrator,
    *,
    poll_interval_s: float = 1.0,
    jobs_per_worker: int = 8,
) -> BrokerServiceState:
    """Run broker until SIGTERM/SIGINT. Ingest polled once per cycle inside run_broker_round."""
    stop = False

    def _stop_handler(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop_handler)
    signal.signal(signal.SIGINT, _stop_handler)

    state = BrokerServiceState()
    while not stop:
        state.rounds += 1
        round_result = run_broker_round(
            orchestrator,
            jobs_per_worker=jobs_per_worker,
        )
        state.jobs_processed += round_result.jobs_processed
        state.m9_quote_results += round_result.m9_quote_results
        state.last_heartbeat_utc = datetime.now(timezone.utc).isoformat()
        write_heartbeat(orchestrator.session_id, state)
        time.sleep(max(0.05, float(poll_interval_s)))
    return state
