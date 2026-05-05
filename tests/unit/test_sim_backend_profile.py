"""
E1.34 P0.1: Profile-aware simulation backend selection.

Verifies that:
- Without a profile, ARBY_SIM_BACKEND drives the selector (backward-compat).
- With profile="discovery", ARBY_SIM_BACKEND_DISC wins when set to a valid backend.
- With profile="prod", ARBY_SIM_BACKEND_PROD wins when set.
- Unknown profile-override values fall back to ARBY_SIM_BACKEND (not silently
  dropped to tenderly).
- Unknown profile names fall through cleanly.
"""
from __future__ import annotations

import pytest

from m7.orderflow.simulation import (
    BACKEND_ANVIL,
    BACKEND_RPC_FORK,
    BACKEND_TENDERLY,
    get_simulation_backend,
)


_ALL_VARS = (
    "ARBY_SIM_BACKEND",
    "ARBY_SIM_BACKEND_DISC",
    "ARBY_SIM_BACKEND_PROD",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for var in _ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


class TestProfileAwareBackend:
    def test_default_no_env_no_profile(self):
        # Default is now rpc_fork (Tenderly is opt-in via ARBY_SIM_BACKEND=tenderly)
        assert get_simulation_backend() == BACKEND_RPC_FORK

    def test_global_env_without_profile(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "rpc_fork")
        assert get_simulation_backend() == BACKEND_RPC_FORK

    def test_discovery_override_wins(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "tenderly")
        monkeypatch.setenv("ARBY_SIM_BACKEND_DISC", "rpc_fork")
        assert get_simulation_backend(profile="discovery") == BACKEND_RPC_FORK
        # PROD lane unaffected.
        assert get_simulation_backend(profile="prod") == BACKEND_TENDERLY

    def test_prod_override_wins(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "tenderly")
        monkeypatch.setenv("ARBY_SIM_BACKEND_PROD", "anvil")
        assert get_simulation_backend(profile="prod") == BACKEND_ANVIL
        assert get_simulation_backend(profile="discovery") == BACKEND_TENDERLY

    def test_disc_alias_accepted(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND_DISC", "anvil")
        assert get_simulation_backend(profile="disc") == BACKEND_ANVIL

    def test_unknown_disc_value_falls_back(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "rpc_fork")
        monkeypatch.setenv("ARBY_SIM_BACKEND_DISC", "not_a_backend")
        # Invalid override → fall through to global env (rpc_fork).
        assert get_simulation_backend(profile="discovery") == BACKEND_RPC_FORK

    def test_unknown_profile_name_uses_global(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "anvil")
        assert get_simulation_backend(profile="staging") == BACKEND_ANVIL

    def test_profile_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND_DISC", "rpc_fork")
        assert get_simulation_backend(profile="DISCOVERY") == BACKEND_RPC_FORK

    def test_override_value_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND_DISC", "RPC_FORK")
        assert get_simulation_backend(profile="discovery") == BACKEND_RPC_FORK

    def test_backward_compat_no_profile_unchanged(self, monkeypatch):
        """Callers not passing profile get exactly legacy behavior."""
        monkeypatch.setenv("ARBY_SIM_BACKEND", "anvil")
        monkeypatch.setenv("ARBY_SIM_BACKEND_DISC", "rpc_fork")
        # No profile → profile-specific env ignored.
        assert get_simulation_backend() == BACKEND_ANVIL
