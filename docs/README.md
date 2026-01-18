# PATH: README.md
# ARBY - Cryptocurrency Arbitrage Bot

## Overview

ARBY is a cryptocurrency arbitrage bot designed to identify and execute profitable 
DEX-to-DEX arbitrage opportunities across multiple Layer 2 networks.

## Project Structure
```
arby/
├── config/           # Configuration files (chains, dexes, tokens)
├── core/             # Core utilities (math, logging, models)
├── strategy/         # Trading strategy and paper trading
│   ├── jobs/         # CLI entry points
│   └── paper_trading.py
├── monitoring/       # Health monitoring and truth reports
├── tests/            # Unit and integration tests
│   └── unit/
└── data/             # Runtime data (runs, snapshots)
```

## Quick Start
```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/unit/ -v

# Run SMOKE scan
python -m strategy.jobs.run_scan --cycles 1 --output-dir data/runs/smoke_test
```

## Key Features

- **No Float Money**: All money values use Decimal/string (Roadmap 3.2)
- **Structured Logging**: Context via `extra={"context": {...}}` (Roadmap A)
- **RPC Health Tracking**: Consistent metrics with reject histogram
- **Paper Trading**: Simulated execution with PnL tracking

## Testing
```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test files
pytest tests/unit/test_error_contract.py -v
pytest tests/unit/test_paper_trading.py -v
pytest tests/unit/test_confidence.py -v
```

## Configuration

See `config/` directory for:
- `chains.yaml` - Network configuration
- `dexes.yaml` - DEX protocol anchors
- `strategy.yaml` - Trading parameters

## License

MIT