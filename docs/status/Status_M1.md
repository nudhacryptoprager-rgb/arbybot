# Status M1 — Real Gas Price + Paper Trading

_Last cleaned: 2026-01-21_

## Scope
M1 adds: real gas price from RPC, paper-trading session plumbing, and schema fields needed for PnL representation (without floats).

## Done (per `docs/Status_M1.md`)
- Real gas price fetched from RPC (`eth_gasPrice`) and surfaced into snapshots / reporting.
- Paper-trading simulation layer (session, record trade, summary).
- Spread schema expanded for PnL (string money fields / no-float expectations).
- Curve gates fixes aligned with quote pipeline (reject reasons not crashing the run).
- Tests green at the time of the status document (see original for exact count).

## Evidence
Source document:
- `docs/Status_M1.md`

## Next steps (as stated in M1, target = M2)
1. **Slippage simulation** — estimate actual fill price
2. **Trade tracking** — accumulate paper PnL over time
3. **Router simulation** — simulate swap tx
4. **Multiple pairs** — expand beyond WETH/USDC
---
*Документ згенеровано: 2026-01-11*

## Verify (Windows / PowerShell)
```powershell
python -m pytest -q
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data\runs\smoke_m1_check
```
