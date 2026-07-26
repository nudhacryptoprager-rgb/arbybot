"""Fair per-pool data-quality scorecards for the M9 graph-arb scanner.

Problem
-------
The exotic / new-pool field is dominated by thin, microcap pools (e.g. the
``NEURAL_WETH`` family) whose every cycle overflows the depth-aware phantom
ceiling — collapsing ``qsr`` to 0.  We want to exclude those *structurally
toxic* pools **early**, but the previous filters were too blunt:

* a single bad cycle / one oversized size could condemn a pool, and
* a deep, honest pool dragged into a phantom cycle by a thin partner was
  blamed for its partner's toxicity.

Methodology (fair evaluation)
-----------------------------
Every found pool earns a verdict only from *confirmed, attributed evidence*:

1. **Fair sample first.** Below ``min_samples`` non-transient observations a
   pool stays ``LOW_SAMPLE`` (keep + keep probing) — never quarantined.  The
   system must *achieve* confirmed data from each pool before judging it.
2. **A valid quote is credit.** Any cycle that reaches ``POSITIVE_GROSS`` /
   ``NEGATIVE_GROSS`` is honest, usable data for *every* pool in it — even when
   the spread is unprofitable.  Producing valid data ⇒ the pool is a real data
   source ⇒ ``HEALTHY`` ⇒ never excluded.
3. **Transient noise is ignored.** RPC / revert / timeout errors are excluded
   from the denominator so a flaky provider never condemns a pool.
4. **Blame the bottleneck, not its partners.** A depth overflow (``PHANTOM`` /
   ``OVERSIZED_VS_DEPTH``) is attributed to the *thinnest* pool of the cycle
   (the bottleneck ``effective_depth_usd``).  Deeper partners that returned a
   usable leg quote are credited as ``VALID``.
5. **Toxic needs consistency.** ``TOXIC`` (a quarantine recommendation) requires
   enough samples, ~zero valid rate, a dominant structural / depth-toxic
   signature, **and** failure across ``>= min_sizes_for_toxic`` distinct sizes —
   so we know the depth-capped ladder was honestly exhausted, not just one
   oversized size.
6. **Soft, reversible quarantine.** A recommendation carries a ``retry_after_utc``
   TTL: the pool is re-evaluated later, never permanently condemned.

Design rules
------------
* Every function is **pure** (no RPC / IO) so it is unit-testable offline.
* Public API is **additive** — nothing here renames or removes existing symbols.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from m9.graph_arb.models import CycleQuoteResult

# --- per-observation outcome categories -----------------------------------
OUTCOME_VALID = "VALID"                    # honest, usable quote (credit)
OUTCOME_DEPTH_OVERFLOW = "DEPTH_OVERFLOW"  # phantom / oversized vs depth (bottleneck)
OUTCOME_STRUCTURAL_ZERO = "STRUCTURAL_ZERO"  # quote returned zero output
OUTCOME_TRANSIENT = "TRANSIENT"            # RPC / revert / timeout (ignored)
OUTCOME_FAILED = "FAILED"                  # other quote failure
OUTCOME_TOXIC_STABLE = "TOXIC_STABLE_POOL"  # stable-pair ratio outlier (structural)

# --- per-pool classifications ---------------------------------------------
CLASS_HEALTHY = "HEALTHY"        # confirmed valid data → keep
CLASS_PROBATION = "PROBATION"    # mixed / ambiguous → keep + keep observing
CLASS_LOW_SAMPLE = "LOW_SAMPLE"  # not enough evidence yet → keep + keep probing
CLASS_TOXIC = "TOXIC"            # consistently no valid data → quarantine (soft)

# --- quarantine reject reasons (surfaced into recommendation entries) ------
REASON_DEPTH_TOXIC = "DEPTH_TOXIC_NO_VALID_DATA"
REASON_STRUCTURAL_ZERO = "STRUCTURAL_ZERO_OUTPUT"
REASON_TOXIC_STABLE = "TOXIC_STABLE_POOL_RATIO_OUTLIER"

# Cycle reject reasons that mean "depth overflow" (not a quote failure).
_DEPTH_OVERFLOW_REASONS = frozenset({"PHANTOM_QUOTE_BPS_OVERFLOW", "OVERSIZED_VS_DEPTH"})
# Cycle statuses that mean a usable round-trip quote was produced.
_VALID_STATUSES = frozenset({"POSITIVE_GROSS", "NEGATIVE_GROSS"})
# Substrings marking a transient (non-structural) leg failure.
_TRANSIENT_MARKERS = ("RPC", "REVERT", "TIMEOUT", "THROTTLE", "COOLDOWN")


@dataclass(frozen=True)
class ScorecardConfig:
    """Thresholds governing the fair pool-evaluation methodology."""

    min_samples: int = 8              # min non-transient obs before any verdict
    min_sizes_for_toxic: int = 2      # distinct sizes that must fail before TOXIC
    min_blocks_for_toxic_stable: int = 3  # repeated same-size invariant across buckets
    healthy_valid_rate: float = 0.10  # valid_rate at/above which a pool is HEALTHY
    toxic_dominance_rate: float = 0.90  # depth/zero share required for TOXIC
    quarantine_ttl_hours: float = 6.0   # soft retry TTL on a recommendation


@dataclass
class PoolObservation:
    """Mutable accumulator of one pool's quote outcomes across a run."""

    pool_address: str
    pair_id: str
    dex_id: str
    fee_bps: float
    fee: int
    valid: int = 0
    depth_overflow: int = 0
    structural_zero: int = 0
    toxic_stable: int = 0
    transient: int = 0
    failed: int = 0
    sizes_tested: Set[float] = field(default_factory=set)
    sizes_valid: Set[float] = field(default_factory=set)
    toxic_stable_buckets: Set[tuple] = field(default_factory=set)

    def record(self, outcome: str, size_usd: float, *, time_bucket: int = 0) -> None:
        if outcome == OUTCOME_VALID:
            self.valid += 1
            self.sizes_valid.add(size_usd)
        elif outcome == OUTCOME_DEPTH_OVERFLOW:
            self.depth_overflow += 1
        elif outcome == OUTCOME_STRUCTURAL_ZERO:
            self.structural_zero += 1
        elif outcome == OUTCOME_TOXIC_STABLE:
            self.toxic_stable += 1
            self.toxic_stable_buckets.add((round(float(size_usd), 4), int(time_bucket)))
        elif outcome == OUTCOME_TRANSIENT:
            self.transient += 1
        else:
            self.failed += 1
        # Transient observations don't count as a real "test" of the pool.
        if outcome != OUTCOME_TRANSIENT:
            self.sizes_tested.add(size_usd)


