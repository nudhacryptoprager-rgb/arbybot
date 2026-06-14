#!/usr/bin/env python3
"""Fail on unclassified on-chain addresses outside config/.

Reads ``config/hardcode_audit_allowlist.yaml``. Files listed under
ALLOWED_PROTOCOL_CONSTANT, CONFIG_REQUIRED, DELETE_OR_ARCHIVE, or
``scan_exempt_paths`` may contain addresses. All other scanned files must not.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_ADDR_RE = re.compile(r"0x[a-fA-F0-9]{40}|0x[a-fA-F0-9]{64}")
_DEFAULT_SCAN_ROOTS = (
    "discovery",
    "dex",
    "m8",
    "m8_1",
    "m8_2",
    "m9",
    "scripts",
    "strategy",
    "monitoring",
    "core",
    "m7",
    "execution",
)
_EXCLUDE_PARTS = {"config", "data", "docs", "tests", "archive", "__pycache__"}


def _load_allowlist() -> Dict[str, Any]:
    from config import CONFIG_DIR, load_yaml

    path = CONFIG_DIR / "hardcode_audit_allowlist.yaml"
    if not path.exists():
        return {}
    return load_yaml("hardcode_audit_allowlist.yaml")


def _classified_paths(allowlist: Dict[str, Any]) -> Tuple[Set[str], List[str]]:
    """Exact paths and directory prefixes (CONFIG_REQUIRED dirs end with /)."""
    exact: Set[str] = set()
    prefixes: List[str] = []
    for section in (
        "ALLOWED_PROTOCOL_CONSTANT",
        "CONFIG_REQUIRED",
        "DELETE_OR_ARCHIVE",
    ):
        for entry in allowlist.get(section) or []:
            if not isinstance(entry, dict) or not entry.get("path"):
                continue
            p = str(entry["path"]).replace("\\", "/")
            if p.endswith("/"):
                prefixes.append(p)
            else:
                exact.add(p)
    for p in allowlist.get("scan_exempt_paths") or []:
        exact.add(str(p).replace("\\", "/"))
    return exact, prefixes


def _path_is_classified(rel: str, exact: Set[str], prefixes: List[str]) -> bool:
    if rel in exact:
        return True
    return any(rel.startswith(pref) for pref in prefixes)


def _archived_must_not_exist(allowlist: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for entry in allowlist.get("DELETE_OR_ARCHIVE") or []:
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get("path") or "").replace("\\", "/")
        if not rel:
            continue
        if (REPO_ROOT / rel).exists():
            errors.append(f"HARDCODE_AUDIT: DELETE_OR_ARCHIVE still present: {rel}")
    return errors


def _scan_file(path: Path) -> List[Tuple[int, str]]:
    hits: List[Tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in _ADDR_RE.finditer(line):
            hits.append((lineno, m.group(0).lower()))
    return hits


def _iter_scan_files(roots: Tuple[str, ...]) -> List[Path]:
    out: List[Path] = []
    for root_name in roots:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".yaml", ".yml", ".json", ".md"}:
                continue
            if any(part in _EXCLUDE_PARTS for part in path.parts):
                continue
            out.append(path)
    return out


def run_hardcode_audit(
    *,
    roots: Tuple[str, ...] = _DEFAULT_SCAN_ROOTS,
    allowlist: Dict[str, Any] | None = None,
) -> List[str]:
    """Return error strings (empty = pass)."""
    allowlist = allowlist if allowlist is not None else _load_allowlist()
    exact, prefixes = _classified_paths(allowlist)
    errors = _archived_must_not_exist(allowlist)

    for path in _iter_scan_files(roots):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if _path_is_classified(rel, exact, prefixes):
            continue
        if rel.startswith("scripts/archive/"):
            continue
        hits = _scan_file(path)
        if hits:
            sample = ", ".join(f"L{ln}:{addr[:10]}…" for ln, addr in hits[:3])
            errors.append(
                f"HARDCODE_AUDIT: unclassified addresses in {rel} ({len(hits)} hits; {sample})"
            )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Hardcode address audit gate")
    ap.add_argument("--roots", nargs="*", default=list(_DEFAULT_SCAN_ROOTS))
    args = ap.parse_args()
    errors = run_hardcode_audit(roots=tuple(args.roots))
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        print(f"HARDCODE_AUDIT: FAIL ({len(errors)} issues)", file=sys.stderr)
        return 1
    print("HARDCODE_AUDIT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
