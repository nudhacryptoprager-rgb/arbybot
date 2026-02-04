#!/usr/bin/env python3
# PATH: scripts/ci_m5_0_gate.py
"""
M5_0 CI Gate v2.1.0.

CANONICAL COMMANDS:
  python scripts/ci_m5_0_gate.py --offline
  python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml

MODES (MUTUALLY EXCLUSIVE):
  --offline   ALWAYS works, IGNORES ALL ENV
  --online    Runs real scan, IGNORES ARBY_RUN_DIR

ENV VARIABLES (for --online and ADVANCED modes):
  ARBY_CONFIG       Override --config
  ARBY_CYCLES       Override --cycles
  ARBY_OUTPUT_ROOT  Override --output-root
  ARBY_RUN_DIR      [ADVANCED only] Explicit run directory
  ARBY_REQUIRE_REAL Require real (non-fixture) artifacts

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

__version__ = "2.1.0"

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
        # Top-level metrics
        "quotes_total": 4,
        "quotes_fetched": 4,
        "dexes_active": 2,
        "price_sanity_passed": 3,
        "price_sanity_failed": 1,
        # Nested stats
        "stats": {
            "quotes_total": 4, "quotes_fetched": 4, "gates_passed": 3,
            "dexes_active": 2, "price_sanity_passed": 3, "price_sanity_failed": 1,
        },
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
        # Top-level metrics
        "quotes_total": 4,
        "quotes_fetched": 4,
        "dexes_active": 2,
        "price_sanity_passed": 3,
        "price_sanity_failed": 1,
        # Nested health
        "health": {
            "quotes_total": 4, "quotes_fetched": 4, "gates_passed": 3,
            "dexes_active": 2, "price_sanity_passed": 3, "price_sanity_failed": 1,
            "rpc_success_rate": 1.0,
        },
    }
    truth_path = reports_dir / f"truth_report_{timestamp}.json"
    with open(truth_path, "w") as f:
        json.dump(truth_data, f, indent=2)
    artifacts["truth_report"] = truth_path
    
    reject_data = {
        "schema_version": "3.2.0",
        "timestamp": now,
        "run_mode": "FIXTURE_OFFLINE",
        "rejects": [{
            "pair": "WETH/USDC", "dex_id": "sushiswap_v3",
            "deviation_bps": 10000, "deviation_bps_capped": False,
            "inversion_applied": False, "suspect_quote": True,
        }],
        "total_rejects": 1,
    }
    reject_path = reports_dir / f"reject_histogram_{timestamp}.json"
    with open(reject_path, "w") as f:
        json.dump(reject_data, f, indent=2)
    artifacts["reject_histogram"] = reject_path
    
    return artifacts


def discover_artifacts(run_dir: Path) -> Dict[str, Optional[Path]]:
    """
    Discover artifacts in run directory.
    
    Looks in:
    1. reports/ (PRIMARY - ci_m5_0_gate.py standard)
    2. snapshots/ (FALLBACK - legacy location)
    """
    artifacts = {"scan": None, "truth_report": None, "reject_histogram": None}
    
    # Try reports/ first (PRIMARY)
    reports_dir = run_dir / "reports"
    if reports_dir.exists():
        for f in reports_dir.glob("*.json"):
            name = f.name
            if name.startswith("scan_") and artifacts["scan"] is None:
                artifacts["scan"] = f
            elif name.startswith("truth_report_") and artifacts["truth_report"] is None:
                artifacts["truth_report"] = f
            elif name.startswith("reject_histogram_") and artifacts["reject_histogram"] is None:
                artifacts["reject_histogram"] = f
    
    # Fallback to snapshots/ for scan only
    if artifacts["scan"] is None:
        snapshots_dir = run_dir / "snapshots"
        if snapshots_dir.exists():
            for f in snapshots_dir.glob("scan_*.json"):
                artifacts["scan"] = f
                break
    
    return artifacts


def get_run_dir_candidates(output_root: Path = DEFAULT_OUTPUT_ROOT) -> List[Path]:
    """Get run directories sorted by recency."""
    if not output_root.exists():
        return []
    
    candidates = []
    for d in output_root.iterdir():
        if d.is_dir():
            # Check both reports/ and snapshots/
            has_reports = (d / "reports").exists() and list((d / "reports").glob("*.json"))
            has_snapshots = (d / "snapshots").exists() and list((d / "snapshots").glob("*.json"))
            if has_reports or has_snapshots:
                all_files = list((d / "reports").glob("*.json")) if has_reports else []
                all_files += list((d / "snapshots").glob("*.json")) if has_snapshots else []
                if all_files:
                    mtime = max(f.stat().st_mtime for f in all_files)
                    candidates.append((d, mtime))
    
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [c[0] for c in candidates]


def validate_schema_version(data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate schema_version exists and is valid."""
    version = data.get("schema_version")
    if not version:
        return False, "Missing schema_version"
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        return False, f"Invalid schema_version: {version}"
    return True, f"schema_version={version}"