def classify_leg_reject(reason: Optional[str]) -> str:
    """Map a per-leg reject_reason to an observation outcome.

    Transient (RPC/revert/timeout) failures are *not* held against the pool;
    a zero-output quote is structural; a stable-pool ratio outlier is a
    structural toxicity signal (TOXIC_STABLE_POOL) that should feed the
    quarantine recommender rather than be lumped with generic FAILED.
    """
    if not reason:
        return OUTCOME_FAILED
    upper = reason.upper()
    if "TOXIC_STABLE_POOL" in upper or "STABLE_RATIO_OUTLIER" in upper:
        return OUTCOME_TOXIC_STABLE
    if "ZERO_OUTPUT" in upper:
        return OUTCOME_STRUCTURAL_ZERO
    if any(marker in upper for marker in _TRANSIENT_MARKERS):
        return OUTCOME_TRANSIENT
    return OUTCOME_FAILED


def _bottleneck_pool_keys(qr: CycleQuoteResult) -> Set[str]:
    """Pool addresses (lower) of the cycle's thinnest edge(s).

    When no edge carries a measured depth we cannot single out a culprit, so
    every edge is treated as a bottleneck (conservative, but multi-size +
    sample gates still protect honest pools).
    """
    depths = [
        e.effective_depth_usd
        for e in qr.cycle.edges
        if isinstance(e.effective_depth_usd, (int, float))
    ]
    if not depths:
        return {e.pool_address.lower() for e in qr.cycle.edges}
    bottleneck = min(depths)
    return {
        e.pool_address.lower()
        for e in qr.cycle.edges
        if isinstance(e.effective_depth_usd, (int, float))
        and e.effective_depth_usd <= bottleneck
    }


