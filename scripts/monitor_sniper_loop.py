#!/usr/bin/env python3
"""Append sniper artifact snapshots every N seconds for soak timeline."""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_OUT = _REPO / "data/tmp/sniper_monitor_timeline.log"
_INTERVAL_S = 60  # aligned with dashboard + artifact write cadence
_DURATION_S = 3900  # 65 min


def main() -> int:
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _DURATION_S
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
            fh.flush()
            time.sleep(_INTERVAL_S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
