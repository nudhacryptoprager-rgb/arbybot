"""Tests for M8 sniper entrypoint contracts.

Verifies:
1. m8.runtime.smoke_run is importable and exports main().
2. m8.runtime.smoke_run has a __main__ guard (can be run with python -m).
3. scripts/sniper_smoke_run.py exists and calls sys.exit(main()).
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os


class TestM8SmokeRunEntrypoint:
    def test_smoke_run_importable(self):
        mod = importlib.import_module("m8.runtime.smoke_run")
        assert mod is not None

    def test_smoke_run_has_main_callable(self):
        from m8.runtime import smoke_run
        assert callable(getattr(smoke_run, "main", None)), (
            "m8.runtime.smoke_run must export a callable main()"
        )

    def test_smoke_run_has_dunder_main_guard(self):
        """Verify the module contains `if __name__ == '__main__':` block."""
        import m8.runtime.smoke_run as _mod
        src_path = inspect.getfile(_mod)
        with open(src_path, "r", encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source)
        found = any(
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            for node in ast.walk(tree)
        )
        assert found, (
            "m8/runtime/smoke_run.py missing `if __name__ == '__main__':` block"
        )

    def test_sniper_smoke_run_script_exists(self):
        """Canonical script entry must exist in scripts/."""
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        script_path = os.path.join(repo_root, "scripts", "sniper_smoke_run.py")
        assert os.path.isfile(script_path), (
            "scripts/sniper_smoke_run.py not found — canonical entry missing"
        )

    def test_sniper_smoke_run_calls_sys_exit_main(self):
        """scripts/sniper_smoke_run.py must call sys.exit(main())."""
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        script_path = os.path.join(repo_root, "scripts", "sniper_smoke_run.py")
        with open(script_path, "r", encoding="utf-8") as fh:
            source = fh.read()
        assert "sys.exit" in source, (
            "scripts/sniper_smoke_run.py must call sys.exit() for proper exit-code propagation"
        )
        assert "main()" in source, (
            "scripts/sniper_smoke_run.py must call main() from m8.runtime.smoke_run"
        )
