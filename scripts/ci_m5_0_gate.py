#!/usr/bin/env python3
# PATH: scripts/ci_m5_0_gate.py
"""
M5_0 CI Gate v2.0.0.

CANONICAL COMMANDS:
  python scripts/ci_m5_0_gate.py --offline
  python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml

MODES (MUTUALLY EXCLUSIVE):
  --offline   ALWAYS works, IGNORES ALL ENV
  --online    Runs real scan, IGNORES ARBY_RUN_DIR

EXIT CODES: 0=PASS, 1=FAIL validation, 2=FAIL missing, 3=FAIL scanner
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__version__ = "2.0.0"

DEFAULT_OUTPUT_ROOT = Path("data/runs")
DEFAULT_CONFIG = "config/real_minimal.yaml"


def generate_fixture_artifacts(output_dir: Path, timestamp: str) -> Dict[str, Path]:
    """Generate fixture artifacts for --offline."""
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    artifacts = {}
    now = datetime.now(timezone.utc).isoformat()
    
    scan_data = {
        "schema_version": "3.2.0",
        "timestamp": now,
        "run_mode": "FIXTURE_OFFLINE",
        "chain_id": 42161,
        "stats": {"quotes_total": 4, "quotes_fetched": 4, "dexes_active": 2,
                  "price_sanity_passed": 3, "price_sanity_failed": 1},
    }
    scan_path = reports_dir / f"scan_{timestamp}.json"
    with open(scan_path, "w") as f:
        json.dump(scan_data, f, indent=2)
    artifacts["scan"] = scan_path
    
    truth_data = {
        "schema_version": "3.2.0",
        "timestamp": now,
        "run_mode": "FIXTURE_OFFLINE",
        "execution_enabled": False,
        "execution_blocker": "EXECUTION_DISABLED",
        "health": {"quotes_total": 4, "quotes_fetched": 4, "dexes_active": 2,
                   "price_sanity_passed": 3, "price_sanity_failed": 1,
                   "rpc_success_rate": 1.0},
    }
    truth_path = reports_dir / f"truth_report_{timestamp}.json"
    with open(truth_path, "w") as f:
        json.dump(truth_data, f, indent=2)
    artifacts["truth_report"] = truth_path
    
    reject_data = {
        "schema_version": "3.2.0",
        "timestamp": now,
        "run_mode": "FIXTURE_OFFLINE",
        "rejects": [{"pair": "WETH/USDC", "deviation_bps": 9966, "inversion_applied": False}],
    }
    reject_path = reports_dir / f"reject_histogram_{timestamp}.json"
    with open(reject_path, "w") as f:
        json.dump(reject_data, f, indent=2)
    artifacts["reject_histogram"] = reject_path
    
    return artifacts


def discover_artifacts(run_dir: Path) -> Dict[str, Optional[Path]]:
    """Discover artifacts in run directory."""
    reports_dir = run_dir / "reports"
    artifacts = {"scan": None, "truth_report": None, "reject_histogram": None}
    
    if not reports_dir.exists():
        return artifacts
    
    for f in reports_dir.glob("*.json"):
        name = f.name
        if name.startswith("scan_"):
            artifacts["scan"] = f
        elif name.startswith("truth_report_"):
            artifacts["truth_report"] = f
        elif name.startswith("reject_histogram_"):
            artifacts["reject_histogram"] = f
    
    return artifacts


def get_run_dir_candidates(output_root: Path = DEFAULT_OUTPUT_ROOT) -> List[Path]:
    """Get run directories sorted by recency."""
    if not output_root.exists():
        return []
    
    candidates = []
    for d in output_root.iterdir():
        if d.is_dir() and (d / "reports").exists():
            reports = list((d / "reports").glob("*.json"))
            if reports:
                mtime = max(f.stat().st_mtime for f in reports)
                candidates.append((d, mtime))
    
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [c[0] for c in candidates]


def validate_schema_version(data: Dict[str, Any]) -> Tuple[bool, str]:
    version = data.get("schema_version")
    if not version or not re.match(r"^\d+\.\d+\.\d+$", version):
        return False, f"Invalid schema_version: {version}"
    return True, f"schema_version={version}"


def validate_health_metrics(data: Dict[str, Any]) -> Tuple[bool, str]:
    health = data.get("health", data.get("stats", {}))
    if health.get("quotes_total", 0) < 1 or health.get("dexes_active", 0) < 1:
        return False, "health metrics too low"
    return True, "health OK"


def validate_artifacts(artifacts: Dict[str, Optional[Path]], require_real: bool = False) -> Tuple[bool, List[str]]:
    """Validate all artifacts."""
    messages = []
    all_passed = True
    
    for name, path in artifacts.items():
        if path is None:
            messages.append(f"FAIL: {name} missing")
            all_passed = False
            continue
        
        try:
            with open(path) as f:
                data = json.load(f)
            
            ok, msg = validate_schema_version(data)
            messages.append(f"{'OK' if ok else 'FAIL'}: {name} - {msg}")
            if not ok:
                all_passed = False
            
            run_mode = data.get("run_mode", "")
            if require_real and "FIXTURE" in run_mode:
                messages.append(f"FAIL: {name} - fixture rejected")
                all_passed = False
            
            if name == "truth_report":
                ok, msg = validate_health_metrics(data)
                messages.append(f"{'OK' if ok else 'FAIL'}: {name} - {msg}")
                if not ok:
                    all_passed = False
                    
        except Exception as e:
            messages.append(f"FAIL: {name} - {e}")
            all_passed = False
    
    return all_passed, messages


def run_real_scan(output_dir: Path, config: str, cycles: int = 1) -> Tuple[bool, str]:
    """Run real scan."""
    cmd = [sys.executable, "-m", "strategy.jobs.run_scan_real",
           "--cycles", str(cycles), "--output-dir", str(output_dir)]
    if config:
        cmd.extend(["--config", config])
    
    try:
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=300)
        return result.returncode == 0, f"Exit code {result.returncode}"
    except Exception as e:
        return False, str(e)


def main() -> int:
    parser = argparse.ArgumentParser(description="M5_0 CI Gate v2.0.0")
    
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--offline", action="store_true", help="Offline mode (IGNORES ALL ENV)")
    mode_group.add_argument("--online", action="store_true", help="Online mode")
    
    parser.add_argument("--run-dir", type=Path, help="[ADVANCED] Explicit run directory")
    parser.add_argument("--require-real", action="store_true", help="Reject fixture artifacts")
    parser.add_argument("--config", type=str, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    
    args = parser.parse_args()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # OFFLINE MODE
    if args.offline:
        print(f"\n{'='*60}")
        print(f"M5_0 GATE v{__version__} - OFFLINE")
        print(f"{'='*60}")
        
        run_dir = args.output_root / f"ci_m5_0_gate_offline_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        
        artifacts_paths = generate_fixture_artifacts(run_dir, timestamp)
        artifacts = discover_artifacts(run_dir)
        
        print(f"\n[OFFLINE] Generated: {len(artifacts_paths)} artifacts")
        
        passed, messages = validate_artifacts(artifacts, require_real=False)
        for msg in messages:
            print(f"  {msg}")
        
        print(f"\nRESULT: {'PASS' if passed else 'FAIL'}")
        return 0 if passed else 1
    
    # ONLINE MODE
    if args.online:
        print(f"\n{'='*60}")
        print(f"M5_0 GATE v{__version__} - ONLINE")
        print(f"{'='*60}")
        
        run_dir = args.output_root / f"ci_m5_0_gate_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        
        success, message = run_real_scan(run_dir, args.config, args.cycles)
        if not success:
            print(f"\nRESULT: FAIL - {message}")
            return 3
        
        artifacts = discover_artifacts(run_dir)
        passed, messages = validate_artifacts(artifacts, require_real=True)
        for msg in messages:
            print(f"  {msg}")
        
        print(f"\nRESULT: {'PASS' if passed else 'FAIL'}")
        return 0 if passed else 1
    
    # ADVANCED MODE
    print(f"\nM5_0 GATE v{__version__} - ADVANCED")
    print("TIP: Use --offline or --online instead")
    
    run_dir = args.run_dir or (Path(os.environ.get("ARBY_RUN_DIR", "")) if os.environ.get("ARBY_RUN_DIR") else None)
    
    if not run_dir:
        candidates = get_run_dir_candidates(args.output_root)
        run_dir = candidates[0] if candidates else None
    
    if not run_dir or not run_dir.exists():
        print("\nERROR: No run directory. Use --offline or --online")
        return 2
    
    require_real = args.require_real or os.environ.get("ARBY_REQUIRE_REAL") == "1"
    
    artifacts = discover_artifacts(run_dir)
    passed, messages = validate_artifacts(artifacts, require_real=require_real)
    for msg in messages:
        print(f"  {msg}")
    
    print(f"\nRESULT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
