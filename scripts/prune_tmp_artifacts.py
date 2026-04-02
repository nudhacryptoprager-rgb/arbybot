#!/usr/bin/env python3
"""
M7.A.5.32 — Retention tool for data/tmp.

Rules:
  m7a_* files: keep last 2 per prefix (e.g. m7a_510, m7a_511...)
  helper *.py files: keep last 5
  *.txt / *.log files: keep last 3
  anything older than 14 days: delete
  L0_*/L1_*/L2_*/L3_* suppression files: keep last 2

Usage:
    py -3.11 scripts/prune_tmp_artifacts.py --dry-run
    py -3.11 scripts/prune_tmp_artifacts.py
    py -3.11 scripts/prune_tmp_artifacts.py --keep-per-prefix 3 --keep-helpers 10
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

TMP_DIR = Path("data") / "tmp"
MAX_AGE_DAYS = 14


def parse_args():
    ap = argparse.ArgumentParser(description="Prune data/tmp artifacts")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    ap.add_argument("--keep-per-prefix", type=int, default=2, help="M7 artifacts to keep per prefix")
    ap.add_argument("--keep-helpers", type=int, default=5, help="Helper .py files to keep")
    ap.add_argument("--keep-logs", type=int, default=3, help="Log/txt files to keep")
    ap.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS, help="Delete files older than N days")
    return ap.parse_args()


def _classify_file(name: str) -> str:
    """Classify a file into a retention group."""
    if name.endswith(".py"):
        return "helper"
    if name.endswith(".txt") or name.endswith(".log"):
        return "log"
    # M7 artifact prefixes: m7a_510, m7a_511, etc.
    m = re.match(r"^(m7a_\d+)", name)
    if m:
        return f"m7a:{m.group(1)}"
    # Suppression layer files
    if re.match(r"^L\d+_", name):
        return "suppression"
    return "other"


def _get_prefix(name: str) -> str:
    """Extract the M7 prefix for grouping (e.g. m7a_510 from m7a_510_300b.json)."""
    m = re.match(r"^(m7a_\d+)", name)
    return m.group(1) if m else name


def prune(args) -> dict:
    """Prune data/tmp and return stats."""
    if not TMP_DIR.exists():
        print(f"  {TMP_DIR} does not exist, nothing to prune")
        return {"deleted": 0, "kept": 0, "skipped": 0}

    files = sorted(TMP_DIR.iterdir())
    if not files:
        print(f"  {TMP_DIR} is empty")
        return {"deleted": 0, "kept": 0, "skipped": 0}

    now = time.time()
    max_age_seconds = args.max_age_days * 86400

    # Group files by classification
    groups: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        if not f.is_file():
            continue
        cls = _classify_file(f.name)
        groups[cls].append(f)

    to_delete: list[Path] = []
    to_keep: list[Path] = []

    for cls, file_list in groups.items():
        # Sort by modification time (newest first)
        file_list.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        if cls == "helper":
            keep_n = args.keep_helpers
        elif cls == "log":
            keep_n = args.keep_logs
        elif cls.startswith("m7a:"):
            keep_n = args.keep_per_prefix
        elif cls == "suppression":
            keep_n = args.keep_per_prefix
        else:
            keep_n = args.keep_per_prefix

        for i, f in enumerate(file_list):
            age = now - f.stat().st_mtime
            if age > max_age_seconds:
                to_delete.append(f)
            elif i >= keep_n:
                to_delete.append(f)
            else:
                to_keep.append(f)

    # Report
    total_size = sum(f.stat().st_size for f in to_delete)
    print(f"  Files to delete: {len(to_delete)} ({total_size / 1024 / 1024:.2f} MB)")
    print(f"  Files to keep:   {len(to_keep)}")

    if args.dry_run:
        print(f"\n  [DRY RUN] Would delete:")
        for f in sorted(to_delete, key=lambda f: f.name):
            age_days = (now - f.stat().st_mtime) / 86400
            print(f"    {f.name} ({f.stat().st_size / 1024:.1f} KB, {age_days:.0f}d old)")
        return {"deleted": 0, "kept": len(to_keep), "would_delete": len(to_delete)}

    deleted = 0
    for f in to_delete:
        try:
            f.unlink()
            deleted += 1
        except Exception as exc:
            print(f"  WARN: Failed to delete {f.name}: {exc}")

    print(f"  Deleted {deleted} files, kept {len(to_keep)}")
    return {"deleted": deleted, "kept": len(to_keep), "skipped": 0}


def main():
    args = parse_args()
    print(f"=== Prune data/tmp ===")
    print(f"  Rules: m7a keep={args.keep_per_prefix}, helpers keep={args.keep_helpers}, "
          f"logs keep={args.keep_logs}, max_age={args.max_age_days}d")
    stats = prune(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
