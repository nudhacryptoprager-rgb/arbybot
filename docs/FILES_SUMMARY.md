# PATH: docs/FILES_SUMMARY.md
# Issue #3 - Complete File List

## Core Module (`core/`)

| File | Purpose |
|------|---------|
| `__init__.py` | Package exports |
| `format_money.py` | Safe money formatting with ROUND_HALF_UP |
| `constants.py` | Enums (RejectReason, TradeOutcome), defaults |
| `exceptions.py` | Typed exceptions (InfraError, QuoteError, etc.) |
| `math.py` | Decimal math utilities (bps conversion, etc.) |
| `models.py` | Data models (Quote, Opportunity, Trade, PnLBreakdown) |
| `time.py` | Time/freshness utilities |
| `logging.py` | Structured logging formatters |

## Strategy Module (`strategy/`)

| File | Purpose |
|------|---------|
| `__init__.py` | Package exports |
| `paper_trading.py` | PaperTrade, PaperSession classes |
| `jobs/__init__.py` | Jobs package exports |
| `jobs/run_scan.py` | Scanner entry point |

## Monitoring Module (`monitoring/`)

| File | Purpose |
|------|---------|
| `__init__.py` | Package exports |
| `truth_report.py` | TruthReport, RPCHealthMetrics, build functions |

## Config (`config/`)

| File | Purpose |
|------|---------|
| `__init__.py` | Config loading utilities |
| `chains.yaml` | Chain configuration (RPC, explorers) |
| `dexes.yaml` | DEX protocol anchors |
| `core_tokens.yaml` | Core token addresses |
| `strategy.yaml` | Trading parameters |

## Tests (`tests/`)

| File | Purpose |
|------|---------|
| `conftest.py` | Pytest configuration |
| `unit/test_error_contract.py` | **Issue #3 AC tests** |
| `unit/test_paper_trading.py` | **Issue #3 AC tests** |
| `unit/test_confidence.py` | **Issue #3 AC tests** |
| `unit/test_format_money.py` | format_money tests |
| `unit/test_truth_report.py` | TruthReport tests |
| `unit/test_rounding.py` | ROUND_HALF_UP verification |
| `unit/test_health_metrics.py` | RPC health tests |
| `unit/test_logging_contract.py` | Logging API enforcement |
| `unit/test_decimal_safety.py` | No-float enforcement |
| `unit/test_integration.py` | End-to-end tests |
| `unit/test_backwards_compat.py` | API compatibility |
| `unit/test_smoke_artifacts.py` | Artifact generation tests |
| `unit/test_core_models.py` | Data model tests |
| `unit/test_math.py` | Math utility tests |
| `unit/test_time.py` | Time utility tests |
| `unit/test_config.py` | Config loading tests |
| `unit/test_validators.py` | Validator tests |
| `integration/test_smoke_run.py` | Full SMOKE integration test |

## Utils (`utils/`)

| File | Purpose |
|------|---------|
| `__init__.py` | Package init |
| `validators.py` | Validation utilities |

## Scripts (`scripts/`)

| File | Purpose |
|------|---------|
| `__init__.py` | Package init |
| `smoke_test.py` | SMOKE test runner |
| `verify_all.ps1` | PowerShell verification script |
| `run_all_tests.ps1` | Run all tests script |

## Docs (`docs/`)

| File | Purpose |
|------|---------|
| `ISSUE_3_CHECKLIST.md` | Issue #3 acceptance criteria checklist |
| `TESTING.md` | Testing guide |
| `FILES_SUMMARY.md` | This file |

## Root Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Python project configuration |
| `README.md` | Project readme |
| `.gitignore` | Git ignore rules |
| `.env.example` | Environment template |