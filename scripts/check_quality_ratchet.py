#!/usr/bin/env python3
"""Quality ratchet — fail CI on NEW ruff/mypy violations.

The repo carries a large legacy lint/type debt.  Instead of a big-bang
cleanup, this gate enforces a *ratchet*: the violation count may only go
down, never up.  Baselines live in ``config/quality/<tool>_baseline.txt``.

Deterministic invocations:
  ruff: ``py -3.11 -m ruff check .`` (pyproject select rules; build/ excluded
        by ruff defaults)
  mypy: ``py -3.11 -m mypy . --explicit-package-bases --exclude <build/venv>``
        (explicit package bases required for the flat repo layout)

Optional supply-chain check: ``--pip-audit`` runs pip-audit when installed;
otherwise it reports SKIP (never blocks offline CI).

Exit codes: 0 = PASS (counts <= baseline), 1 = regression, 2 = tool failure.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = REPO_ROOT / "config" / "quality"

_RUFF_COUNT_RE = re.compile(r"^Found (\d+) errors?\.", re.MULTILINE)
_MYPY_COUNT_RE = re.compile(r"^Found (\d+) errors? in \d+ files?", re.MULTILINE)

MYPY_EXCLUDE = r"(^|\\|/)(build|\.venv|venv)(\\|/)"


def parse_ruff_count(output: str) -> Optional[int]:
    m = _RUFF_COUNT_RE.search(output)
    return int(m.group(1)) if m else (0 if "All checks passed" in output else None)


def parse_mypy_count(output: str) -> Optional[int]:
    m = _MYPY_COUNT_RE.search(output)
    if m:
        return int(m.group(1))
    if "Success: no issues found" in output:
        return 0
    return None


def read_baseline(tool: str) -> Optional[int]:
    path = BASELINE_DIR / f"{tool}_baseline.txt"
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def write_baseline(tool: str, count: int) -> Path:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    path = BASELINE_DIR / f"{tool}_baseline.txt"
    path.write_text(f"{count}\n", encoding="utf-8")
    return path


def run_tool(tool: str) -> Tuple[Optional[int], str]:
    """Run the tool; return (violation_count, raw_output_tail)."""
    if tool == "ruff":
        cmd = [sys.executable, "-m", "ruff", "check", "."]
        parser = parse_ruff_count
    elif tool == "mypy":
        cmd = [
            sys.executable, "-m", "mypy", ".",
            "--explicit-package-bases",
            "--exclude", MYPY_EXCLUDE,
        ]
        parser = parse_mypy_count
    else:
        raise ValueError(f"unknown tool: {tool}")
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    count = parser(output)
    return count, output.strip().splitlines()[-1] if output.strip() else ""


def check_tool(tool: str, *, update_baseline: bool = False) -> bool:
    """Return True when the tool passes the ratchet."""
    baseline = read_baseline(tool)
    count, tail = run_tool(tool)
    if count is None:
        print(f"[{tool}] ERROR: could not parse violation count ({tail})")
        return False
    if update_baseline:
        path = write_baseline(tool, count)
        print(f"[{tool}] baseline updated: {count} ({path})")
        return True
    if baseline is None:
        print(f"[{tool}] ERROR: baseline missing; run --update-baseline first")
        return False
    delta = count - baseline
    status = "PASS" if delta <= 0 else "FAIL"
    print(
        f"[{tool}] {status}: current={count} baseline={baseline} delta={delta:+d}"
    )
    if delta > 0:
        print(f"[{tool}] regression: {delta} NEW violation(s) introduced")
    return delta <= 0


def run_pip_audit() -> bool:
    """Optional supply-chain audit; SKIP (not FAIL) when pip-audit absent."""
    try:
        import pip_audit  # noqa: F401
    except ImportError:
        print("[pip-audit] SKIP: pip-audit not installed (optional supply-chain gate)")
        return True
    proc = subprocess.run(
        [sys.executable, "-m", "pip_audit", "--progress-spinner", "off"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=900,
    )
    tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    for line in tail[-5:]:
        print(f"[pip-audit] {line}")
    return proc.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Quality ratchet gate (ruff/mypy)")
    ap.add_argument("--tool", choices=["ruff", "mypy"], help="check only one tool")
    ap.add_argument(
        "--update-baseline",
        action="store_true",
        help="rewrite baselines with current counts (ratchet down intentionally)",
    )
    ap.add_argument(
        "--pip-audit",
        action="store_true",
        help="also run pip-audit when installed (SKIP when absent)",
    )
    args = ap.parse_args()

    tools = [args.tool] if args.tool else ["ruff", "mypy"]
    ok = True
    for tool in tools:
        ok = check_tool(tool, update_baseline=bool(args.update_baseline)) and ok
    if args.pip_audit:
        ok = run_pip_audit() and ok
    print("quality ratchet:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
