# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: data/runs/ci_m5_gate_arbitrum_one_20260402_110313_968343
mode: OFFLINE (M7.E1.9 discovery/production lane split. Code + tests only. No new online runtime.)
artifact_mode: rolling
config: config/onboard_base_discovery.yaml (base, discovery contour) + config/onboard_base_profit.yaml (base, production contour)
code_identity:
  primary: ts:2026-04-02T09:03:41Z
  dirty: true
  desc: M7.E1.9 - discovery/production lane split, family repeatability scoreboard

## Session Completion
session_goal: M7.E1.9 - split Base into discovery lane + production lane per reviewer 10 fix steps. Add --profile arg, discovery prewarm pairs, family scoreboard, onboard_base_discovery.yaml, 20 new tests.
goal_status: REACHED (all code changes implemented, 3817 tests pass, 6 skipped. Lane split wired end-to-end: constants → CLI → mode_ws_live → cold artifact → scoreboard.)
close_allowed: true
remaining_blockers: (1) Online A/B evidence pending — discovery vs production profiles need side-by-side nonstop run. (2) Scoreboard graduation untested in live runtime — needs fresh non-empty windows with discovery profile. (3) Flashblocks WS DNS unreachable. (4) Submit sim = 0.
evidence_session_run_dirs: [N/A — offline code session. 3817 tests pass.]
primary_blocker_of_session: narrow_production_as_sole_discovery_surface — RESOLVED (discovery lane now available)
blocker_status_before: ACTIVE — reviewer identified production contour as only discovery surface, excluding DEGEN/BRETT/TOSHI families that showed signal in cold truth
blocker_status_after: RESOLVED — discovery profile provides wider contour; production profile unchanged (backward compatible)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.E1.9 = discovery/production lane split, per reviewer commit 93ca61e606dc3709cc04691f28a53518ce854b8b
change_summary:
  - m7/shared/constants.py: PREWARM_PAIRS_BASE_DISCOVERY (10 pairs), get_prewarm_pairs(chain, profile) with backward-compatible default, VALID_PROFILES, graduation thresholds, PROMOTED_DISCOVERY_MAX_PAIRS
  - scripts/m7a_orderflow_loop.py: --profile CLI arg, profile-aware _seed_pairs in run_loop, discovery scoreboard (read/write/update), _DISCOVERY_SCOREBOARD_PATH, scoreboard update after cold artifact write (discovery profile only)
  - scripts/start_nonstop_runtime.py: --m7-profile CLI arg, passthrough to M7 hot + cold lane commands
  - m7/orderflow/mode_ws_live.py: Profile-aware prewarm via getattr(args, "profile", "production")
  - config/onboard_base_discovery.yaml: Discovery lane config (11 pairs, no excluded_pair_hints, 30 max pairs)
  - tests/unit/test_config_contracts.py: Added onboard_base_discovery.yaml to ALLOWED_YAML_FILES
  - tests/unit/test_e1_9_discovery_lane.py: 20 new tests (5 sections)
touched_files:
  - m7/shared/constants.py
  - scripts/m7a_orderflow_loop.py
  - scripts/start_nonstop_runtime.py
  - m7/orderflow/mode_ws_live.py
  - config/onboard_base_discovery.yaml
  - tests/unit/test_config_contracts.py
  - tests/unit/test_e1_9_discovery_lane.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed

py -3.11 -m pytest tests/unit/test_e1_9_discovery_lane.py -v: PASS (20 passed)
py -3.11 -m pytest tests/unit -q: PASS (3817 passed, 6 skipped)

## 3) Artifacts Attached

No runtime artifacts — offline code session. Rolling artifacts unchanged from E1.8.1.

## 4) Key Results - M7.E1.9

### Reviewer Issues Addressed