def accumulate_observations(
    cycle_results: List[CycleQuoteResult],
) -> Dict[str, PoolObservation]:
    """Attribute each cycle's outcome fairly to the pools that caused it."""
    pools: Dict[str, PoolObservation] = {}

    def _obs(edge) -> PoolObservation:
        key = edge.pool_address.lower()
        obs = pools.get(key)
        if obs is None:
            fee_raw = getattr(edge, "fee", None)
            try:
                fee_int = int(fee_raw)
            except (TypeError, ValueError):
                fee_int = 0
            obs = PoolObservation(
                pool_address=edge.pool_address,
                pair_id=edge.pair_id,
                dex_id=edge.dex_id,
                fee_bps=round(edge.fee_bps, 4),
                fee=fee_int,
            )
            pools[key] = obs
        return obs

    for sweep_idx, qr in enumerate(cycle_results):
        size = qr.size_usd
        edges = qr.cycle.edges
        time_bucket = sweep_idx // 8

        # (1) Cycle produced a usable round-trip quote → credit every pool.
        if qr.status in _VALID_STATUSES:
            for edge in edges:
                _obs(edge).record(OUTCOME_VALID, size, time_bucket=time_bucket)
            continue

        # (2) Depth overflow → blame the bottleneck, credit deeper partners.
        if qr.reject_reason in _DEPTH_OVERFLOW_REASONS:
            bottleneck = _bottleneck_pool_keys(qr)
            for edge in edges:
                if edge.pool_address.lower() in bottleneck:
                    _obs(edge).record(OUTCOME_DEPTH_OVERFLOW, size, time_bucket=time_bucket)
                else:
                    _obs(edge).record(OUTCOME_VALID, size, time_bucket=time_bucket)
            continue

        # (3) Leg-level failure → walk legs positionally; credit legs that
        #     returned ok, attribute the first failing leg to its pool, and
        #     leave untested downstream pools alone.
        legs = qr.leg_results or []
        for i, leg in enumerate(legs):
            if i >= len(edges):
                break
            edge = edges[i]
            if getattr(leg, "ok", False):
                _obs(edge).record(OUTCOME_VALID, size, time_bucket=time_bucket)
            else:
                _obs(edge).record(
                    classify_leg_reject(leg.reject_reason),
                    size,
                    time_bucket=time_bucket,
                )
                break

    return pools


def _classify(obs: PoolObservation, config: ScorecardConfig) -> tuple[str, float, str]:
    """Return (classification, valid_rate, toxic_reason)."""
    non_transient = (
        obs.valid + obs.depth_overflow + obs.structural_zero + obs.toxic_stable + obs.failed
    )
    denom = max(1, non_transient)
    valid_rate = obs.valid / denom
    toxic_signal = obs.depth_overflow + obs.structural_zero + obs.toxic_stable
    toxic_rate = toxic_signal / denom
    # Pick the dominant structural reason. TOXIC_STABLE_POOL is a protocol
    # invariant failure (stable-pair ratio outlier) — it should surface as
    # its own reason, not be masked by depth-overflow counts.
    if obs.toxic_stable > max(obs.structural_zero, obs.depth_overflow):
        toxic_reason = REASON_TOXIC_STABLE
    elif obs.structural_zero > obs.depth_overflow:
        toxic_reason = REASON_STRUCTURAL_ZERO
    else:
        toxic_reason = REASON_DEPTH_TOXIC

    if non_transient < config.min_samples:
        return CLASS_LOW_SAMPLE, valid_rate, toxic_reason
    if valid_rate >= config.healthy_valid_rate:
        return CLASS_HEALTHY, valid_rate, toxic_reason
    toxic_stable_same_size_buckets = {
        size
        for size, _bucket in obs.toxic_stable_buckets
        if sum(1 for s, _ in obs.toxic_stable_buckets if s == size) >= config.min_blocks_for_toxic_stable
    }
    if (
        obs.valid == 0
        and toxic_rate >= config.toxic_dominance_rate
        and toxic_reason == REASON_TOXIC_STABLE
        and obs.toxic_stable >= config.min_samples
        and toxic_stable_same_size_buckets
    ):
        return CLASS_TOXIC, valid_rate, toxic_reason
    if (
        obs.valid == 0
        and toxic_rate >= config.toxic_dominance_rate
        and len(obs.sizes_tested) >= config.min_sizes_for_toxic
    ):
        return CLASS_TOXIC, valid_rate, toxic_reason
    return CLASS_PROBATION, valid_rate, toxic_reason


