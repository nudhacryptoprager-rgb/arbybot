# PATH: tests/conftest.py
"""
Pytest configuration and fixtures for ARBY tests.
"""

import sys
from pathlib import Path
import os

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