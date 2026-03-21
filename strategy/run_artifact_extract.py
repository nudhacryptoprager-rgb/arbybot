"""
strategy/run_artifact_extract.py - Artifact extraction helpers for run directories.

Extracted from start.py (R33) to separate artifact I/O from orchestration.
Functions read scan artifacts (run_summary, gate_result, scan_stats, truth_report)
from a runDir's reports/ folder.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


CI_M5_DIR_RE = re.compile(r"^ci_m5_gate_(?:[a-z_]+_)?\d{8}_\d{6}(?:_\d+)?$")


def extract_run_summary(run_dir: Path | None) -> dict[str, Any] | None:
    """Read the latest run_summary from a runDir."""
    if run_dir is None or not run_dir.exists():
        return None
    reports = run_dir / "reports"
    if not reports.exists():
        return None
    summaries = sorted(reports.glob("run_summary_*.json"))
    if not summaries:
        return None
    try:
        with open(summaries[-1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def extract_gate_result(run_dir: Path | None) -> dict[str, Any] | None:
    """Read gate_result.json from a runDir."""
    if run_dir is None or not run_dir.exists():
        return None
    path = run_dir / "reports" / "gate_result.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def extract_scan_stats(run_dir: Path | None) -> dict[str, Any] | None:
    """Read the latest scan_*.json and return its stats sub-dict.

    The scan JSON contains ``stats.discovery_runtime`` which is not present in
    run_summary.  Used by ``update_chain_stats`` to populate discovery_coverage.
    """
    if run_dir is None or not run_dir.exists():
        return None
    reports = run_dir / "reports"
    if not reports.exists():
        return None
    scans = sorted(reports.glob("scan_*.json"))
    if not scans:
        return None
    try:
        with open(scans[-1], encoding="utf-8") as f:
            data = json.load(f)
        return data.get("stats")
    except Exception:
        return None


def extract_truth_report(run_dir: Path | None) -> dict[str, Any] | None:
    """Read the latest truth_report from a runDir."""
    if run_dir is None or not run_dir.exists():
        return None
    reports = run_dir / "reports"
    if not reports.exists():
        return None
    truths = sorted(reports.glob("truth_report_*.json"))
    if not truths:
        return None
    try:
        with open(truths[-1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def validate_chain_id_match(run_dir: Path, expected_chain_id: int, chain_name: str) -> None:
    """Warn if any scan artifact in run_dir has a chain_id mismatch.

    This catches runDir collision bugs where two chains write into the same directory.
    """
    reports = run_dir / "reports"
    if not reports.exists():
        return
    for scan_file in reports.glob("scan_*.json"):
        try:
            with open(scan_file, encoding="utf-8") as f:
                data = json.load(f)
            actual = data.get("chain_id")
            if actual is not None and actual != expected_chain_id:
                print(
                    f"[CHAIN_MISMATCH] {run_dir.name}: expected chain_id={expected_chain_id} "
                    f"({chain_name}) but scan artifact has chain_id={actual}"
                )
        except Exception:
            pass


def delete_if_empty_run_dir(run_dir: Path) -> bool:
    """Delete a runDir if it has no reports/ subdirectory."""
    try:
        if run_dir.name and CI_M5_DIR_RE.match(run_dir.name):
            reports = run_dir / "reports"
            if not reports.exists():
                shutil.rmtree(run_dir)
                return True
    except Exception:
        return False
    return False


def prune_run_dirs(keep: int) -> None:
    """Prune old run directories, keeping the most recent `keep`."""
    subprocess.run(
        [sys.executable, "scripts/prune_run_dirs.py", "--keep", str(keep), "--yes"],
        check=False,
    )
