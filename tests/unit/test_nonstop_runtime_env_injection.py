"""
E1.35: ManagedProcess env injection for DISC lane wiring.

Verifies that:
- `env=None` → subprocess inherits supervisor env unchanged.
- `env={"ARBY_SIM_BACKEND": "rpc_fork"}` → override merged over os.environ.
- Other env variables from the supervisor are still visible to the child.

Minimal, fast: we don't actually Popen anything — the Popen call is patched
so we can inspect what args would have been passed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make scripts/ importable so we can pull ManagedProcess.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import start_nonstop_runtime as snr  # noqa: E402


@pytest.fixture
def fake_popen():
    """Patch subprocess.Popen inside the module with a MagicMock."""
    with patch.object(snr.subprocess, "Popen") as mock:
        fake = MagicMock()
        fake.pid = 12345
        fake.poll.return_value = None
        mock.return_value = fake
        yield mock


class TestManagedProcessEnvInjection:
    def test_env_none_inherits_supervisor(self, fake_popen, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "tenderly")
        proc = snr.ManagedProcess(
            name="t",
            cmd=["py", "foo.py"],
            restart_delay=1,
            max_restarts=1,
            env=None,
        )
        proc.start()
        # When env=None we pass env=None to Popen (full inherit).
        kwargs = fake_popen.call_args.kwargs
        assert kwargs.get("env") is None

    def test_env_dict_merges_over_environ(self, fake_popen, monkeypatch):
        monkeypatch.setenv("ARBY_SIM_BACKEND", "tenderly")
        monkeypatch.setenv("SOME_OTHER", "kept")
        proc = snr.ManagedProcess(
            name="disc",
            cmd=["py", "foo.py"],
            restart_delay=1,
            max_restarts=1,
            env={"ARBY_SIM_BACKEND": "rpc_fork"},
        )
        proc.start()
        kwargs = fake_popen.call_args.kwargs
        env = kwargs.get("env")
        assert env is not None
        # Override wins.
        assert env["ARBY_SIM_BACKEND"] == "rpc_fork"
        # Inherited variables still present.
        assert env["SOME_OTHER"] == "kept"

    def test_default_env_signature_backward_compat(self, fake_popen):
        """ManagedProcess constructed without env kw should work unchanged."""
        proc = snr.ManagedProcess(
            name="t", cmd=["py", "foo.py"], restart_delay=1, max_restarts=1
        )
        assert proc.env is None
        proc.start()
        kwargs = fake_popen.call_args.kwargs
        assert kwargs.get("env") is None

    def test_empty_env_dict_still_merges(self, fake_popen):
        """env={} is explicit "same as inherit" but still takes the merge path."""
        proc = snr.ManagedProcess(
            name="t",
            cmd=["py", "foo.py"],
            restart_delay=1,
            max_restarts=1,
            env={},
        )
        proc.start()
        kwargs = fake_popen.call_args.kwargs
        # Empty dict is falsy → we keep env=None to preserve legacy default.
        assert kwargs.get("env") is None
