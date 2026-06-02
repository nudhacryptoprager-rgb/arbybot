"""Tests for M9 active manifest and audit script."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config" / "m9_active_manifest.yaml"


def test_manifest_loads_and_lists_primary():
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema_version"] == "m9_active_manifest.1"
    assert data["primary_config"] == "config/exotic_base_anchor.yaml"
    paths = {e["path"] for e in data["active_configs"]}
    assert "config/adapter_metadata.yaml" in paths


def test_audit_script_runs():
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_m9_active_config.py"),
            "--json",
            "data/tmp/m9_config_audit_test.json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    out = ROOT / "data/tmp/m9_config_audit_test.json"
    assert out.exists()
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["active_missing"] == 0


def test_exotic_dex_productivity_block():
    exotic = yaml.safe_load(
        (ROOT / "config/exotic_base_anchor.yaml").read_text(encoding="utf-8")
    )
    prod = exotic.get("m9_dex_productivity") or {}
    assert prod["balancer_vault"]["enabled_for_productive"] is False
    assert prod["curve_stable"]["enabled_for_productive"] is True