def validate_health_metrics(data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate health metrics exist and are reasonable."""
    # Check both top-level and nested health
    health = data.get("health", {})
    stats = data.get("stats", {})
    
    quotes_total = data.get("quotes_total") or health.get("quotes_total") or stats.get("quotes_total", 0)
    dexes_active = data.get("dexes_active") or health.get("dexes_active") or stats.get("dexes_active", 0)
    
    if quotes_total < 1:
        return False, f"quotes_total={quotes_total} < 1"
    if dexes_active < 1:
        return False, f"dexes_active={dexes_active} < 1"
    
    return True, f"quotes_total={quotes_total}, dexes_active={dexes_active}"


def validate_artifacts(artifacts: Dict[str, Optional[Path]], require_real: bool = False) -> Tuple[bool, List[str]]:
    """Validate all artifacts."""
    messages = []
    all_passed = True
    
    # Check all artifacts exist
    for name, path in artifacts.items():
        if path is None:
            messages.append(f"FAIL: {name} missing")
            all_passed = False
            continue
        messages.append(f"OK: {name} found")
    
    if not all_passed:
        return False, messages
    
    # Validate each artifact
    for name, path in artifacts.items():
        try:
            with open(path) as f:
                data = json.load(f)
            
            # Validate schema_version (required for all)
            ok, msg = validate_schema_version(data)
            messages.append(f"{'OK' if ok else 'FAIL'}: {name} - {msg}")
            if not ok:
                all_passed = False
            
            # Check run_mode
            run_mode = data.get("run_mode", "")
            if require_real and "FIXTURE" in run_mode:
                messages.append(f"FAIL: {name} - fixture rejected (require_real=True)")
                all_passed = False
            else:
                messages.append(f"OK: {name} - run_mode={run_mode}")
            
            # Validate health metrics for truth_report
            if name == "truth_report":
                ok, msg = validate_health_metrics(data)
                messages.append(f"{'OK' if ok else 'FAIL'}: {name} - {msg}")
                if not ok:
                    all_passed = False
                # If requiring real artifacts, ensure current_block is not a sentinel
                if require_real:
                    try:
                        from core.constants import FAKE_BLOCK_SENTINELS
                        cb = data.get("current_block") or data.get("stats", {}).get("current_block")
                        if cb in FAKE_BLOCK_SENTINELS:
                            messages.append(f"FAIL: {name} - current_block is sentinel ({cb})")
                            all_passed = False
                        else:
                            messages.append(f"OK: {name} - current_block={cb}")
                    except Exception:
                        messages.append(f"WARN: {name} - could not validate current_block")
            # Additional check: validate reject histogram cap semantics
            if name == "reject_histogram":
                try:
                    rejects = data.get("rejects", [])
                    for r in rejects:
                        raw = r.get("deviation_bps_raw")
                        maxd = r.get("max_deviation_bps")
                        capped = r.get("deviation_bps_capped")
                        if raw is not None and maxd is not None:
                            try:
                                if int(raw) > int(maxd) and not bool(capped):
                                    messages.append(f"FAIL: {name} - reject {r.get('pair')} raw({raw})>max({maxd}) but capped=false")
                                    all_passed = False
                            except Exception:
                                messages.append(f"WARN: {name} - could not evaluate cap for reject {r}")
                except Exception:
                    messages.append(f"WARN: {name} - could not validate reject_histogram semantics")
                    
        except json.JSONDecodeError as e:
            messages.append(f"FAIL: {name} - invalid JSON: {e}")
            all_passed = False
        except Exception as e:
            messages.append(f"FAIL: {name} - {e}")
            all_passed = False
    
    return all_passed, messages


def run_real_scan(output_dir: Path, config: str, cycles: int = 1) -> Tuple[bool, str]:
    """Run real scan via strategy.jobs.run_scan_real."""
    cmd = [
        sys.executable, "-m", "strategy.jobs.run_scan_real",
        "--cycles", str(cycles),
        "--output-dir", str(output_dir),
    ]
    if config:
        cmd.extend(["--config", config])
    
    print(f"\n[ONLINE] Running: {' '.join(cmd)}")
    print("-" * 60)
    
    try:
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=300)
        if result.returncode == 0:
            return True, "Scan completed successfully"
        else:
            return False, f"Exit code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Timeout (300s)"
    except FileNotFoundError:
        return False, "Module strategy.jobs.run_scan_real not found"
    except Exception as e:
        return False, str(e)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"M5_0 CI Gate v{__version__}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CANONICAL COMMANDS:
  python scripts/ci_m5_0_gate.py --offline
  python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml

ENV VARIABLES:
  ARBY_CONFIG       Override --config (--online/ADVANCED)
  ARBY_CYCLES       Override --cycles (--online/ADVANCED)
  ARBY_OUTPUT_ROOT  Override --output-root
  ARBY_RUN_DIR      Explicit run directory (ADVANCED only)
  ARBY_REQUIRE_REAL Require real artifacts (set to "1")
        """
    )
    
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--offline", action="store_true",
                            help="Offline mode (IGNORES ALL ENV)")
    mode_group.add_argument("--online", action="store_true",
                            help="Online mode (runs real scan)")
    
    parser.add_argument("--run-dir", type=Path,
                        help="[ADVANCED] Explicit run directory")
    parser.add_argument("--require-real", action="store_true",
                        help="Reject fixture artifacts")
    parser.add_argument("--list-candidates", action="store_true",
                        help="List available run directories")
    
    # With ENV fallbacks for --online/ADVANCED
    parser.add_argument("--config", type=str,
                        default=os.environ.get("ARBY_CONFIG", DEFAULT_CONFIG),
                        help=f"Config file (default: $ARBY_CONFIG or {DEFAULT_CONFIG})")
    parser.add_argument("--output-root", type=Path,
                        default=Path(os.environ.get("ARBY_OUTPUT_ROOT", str(DEFAULT_OUTPUT_ROOT))),
                        help=f"Output root (default: $ARBY_OUTPUT_ROOT or {DEFAULT_OUTPUT_ROOT})")
    parser.add_argument("--cycles", type=int,
                        default=int(os.environ.get("ARBY_CYCLES", "1")),
                        help="Scan cycles (default: $ARBY_CYCLES or 1)")
    
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    
    args = parser.parse_args()
    
    # Handle --list-candidates
    if args.list_candidates:
        candidates = get_run_dir_candidates(args.output_root)
        if candidates:
            print(f"Available run directories in {args.output_root}:")
            for i, d in enumerate(candidates[:10], 1):
                artifacts = discover_artifacts(d)
                count = sum(1 for v in artifacts.values() if v is not None)
                print(f"  {i}. {d.name} ({count}/3 artifacts)")
        else:
            print(f"No run directories found in {args.output_root}")
        return 0
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # =========================================================================
    # OFFLINE MODE
    # =========================================================================
    if args.offline:
        print(f"\n{'='*60}")
        print(f"M5_0 GATE v{__version__} - OFFLINE")
        print(f"{'='*60}")
        print("\n[OFFLINE] IGNORING ALL ENV VARIABLES")
        
        run_dir = args.output_root / f"ci_m5_0_gate_offline_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"[OFFLINE] Creating: {run_dir}")
        
        artifacts_paths = generate_fixture_artifacts(run_dir, timestamp)
        artifacts = discover_artifacts(run_dir)
        
        print(f"\n[OFFLINE] Generated {len(artifacts_paths)} artifacts:")
        for name, path in artifacts_paths.items():
            print(f"  - {name}: {path.name}")
        
        print(f"\n{'='*60}")
        print("VALIDATION")
        print(f"{'='*60}\n")
        
        passed, messages = validate_artifacts(artifacts, require_real=False)
        for msg in messages:
            print(f"  {msg}")
        
        print(f"\n{'='*60}")
        print(f"RESULT: {'PASS' if passed else 'FAIL'}")
        print(f"RunDir: {run_dir}")
        return 0 if passed else 1
    
    # =========================================================================
    # ONLINE MODE
    # =========================================================================
    if args.online:
        print(f"\n{'='*60}")
        print(f"M5_0 GATE v{__version__} - ONLINE")
        print(f"{'='*60}")
        print("\n[ONLINE] IGNORING ARBY_RUN_DIR (creating new run directory)")
        
        run_dir = args.output_root / f"ci_m5_0_gate_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"[ONLINE] RunDir: {run_dir}")
        print(f"[ONLINE] Config: {args.config}")
        print(f"[ONLINE] Cycles: {args.cycles}")
        
        success, message = run_real_scan(run_dir, args.config, args.cycles)
        
        print(f"\n[ONLINE] {message}")
        
        if not success:
            print(f"\n{'='*60}")
            print(f"RESULT: FAIL - Scanner error")
            return 3
        
        artifacts = discover_artifacts(run_dir)
        missing = [name for name, path in artifacts.items() if path is None]
        if missing:
            print(f"\n{'='*60}")
            print(f"RESULT: FAIL - Missing artifacts: {missing}")
            return 2
        
        print(f"\n{'='*60}")
        print("VALIDATION")
        print(f"{'='*60}\n")
        
        passed, messages = validate_artifacts(artifacts, require_real=True)
        for msg in messages:
            print(f"  {msg}")
        
        print(f"\n{'='*60}")
        print(f"RESULT: {'PASS' if passed else 'FAIL'}")
        print(f"RunDir: {run_dir}")
        return 0 if passed else 1
    
    # =========================================================================
    # ADVANCED MODE (uses ARBY_RUN_DIR or --run-dir)
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"M5_0 GATE v{__version__} - ADVANCED")
    print(f"{'='*60}")
    print("\nTIP: Use --offline or --online for standard workflows")
    
    run_dir = None
    if args.run_dir:
        run_dir = args.run_dir
        print(f"\n[ADVANCED] Using --run-dir: {run_dir}")
    elif os.environ.get("ARBY_RUN_DIR"):
        run_dir = Path(os.environ["ARBY_RUN_DIR"])
        print(f"\n[ADVANCED] Using ARBY_RUN_DIR: {run_dir}")
    else:
        candidates = get_run_dir_candidates(args.output_root)
        if candidates:
            run_dir = candidates[0]
            print(f"\n[ADVANCED] Using latest: {run_dir}")
        else:
            print(f"\nERROR: No run directory found")
            print(f"Use --offline to create fixtures or --online to run real scan")
            return 2
    
    if not run_dir.exists():
        print(f"\nERROR: Run directory not found: {run_dir}")
        return 2
    
    require_real = args.require_real or os.environ.get("ARBY_REQUIRE_REAL") == "1"
    
    artifacts = discover_artifacts(run_dir)
    missing = [name for name, path in artifacts.items() if path is None]
    if missing:
        print(f"\nERROR: Missing artifacts: {missing}")
        return 2
    
    print(f"\n{'='*60}")
    print("VALIDATION")
    print(f"{'='*60}\n")
    
    passed, messages = validate_artifacts(artifacts, require_real=require_real)
    for msg in messages:
        print(f"  {msg}")
    
    print(f"\n{'='*60}")
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    print(f"RunDir: {run_dir}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
