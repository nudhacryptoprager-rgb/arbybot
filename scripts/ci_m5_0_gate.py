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

# Ensure repository root is on sys.path so `python scripts/ci_m5_0_gate.py` works
try:
    REPO_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(REPO_ROOT))
except Exception:
    pass

# Load .env from repo root (best-effort)
from core.env import load_root_dotenv
load_root_dotenv()

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
        "current_block": 100,
        "chain_id": 42161,
        "infra": {"rpc_provider": "fixture", "transport": "http", "ws_enabled": False, "tenderly_enabled": False},
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
        "current_block": 100,
        "execution_enabled": False,
        "execution_blocker": "EXECUTION_DISABLED",
        "infra": {"rpc_provider": "fixture", "transport": "http", "ws_enabled": False, "tenderly_enabled": False},
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
        "current_block": 100,
        "infra": {"rpc_provider": "fixture", "transport": "http", "ws_enabled": False, "tenderly_enabled": False},
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


def validate_scan_fields(data: Dict[str, Any], path: Optional[Path] = None, require_real: bool = False) -> Tuple[bool, str]:
    """Validate top-level scan fields required by M5_0.

    Returns (ok, message).
    """
    try:
        keys = list(data.keys())
        # schema and run_mode already checked elsewhere
        cb = data.get("current_block")
        if cb is None:
            return False, f"scan.current_block missing; keys={keys}"
        if not isinstance(cb, int):
            return False, f"scan.current_block not int: {type(cb).__name__} ({cb})"
        if require_real and cb <= 0:
            return False, f"scan.current_block must be >0 for online runs, got {cb}"

        quotes_total = data.get("quotes_total")
        if quotes_total is None:
            return False, f"scan.quotes_total missing; keys={keys}"
        # allow zero in offline but require >=1 in online
        if require_real and int(quotes_total) < 1:
            return False, f"scan.quotes_total < 1 for online runs: {quotes_total}"

        dexes_active = data.get("dexes_active")
        if dexes_active is None:
            return False, f"scan.dexes_active missing; keys={keys}"
        if int(dexes_active) < 1:
            return False, f"scan.dexes_active < 1: {dexes_active}"

        return True, f"scan fields OK"
    except Exception as e:
        return False, f"Exception validating scan fields: {type(e).__name__}: {e}"


def validate_truth_report_fields(data: Dict[str, Any], path: Optional[Path] = None, require_real: bool = False) -> Tuple[bool, str]:
    """Validate truth_report required fields per M5_0.

    Returns (ok, message).
    """
    try:
        keys = list(data.keys())
        # schema and run_mode expected to be checked
        cb = data.get("current_block")
        if cb is None:
            return False, f"truth_report.current_block missing; keys={keys}"
        if not isinstance(cb, int):
            return False, f"truth_report.current_block not int: {type(cb).__name__} ({cb})"
        if require_real and cb <= 0:
            return False, f"truth_report.current_block must be >0 for online runs, got {cb}"

        quotes_total = data.get("quotes_total")
        quotes_fetched = data.get("quotes_fetched")
        if quotes_total is None or quotes_fetched is None:
            return False, f"truth_report.quotes_total/quotes_fetched missing; keys={keys}"
        if require_real and int(quotes_fetched) < 1:
            return False, f"truth_report.quotes_fetched < 1 for online runs: {quotes_fetched}"

        dexes_active = data.get("dexes_active")
        if dexes_active is None:
            return False, f"truth_report.dexes_active missing; keys={keys}"
        if int(dexes_active) < 1:
            return False, f"truth_report.dexes_active < 1: {dexes_active}"

        # price sanity metrics existence
        if "price_sanity_passed" not in data or "price_sanity_failed" not in data:
            # also check nested health
            health = data.get("health", {}) or {}
            if "price_sanity_passed" not in health or "price_sanity_failed" not in health:
                return False, f"price_sanity_passed/failed missing in truth_report (keys={keys})"

        return True, "truth_report fields OK"
    except Exception as e:
        return False, f"Exception validating truth_report fields: {type(e).__name__}: {e}"


def validate_reject_histogram_fields(data: Dict[str, Any], path: Optional[Path] = None) -> Tuple[bool, str]:
    try:
        keys = list(data.keys())
        if "rejects" not in data:
            return False, f"reject_histogram.missing 'rejects' key; keys={keys}"
        if not isinstance(data.get("rejects"), list):
            return False, f"reject_histogram.rejects not a list"
        # gate breakdown optional but helpfully present in health/gate_breakdown
        return True, "reject_histogram fields OK"
    except Exception as e:
        return False, f"Exception validating reject_histogram: {type(e).__name__}: {e}"


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


