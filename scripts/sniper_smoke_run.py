"""M8 Phase 1 -- Thin wrapper for the new-pool factory event smoke runner.

The full implementation lives in ``m8.runtime.smoke_run``.
This file re-exports ``main`` for backward-compat imports and acts as
the CLI entry point via ``if __name__ == "__main__"``.

Usage::

    ARBY_SNIPER_ENABLE=1 BASE_RPC=https://... py -3.11 scripts/sniper_smoke_run.py
    ARBY_SNIPER_ENABLE=1 py -3.11 scripts/sniper_smoke_run.py --offline --duration-minutes 0
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from m8.runtime.smoke_run import main  # noqa: F401 -- re-exported for test imports

if __name__ == "__main__":
    sys.exit(main())
