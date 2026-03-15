#!/usr/bin/env python3
"""
Retention script for cleaning up old runDir directories in data/runs/.

Usage:
    python scripts/prune_run_dirs.py --keep 50 --dry-run    # Preview what would be deleted
    python scripts/prune_run_dirs.py --keep 50 --yes         # Actually delete

Protected directories (never deleted):
    - data/runs/_rolling/
    - data/runs/_incidents/
    - data/runs/_cache/
    - Latest run referenced in _latest.json (run_summary_latest.inputs.run_dir_name)
    - Last incident path from _latest.json (paths.last_incident)

v2.0.5 (2026-02-13): Initial implementation per retention policy.
"""

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "data" / "runs"

# Directories that are never deleted
PROTECTED_PREFIXES = ("_rolling", "_incidents", "_cache")


def get_protected_from_latest() -> set:
    """Get protected run_dir names from _latest.json."""
    protected = set()
    
    latest_path = RUNS_DIR / "_rolling" / "_latest.json"
    if latest_path.exists():
        try:
            with open(latest_path) as f:
                data = json.load(f)
            
            # Protect run referenced in paths
            paths = data.get("paths", {})
            if paths.get("run_summary_latest"):
                # Extract run_dir from path if present
                pass  # run_summary_latest is just filename
            
            # Protect last_incident path
            if paths.get("last_incident"):
                incident_path = paths["last_incident"]
                # Extract dirname from path like "data/runs/ci_m5_gate_.../..."
                parts = Path(incident_path).parts
                for i, p in enumerate(parts):
                    if p == "runs" and i + 1 < len(parts):
                        protected.add(parts[i + 1])
                        break
        except Exception:
            pass
    
    run_summary_path = RUNS_DIR / "_rolling" / "run_summary_latest.json"
    if run_summary_path.exists():
        try:
            with open(run_summary_path) as f:
                data = json.load(f)
            
            # Protect the latest run_dir
            inputs = data.get("inputs", {})
            run_dir_name = inputs.get("run_dir_name")
            if run_dir_name:
                protected.add(run_dir_name)
        except Exception:
            pass
    
    return protected


def get_protected_from_status_md() -> set:
    """v2.1.0: Get protected run_dir names referenced in Status_M4.md.
    
    Scans Status_M4.md for patterns like:
    - ci_m5_gate_YYYYMMDD_HHMMSS
    - ci_m4_gate_YYYYMMDD_HHMMSS
    - Any directory name matching run_dir patterns
    """
    import re
    
    protected = set()
    status_path = REPO_ROOT / "docs" / "status" / "Status_M4.md"
    
    if not status_path.exists():
        return protected
    
    try:
        content = status_path.read_text(encoding="utf-8")
        
        # Match common runDir patterns:
        # ci_m5_gate_20260215_140031 (legacy)
        # ci_m5_gate_arbitrum_one_20260315_122041_456789 (R28.6 chain-scoped)
        # ci_m4_gate_20260215_140031
        # ci_m5_0_gate_offline_20260215_140031
        pattern = r'(ci_m[45][_0-9a-z]*gate[_0-9a-z]*_\d{8}_\d{6}(?:_\d+)?)'
        matches = re.findall(pattern, content, re.IGNORECASE)
        
        for match in matches:
            protected.add(match)
            
    except Exception:
        pass
    
    return protected


def get_run_dirs() -> list:
    """Get list of run directories sorted by modification time (oldest first)."""
    run_dirs = []
    
    if not RUNS_DIR.exists():
        return run_dirs
    
    for d in RUNS_DIR.iterdir():
        if not d.is_dir():
            continue
        
        # Skip protected prefixes
        if any(d.name.startswith(prefix) for prefix in PROTECTED_PREFIXES):
            continue
        
        # Get modification time
        try:
            mtime = d.stat().st_mtime
            run_dirs.append((d, mtime))
        except Exception:
            continue
    
    # Sort by modification time (oldest first)
    run_dirs.sort(key=lambda x: x[1])
    
    return [d for d, _ in run_dirs]


def prune_run_dirs(keep: int, dry_run: bool, yes: bool) -> dict:
    """Prune old run directories, keeping the N most recent.
    
    Args:
        keep: Number of most recent directories to keep
        dry_run: If True, only preview what would be deleted
        yes: If True, skip confirmation prompt
    
    Returns:
        dict with counts of protected, kept, and deleted directories
    """
    # v2.1.0: Combine protection from _latest.json AND Status_M4.md
    protected_dirs = get_protected_from_latest()
    protected_dirs.update(get_protected_from_status_md())
    all_dirs = get_run_dirs()
    
    # Partition into protected and deletable
    deletable = []
    kept_protected = []
    
    for d in all_dirs:
        if d.name in protected_dirs:
            kept_protected.append(d)
        else:
            deletable.append(d)
    
    # Keep the most recent N (deletable is sorted oldest-first)
    if len(deletable) <= keep:
        to_delete = []
        to_keep = deletable
    else:
        to_delete = deletable[:-keep]
        to_keep = deletable[-keep:]
    
    result = {
        "total_dirs": len(all_dirs),
        "protected_count": len(kept_protected),
        "kept_count": len(to_keep),
        "delete_count": len(to_delete),
        "protected_names": [d.name for d in kept_protected],
        "deleted_names": [],
        "dry_run": dry_run,
    }
    
    if not to_delete:
        print(f"Nothing to delete. {len(all_dirs)} directories, keeping all.")
        return result
    
    # Preview
    print(f"\nRetention summary:")
    print(f"  Total run directories: {len(all_dirs)}")
    print(f"  Protected (never delete): {len(kept_protected)}")
    print(f"  Keeping (most recent): {len(to_keep)}")
    print(f"  To delete: {len(to_delete)}")
    
    if kept_protected:
        print(f"\nProtected directories:")
        for d in kept_protected[:5]:
            print(f"    {d.name}")
        if len(kept_protected) > 5:
            print(f"    ... and {len(kept_protected) - 5} more")
    
    print(f"\nDirectories to delete (oldest first):")
    for d in to_delete[:10]:
        print(f"    {d.name}")
    if len(to_delete) > 10:
        print(f"    ... and {len(to_delete) - 10} more")
    
    if dry_run:
        print("\n[DRY-RUN] No directories deleted. Use --yes to actually delete.")
        return result
    
    if not yes:
        # Prompt for confirmation
        try:
            response = input(f"\nDelete {len(to_delete)} directories? [y/N] ")
            if response.lower() not in ("y", "yes"):
                print("Aborted.")
                return result
        except EOFError:
            print("Aborted (no input).")
            return result
    
    # Actually delete
    deleted = 0
    for d in to_delete:
        try:
            shutil.rmtree(d)
            result["deleted_names"].append(d.name)
            deleted += 1
        except Exception as e:
            print(f"  Error deleting {d.name}: {e}")
    
    result["delete_count"] = deleted
    print(f"\nDeleted {deleted} directories.")
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Prune old runDir directories, keeping the N most recent."
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=50,
        help="Number of most recent run directories to keep (default: 50)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt and delete immediately"
    )
    
    args = parser.parse_args()
    
    if not RUNS_DIR.exists():
        print(f"Runs directory does not exist: {RUNS_DIR}")
        return
    
    # Default to dry-run if neither --yes nor --dry-run specified
    dry_run = args.dry_run or (not args.yes and not args.dry_run)
    
    result = prune_run_dirs(
        keep=args.keep,
        dry_run=dry_run,
        yes=args.yes
    )
    
    return 0 if result else 1


if __name__ == "__main__":
    exit(main() or 0)