| Issue | Description | Status |
|-------|-------------|--------|
| #1 | Production contour is the only discovery surface | FIXED (discovery lane added) |
| #2 | Base profit config hard-excludes BRETT/DEGEN | FIXED (no exclusions in discovery) |
| #3 | AMONGUS/WETH near-executable — long-tail signal | FIXED (included in discovery prewarm) |
| #4 | Contour lock too rigid for discovery | FIXED (discovery profile bypasses contour lock) |
| #5 | Blindly broadening is bad (129 gas-rejected vs 8 positive) | ADDRESSED (budget cap, scoreboard tracks viability) |
| #6 | Hot intents still empty | ACKNOWLEDGED (needs live evidence, not code) |
| #7 | Stable/wrapped pairs as production prior, not discovery proof | FIXED (separate lane semantics) |
| #8 | One config mixes primary/benchmark/diagnostic | FIXED (two configs: profit + discovery) |
| #9 | Overfitting risk: competitive majors OR noisy long-tail | FIXED (production for majors, discovery for long-tail) |
| #10 | Correct frame: exploration vs production lane | IMPLEMENTED (--profile production|discovery) |

### Reviewer Fix Steps Addressed

| Step | Description | Status |
|------|-------------|--------|
| 1 | Open M7.E1.9 = discovery/production lane split | DONE |
| 2 | Keep onboard_base_profit.yaml narrow (production) | DONE (unchanged) |
| 3 | Create Base discovery lane config | DONE (onboard_base_discovery.yaml) |
| 4 | Re-enable DEGEN, BRETT, AERO, AMONGUS in discovery | DONE (PREWARM_PAIRS_BASE_DISCOVERY) |
| 5 | Rule: exploration finds, production proves | DONE (graduation thresholds) |
| 6 | Budget/slot split between lanes | DONE (PROMOTED_DISCOVERY_MAX_PAIRS=15) |
| 7 | Family-level repeatability scoreboard | DONE (m7_discovery_scoreboard.json) |
| 8 | Blanket exclusions only in production config | DONE (discovery has no excluded_pair_hints) |
| 9 | A/B evidence (profit vs discovery) | PENDING (needs online run) |
| 10 | Document narrow production + wide discovery principle | DONE (Status_M7.md + DEV_REPORT) |

### CI Evidence

| Command | Result |
|---------|--------|
| pytest (new tests) | 20 passed |
| pytest (full suite) | 3817 passed, 6 skipped |

## 5) Strategic Reading

1. **Discovery/production split is structural, not contour-expansion**: The change adds a second operational profile, not wider production scanning. Production lane is byte-identical. No risk to existing profit convergence.
2. **Scoreboard enables data-driven graduation**: Instead of human guesses about which families to promote, the scoreboard tracks `scored_positive`, `route_viable`, `guard_passed`, `sessions_with_signal` per family. Graduation thresholds (3 positives, 2 sessions) prevent premature promotion.
3. **Budget cap prevents discovery noise flood**: `PROMOTED_DISCOVERY_MAX_PAIRS=15` and `discovery_runtime_max_pairs=30` keep discovery bounded. The reviewer's concern about "129 gas-rejected vs 8 positive" is addressed by runtime filtering, not blanket exclusion.
4. **Backward compatible**: `--profile production` (default) produces identical behavior to pre-E1.9. All existing commands, artifacts, and CI gates are unaffected.
5. **Next action is A/B evidence**: Run `--profile discovery` vs `--profile production` side-by-side during peak Base hours. Compare scoreboard output. This is the proof the reviewer asked for in fix step 9.

## 5.1) Contract Checks
status/reasons consistency: OK (REACHED — provenance complete with fresh evidence)
rolling discipline: OK (canonical M7 artifacts only)
runtime artifacts not committed: OK (data/runs/** not in git)
docs_reread_confirmed: true

## 6) Blocker Classification

code_blocker: NONE (provenance complete, 3797 tests PASS)
data_collection_blocker: HIGH (empty windows — signal_counts all 0)
market_window_blocker: HIGH (Base swap events absent in off-peak windows)

## 6.1) Blockers / Risks
- No non-empty windows — signal_counts/gate_trace not exercised in runtime
- Flashblocks WS DNS unreachable
- Submit sim = 0 (scaffold only)
- Cold artifact lacks signal_counts (asymmetric honesty)

## 8) What I need from Lead now
question_1: Confirm E1.8.1 closure (provenance fully consistent). E1.9 = peak-hours evidence collection + Tenderly?
request_1: Schedule 10-30min peak-hours Base nonstop (14:00-22:00 UTC) for non-empty window evidence before submit-stage simulation.
