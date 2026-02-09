"""
M4 Discovery Module

Artifact discovery and run directory location for M4 gate.

Functions:
- find_latest_run_dir(): Find the most recent run directory
- discover_m4_artifacts(): Discover M4 execution artifacts in a run directory

Usage:
    from m4.discovery import find_latest_run_dir, discover_m4_artifacts
    
    run_dir = find_latest_run_dir(require_truth_report=True)
    artifacts = discover_m4_artifacts(run_dir)
"""

from pathlib import Path
from typing import Dict, Optional

# Repository root - assumes this file is at m4/discovery.py
REPO_ROOT = Path(__file__).resolve().parent.parent


def find_latest_run_dir(require_truth_report: bool = False) -> Optional[Path]:
    """
    Find the most recent run directory.
    
    Scans data/runs/ for directories sorted by modification time.
    
    Args:
        require_truth_report: If True, only return run with truth_report
        
    Returns:
        Path to latest run directory, or None if not found
    """
    runs_dir = REPO_ROOT / "data" / "runs"
    if not runs_dir.exists():
        return None
    
    run_dirs = sorted(
        [d for d in runs_dir.iterdir() if d.is_dir()],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    
    if not require_truth_report:
        return run_dirs[0] if run_dirs else None
    
    # Find first run with truth_report
    for run_dir in run_dirs:
        reports_dir = run_dir / "reports"
        if reports_dir.exists():
            truth_files = list(reports_dir.glob("truth_report_*.json"))
            if truth_files:
                return run_dir
    
    return None


def discover_m4_artifacts(run_dir: Path) -> Dict[str, Optional[Path]]:
    """
    Discover M4 execution artifacts in a run directory.
    
    Looks for the latest (by filename) of each artifact type in reports/
    
    Args:
        run_dir: Path to run directory
        
    Returns:
        Dict with keys:
            - signals: Path to signals_*.json or None
            - execution_report: Path to execution_report_*.json or None
            - truth_report: Path to truth_report_*.json or None (fallback for signals)
    """
    reports_dir = run_dir / "reports"
    
    artifacts: Dict[str, Optional[Path]] = {
        "signals": None,
        "execution_report": None,
        "truth_report": None,  # May use M5 truth_report for signals
    }
    
    if not reports_dir.exists():
        return artifacts
    
    # Find execution_report (latest by filename)
    exec_files = list(reports_dir.glob("execution_report_*.json"))
    if exec_files:
        artifacts["execution_report"] = sorted(exec_files, key=lambda x: x.name, reverse=True)[0]
    
    # Find signals (latest by filename)
    sig_files = list(reports_dir.glob("signals_*.json"))
    if sig_files:
        artifacts["signals"] = sorted(sig_files, key=lambda x: x.name, reverse=True)[0]
    
    # Find truth_report (fallback for signals)
    truth_files = list(reports_dir.glob("truth_report_*.json"))
    if truth_files:
        artifacts["truth_report"] = sorted(truth_files, key=lambda x: x.name, reverse=True)[0]
    
    return artifacts
