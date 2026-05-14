"""M8 — New-Pool Sniping package.

Sub-packages:
  m8.discovery   — factory event listener and pool parser
  m8.monitoring  — funnel tracker, artifact writer, honeypot detector
  m8.scoring     — Phase 2+ spread/profit estimators (not yet implemented)
  m8.runtime     — CLI entry points and smoke runners

Migration status (m8_package_status: NAMESPACE_SLICE_WITH_RUNTIME):
  m8.discovery   — re-exports only; source in discovery/new_pool_listener.py
  m8.monitoring  — re-exports only; sources in monitoring/sniper_*.py
  m8.scoring     — stub (Phase 2)
  m8.runtime     — FULL IMPLEMENTATION in m8/runtime/smoke_run.py;
                   scripts/sniper_smoke_run.py is now a thin wrapper.

Compatibility note:
  ``from scripts.sniper_smoke_run import main`` continues to work — the
  scripts/ wrapper re-exports ``main`` from m8.runtime.smoke_run.
  Core modules for discovery and monitoring still live at their original
  paths with re-exports here.  Further moves happen incrementally,
  verifying tests + soak after each migration step.
"""
