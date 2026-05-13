"""m8.discovery — factory event listener and pool parser.

Re-exports all public symbols from ``discovery.new_pool_listener``
so that M8-internal code can import from ``m8.discovery`` directly.

Migration note:
  The canonical module is currently ``discovery.new_pool_listener``.
  Imports from that path remain valid and tests use them.
  When the file is moved here, a compat re-export will be added to
  ``discovery/new_pool_listener.py``.
"""
from discovery.new_pool_listener import (  # noqa: F401
    FactoryConfig,
    NewPoolEvent,
    dedup_events,
    load_factory_config,
    make_event_id,
    parse_raw_log,
)

__all__ = [
    "FactoryConfig",
    "NewPoolEvent",
    "dedup_events",
    "load_factory_config",
    "make_event_id",
    "parse_raw_log",
]