def build_pool_scorecards(
    cycle_results: List[CycleQuoteResult],
    config: Optional[ScorecardConfig] = None,
) -> List[Dict[str, object]]:
    """Produce one honest scorecard per observed pool.

    Sorted TOXIC first (by toxic signal), then by total observations, so the
    operator / dashboard sees the worst offenders at the top.
    """
    cfg = config or ScorecardConfig()
    pools = accumulate_observations(cycle_results)
    cards: List[Dict[str, object]] = []
    for obs in pools.values():
        classification, valid_rate, toxic_reason = _classify(obs, cfg)
        non_transient = (
            obs.valid + obs.depth_overflow + obs.structural_zero + obs.toxic_stable + obs.failed
        )
        cards.append(
            {
                "pool_address": obs.pool_address,
                "pair_id": obs.pair_id,
                "dex_id": obs.dex_id,
                "fee_bps": obs.fee_bps,
                "fee": obs.fee,
                "classification": classification,
                "valid_count": obs.valid,
                "depth_overflow_count": obs.depth_overflow,
                "structural_zero_count": obs.structural_zero,
                "toxic_stable_count": obs.toxic_stable,
                "failed_count": obs.failed,
                "transient_count": obs.transient,
                "samples": non_transient,
                "valid_rate": round(valid_rate, 4),
                "sizes_tested": sorted(obs.sizes_tested),
                "sizes_valid": sorted(obs.sizes_valid),
                "toxic_reason": toxic_reason if classification == CLASS_TOXIC else None,
            }
        )

    _class_rank = {CLASS_TOXIC: 0, CLASS_PROBATION: 1, CLASS_LOW_SAMPLE: 2, CLASS_HEALTHY: 3}
    cards.sort(
        key=lambda c: (
            _class_rank.get(c["classification"], 9),
            -(
                int(c["depth_overflow_count"])
                + int(c["structural_zero_count"])
                + int(c.get("toxic_stable_count") or 0)
            ),
            -int(c["samples"]),
        )
    )
    return cards


