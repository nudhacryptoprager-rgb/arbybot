# PATH: core/gate_helpers.py
"""
Shared gate helpers: artifact discovery, schema validation, fixture generation.

Extracted from scripts/ci_m5_0_gate.py (R28) so that multiple gates and
tests can reuse these without depending on the script module.

The script re-exports these for backward compatibility.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Artifact Discovery ─────────────────────────────────────────────────

DEFAULT_OUTPUT_ROOT = Path("data/runs")


def discover_artifacts(run_dir: Path) -> Dict[str, Optional[Path]]:
    """
    Discover artifacts in run directory.

    Looks in:
    1. reports/ (PRIMARY - ci_m5_0_gate.py standard)
    2. snapshots/ (FALLBACK - legacy location)
    """
    artifacts: Dict[str, Optional[Path]] = {
        "scan": None,
        "truth_report": None,
        "reject_histogram": None,
    }

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


def get_run_dir_candidates(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> List[Path]:
    """Get run directories sorted by recency."""
    if not output_root.exists():
        return []

    candidates = []
    for d in output_root.iterdir():
        if d.is_dir():
            has_reports = (d / "reports").exists() and list(
                (d / "reports").glob("*.json")
            )
            has_snapshots = (d / "snapshots").exists() and list(
                (d / "snapshots").glob("*.json")
            )
            if has_reports or has_snapshots:
                all_files = (
                    list((d / "reports").glob("*.json")) if has_reports else []
                )
                all_files += (
                    list((d / "snapshots").glob("*.json")) if has_snapshots else []
                )
                if all_files:
                    mtime = max(f.stat().st_mtime for f in all_files)
                    candidates.append((d, mtime))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return [c[0] for c in candidates]


# ── Schema Validation ──────────────────────────────────────────────────


def validate_schema_version(data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate schema_version exists and is valid semver."""
    version = data.get("schema_version")
    if not version:
        return False, "Missing schema_version"
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        return False, f"Invalid schema_version: {version}"
    return True, f"schema_version={version}"


def validate_anti_placeholder(
    data: Dict[str, Any], require_real: bool = False
) -> Tuple[bool, str]:
    """Validate anti-placeholder invariant: no quotes with null pool_address/tick/sqrt_price_x96.

    M4.2 UPDATE: When quote_source="quoter_v2", tick/sqrt_price_x96 are legitimately null
    because QuoterV2 returns amount_out directly without tick/sqrt state.
    """
    quotes = data.get("quotes_sample", [])
    if not quotes:
        return True, "anti_placeholder OK (no quotes_sample)"

    violations = []
    for i, q in enumerate(quotes):
        dex_id = q.get("dex_id", "unknown")
        pair = f"{q.get('token_in', '?')}/{q.get('token_out', '?')}"
        quote_source = q.get("quote_source", "slot0")

        pool_addr = q.get("pool_address")
        if (
            pool_addr is None
            or pool_addr == ""
            or pool_addr == "0x0000000000000000000000000000000000000000"
        ):
            violations.append(f"quote[{i}] {dex_id} {pair}: pool_address=null")

        if "v3" in dex_id.lower() and quote_source != "quoter_v2":
            tick = q.get("tick")
            sqrt_price = q.get("sqrt_price_x96")
            if tick is None:
                violations.append(
                    f"quote[{i}] {dex_id} {pair}: tick=null (v3 requires tick)"
                )
            if sqrt_price is None:
                violations.append(
                    f"quote[{i}] {dex_id} {pair}: sqrt_price_x96=null (v3 requires sqrt)"
                )

    if violations:
        msg = f"ANTI_PLACEHOLDER VIOLATION: {len(violations)} placeholder quotes: {violations[:3]}"
        if require_real:
            return False, msg
        else:
            return True, f"WARN: {msg}"

    return True, f"anti_placeholder OK ({len(quotes)} quotes checked)"
