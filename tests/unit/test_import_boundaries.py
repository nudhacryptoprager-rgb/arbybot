"""Import-boundary enforcement tests (clean-architecture direction).

Locks the contract: core / state / application must not import scripts,
milestone packages (m8/m8_1/m9), or the dashboard.  Includes regression
proof that the ProviderRouter dependency inversion holds (core no longer
imports from m9).
"""
from __future__ import annotations

from pathlib import Path

import scripts.audit_layer_responsibility as audit

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_current_tree_has_no_import_boundary_violations():
    violations = audit.check_import_boundaries(REPO_ROOT)
    assert violations == [], f"import boundary violations: {violations}"


def test_core_does_not_import_milestone_packages():
    """Regression: core/provider_router* must not import from m9."""
    import re

    pattern = re.compile(r"^\s*(?:from|import)\s+(m8|m8_1|m9)(\.|\s|$)")
    offenders = []
    for path in (REPO_ROOT / "core").glob("*.py"):
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if pattern.match(line):
                offenders.append(f"{path.name}:{lineno}:{line.strip()}")
    assert offenders == [], f"core importing milestone packages: {offenders}"


def test_provider_router_inversion_shim_works():
    """m9 shim re-exports the core implementation (thin wrapper pattern)."""
    from core.provider_router_impl import ProviderRouter as CoreRouter
    from core.provider_router import ProviderRouter as CoreAlias
    from m9.graph_arb.provider_router import ProviderRouter as M9Router

    assert CoreRouter is CoreAlias
    assert M9Router is CoreRouter


def test_boundary_checker_detects_synthetic_violation(tmp_path):
    pkg = tmp_path / "application"
    pkg.mkdir()
    (pkg / "bad.py").write_text("from m9.graph_arb import runner\n", encoding="utf-8")
    violations = audit.check_import_boundaries(tmp_path)
    assert any(v["rule_id"] == "APPLICATION_FORBIDDEN_IMPORT" for v in violations)


def test_boundary_checker_allows_clean_package(tmp_path):
    pkg = tmp_path / "state"
    pkg.mkdir()
    (pkg / "ok.py").write_text(
        "import json\nfrom core.json_io import atomic_write_json\n", encoding="utf-8"
    )
    violations = audit.check_import_boundaries(tmp_path)
    assert violations == []
