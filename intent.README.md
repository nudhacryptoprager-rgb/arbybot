# intent.txt (Canonical Universe)

`config/intent.txt` defines the **minimal trading universe** (pairs per chain) for scanning and execution.

This file is **version-controlled** and is the *only* source of truth for the minimal pair list.

## Format
One pair per line:

```
<chain_key>:<BASE>/<QUOTE>
```

Examples:
- `arbitrum_one:WETH/USDC`
- `base:AERO/USDC`

Comments start with `#`. Blank lines are allowed.

## What belongs here (and what does not)
### ✅ Belongs here
- The **minimal** list of pairs you want the system to support (by symbol).
- The target chain key (must match a key in `config/chains.yaml`).

### ❌ Does NOT belong here
- Token addresses, decimals, pool addresses, TVL/volume.
- “Best DEX” choices.

Those are derived dynamically via:
1) discovery (factory enumeration / optional DexScreener hints),
2) on-chain verification,
3) persistence to `data/registry.sqlite`.

## Workflow
### When this changes
Any PR that changes `config/intent.txt` **must** include:
1) A short rationale: why add/remove the pair.
2) A fresh run of `monitoring/truth_report.py` (or the CI artifact) demonstrating:
   - reject reasons histogram,
   - top opportunities (if any),
   - health (timeouts/reverts).

### CI / tooling expectations
- `discovery/intent_loader.py` parses this file.
- `discovery/index_factories.py` enumerates all pools for these pairs on supported DEX types (V3/V2/Algebra).
- `discovery/verify.py` verifies token/pool contracts on-chain and writes to `data/registry.sqlite`.

## Design intent
This file expresses **business intent**, not chain truth.
Symbols are only *names*; addresses are resolved and verified on-chain.

Last generated: 2026-01-04