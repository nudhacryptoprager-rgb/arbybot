# PATH: tests/unit/test_packaging_contract.py
"""Packaging contract smoke tests.

Locks the contract that all active top-level runtime packages are:
  1. declared in ``pyproject.toml`` under ``[tool.setuptools.packages.find].include``;
  2. importable from a clean process (no heavy import-time side effects);
  3. shipped inside the built wheel.

This guards against silent packaging drift (a new package added to the repo
but forgotten in ``pyproject.toml`` -> a wheel that ships fine in editable
mode but is incomplete when installed).

Offline + deterministic: no RPC, no network, no ``.env``.
"""
from __future__ import annotations

import fnmatch
import importlib
import os
import sys
import tempfile
import zipfile

import pytest

try:
    import tomllib  # Python 3.11+ stdlib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


# ---------------------------------------------------------------------------
# Canonical active top-level runtime roots that MUST ship in the wheel.
# Keep in sync with [tool.setuptools.packages.find].include in pyproject.toml.
#
# Discovering subpackages dynamically from the filesystem (see
# ``_discover_repo_packages``) guarantees the wheel closure matches reality,
# so a new subpackage added to the repo but forgotten in ``pyproject.toml``
# fails CI instead of silently shipping an incomplete wheel.
# ---------------------------------------------------------------------------
REQUIRED_RUNTIME_ROOTS = [
    "core",
    "strategy",
    "monitoring",
    "execution",
    "engine",
    "dex",
    "cex",
    "chains",
    "discovery",
    "m4",
    "m7",
    "m8",
    "m8_1",
    "m9",
]

# Backwards-compatible alias for the public contract surface used by other
# tests / tooling that may import this constant.
REQUIRED_RUNTIME_PACKAGES = REQUIRED_RUNTIME_ROOTS

# ``scripts`` is intentionally NOT a wheel-included package: it lives in the
# repo as the operator/CI CLI entry ("repo-only execution model"). If you
# want the wheel to ship CLI modules, that decision must be made explicitly
# here and mirror the pyproject ``include`` list. See OPENCODE.md §2.

