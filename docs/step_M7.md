# M7 - Triangular Feasibility and Controlled Execution Gate

## Purpose

This document is the canonical working specification for Milestone 7.

M7 exists to answer one bounded question:

**Can triangular DEX↔DEX↔DEX cycles, evaluated with the same measured-truth discipline as the current system, produce materially better economics than the closed public two-leg thesis?**

M7 must not begin as a broad strategy expansion. It begins as a tightly controlled research phase that reuses the current data, quoting, truth, sweep, and rolling infrastructure.

---

## Phase Split

M7 is divided into two separate phases.

### M7.A - Triangular Feasibility

Read-only research phase.

Deliverables:
- graph builder
- cycle finder
- measured cycle scoring
- canonical triangular truth artifacts

Forbidden in M7.A:
- real atomic execution
- private submission
- new paid infrastructure
- cross-chain routing

### M7.B - Atomic Multi-hop Execution

Execution phase.

This phase is closed by default and may only open if M7.A proves a repeatable measured edge that is materially better than the closed public two-leg thesis.

---

## Core Thesis

M7 is not allowed to optimize for raw cycle count or raw spread.

The only thing that matters is **measured executable net-after-cost**.

Triangular work is justified only if it shows repeatable cycle economics that are stronger than the current public-infrastructure two-leg ceiling. If it does not, M7 must stop at M7.A and remain a frozen R&D branch.

---

## Scope Boundary

### One-chain start

The first scope of M7 must be single-chain.

The first chain is `arbitrum_one`, not because it is already profitable, but because it currently provides the richest executable evidence surface in the project. That makes it the best engineering testbed for graph truth, cycle scoring, and artifact discipline.

`base` remains relevant as a later validation chain, but it is not the first build target for M7.A.

### Narrow universe

The first scope must be narrow.

Only include:
- core and liquid token pairs
- DEXes and adapter types that already work stably in the current repo
- pools that already participate in the existing quote and truth path

Do not expand:
- chains
- adapters
- token universe
- DEX universe

all at the same time.

### Verified pool graph only

The graph must be built from verified executable edges, not from symbolic token adjacency.

Graph rules:
- node = token
- edge = concrete on-chain pool on a supported adapter
- each edge must have a resolved pool address
- each edge must have known adapter semantics
- each edge must be directional for quoting purposes

A token pair is not enough to create a graph edge. The edge must correspond to a real pool that the current system can quote and reason about.

---

## Cycle Finder Constraints

The first cycle finder must be limited to `3-hop simple cycles`.

Allowed form:
- `A -> B -> C -> A`

Forbidden in the first phase:
- `4+` hop cycles
- repeated-token degenerate loops
- repeated-edge loops
- cross-chain cycles
- aggregator routing
- recursive route expansion

The goal of M7.A is controlled truth discovery, not maximum route breadth.

---

## Canonical Truth Model

Triangular truth must reuse the same measured-cost discipline already established by the current roundtrip engine.

Cycle ranking is allowed only after the following are accounted for:
- fees on every leg
- slippage on every leg
- gas
- route viability
- provenance quality

Raw graph edge is diagnostic only.

It must never drive promotion into canonical truth.

---

## Required Cycle Artifact

Every candidate triangular cycle must produce a machine-readable decomposition artifact.

Minimum required fields:
- `gross_bps`
- `fee_leg1_bps`
- `fee_leg2_bps`
- `fee_leg3_bps`
- `slippage_leg1_bps`
- `slippage_leg2_bps`
- `slippage_leg3_bps`
- `gas_bps`
- `final_net_bps`
- `best_size_usd`
- `block_tag`
- `provenance_summary`

Recommended supporting fields:
- pool identity per leg
- adapter type per leg
- fee tier per leg
- size curve summary
- route viability flags
- reject or demotion reason

The artifact must make it obvious which leg is binding and why the cycle survives or fails.

---

## Same-state Acceptance Criterion

Same-state or same-snapshot consistency is a hard acceptance criterion for M7.A.

A cycle may remain diagnostic if snapshot provenance is incomplete, but it must not be promoted into canonical truth unless the system can clearly record a sufficiently consistent market state for all legs.

Classification rules:
- `same_state_proven` -> eligible for canonical truth
- `same_state_ambiguous` -> diagnostic only
- `same_state_violated` -> reject

If a cycle is near breakeven, provenance discipline must be stricter, not looser.

---

## Ranking and Promotion Rules

Cycle ranking must be driven by `final_net_bps`, not by raw spread.

Promotion rules:
- only cycles with full decomposition may enter canonical truth
- only cycles with acceptable route viability may enter canonical truth
- only cycles with acceptable provenance may enter canonical truth
- cycles with attractive gross edge but weak measured net remain diagnostic only

The first purpose of M7 is explainable truth, not optimistic opportunity inflation.

---

## Acceptance Criteria for M7.A

M7.A is considered successful only if all of the following become true:
- graph build is stable on the chosen one-chain narrow universe
- cycle finder produces valid `3-hop simple cycles`
- every promoted cycle has a full measured decomposition artifact
- provenance-aware evaluation works consistently
- fresh rolling evidence shows repeatable triangular cycles
- those cycles are materially better than the closed public two-leg thesis on a measured net basis

Anything weaker than this is not enough to open execution.

---

## Gate to M7.B

Atomic execution is strictly stage-gated.

M7.B may start only if M7.A demonstrates:
- repeatable triangular cycles
- measured net-after-cost superiority over the closed two-leg public thesis
- stable artifact discipline
- acceptable provenance quality
- candidate quality high enough to justify execution complexity

Execution must not be used to rescue a weak read-only thesis.

---

## Stop Condition

M7 must have a hard stop-condition from the start.

If bounded read-only triangular work does not produce repeatable, provenance-aware, measured economics that clearly outperform the closed public two-leg thesis, then:
- M7.A is considered a valid negative outcome
- M7.B does not open
- M7 is frozen as an R&D branch
- the team does not expand hops, chains, or adapters just to keep the branch alive

This stop-condition is part of the milestone contract, not a fallback opinion.

---

## Non-goals for M7.A

M7.A does not attempt to solve:
- private orderflow
- builder integration
- cross-chain settlement
- paid execution infrastructure
- broad multi-chain routing
- aggregator-as-black-box path finding
- production execution state machine for multi-hop trades

Those belong either to M7.B or to separate future milestones.

---

## Implementation Order

The intended development order for M7.A is:

1. build the verified pool graph on `arbitrum_one`
2. restrict the graph to the narrow approved universe
3. implement `3-hop simple cycle` discovery
4. score cycles with the current measured-cost model
5. emit full decomposition artifacts
6. apply provenance and same-state classification
7. rank only by measured final net
8. decide whether M7 stops or graduates to M7.B

---

## Canonical Interpretation

M7 is not the automatic continuation of the previous milestone.

It is an explicitly bounded research branch that uses the current project's strongest assets:
- stable data collection
- measured truth discipline
- rolling evidence
- explainable artifacts

Its success condition is not "we built a graph engine".

Its success condition is "the graph engine proved a repeatable measured edge strong enough to justify multi-hop execution."