def recommend_quarantine(
    scorecards: List[Dict[str, object]],
    config: Optional[ScorecardConfig] = None,
    now_utc: Optional[datetime] = None,
) -> List[Dict[str, object]]:
    """Build soft quarantine entries (m9_pool_depth_quarantine schema) for TOXIC pools.

    Each entry carries a ``retry_after_utc`` TTL so the pool is re-evaluated
    later — the recommendation is reversible by construction.
    """
    cfg = config or ScorecardConfig()
    now = now_utc or datetime.now(timezone.utc)
    retry_after = (now + timedelta(hours=cfg.quarantine_ttl_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    entries: List[Dict[str, object]] = []
    for card in scorecards:
        if card.get("classification") != CLASS_TOXIC:
            continue
        entries.append(
            {
                "pool_address": card["pool_address"],
                "pair_id": card["pair_id"],
                "fee": card["fee"],
                "reject_reason": card["toxic_reason"],
                "retry_after_utc": retry_after,
                "source": "pool_scorecard",
                "samples": card["samples"],
                "valid_rate": card["valid_rate"],
            }
        )
    return entries


def session_pool_quarantine_path(session_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(session_id))
    return f"data/tmp/m9_pool_quarantine_session_{safe}.json"


def materialize_session_pool_quarantine(
    recommendations: List[Dict[str, object]],
    *,
    session_id: str,
    output_path: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> Optional[str]:
    """Write session-bound pool quarantine artifact for runner admission."""
    if not recommendations or not str(session_id or "").strip():
        return None
    from pathlib import Path

    import json

    path = str(output_path or session_pool_quarantine_path(session_id))
    now = now_utc or datetime.now(timezone.utc)
    doc = {
        "schema_version": "m9_pool_depth_quarantine_session.1",
        "session_id": str(session_id),
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "route_count": len(recommendations),
        "routes": recommendations,
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return str(out)


def load_session_pool_quarantine_addresses(
    session_id: str,
    *,
    output_path: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> Set[str]:
    """Load pool addresses from a session-bound quarantine artifact."""
    from pathlib import Path

    import json

    path = Path(output_path or session_pool_quarantine_path(session_id))
    if not path.is_file():
        return set()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if str(doc.get("session_id") or "") != str(session_id):
        return set()
    now = now_utc or datetime.now(timezone.utc)
    pools: Set[str] = set()
    for entry in doc.get("routes") or []:
        retry_raw = (entry or {}).get("retry_after_utc")
        if retry_raw:
            try:
                retry_at = datetime.fromisoformat(
                    str(retry_raw).replace("Z", "+00:00")
                )
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                if retry_at <= now:
                    continue
            except (TypeError, ValueError):
                pass
        addr = str((entry or {}).get("pool_address") or "").lower()
        if addr:
            pools.add(addr)
    return pools


def merge_pool_observations(
    existing: Dict[str, PoolObservation],
    cycle_results: List[CycleQuoteResult],
) -> Dict[str, PoolObservation]:
    """Incrementally merge sweep observations into a session-long accumulator."""
    fresh = accumulate_observations(cycle_results)
    for key, obs in fresh.items():
        cur = existing.get(key)
        if cur is None:
            existing[key] = obs
            continue
        cur.valid += obs.valid
        cur.depth_overflow += obs.depth_overflow
        cur.structural_zero += obs.structural_zero
        cur.toxic_stable += obs.toxic_stable
        cur.transient += obs.transient
        cur.failed += obs.failed
        cur.sizes_tested.update(obs.sizes_tested)
        cur.sizes_valid.update(obs.sizes_valid)
        cur.toxic_stable_buckets.update(obs.toxic_stable_buckets)
    return existing


def build_pool_scorecards_from_observations(
    pools: Dict[str, PoolObservation],
    config: Optional[ScorecardConfig] = None,
) -> List[Dict[str, object]]:
    """Build scorecards from merged observations without re-scanning cycle rows."""
    cfg = config or ScorecardConfig()
    cards: List[Dict[str, object]] = []
    for obs in pools.values():
        classification, valid_rate, toxic_reason = _classify(obs, cfg)
        non_transient = (
            obs.valid + obs.depth_overflow + obs.structural_zero + obs.toxic_stable + obs.failed
        )
        cards.append(
            {
                "pool_address": obs.pool_address,
                "pair_id": obs.pair_id,
                "dex_id": obs.dex_id,
                "fee_bps": obs.fee_bps,
                "fee": obs.fee,
                "classification": classification,
                "valid_count": obs.valid,
                "depth_overflow_count": obs.depth_overflow,
                "structural_zero_count": obs.structural_zero,
                "toxic_stable_count": obs.toxic_stable,
                "failed_count": obs.failed,
                "transient_count": obs.transient,
                "samples": non_transient,
                "valid_rate": round(valid_rate, 4),
                "sizes_tested": sorted(obs.sizes_tested),
                "sizes_valid": sorted(obs.sizes_valid),
                "toxic_reason": toxic_reason if classification == CLASS_TOXIC else None,
            }
        )
    _class_rank = {CLASS_TOXIC: 0, CLASS_PROBATION: 1, CLASS_LOW_SAMPLE: 2, CLASS_HEALTHY: 3}
    cards.sort(
        key=lambda c: (
            _class_rank.get(c["classification"], 9),
            -(
                int(c["depth_overflow_count"])
                + int(c["structural_zero_count"])
                + int(c.get("toxic_stable_count") or 0)
            ),
            -int(c["samples"]),
        )
    )
    return cards


def refresh_session_pool_quarantine(
    cycle_results: List[CycleQuoteResult],
    *,
    session_id: str,
    config: Optional[ScorecardConfig] = None,
    output_path: Optional[str] = None,
    observations: Optional[Dict[str, PoolObservation]] = None,
) -> Set[str]:
    """Score, materialize, and reload session quarantine for the next admission boundary."""
    path = output_path or session_pool_quarantine_path(session_id)
    if observations is not None:
        cards = build_pool_scorecards_from_observations(observations, config)
    else:
        cards = build_pool_scorecards(cycle_results, config)
    recs = recommend_quarantine(cards, config)
    if recs:
        materialize_session_pool_quarantine(
            recs,
            session_id=session_id,
            output_path=path,
        )
    return load_session_pool_quarantine_addresses(session_id, output_path=path)
