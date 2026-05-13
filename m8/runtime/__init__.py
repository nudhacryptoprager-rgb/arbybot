"""m8.runtime — CLI entry points and smoke runners.

Currently wraps ``scripts.sniper_smoke_run`` and ``scripts.sniper_factory_probe``.
Once those scripts are migrated here, ``scripts/`` will become thin wrappers.

Usage (via scripts/ wrappers)::

    ARBY_SNIPER_ENABLE=1 py -3.11 scripts/sniper_smoke_run.py --chain base ...
    py -3.11 scripts/sniper_factory_probe.py --chain base --blocks-back 5000
"""
