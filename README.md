# ARBY - DEX Arbitrage Engine

**Crypto Arbitrage Project with Truth Engine and Execution**

## Overview

ARBY is a multi-chain DEX-DEX arbitrage system designed to:
1. Generate **truthful executable opportunities** (Truth Engine)
2. Execute trades with **controlled risk** (Execution Engine)
3. Scale through **protocol adapters** (not hardcoded DEX logic)

## Quick Start

### Prerequisites

- Python 3.11+
- Alchemy API key
- (Optional) Tenderly account for simulation

### Installation

```bash
# Clone repository
git clone <repo-url>
cd arby

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Running

```bash
# Run scanner (single cycle)
python -m strategy.jobs.run_scan --chain arbitrum_one --once

# Run scanner (continuous)
python -m strategy.jobs.run_scan --chain arbitrum_one --interval 1000

# Run paper trading
python -m strategy.jobs.run_paper --chain arbitrum_one --duration 3600
```

## Project Structure

```
arby/
├── config/                 # Configuration (trust anchors + strategy)
│   ├── chains.yaml         # Network configuration
│   ├── core_tokens.yaml    # Verified token addresses
│   ├── dexes.yaml          # DEX contracts and adapter types
│   ├── fees.yaml           # Fee configuration
│   ├── strategy.yaml       # Trading parameters
│   └── intent.txt          # Target trading pairs
│
├── core/                   # Core utilities
│   ├── models.py           # Data models (Quote, Opportunity, Trade)
│   ├── constants.py        # Enums and constants
│   ├── exceptions.py       # Typed exceptions with error codes
│   ├── math.py             # Safe math (no float!)
│   ├── time.py             # Freshness and block pinning
│   └── logging.py          # Structured JSON logging
│
├── chains/                 # Blockchain interaction
├── dex/                    # DEX adapters
├── cex/                    # CEX adapters (future)
├── discovery/              # Pool/token discovery
├── engine/                 # Quote and opportunity engines
├── execution/              # Trade execution
├── strategy/               # Scanning and trading
│   └── jobs/               # CLI entrypoints
├── monitoring/             # Health and reporting
├── tests/                  # Unit and integration tests
└── data/                   # Generated data (gitignored)
```

## Core Principles

### 1. No Float Money
All monetary values use `int` (wei) or `Decimal`. Float is forbidden in quoting/price/PnL.

### 2. Directional Pricing
- DEX BUY = quote → base (ExactOutput)
- DEX SELL = base → quote (ExactInput)
- Mid price is forbidden for arbitrage evaluation

### 3. Every Reject Has a Reason
No silent failures. Every rejected opportunity has an error code:
`STALE_BLOCK`, `SLIPPAGE_TOO_HIGH`, `CEX_DEPTH_LOW`, etc.

### 4. Simulate Before Sign
No trade execution without prior simulation (eth_call/Tenderly).

## Milestones

See [Roadmap.md](Roadmap.md) for detailed development plan.

- **M0**: Bootstrap ✅
- **M1**: Truth Engine (quotes, freshness, PnL)
- **M2**: Adapters (V3, Algebra, V2)
- **M3**: Opportunity Engine (scoring, ranking)
- **M4**: Execution (simulation, private tx)
- **M5**: Production (reports, health)

## Configuration

### Adding a Chain

1. Add chain config to `config/chains.yaml`
2. Add core tokens to `config/core_tokens.yaml`
3. Add DEX configs to `config/dexes.yaml`
4. Add pairs to `config/intent.txt`

### Adding a DEX

1. Add DEX config to `config/dexes.yaml` with `adapter_type`
2. Ensure adapter exists in `dex/adapters/`
3. Add ABI to `dex/abi/` if needed

## Development

```bash
# Run tests
pytest

# Run linter
ruff check .

# Run formatter
black .

# Type checking
mypy .
```

## License

MIT