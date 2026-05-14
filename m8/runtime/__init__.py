"""m8.runtime -- CLI entry points and smoke runners.

``m8/runtime/smoke_run.py`` is the canonical implementation of the
new-pool factory event smoke runner.  ``scripts/sniper_smoke_run.py``
is now a thin wrapper that re-exports ``main`` from here.

Usage (via scripts/ wrappers)::

    ARBY_SNIPER_ENABLE=1 py -3.11 scripts/sniper_smoke_run.py --chain base ...
    py -3.11 scripts/sniper_factory_probe.py --chain base --blocks-back 5000

Or directly::

    from m8.runtime.smoke_run import main
"""
