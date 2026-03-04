# PATH: tests/conftest.py
"""
Pytest configuration and fixtures for ARBY tests.

v3.2.12: Added global cache path redirection to prevent tests from polluting
         production data/cache/ directory.
"""

import sys
from pathlib import Path
import os
import tempfile

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def pytest_configure(config):
    """Configure pytest."""
    # Add custom markers
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    # Prevent unit tests from making real RPC/network calls by default.
    # Integration tests that require network should explicitly enable it.
    os.environ.setdefault("ARBY_SKIP_RPC", "1")


# =============================================================================
# CACHE ISOLATION FIXTURE (v3.2.12)
# =============================================================================

@pytest.fixture(autouse=True)
def isolate_cache_paths(monkeypatch, tmp_path):
    """
    Global autouse fixture that redirects all cache path helpers to tmp_path.
    
    v3.2.12: Prevents tests from writing to production data/cache/ directory.
    All chain-scoped caches (_get_*_cache_path) are redirected to tmp_path.
    
    This prevents:
    - Pollution of production cache with synthetic test data
    - Cross-test pollution through shared singleton state
    - Cache state leaking between ONLINE runs and pytest
    """
    fake_cache = tmp_path / "cache"
    fake_cache.mkdir(exist_ok=True)
    
    # Redirect dynamic_anchors cache path
    # v3.2.14: Treat chain_key="unknown" same as None (legacy fallback)
    def _fake_anchor_path(chain_key=None):
        key = chain_key if chain_key and chain_key != "unknown" else "legacy"
        return fake_cache / f"dynamic_anchors_{key}.json"
    monkeypatch.setattr(
        "strategy.dynamic_anchors._get_anchor_cache_path",
        _fake_anchor_path
    )
    
    # Redirect quarantine cache path
    # v3.2.14: Treat chain_key="unknown" same as None (legacy fallback)
    def _fake_quarantine_path(chain_key=None):
        key = chain_key if chain_key and chain_key != "unknown" else "legacy"
        return fake_cache / f"quarantine_{key}.json"
    monkeypatch.setattr(
        "strategy.quarantine._get_quarantine_cache_path",
        _fake_quarantine_path
    )
    
    # Redirect runtime_disabled cache path (returns str, not Path)
    # v3.2.14: Treat chain_key="unknown" same as None (legacy fallback)
    def _fake_runtime_disabled_path(chain_key=None):
        key = chain_key if chain_key and chain_key != "unknown" else "legacy"
        return str(fake_cache / f"runtime_disabled_{key}.json")
    monkeypatch.setattr(
        "strategy.runtime_disabled._get_runtime_disabled_cache_path",
        _fake_runtime_disabled_path
    )
    
    # Reset all singletons to ensure clean state per test
    from strategy.dynamic_anchors import reset_anchor_manager
    from strategy.quarantine import reset_quarantine_manager
    from strategy.runtime_disabled import clear_runtime_disabled_manager
    
    reset_anchor_manager()
    reset_quarantine_manager()
    clear_runtime_disabled_manager()
    
    yield
    
    # Cleanup: reset singletons again after test
    reset_anchor_manager()
    reset_quarantine_manager()
    clear_runtime_disabled_manager()