def validate_artifacts(artifacts: Dict[str, Optional[Path]], require_real: bool = False,
                       require_infra_hosts: bool = False,
                       require_cross_artifact: bool = False,
                       require_tenderly: bool = False) -> Tuple[bool, List[str]]:
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
    loaded_data: Dict[str, Dict[str, Any]] = {}
    for name, path in artifacts.items():
        try:
            with open(path) as f:
                data = json.load(f)
            loaded_data[name] = data
            
            # Validate schema_version (required for all)
            ok, msg = validate_schema_version(data)
            messages.append(f"{'OK' if ok else 'FAIL'}: {name} - {msg}")
            if not ok:
                all_passed = False
            
            # Check run_mode presence and value
            if "run_mode" not in data:
                messages.append(f"FAIL: {name} - missing run_mode")
                all_passed = False
            else:
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
                # Strict truth_report field validation
                ok_tr, msg_tr = validate_truth_report_fields(data, path)
                messages.append(f"{'OK' if ok_tr else 'FAIL'}: {name} - {msg_tr}")
                if not ok_tr:
                    all_passed = False
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
                # Strict reject_histogram validation
                ok_rh, msg_rh = validate_reject_histogram_fields(data, path)
                messages.append(f"{'OK' if ok_rh else 'FAIL'}: {name} - {msg_rh}")
                if not ok_rh:
                    all_passed = False
                    
        except json.JSONDecodeError as e:
            messages.append(f"FAIL: {name} - invalid JSON: {e}")
            all_passed = False
        except Exception as e:
            messages.append(f"FAIL: {name} - {e}")
            all_passed = False
    
        try:
            if "scan" in loaded_data and "truth_report" in loaded_data:
                ok_cb, msg_cb = validate_current_block(loaded_data.get("scan", {}), loaded_data.get("truth_report", {}))
                if ok_cb:
                    messages.append(f"OK: current_block - {msg_cb}")
                else:
                    messages.append(f"FAIL: current_block - {msg_cb}")
                    all_passed = False
        except Exception as e:
            messages.append(f"FAIL: current_block validation exception: {type(e).__name__}: {e}")

        # Cross-artifact summary cross-checks (scan vs truth_report vs reject_histogram)
        try:
            s = loaded_data.get("scan", {})
            t = loaded_data.get("truth_report", {})
            r = loaded_data.get("reject_histogram", {})

            def _get(d, key):
                return d.get(key) if d else None

            # Compare top-level counts
            mismatches = []
            for key in ("quotes_total", "quotes_fetched", "dexes_active", "price_sanity_passed", "price_sanity_failed"):
                sv = _get(s, key)
                tv = _get(t, key)
                if sv is not None and tv is not None and int(sv) != int(tv):
                    mismatches.append((key, sv, tv))

            if mismatches:
                for key, sv, tv in mismatches:
                    if require_cross_artifact:
                        messages.append(f"FAIL: summary_mismatch - {key} scan={sv} truth_report={tv}")
                        all_passed = False
                    else:
                        messages.append(f"WARN: summary_mismatch - {key} scan={sv} truth_report={tv}")

            # Basic reject histogram vs totals sanity
            try:
                total_rejects = int(r.get("total_rejects", 0)) if r else 0
                rejects_len = len(r.get("rejects", [])) if r else 0
                if total_rejects != rejects_len:
                    messages.append(f"WARN: reject_histogram.total_rejects ({total_rejects}) != len(rejects) ({rejects_len})")
            except Exception:
                messages.append("WARN: could not cross-check reject_histogram totals")
        except Exception as e:
            messages.append(f"WARN: cross-artifact checks failed: {type(e).__name__}: {e}")

        # Infra transparency checks: confirm provider and host present and consistent
        try:
            infra_s = (s.get("infra") or {})
            infra_t = (t.get("infra") or {})
            infra_r = (r.get("infra") or {})

            # Extract provider/hosts
            prov_s = infra_s.get("rpc_provider")
            prov_t = infra_t.get("rpc_provider")
            host_s = infra_s.get("rpc_http_host")
            host_t = infra_t.get("rpc_http_host")

            if not prov_s or not host_s:
                if require_infra_hosts or require_real:
                    messages.append("FAIL: scan.infra missing rpc_provider or rpc_http_host")
                    all_passed = False
                else:
                    messages.append("WARN: scan.infra missing rpc_provider or rpc_http_host")
            if not prov_t or not host_t:
                if require_infra_hosts or require_real:
                    messages.append("FAIL: truth_report.infra missing rpc_provider or rpc_http_host")
                    all_passed = False
                else:
                    messages.append("WARN: truth_report.infra missing rpc_provider or rpc_http_host")

            # If env required Alchemy, ensure provider is alchemy
            if os.environ.get("ARBY_REQUIRE_ALCHEMY") == "1":
                if prov_s != "alchemy" or prov_t != "alchemy":
                    messages.append(f"FAIL: REQUIRE_ALCHEMY set but provider != alchemy (scan={prov_s} truth={prov_t})")
                    all_passed = False

            # Heuristic: chain_id vs rpc host mismatch (blocker)
            try:
                chain_id_s = s.get("chain_id")
                chain_id_t = t.get("chain_id")
                # prefer scan chain_id if present
                chain_id_val = chain_id_s or chain_id_t
                if chain_id_val is not None:
                    try:
                        cid = int(chain_id_val)
                        # Quick heuristic for known mismatch: Arbitrum chain_id (42161) must not point to Mantle host
                        if cid == 42161:
                            hs = (host_s or "").lower()
                            ht = (host_t or "").lower()
                            if "mantle" in hs or "mantle" in ht:
                                messages.append(f"FAIL: chain_id=42161 (Arbitrum) but rpc_http_host contains 'mantle' (scan={host_s} truth={host_t})")
                                all_passed = False
                    except Exception:
                        pass
            except Exception:
                pass

            # Tenderly diagnostic consistency
            for name, infra in (("scan", infra_s), ("truth_report", infra_t)):
                if infra.get("tenderly_enabled"):
                    ok = infra.get("tenderly_ok")
                    err = infra.get("tenderly_error")
                    if ok is not True and (not err):
                        if require_tenderly:
                            messages.append(f"FAIL: {name}.infra tenderly_enabled true but no tenderly_ok or tenderly_error")
                            all_passed = False
                        else:
                            messages.append(f"WARN: {name}.infra tenderly_enabled true but no tenderly_ok or tenderly_error")

            # WS diagnostics validation
            for name, infra in (("scan", infra_s), ("truth_report", infra_t)):
                if infra.get("ws_enabled"):
                    attempted = infra.get("ws_attempted")
                    connected = infra.get("ws_connected")
                    fallback = infra.get("ws_fallback_to_http")
                    ws_err = infra.get("ws_error")
                    if attempted is not True and attempted is not False:
                        messages.append(f"WARN: {name}.infra missing ws_attempted")
                    if connected is not True and connected is not False:
                        messages.append(f"WARN: {name}.infra missing ws_connected")
                    if connected is False and not (ws_err or fallback):
                        messages.append(f"FAIL: {name}.infra ws_enabled true but not connected and no ws_error/fallback provided")
                        all_passed = False
        except Exception as e:
            messages.append(f"WARN: infra transparency checks failed: {type(e).__name__}: {e}")
    return all_passed, messages


