#!/usr/bin/env python3
"""Periodic checkpoint log for sniper + hot-path runtime soaks."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_OUT = _REPO / "data/tmp/runtime_soak_timeline.log"
_INTERVAL_S = 60
_DEFAULT_DURATION_S = 7500  # 125 min


def _hot_path_snapshot() -> str:
    path = _REPO / "data/tmp/m8_hot_path_latest.json"
    if not path.exists():
        return "hot_path: MISSING artifact"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return f"hot_path: READ_ERROR {exc}"
    return (
        f"hot_path: gen={d.get('generated_at_utc')} "
        f"events={d.get('hot_path_events_seen')} "
        f"mirrors={d.get('hot_path_mirrors_found')} "
        f"cross_mech={d.get('hot_path_cross_mechanic_candidates')} "
        f"phase_1_5={d.get('phase_1_5')} "
        f"token_class_histogram={d.get('token_class_histogram')} "
        f"ready={ (d.get('acceptance') or {}).get('ready_for_bridge_shadow') }"
    )


def main() -> int:
    duration_s = int(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_DURATION_S
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + duration_s
    with _OUT.open("a", encoding="utf-8") as fh:
        while time.monotonic() < deadline:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fh.write(f"\n===== checkpoint {ts} =====\n")
            fh.flush()
            subprocess.run(
                [sys.executable, str(_REPO / "scripts/monitor_sniper_runtime.py")],
                cwd=str(_REPO),
                stdout=fh,
                stderr=subprocess.STDOUT,
            )
            fh.write(_hot_path_snapshot() + "\n")
            wl = _REPO / "data/tmp/m8_token_watchlist_latest.json"
            if wl.exists():
                try:
                    w = json.loads(wl.read_text(encoding="utf-8"))
                    m = w.get("metrics") or {}
                    fh.write(
                        f"watchlist: tokens={len(w.get('tokens') or {})} "
                        f"transitions_1_to_2={m.get('transitions_1_to_2')} "
                        f"t2s_p50={ (w.get('metrics') or {}).get('time_to_second_pool_s') }\n"
                    )
                except (json.JSONDecodeError, OSError):
                    pass
            fh.flush()
            time.sleep(_INTERVAL_S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
