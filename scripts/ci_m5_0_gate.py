#!/usr/bin/env python3
# PATH: scripts/ci_m5_0_gate.py
"""
M5_0 CI Gate v2.0.0 - Infrastructure Hardening validation.

TWO CANONICAL COMMANDS:
  python scripts/ci_m5_0_gate.py --offline
  python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml

MODES (MUTUALLY EXCLUSIVE):
  --offline   Create fixture, ALWAYS works, IGNORES ALL ENV
  --online    Run real scan, IGNORES ARBY_RUN_DIR

PRIORITY: CLI > ENV (always)

EXIT CODES:
  0 = PASS
  1 = FAIL (validation)
  2 = FAIL (artifacts missing)
  3 = FAIL (scanner error)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
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
    
    scan_data = {
        "schema_version": "3.2.0",
        "timestamp": datetime.utcnow().isoformat(),
        "run_mode": "FIXTURE_OFFLINE",
        "chain_id": 42161,
        "current_block": 999999999,
        "quotes": [{"pair": "WETH/USDC", "dex_id": "uniswap_v3", "fee": 500, "price": "2650.0"}],
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
        "timestamp": datetime.utcnow().isoformat(),
        "run_mode": "FIXTURE_OFFLINE",
        "execution_enabled": False,
        "execution_blocker": "EXECUTION_DISABLED",
        "cost_model_available": False,
        "chain_id": 42161,
        "current_block": 999999999,
        "health": {
            "quotes_total": 4, "quotes_fetched": 4, "gates_passed": 3,
            "dexes_active": 2, "price_sanity_passed": 3, "price_sanity_failed": 1,
            "price_stability_factor": 0.95, "rpc_errors": 0, "rpc_success_rate": 1.0,
        },
        "spread_signals": [],
        "stats": scan_data["stats"],
    }
    truth_path = reports_dir / f"truth_report_{timestamp}.json"
    with open(truth_path, "w") as f:
        json.dump(truth_data, f, indent=2)
    artifacts["truth_report"] = truth_path
    
    reject_data = {
        "schema_version": "3.2.0",
        "timestamp": datetime.utcnow().isoformat(),
        "run_mode": "FIXTURE_OFFLINE",
        "rejects": [{
            "pair": "WETH/USDC", "dex_id": "sushiswap_v3", "pool_fee": 3000,
            "implied_price": "8.605", "deviation_bps": 9966, "deviation_bps_raw": 9966,
            "deviation_bps_capped": False, "max_deviation_bps": 5000, "error": "deviation_exceeded",
            "inversion_applied": False, "suspect_quote": True, "suspect_reason": "way_below_expected",
        }],
        "total_rejects": 1,
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


def print_candidates(output_root: Path = DEFAULT_OUTPUT_ROOT) -> None:
    """Print available run directories."""
    candidates = get_run_dir_candidates(output_root)
    if not candidates:
        print(f"No run directories in {output_root}")
        return
    print(f"\nAvailable run directories:\n")
    for i, d in enumerate(candidates[:10], 1):
        artifacts = discover_artifacts(d)
        count = sum(1 for v in artifacts.values() if v is not None)
        print(f"  {i}. {d.name} ({count}/3)")


def validate_schema_version(data: Dict[str, Any]) -> Tuple[bool, str]:
    version = data.get("schema_version")
    if not version:
        return False, "Missing schema_version"
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        return False, f"Invalid: {version}"
    return True, f"schema_version={version}"


def validate_run_mode(data: Dict[str, Any]) -> Tuple[bool, str]:
    mode = data.get("run_mode")
    if not mode:
        return False, "Missing run_mode"
    return True, f"run_mode={mode}"


def validate_health_metrics(data: Dict[str, Any]) -> Tuple[bool, str]:
    health = data.get("health", data.get("stats", {}))
    required = ["quotes_total", "quotes_fetched", "dexes_active"]
    missing = [k for k in required if k not in health]
    if missing:
        return False, f"Missing: {missing}"
    if health.get("quotes_total", 0) < 1:
        return False, "quotes_total < 1"
    if health.get("quotes_fetched", 0) < 1:
        return False, "quotes_fetched < 1"
    if health.get("dexes_active", 0) < 1:
        return False, "dexes_active < 1"
    return True, f"health OK"


def validate_price_sanity_metrics(data: Dict[str, Any]) -> Tuple[bool, str]:
    health = data.get("health", data.get("stats", {}))
    passed = health.get("price_sanity_passed")
    failed = health.get("price_sanity_failed")
    if passed is None and failed is None:
        return False, "Missing price_sanity metrics"
    return True, f"price_sanity OK"


def validate_artifacts(artifacts: Dict[str, Optional[Path]], require_real: bool = False) -> Tuple[bool, List[str]]:
    """Validate all artifacts."""
    messages = []
    all_passed = True
    
    for name, path in artifacts.items():
        if path is None:
            messages.append(f"FAIL: {name} missing")
            all_passed = False
        else:
            messages.append(f"OK: {name}")
    
    if not all_passed:
        return False, messages
    
    for name, path in artifacts.items():
        try:
            with open(path) as f:
                data = json.load(f)
            
            ok, msg = validate_schema_version(data)
            if not ok:
                messages.append(f"FAIL: {name} - {msg}")
                all_passed = False
            else:
                messages.append(f"OK: {name} - {msg}")
            
            ok, msg = validate_run_mode(data)
            if not ok:
                messages.append(f"FAIL: {name} - {msg}")
                all_passed = False
            else:
                run_mode = data.get("run_mode", "")
                if require_real and "FIXTURE" in run_mode:
                    messages.append(f"FAIL: {name} - fixture rejected")
                    all_passed = False
                else:
                    messages.append(f"OK: {name} - {msg}")
            
            if name == "truth_report":
                ok, msg = validate_health_metrics(data)
                if not ok:
                    messages.append(f"FAIL: {name} - {msg}")
                    all_passed = False
                else:
                    messages.append(f"OK: {name} - {msg}")
                
                ok, msg = validate_price_sanity_metrics(data)
                if not ok:
                    messages.append(f"FAIL: {name} - {msg}")
                    all_passed = False
                else:
                    messages.append(f"OK: {name} - {msg}")
                    
        except json.JSONDecodeError:
            messages.append(f"FAIL: {name} - invalid JSON")
            all_passed = False
        except Exception as e:
            messages.append(f"FAIL: {name} - {e}")
            all_passed = False
    
    return all_passed, messages


def run_real_scan(output_dir: Path, config: str, cycles: int = 1) -> Tuple[bool, str]:
    """Run real scan."""
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
            return True, "Scan completed"
        else:
            return False, f"Exit code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Timeout (300s)"
    except FileNotFoundError:
        return False, "Module not found"
    except Exception as e:
        return False, f"Error: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="M5_0 CI Gate v2.0.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CANONICAL COMMANDS:
  python scripts/ci_m5_0_gate.py --offline
  python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml

ADVANCED (use --offline or --online instead):
  python scripts/ci_m5_0_gate.py --run-dir data/runs/real_xxx
        """
    )
    
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--offline", action="store_true",
        help="Offline mode: create fixture (IGNORES ALL ENV)")
    mode_group.add_argument("--online", action="store_true",
        help="Online mode: run real scan (IGNORES ARBY_RUN_DIR)")
    
    parser.add_argument("--run-dir", type=Path, help="[ADVANCED] Explicit run directory")
    parser.add_argument("--require-real", action="store_true", help="Reject fixture artifacts")
    parser.add_argument("--list-candidates", action="store_true", help="List run directories")
    
    parser.add_argument("--config", type=str, default=DEFAULT_CONFIG,
        help=f"Config for --online (default: {DEFAULT_CONFIG})")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT,
        help=f"Output root (default: {DEFAULT_OUTPUT_ROOT})")
    parser.add_argument("--cycles", type=int, default=1, help="Scan cycles for --online")
    
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    
    args = parser.parse_args()
    
    if args.list_candidates:
        print_candidates(args.output_root)
        return 0
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # =========================================================================
    # OFFLINE MODE (ignores ALL ENV)
    # =========================================================================
    if args.offline:
        print(f"\n{'='*60}")
        print(f"M5_0 GATE v{__version__} - OFFLINE")
        print(f"{'='*60}")
        print("\n[OFFLINE] IGNORING ALL ENV (ARBY_RUN_DIR, ARBY_REQUIRE_REAL)")
        
        run_dir = args.output_root / f"ci_m5_0_gate_offline_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"[OFFLINE] Creating: {run_dir}")
        
        artifacts_paths = generate_fixture_artifacts(run_dir, timestamp)
        artifacts = discover_artifacts(run_dir)
        
        print(f"\n[OFFLINE] Generated:")
        for name, path in artifacts_paths.items():
            print(f"  - {name}: {path.name}")
        
        print(f"\n{'='*60}")
        print("VALIDATION")
        print(f"{'='*60}\n")
        
        passed, messages = validate_artifacts(artifacts, require_real=False)
        for msg in messages:
            print(f"  {msg}")
        
        print(f"\n{'='*60}")
        if passed:
            print(f"RESULT: PASS")
            print(f"RunDir: {run_dir}")
            return 0
        else:
            print(f"RESULT: FAIL")
            return 1
    
    # =========================================================================
    # ONLINE MODE (ignores ARBY_RUN_DIR)
    # =========================================================================
    if args.online:
        print(f"\n{'='*60}")
        print(f"M5_0 GATE v{__version__} - ONLINE")
        print(f"{'='*60}")
        print("\n[ONLINE] IGNORING ARBY_RUN_DIR (creating new runDir)")
        
        run_dir = args.output_root / f"ci_m5_0_gate_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"[ONLINE] RunDir: {run_dir}")
        print(f"[ONLINE] Config: {args.config}")
        print(f"[ONLINE] Cycles: {args.cycles}")
        
        success, message = run_real_scan(run_dir, args.config, args.cycles)
        
        if not success:
            print(f"\n{'='*60}")
            print(f"RESULT: FAIL - {message}")
            return 3
        
        print(f"\n{'-'*60}")
        print(f"[ONLINE] {message}")
        
        artifacts = discover_artifacts(run_dir)
        missing = [name for name, path in artifacts.items() if path is None]
        if missing:
            print(f"\n{'='*60}")
            print(f"RESULT: FAIL - Missing: {missing}")
            return 2
        
        print(f"\n{'='*60}")
        print("VALIDATION")
        print(f"{'='*60}\n")
        
        passed, messages = validate_artifacts(artifacts, require_real=True)
        for msg in messages:
            print(f"  {msg}")
        
        print(f"\n{'='*60}")
        if passed:
            print(f"RESULT: PASS")
            print(f"RunDir: {run_dir}")
            return 0
        else:
            print(f"RESULT: FAIL")
            return 1
    
    # =========================================================================
    # ADVANCED MODE (for backward compat)
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"M5_0 GATE v{__version__} - ADVANCED")
    print(f"{'='*60}")
    print("\nTIP: Use --offline or --online instead")
    
    run_dir = None
    if args.run_dir:
        run_dir = args.run_dir
        print(f"\n[ADVANCED] --run-dir: {run_dir}")
    elif os.environ.get("ARBY_RUN_DIR"):
        run_dir = Path(os.environ["ARBY_RUN_DIR"])
        print(f"\n[ADVANCED] ARBY_RUN_DIR: {run_dir}")
    else:
        candidates = get_run_dir_candidates(args.output_root)
        if candidates:
            run_dir = candidates[0]
            print(f"\n[ADVANCED] Using latest: {run_dir}")
        else:
            print(f"\nERROR: No run directory. Use --offline or --online")
            return 2
    
    if not run_dir.exists():
        print(f"\nERROR: Not found: {run_dir}")
        return 2
    
    require_real = args.require_real or os.environ.get("ARBY_REQUIRE_REAL") == "1"
    
    artifacts = discover_artifacts(run_dir)
    missing = [name for name, path in artifacts.items() if path is None]
    if missing:
        print(f"\nERROR: Missing: {missing}")
        return 2
    
    print(f"\n{'='*60}")
    print("VALIDATION")
    print(f"{'='*60}\n")
    
    passed, messages = validate_artifacts(artifacts, require_real=require_real)
    for msg in messages:
        print(f"  {msg}")
    
    print(f"\n{'='*60}")
    if passed:
        print(f"RESULT: PASS")
        print(f"RunDir: {run_dir}")
        return 0
    else:
        print(f"RESULT: FAIL")
        return 1


if __name__ == "__main__":
    sys.exit(main())
