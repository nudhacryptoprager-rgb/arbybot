# ARBY Testing Guide

## M5_0 CI Gate

### Two Canonical Commands

```powershell
# 1. OFFLINE (always works, ignores ALL ENV)
python scripts/ci_m5_0_gate.py --offline

# 2. ONLINE (runs real scan, ignores ARBY_RUN_DIR)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml
```

### Mode Semantics

| Mode | Creates | Ignores | Validates |
|------|---------|---------|-----------|
| `--offline` | `ci_m5_0_gate_offline_<ts>/` | ALL ENV | Fixture |
| `--online` | `ci_m5_0_gate_<ts>/` | ARBY_RUN_DIR | Real |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | FAIL (validation) |
| 2 | FAIL (artifacts missing) |
| 3 | FAIL (scanner error) |

---

## Quick Start

```powershell
# 1. Import smoke tests (catch ImportError early)
python -m pytest tests/unit/test_imports_contract.py -v

# 2. All unit tests
python -m pytest tests/unit -q

# 3. Offline gate
python scripts/ci_m5_0_gate.py --offline

# 4. Online gate (requires RPC)
python scripts/ci_m5_0_gate.py --online --config config/real_m5_0_golden.yaml
```

---

## Unit Tests

```powershell
# Import contract tests
python -m pytest tests/unit/test_imports_contract.py -v

# Price sanity tests
python -m pytest tests/unit/test_price_sanity_inversion.py -v

# Gate tests
python -m pytest tests/unit/test_ci_m5_0_gate.py -v

# Adapter tests
python -m pytest tests/unit/test_algebra_adapter.py -v

# All unit tests
python -m pytest tests/unit -q
```

---

## Artifact Locations

| Mode | Location |
|------|----------|
| `--offline` | `data/runs/ci_m5_0_gate_offline_<ts>/` |
| `--online` | `data/runs/ci_m5_0_gate_<ts>/` |

---

## Advanced Mode (Deprecated)

For backward compatibility only:

```powershell
# Explicit run directory
python scripts/ci_m5_0_gate.py --run-dir data/runs/real_xxx

# With ENV (deprecated)
$env:ARBY_RUN_DIR = "data\runs\real_xxx"
python scripts/ci_m5_0_gate.py
```

**Note**: Prefer `--offline` or `--online` for new workflows.

## M5_0 Gate Semantics

- `truth_report.current_block` and `scan.current_block` MUST be present at top-level when running `--online`.
- Both fields MUST be integers > 0 and MUST be equal across `scan` and `truth_report`.
- `--offline` mode uses fixtures and does not require RPC pin; `--online` fails hard if `current_block` is missing/invalid/mismatched.

### Environment variables & RPC URL resolution

- `ALCHEMY_API_KEY` (recommended): single API key used to generate Alchemy HTTP/WS endpoints when explicit URLs are not provided.
- `ALCHEMY_RPC_HTTP` / `ALCHEMY_RPC_WS` (optional): explicit endpoints. If present, they take priority over `ALCHEMY_API_KEY`.
- `ARBY_RPC_HTTP_PRIMARY` / `ARBY_RPC_WS_PRIMARY`: internal env keys that the gate may inject into the scanner subprocess to pin a resolved provider.
- `NETWORK`: canonical network name (e.g., `arbitrum`, `base`, `linea`, `mantle`) — used when building Alchemy URLs from `ALCHEMY_API_KEY`.
- `TENDERLY_USER`, `TENDERLY_PROJECT`, `TENDERLY_ACCESS_KEY` (optional): when present `infra.tenderly_enabled=true` is written to artifacts; secrets are never logged.

Rules the gate follows to resolve RPC endpoints (single source of truth):

1. If `ALCHEMY_RPC_HTTP` (or `ARBY_RPC_HTTP_PRIMARY`) is set → use it (provider inferred from URL).
2. Else if `ALCHEMY_API_KEY` + `NETWORK`/`chain_id` → build Alchemy HTTP and WS URLs via `core.rpc_urls` and use those.
3. Else → fall back to a public RPC URL for the canonical network (e.g., `https://arb1.arbitrum.io/rpc`).

WS is optional: the gate/scanner will attempt to resolve a WS URL but will not fail if none is available unless `--ws-required` is passed to the gate.

The gate writes a small `infra` section into `scan` and `truth_report` artifacts (no secrets):

```
"infra": {
	"rpc_provider": "alchemy|public|fixture|unknown",
	"transport": "http|ws+http",
	"ws_enabled": false,
	"ws_connected": false,
	"ws_error": null,
	"tenderly_enabled": false
}
```

This makes it explicit whether WS/Tenderly were available and whether the scanner attempted a handshake.

Artifacts location (canonical): `data/runs/<run>/reports/scan_*.json`, `truth_report_*.json`, `reject_histogram_*.json`.

When debugging gate failures, the gate prints resolved artifact paths and schema_version to help identify mismatched runners.