def validate_current_block(scan_data: Dict[str, Any], truth_data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate current_block present, int>0 and equal between scan and truth_report.

    Returns (ok, message)
    """
    try:
        # Only consider top-level fields per contract
        scan_cb = scan_data.get("current_block")
        truth_cb = truth_data.get("current_block")

        missing = []
        if scan_cb is None:
            missing.append("scan.current_block")
        if truth_cb is None:
            missing.append("truth_report.current_block")
        if missing:
            return False, f"Missing current_block in: {', '.join(missing)}; truth keys: {list(truth_data.keys())}, scan keys: {list(scan_data.keys())}"

        # Type checks: must be int
        if not isinstance(scan_cb, int):
            return False, f"scan.current_block not int: {type(scan_cb).__name__} ({scan_cb})"
        if not isinstance(truth_cb, int):
            return False, f"truth_report.current_block not int: {type(truth_cb).__name__} ({truth_cb})"

        # Value checks
        if scan_cb <= 0:
            return False, f"scan.current_block must be >0, got {scan_cb}"
        if truth_cb <= 0:
            return False, f"truth_report.current_block must be >0, got {truth_cb}"

        # Equality
        if scan_cb != truth_cb:
            return False, f"current_block mismatch: scan={scan_cb} truth_report={truth_cb}"

        return True, f"current_block OK: {scan_cb}"
    except Exception as e:
        return False, f"Exception validating current_block: {type(e).__name__}: {e}"


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
    
    # Resolve RPC URLs from env: prefer explicit ALCHEMY_RPC_HTTP/WS, else build from ALCHEMY_API_KEY
    try:
        from core.rpc_urls import resolve_rpc_http, resolve_rpc_ws
    except Exception:
        resolve_rpc_http = resolve_rpc_ws = None

    env_for_run = os.environ.copy()
    # Determine canonical network/chain: prefer ENV NETWORK, otherwise leave to scanner/config
    network = os.environ.get("NETWORK") or os.environ.get("CHAIN")
    chain_id = os.environ.get("CHAIN_ID")
    try:
        chain_id_int = int(chain_id) if chain_id else None
    except Exception:
        chain_id_int = None

    # Use resolver to find the best HTTP and WS endpoints and provider metadata
    primary_http = None
    primary_ws = None
    provider_http = "unknown"
    provider_ws = "unknown"
    http_diag = {}
    ws_diag = {}

    if resolve_rpc_http:
        url, provider, diag = resolve_rpc_http(chain_id=chain_id_int, network=network, env=os.environ)
        primary_http = url
        provider_http = provider
        http_diag = diag or {}

    if resolve_rpc_ws:
        urlw, providerw, diagw = resolve_rpc_ws(chain_id=chain_id_int, network=network, env=os.environ)
        primary_ws = urlw
        provider_ws = providerw
        ws_diag = diagw or {}

    # Inject resolved endpoints into scanner env (do not log keys)
    if primary_http:
        env_for_run.setdefault("ARBY_RPC_HTTP_PRIMARY", primary_http)
        env_for_run.setdefault("ARBY_RPC_PROVIDER", provider_http)
        # expose host only (no keys)
        try:
            from urllib.parse import urlparse
            env_for_run.setdefault("ARBY_RPC_HTTP_HOST", urlparse(primary_http).netloc)
        except Exception:
            pass
    if primary_ws:
        env_for_run.setdefault("ARBY_RPC_WS_PRIMARY", primary_ws)
        env_for_run.setdefault("ARBY_RPC_WS_PROVIDER", provider_ws)
        try:
            from urllib.parse import urlparse
            env_for_run.setdefault("ARBY_RPC_WS_HOST", urlparse(primary_ws).netloc)
        except Exception:
            pass

    # Enforce Require-Alchemy behavior if requested
    require_alchemy = os.environ.get("ARBY_REQUIRE_ALCHEMY") == "1" or os.environ.get("REQUIRE_ALCHEMY") == "1"
    if require_alchemy and provider_http != "alchemy":
        print(f"FAIL: Alchemy expected but resolved provider={provider_http} (host={env_for_run.get('ARBY_RPC_HTTP_HOST')})")
        return False, "Alchemy expected but public fallback used"

    # NOTE: WS preference flags are read from the calling process env by the scanner.

    try:
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=300, env=env_for_run)
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
    parser.add_argument("--ws", action="store_true",
                        help="Prefer WS transport when resolving endpoints")
    parser.add_argument("--ws-required", action="store_true",
                        help="Require WS to be available; fail if WS not connected")
    parser.add_argument("--require-infra-hosts", action="store_true",
                        help="Fail if artifacts do not include infra.rpc_provider or infra.rpc_http_host")
    parser.add_argument("--require-cross-artifact", action="store_true",
                        help="Treat cross-artifact summary mismatches as FAIL instead of WARN")
    parser.add_argument("--require-tenderly", action="store_true",
                        help="Require tenderly diagnostics to be present and passing when enabled in artifacts")
    
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    
    args = parser.parse_args()

    # Log presence of sensitive env keys (presence only; do not print values)
    print(f"ENV: ALCHEMY_API_KEY present={bool(os.environ.get('ALCHEMY_API_KEY'))}, TENDERLY_ACCESS_KEY present={bool(os.environ.get('TENDERLY_ACCESS_KEY'))}")
    
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
        # Log resolved artifact paths for clarity
        print("\n[OFFLINE] Artifact paths:")
        for k, p in artifacts.items():
            print(f"  {k}: {p}")
        
        print(f"\n[OFFLINE] Generated {len(artifacts_paths)} artifacts:")
        for name, path in artifacts_paths.items():
            print(f"  - {name}: {path.name}")
        
        print(f"\n{'='*60}")
        print("VALIDATION")
        print(f"{'='*60}\n")
        
        passed, messages = validate_artifacts(
            artifacts,
            require_real=False,
            require_infra_hosts=args.require_infra_hosts,
            require_cross_artifact=args.require_cross_artifact,
            require_tenderly=args.require_tenderly,
        )
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
        
        # Export WS preference flags into the environment so run_real_scan picks them up
        if args.ws:
            os.environ.setdefault("ARBY_PREFER_WS", "1")
        if args.ws_required:
            os.environ.setdefault("ARBY_WS_REQUIRED", "1")

        # For M5_0 DoD: make infra-hosts and cross-artifact checks strict by default in online runs
        # These can still be overridden by explicit flags if needed.
        args.require_infra_hosts = True
        args.require_cross_artifact = True

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
        
        passed, messages = validate_artifacts(
            artifacts,
            require_real=True,
            require_infra_hosts=args.require_infra_hosts,
            require_cross_artifact=args.require_cross_artifact,
            require_tenderly=args.require_tenderly,
        )
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
    
    passed, messages = validate_artifacts(
        artifacts,
        require_real=require_real,
        require_infra_hosts=args.require_infra_hosts,
        require_cross_artifact=args.require_cross_artifact,
        require_tenderly=args.require_tenderly,
    )
    for msg in messages:
        print(f"  {msg}")
    
    print(f"\n{'='*60}")
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    print(f"RunDir: {run_dir}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
