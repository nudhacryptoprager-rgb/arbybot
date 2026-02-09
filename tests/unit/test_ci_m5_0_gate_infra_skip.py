# PATH: tests/unit/test_ci_m5_0_gate_infra_skip.py
"""Test that offline mode skips infra validation without WARN."""

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.ci_m5_0_gate import (
    generate_fixture_artifacts,
    main,
)


class TestOfflineInfraSkip(unittest.TestCase):
    """Offline mode MUST skip infra validation entirely - 0 WARN."""

    def test_offline_no_warn_for_missing_infra_fields(self):
        """
        Offline mode generates FIXTURE_OFFLINE artifacts which have no
        rpc_provider, rpc_http_host, chain_id, etc. This is intentional.
        The gate MUST NOT emit WARN for missing infra fields in offline mode.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)

            # Capture stdout
            captured = io.StringIO()
            with patch('sys.stdout', captured):
                with patch('sys.argv', ['ci_m5_0_gate.py', '--offline', '--output-root', str(output_root)]):
                    result = main()

            output = captured.getvalue()

            # Should PASS
            self.assertEqual(result, 0, f"Expected PASS (0), got {result}")

            # Should NOT contain WARN
            self.assertNotIn("WARN:", output, f"Unexpected WARN in output:\n{output}")

    def test_offline_strict_no_warn(self):
        """--offline --strict should also have 0 WARN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)

            captured = io.StringIO()
            with patch('sys.stdout', captured):
                with patch('sys.argv', ['ci_m5_0_gate.py', '--offline', '--strict', '--output-root', str(output_root)]):
                    result = main()

            output = captured.getvalue()

            self.assertEqual(result, 0)
            self.assertNotIn("WARN:", output)


class TestOnlineInfraValidation(unittest.TestCase):
    """Online mode should validate infra fields."""

    def test_fixture_with_require_real_fails_on_provider(self):
        """
        When run with --require-real on FIXTURE artifacts,
        the gate should FAIL because FIXTURE != real provider.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            generate_fixture_artifacts(run_dir, "20260201_120000")

            captured = io.StringIO()
            with patch('sys.stdout', captured):
                with patch('sys.argv', ['ci_m5_0_gate.py', '--run-dir', str(run_dir), '--require-real']):
                    result = main()

            output = captured.getvalue()

            # Should FAIL
            self.assertNotEqual(result, 0, f"Expected FAIL, got PASS")
            # Should mention FAIL for provider
            self.assertIn("FAIL:", output)


if __name__ == "__main__":
    unittest.main()