# Representative real source files per active sub-package. The wheel must
# ship the actual implementation file, not just an empty ``__init__.py``, so
# that ``importlib.import_module`` from an installed wheel keeps working for
# milestone-scoped adaptation layers. Add new representative entries as
# packages grow.
REPRESENTATIVE_SUBMODULES = [
    "chains/block.py",
    "discovery/index_factories.py",
    "m9/graph_arb/adapter_families.py",
    "m8/discovery/anchor_registry.py",
    # Codex Patch 2.1 additions
    "m7/orderflow/simulation.py",
    "m7/triangular/graph.py",
    "m7/shared/__init__.py",
    "strategy/jobs/run_scan_real.py",
    "dex/adapters/uniswap_v3.py",
    "cex/adapters/__init__.py",
    "execution/flash_loan/aave_adapter.py",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_pyproject() -> dict:
    if tomllib is None:
        pytest.skip("tomllib unavailable (requires Python 3.11 stdlib)")
    path = os.path.join(_REPO_ROOT, "pyproject.toml")
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _discover_repo_packages() -> list[str]:
    """Walk the repo and return every ``__init__.py``-bearing package path
    in dotted form, restricted to ``REQUIRED_RUNTIME_ROOTS``.

    This is the filesystem truth the wheel closure must match. It does NOT
    include ``scripts`` (repo-only CLI) or build/test caches.
    """
    packages: list[str] = []
    for root in REQUIRED_RUNTIME_ROOTS:
        root_path = os.path.join(_REPO_ROOT, *root.split("."))
        if not os.path.isdir(root_path):
            continue
        if os.path.isfile(os.path.join(root_path, "__init__.py")):
            packages.append(root)
        for dirpath, _dirnames, filenames in os.walk(root_path):
            if "__init__.py" not in filenames:
                continue
            rel = os.path.relpath(dirpath, _REPO_ROOT)
            dotted = rel.replace(os.sep, ".")
            if dotted == root or dotted.startswith(root + "."):
                if dotted not in packages:
                    packages.append(dotted)
    return sorted(packages)


def _pyproject_include_matches(include: list[str], package: str) -> bool:
    """Return True if ``package`` is matched by any fnmatch pattern in
    ``include`` (setuptools uses fnmatch-style globbing)."""
    return any(fnmatch.fnmatchcase(package, pat) for pat in include)


class TestPyprojectIncludesActivePackages:
    def test_include_contains_all_required_runtime_roots(self):
        cfg = _load_pyproject()
        include = cfg["tool"]["setuptools"]["packages"]["find"]["include"]
        missing = [p for p in REQUIRED_RUNTIME_ROOTS if p not in include]
        assert not missing, (
            "Active runtime roots missing from "
            "[tool.setuptools.packages.find].include in pyproject.toml: "
            f"{missing}"
        )

    def test_no_duplicate_include_entries(self):
        cfg = _load_pyproject()
        include = cfg["tool"]["setuptools"]["packages"]["find"]["include"]
        assert len(include) == len(set(include)), f"duplicate entries: {include}"

    def test_include_closure_matches_repo_packages(self):
        """Dynamic closure assertion (Codex Patch 2.1 step 2).

        Every ``__init__.py``-bearing package directory under an active runtime
        root must be matched by the pyproject ``include`` globbing set.
        """
        cfg = _load_pyproject()
        include = cfg["tool"]["setuptools"]["packages"]["find"]["include"]
        repo_packages = _discover_repo_packages()
        missing = [
            p for p in repo_packages if not _pyproject_include_matches(include, p)
        ]
        assert not missing, (
            "Repo-native packages not covered by "
            "[tool.setuptools.packages.find].include in pyproject.toml. "
            "Add a wildcard entry (e.g. ``pkg.*``) or the explicit dotted path: "
            f"{missing}"
        )


class TestEachActivePackageImportable:
    """Import every required package from a clean module table.

    Importing must not require RPC, network, or ``.env``. If a package gains
    heavy import-time side effects it should be fixed at source, not here.
    """

    @pytest.mark.parametrize("pkg", REQUIRED_RUNTIME_PACKAGES)
    def test_package_importable_offline(self, pkg, monkeypatch):
        monkeypatch.setenv("ARBY_OFFLINE", "1")
        monkeypatch.setenv("ARBY_SKIP_RPC", "1")
        # Drop any cached module so we exercise a fresh import.
        for name in list(sys.modules):
            if name == pkg or name.startswith(pkg + "."):
                monkeypatch.delitem(sys.modules, name, raising=False)
        mod = importlib.import_module(pkg)
        assert mod is not None and mod.__name__ == pkg


class TestWheelShipsAllActivePackages:
    """Build the wheel offline and assert every required package is shipped."""

    def test_wheel_contains_required_packages(self):
        # Wheel-smoke is mandatory in deterministic CI. It may only be
        # explicitly opted out via ARBY_ALLOW_WHEEL_SMOKE_SKIP=1 (forbidden in
        # normal CI). Default behavior when the build backend is unavailable
        # is a hard FAIL: the dev environment must declare the build backend
        # (see requirements-dev.txt / pyproject.toml [project.optional-dependencies].dev).
        try:
            from setuptools import build_meta as backend  # noqa: F401
        except Exception:
            if os.environ.get("ARBY_ALLOW_WHEEL_SMOKE_SKIP") == "1":
                pytest.skip(
                    "setuptools build backend unavailable and "
                    "ARBY_ALLOW_WHEEL_SMOKE_SKIP=1"
                )
            pytest.fail(
                "setuptools build backend is not importable. Wheel-smoke is "
                "mandatory in deterministic CI. Install dev deps: "
                "`pip install -e .[dev]` or `pip install -r requirements-dev.txt` "
                "(setuptools>=61.0, wheel>=0.40.0). To opt out explicitly set "
                "ARBY_ALLOW_WHEEL_SMOKE_SKIP=1.",
                pytrace=False,
            )

        cwd = os.getcwd()
        os.chdir(_REPO_ROOT)
        try:
            with tempfile.TemporaryDirectory(prefix="arby_wheel_") as wheel_dir:
                wheel_name = backend.build_wheel(wheel_dir)
                wheel_path = os.path.join(wheel_dir, wheel_name)
                assert os.path.isfile(wheel_path), f"wheel not found: {wheel_path}"
                with zipfile.ZipFile(wheel_path) as zf:
                    names = zf.namelist()
                # Closure check: every repo-native active package must ship its
                # __init__.py in the wheel (Codex Patch 2.1 step 3).
                repo_packages = _discover_repo_packages()
                missing = []
                for pkg in repo_packages:
                    init = pkg.replace(".", "/") + "/__init__.py"
                    if init not in names:
                        missing.append(pkg)
                assert not missing, (
                    f"Wheel {wheel_name} is missing __init__.py for "
                    f"active packages: {missing}"
                )
                # Representative submodule check: ensure the wheel actually
                # ships real code (not just empty __init__.py) for the
                # milestone packages that must be deployable
                # (Codex Patch 2.1 step 4).
                missing_sub = [s for s in REPRESENTATIVE_SUBMODULES if s not in names]
                assert not missing_sub, (
                    f"Wheel {wheel_name} is missing representative submodules: "
                    f"{missing_sub}"
                )
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))