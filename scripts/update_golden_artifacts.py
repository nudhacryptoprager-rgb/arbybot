#!/usr/bin/env python3
# PATH: scripts/update_golden_artifacts.py
"""
Golden Artifacts Update Script.

This is the ONLY script authorized to update docs/artifacts/*_golden.json files.
Requires explicit confirmation and logs all updates.

Usage:
  python scripts/update_golden_artifacts.py --run-dir data/runs/<dir> --stage m5_0
  python scripts/update_golden_artifacts.py --run-dir data/runs/<dir> --stage m5
  python scripts/update_golden_artifacts.py --run-dir data/runs/<dir> --stage m4
  python scripts/update_golden_artifacts.py --run-dir data/runs/<dir> --stage all
  
  # Dry run (show what would be updated)
  python scripts/update_golden_artifacts.py --run-dir data/runs/<dir> --stage m5_0 --dry-run

Exit codes:
  0 = Success
  1 = Validation failed (source artifacts invalid)
  2 = User cancelled
  3 = Copy failed
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

GOLDEN_DIR = PROJECT_ROOT / "docs" / "artifacts"

# Stage definitions: what artifacts belong to each stage
STAGE_ARTIFACTS = {
    "m5_0": {
        "scan": "scan_golden.json",
        "truth_report": "truth_report_golden.json",
        "reject_histogram": "reject_histogram_golden.json",
    },
    "m5": {
        "daily_report": "daily_report_golden.json",
    },
    "m4": {
        "signals": "signals_golden.json",
        "execution_report": "execution_report_golden.json",
    },
}

# Schema validation requirements per stage
REQUIRED_FIELDS = {
    "m5_0": {
        "scan": ["schema_version", "run_mode", "timestamp"],
        "truth_report": ["schema_version", "run_mode", "quotes_total", "dexes_active"],
        "reject_histogram": ["schema_version", "run_mode", "rejects"],
    },
    "m5": {
        "daily_report": ["schema_version", "runs_included", "paper_net_pnl_usdc"],
    },
    "m4": {
        "signals": ["schema_version", "signals"],
        "execution_report": ["schema_version", "run_mode", "simulations"],
    },
}


def find_artifact(run_dir: Path, artifact_type: str) -> Optional[Path]:
    """Find artifact in run_dir/reports/ or run_dir/snapshots/."""
    reports_dir = run_dir / "reports"
    snapshots_dir = run_dir / "snapshots"
    
    # Search patterns
    patterns = {
        "scan": "scan_*.json",
        "truth_report": "truth_report_*.json",
        "reject_histogram": "reject_histogram_*.json",
        "daily_report": "daily_report_*.json",
        "signals": "signals_*.json",
        "execution_report": "execution_report_*.json",
    }
    
    pattern = patterns.get(artifact_type)
    if not pattern:
        return None
    
    # Check reports first, then snapshots
    for search_dir in [reports_dir, snapshots_dir]:
        if search_dir.exists():
            matches = list(search_dir.glob(pattern))
            if matches:
                # Return most recent
                return max(matches, key=lambda p: p.stat().st_mtime)
    
    return None


def validate_artifact(path: Path, artifact_type: str, stage: str) -> Tuple[bool, List[str]]:
    """Validate artifact has required fields."""
    errors = []
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, [f"Failed to parse JSON: {e}"]
    
    required = REQUIRED_FIELDS.get(stage, {}).get(artifact_type, [])
    for field in required:
        if field not in data:
            errors.append(f"Missing required field: {field}")
    
    return len(errors) == 0, errors


def copy_artifact(src: Path, dst: Path, dry_run: bool) -> bool:
    """Copy artifact to golden location."""
    if dry_run:
        print(f"  [DRY-RUN] Would copy: {src.name} -> {dst.name}")
        return True
    
    try:
        shutil.copy2(src, dst)
        print(f"  ✅ Copied: {src.name} -> {dst.name}")
        return True
    except Exception as e:
        print(f"  ❌ Failed to copy {src.name}: {e}")
        return False


def update_stage(run_dir: Path, stage: str, dry_run: bool, force: bool) -> Tuple[bool, int]:
    """Update golden artifacts for a stage. Returns (success, count)."""
    artifacts = STAGE_ARTIFACTS.get(stage)
    if not artifacts:
        print(f"Unknown stage: {stage}")
        return False, 0
    
    print(f"\n{'='*60}")
    print(f"STAGE: {stage.upper()}")
    print(f"{'='*60}")
    
    updated = 0
    failed = False
    
    for artifact_type, golden_name in artifacts.items():
        src = find_artifact(run_dir, artifact_type)
        if not src:
            print(f"  ⚠️  {artifact_type}: NOT FOUND in {run_dir}")
            continue
        
        # Validate
        ok, errors = validate_artifact(src, artifact_type, stage)
        if not ok:
            print(f"  ❌ {artifact_type}: VALIDATION FAILED")
            for err in errors:
                print(f"      - {err}")
            if not force:
                failed = True
                continue
            print(f"      (--force: proceeding anyway)")
        
        # Copy
        dst = GOLDEN_DIR / golden_name
        if copy_artifact(src, dst, dry_run):
            updated += 1
        else:
            failed = True
    
    return not failed, updated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update golden artifacts from a run directory",
        epilog="This is the ONLY authorized way to update docs/artifacts/*_golden.json"
    )
    parser.add_argument("--run-dir", required=True, help="Source run directory")
    parser.add_argument("--stage", required=True, choices=["m5_0", "m5", "m4", "all"],
                        help="Stage to update")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated")
    parser.add_argument("--force", action="store_true", help="Update even if validation fails")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()
    
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"❌ Run directory does not exist: {run_dir}")
        return 1
    
    # Ensure golden dir exists
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    
    stages = ["m5_0", "m5", "m4"] if args.stage == "all" else [args.stage]
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           GOLDEN ARTIFACTS UPDATE                            ║
╚══════════════════════════════════════════════════════════════╝

Source:  {run_dir}
Target:  {GOLDEN_DIR}
Stages:  {', '.join(stages)}
Mode:    {'DRY-RUN' if args.dry_run else 'LIVE'}
""")
    
    if not args.dry_run and not args.yes:
        print("⚠️  WARNING: This will overwrite golden reference artifacts!")
        print("   These files are used for CI validation.")
        response = input("\nProceed? [y/N]: ").strip().lower()
        if response != "y":
            print("Cancelled.")
            return 2
    
    total_updated = 0
    any_failed = False
    
    for stage in stages:
        ok, count = update_stage(run_dir, stage, args.dry_run, args.force)
        total_updated += count
        if not ok:
            any_failed = True
    
    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"  Updated: {total_updated} artifacts")
    print(f"  Status:  {'⚠️  SOME FAILURES' if any_failed else '✅ SUCCESS'}")
    
    if not args.dry_run and total_updated > 0:
        # Log update
        log_file = GOLDEN_DIR / "update_log.txt"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} | stages={','.join(stages)} | "
                    f"source={run_dir} | updated={total_updated}\n")
        print(f"  Logged:  {log_file}")
    
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
