"""Regression tests for runner.py config-error guards.

Tests early-exit gates in _run() that fire before expensive operations like
graph building or inventory loading.
"""
from __future__ import annotations

import argparse
import logging


def _minimal_args(**overrides) -> argparse.Namespace:
    """Build a minimal argparse.Namespace that reaches the prequote gate in _run().

    All required fields are set to safe defaults.  Override any field via kwargs.
    The RPC resolution and scan_params parse are both wrapped in try/except, so
    a nonexistent config path is fine for gate-level tests.
    """
    defaults = dict(
        chain="base",
        config="data/tmp/_nonexistent_config_for_gate_test.yaml",
        inventory=None,
        no_prequote=False,
        dynamic_sizes=False,
        sizes_usd=[100.0, 250.0, 500.0],
        dynamic_size_max_cycles=3,
        require_premium_rpc=False,
        require_factory_verified=False,
        verbose=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestNoPrequoteLongDurationGate:
    """Tests for the --no-prequote + duration_minutes >= 5 safety gate."""

    def test_no_prequote_long_duration_returns_config_error(self):
        """--no-prequote + duration_minutes >= 5 without allow flag must be rejected."""
        from m9.graph_arb.runner import EXIT_CONFIG_ERROR, _run  # type: ignore[attr-defined]

        log = logging.getLogger("test.runner_config_gates")
        args = _minimal_args(
            no_prequote=True,
            dynamic_sizes=False,
            duration_minutes=15,
            allow_no_prequote_soak=False,
        )
        result = _run(args, log)
        assert result == EXIT_CONFIG_ERROR, (
            f"Expected EXIT_CONFIG_ERROR ({EXIT_CONFIG_ERROR}) when "
            f"--no-prequote + duration_minutes=15 + no allow flag, got {result}"
        )

    def test_no_prequote_short_duration_does_not_trigger_gate(self):
        """--no-prequote with duration_minutes < 5 must NOT trigger the new gate."""
        from m9.graph_arb.runner import EXIT_CONFIG_ERROR, _run  # type: ignore[attr-defined]

        log = logging.getLogger("test.runner_config_gates")
        # _minimal_args has no duration_minutes → getattr(..., 0) < 5, gate must not fire
        args = _minimal_args(no_prequote=True, dynamic_sizes=False)
        result = _run(args, log)
        # Must not return CONFIG_ERROR due to the new gate (other gates may still fire)
        # Verify by comparing with allow_no_prequote_soak=True — result should be identical
        args2 = _minimal_args(no_prequote=True, dynamic_sizes=False, allow_no_prequote_soak=True)
        result2 = _run(args2, log)
        assert result == result2, (
            "Short-duration --no-prequote must not trigger the new soak gate "
            "(result must match the allow_no_prequote_soak=True variant)"
        )

    def test_no_prequote_long_duration_with_allow_flag_bypasses_gate(self, caplog):
        """--no-prequote + duration>=5 + --allow-no-prequote-soak must bypass the new gate."""
        from m9.graph_arb.runner import _run  # type: ignore[attr-defined]

        log = logging.getLogger("test.runner_config_gates")
        args = _minimal_args(
            no_prequote=True,
            dynamic_sizes=False,
            duration_minutes=15,
            allow_no_prequote_soak=True,
        )
        with caplog.at_level(logging.ERROR):
            _run(args, log)

        new_gate_logs = [
            r for r in caplog.records
            if "allow_no_prequote_soak" in r.message or "duration_minutes=15" in r.message
        ]
        assert not new_gate_logs, (
            "--allow-no-prequote-soak must suppress the new gate error; "
            "found unexpected log(s): " + str([r.message for r in new_gate_logs])
        )


class TestNoPrequoteDynamicSizesGate:
    def test_both_flags_returns_config_error(self):
        """--no-prequote + --dynamic-sizes must be rejected immediately (EXIT_CONFIG_ERROR)."""
        from m9.graph_arb.runner import EXIT_CONFIG_ERROR, _run  # type: ignore[attr-defined]

        log = logging.getLogger("test.runner_config_gates")
        args = _minimal_args(no_prequote=True, dynamic_sizes=True)
        result = _run(args, log)
        assert result == EXIT_CONFIG_ERROR, (
            f"Expected EXIT_CONFIG_ERROR ({EXIT_CONFIG_ERROR}) when "
            f"--no-prequote + --dynamic-sizes both set, got {result}"
        )

    def test_no_prequote_alone_does_not_trigger_gate(self):
        """--no-prequote alone (no --dynamic-sizes) must not trigger the prequote/size gate."""
        from m9.graph_arb.runner import EXIT_CONFIG_ERROR, _run  # type: ignore[attr-defined]

        log = logging.getLogger("test.runner_config_gates")
        args = _minimal_args(no_prequote=True, dynamic_sizes=False)
        result = _run(args, log)
        # May fail for other reasons (empty graph, missing inventory) but the
        # no-prequote gate itself must NOT fire here.
        assert isinstance(result, int), "runner._run must return an int exit code"
        # Verify that if it returns EXIT_CONFIG_ERROR it's not due to the prequote gate
        # by re-running with no_prequote=False and checking identical result.
        args2 = _minimal_args(no_prequote=False, dynamic_sizes=False)
        result2 = _run(args2, log)
        assert result == result2, (
            "Exit code should be identical when --no-prequote is set vs not set "
            "and --dynamic-sizes is False (the prequote gate must not fire)"
        )

    def test_no_require_factory_verified_overrides_env(self, caplog):
        """require_factory_verified=False must not trigger the verified-inventory gate.

        Regression test: --no-require-factory-verified (or env var unset) must
        NOT produce the "HARD FAIL: --require-factory-verified set but verified
        inventory not found" error even when the verified inventory file is absent.
        """
        import os
        import unittest.mock as mock
        from m9.graph_arb.runner import EXIT_CONFIG_ERROR, _run  # type: ignore[attr-defined]

        log = logging.getLogger("test.runner_config_gates")
        # Patch os.path.exists so verified inventory appears absent (extra-safe).
        _verified_path = "data/tmp/m9_verified_inventory.json"
        original_exists = os.path.exists

        def _patched_exists(p):
            if p == _verified_path:
                return False
            return original_exists(p)

        with mock.patch("os.path.exists", side_effect=_patched_exists):
            with caplog.at_level(logging.ERROR):
                args = _minimal_args(require_factory_verified=False)
                _run(args, log)

        hard_fail_logs = [
            r for r in caplog.records
            if "HARD FAIL" in r.message and "require-factory-verified" in r.message
        ]
        assert not hard_fail_logs, (
            "require_factory_verified=False must not trigger the verified-inventory "
            "HARD FAIL gate; found unexpected ERROR log(s): "
            + str([r.message for r in hard_fail_logs])
        )
