"""Tests for m8/ package structure and re-exports.

Verifies:
1. m8 package is importable.
2. m8.discovery re-exports match originals.
3. m8.monitoring re-exports match originals.
4. m8.scoring is importable (stub).
5. m8.runtime is importable (stub).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Package importability
# ---------------------------------------------------------------------------

class TestM8PackageImportable:
    def test_m8_importable(self):
        import m8  # noqa: F401

    def test_m8_discovery_importable(self):
        import m8.discovery  # noqa: F401

    def test_m8_monitoring_importable(self):
        import m8.monitoring  # noqa: F401

    def test_m8_scoring_importable(self):
        import m8.scoring  # noqa: F401

    def test_m8_runtime_importable(self):
        import m8.runtime  # noqa: F401


# ---------------------------------------------------------------------------
# m8.discovery re-exports
# ---------------------------------------------------------------------------

class TestM8DiscoveryReexports:
    def test_FactoryConfig_available(self):
        from m8.discovery import FactoryConfig
        assert FactoryConfig is not None

    def test_NewPoolEvent_available(self):
        from m8.discovery import NewPoolEvent
        assert NewPoolEvent is not None

    def test_load_factory_config_available(self):
        from m8.discovery import load_factory_config
        assert callable(load_factory_config)

    def test_parse_raw_log_available(self):
        from m8.discovery import parse_raw_log
        assert callable(parse_raw_log)

    def test_same_class_as_original(self):
        from m8.discovery import FactoryConfig as M8FC
        from discovery.new_pool_listener import FactoryConfig as OrigFC
        assert M8FC is OrigFC


# ---------------------------------------------------------------------------
# m8.monitoring re-exports
# ---------------------------------------------------------------------------

class TestM8MonitoringReexports:
    def test_FunnelTracker_available(self):
        from m8.monitoring import FunnelTracker
        assert FunnelTracker is not None

    def test_make_sniper_artifact_available(self):
        from m8.monitoring import make_sniper_artifact
        assert callable(make_sniper_artifact)

    def test_HoneypotVerdict_available(self):
        from m8.monitoring import HoneypotVerdict
        assert HoneypotVerdict is not None

    def test_check_token_honeypot_available(self):
        from m8.monitoring import check_token_honeypot
        assert callable(check_token_honeypot)

    def test_FunnelTracker_same_class_as_original(self):
        from m8.monitoring import FunnelTracker as M8FT
        from monitoring.sniper_funnel import FunnelTracker as OrigFT
        assert M8FT is OrigFT

    def test_SCHEMA_REVISION_accessible(self):
        from m8.monitoring import SCHEMA_REVISION
        assert isinstance(SCHEMA_REVISION, str) and SCHEMA_REVISION

    def test_write_sniper_artifact_accessible(self):
        from m8.monitoring import write_sniper_artifact
        assert callable(write_sniper_artifact)
