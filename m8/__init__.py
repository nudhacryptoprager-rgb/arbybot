"""M8 — New-Pool Sniping package.

Sub-packages:
  m8.discovery   — factory event listener and pool parser
  m8.monitoring  — funnel tracker, artifact writer, honeypot detector
  m8.scoring     — Phase 2+ spread/profit estimators (not yet implemented)
  m8.runtime     — CLI entry points and smoke runners

Compatibility note:
  Core modules still live at their original paths (monitoring/sniper_*.py,
  discovery/new_pool_listener.py) with re-exports here.  Actual file moves
  happen incrementally, verifying tests + soak after each migration step.
"""
