"""Priority-based cycle scheduler for M9 graph-arb scanner.

Implements a 2-tier queue:
  - hot_queue:  high-priority cycles (top 80% by score) — quoted every sweep
  - cold_queue: deferred cycles (bottom 20% by score) — quoted at 1:COLD_RATIO rate

Priority score components (higher = better candidate):
  1. factory_class quality: EFFICIENT_BASELINE=10, GAP_RESOLVER_VERIFIED=7,
                            MID_EFFICIENCY=5, LOW_EFFICIENCY=2, THIN_LEGACY=0
  2. cross-DEX diversity: (unique_adapter_types - 1) * 3 pts each
     Cycles spanning >1 DEX type are more likely to have price gaps.
  3. fee efficiency: 100 - total_fee_bps (lower fees → more spread room)
  4. adaptive history: recent quoteability rate adjusts score in range ±14 pts
     (quoteable consistently → +14; always QUOTE_FAILED → -14; neutral at 50%)

Cold cycles get 1 slot per COLD_RATIO (default=5) hot slots, ensuring ~17% of
quote budget covers the long tail without starving RPC on unproductive routes.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from m9.graph_arb.models import CycleQuoteResult, GraphCycle

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

_FACTORY_CLASS_SCORE: Dict[str, float] = {
    "EFFICIENT_BASELINE": 10.0,
    "GAP_RESOLVER_VERIFIED": 7.0,
    "MID_EFFICIENCY": 5.0,
    "LOW_EFFICIENCY": 2.0,
    "THIN_LEGACY": 0.0,
}

_LOW_FEE_MAX: float = 100.0           # fee_efficiency = max(0, 100 - total_fee_bps)
_CROSS_DEX_BONUS: float = 3.0         # per extra unique adapter type beyond 1

# ---------------------------------------------------------------------------
# Adaptive history constants
# ---------------------------------------------------------------------------

_HISTORY_WINDOW: int = 5              # sweeps to retain per cycle
_HISTORY_RANGE: float = 28.0          # total adjustment range (±14 at rate=0/1)

# ---------------------------------------------------------------------------
# Queue split constants
# ---------------------------------------------------------------------------

_COLD_PERCENTILE: float = 0.20        # bottom fraction → cold queue
_COLD_RATIO: int = 5                  # 1 cold slot per COLD_RATIO hot slots

# ---------------------------------------------------------------------------
# Status values treated as "not quoteable" (from quoter.py constants)
# ---------------------------------------------------------------------------

_FAILED_STATUSES = frozenset(["QUOTE_FAILED", "CYCLE_QUOTE_TIMEOUT"])


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def compute_base_score(cycle: GraphCycle) -> float:
    """Compute static priority score for *cycle* (no adaptive history).

    Returns a float where higher means higher quoting priority.
    """
    # 1. Factory class: weakest-link (minimum score across all edges)
    fc_score = min(_FACTORY_CLASS_SCORE.get(e.factory_class, 0.0) for e in cycle.edges)

    # 2. Cross-DEX diversity bonus
    unique_adapters = len(set(e.adapter_type for e in cycle.edges))
    cross_dex = max(0.0, (unique_adapters - 1) * _CROSS_DEX_BONUS)

    # 3. Fee efficiency
    fee_score = max(0.0, _LOW_FEE_MAX - cycle.total_fee_bps)

    return fc_score + cross_dex + fee_score


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class CyclePriorityScheduler:
    """2-tier adaptive cycle scheduler for the M9 sweep loop.

    Usage::

        scheduler = CyclePriorityScheduler(ranked_cycles)

        while not deadline_reached:
            batch = scheduler.next_batch(n=20)
            results = quote(batch)
            scheduler.record_results(results)

    The scheduler:
    - Partitions cycles into hot/cold based on initial scores.
    - ``next_batch(n)`` returns *n* cycles: hot-first with periodic cold slots.
    - ``record_results(results)`` updates adaptive scores and re-partitions.
    """

    def __init__(
        self,
        cycles: List[GraphCycle],
        cold_ratio: int = _COLD_RATIO,
    ) -> None:
        self._cold_ratio = cold_ratio
        self._cycle_by_id: Dict[str, GraphCycle] = {c.cycle_id: c for c in cycles}
        self._scores: Dict[str, float] = {
            c.cycle_id: compute_base_score(c) for c in cycles
        }
        # Quoteability history per cycle: list of bool (True = quoteable)
        self._history: Dict[str, List[bool]] = defaultdict(list)
        # Counter for cold quota injection
        self._hot_slots_since_cold: int = 0
        # Hot / cold id sets (populated by _reclassify_all)
        self._hot_ids: set = set()
        self._cold_ids: set = set()
        self._reclassify_all()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reclassify_all(self) -> None:
        """Partition all cycles into hot / cold based on current scores."""
        if not self._scores:
            return
        sorted_scores = sorted(self._scores.values())
        n_cold = max(1, int(len(sorted_scores) * _COLD_PERCENTILE))
        # Threshold: the value at the n_cold-th percentile boundary
        threshold = sorted_scores[n_cold - 1]
        self._hot_ids = {cid for cid, s in self._scores.items() if s > threshold}
        self._cold_ids = {cid for cid in self._scores if cid not in self._hot_ids}

    def _sorted_by_score(self, ids: set) -> List[GraphCycle]:
        """Return cycles for *ids* sorted by descending score."""
        return sorted(
            [self._cycle_by_id[cid] for cid in ids if cid in self._cycle_by_id],
            key=lambda c: -self._scores[c.cycle_id],
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def next_batch(self, n: int) -> List[GraphCycle]:
        """Return up to *n* cycles for the next sweep.

        Hot cycles are returned first.  After every ``cold_ratio`` hot slots,
        one cold slot is injected so the long tail is not completely ignored.
        If the hot queue is exhausted, cold cycles fill the remainder.
        """
        hot_sorted = self._sorted_by_score(self._hot_ids)
        cold_sorted = self._sorted_by_score(self._cold_ids)
        result: List[GraphCycle] = []
        hi = 0
        ci = 0

        for _ in range(n):
            # Inject a cold slot once enough hot slots have been consumed
            if self._hot_slots_since_cold >= self._cold_ratio and ci < len(cold_sorted):
                result.append(cold_sorted[ci])
                ci += 1
                self._hot_slots_since_cold = 0
            elif hi < len(hot_sorted):
                result.append(hot_sorted[hi])
                hi += 1
                self._hot_slots_since_cold += 1
            elif ci < len(cold_sorted):
                result.append(cold_sorted[ci])
                ci += 1
                self._hot_slots_since_cold = 0
            else:
                break  # All queues exhausted

        return result

    def record_results(self, results: List[CycleQuoteResult]) -> None:
        """Update adaptive scores based on quote results from the last sweep.

        Cycles that are consistently quoteable receive a positive adjustment;
        cycles that consistently fail (429s, reverts) are demoted toward cold.
        """
        for qr in results:
            cid = qr.cycle.cycle_id
            if cid not in self._scores:
                continue
            quoteable = qr.status not in _FAILED_STATUSES

            hist = self._history[cid]
            hist.append(quoteable)
            if len(hist) > _HISTORY_WINDOW:
                hist.pop(0)

            # Adaptive adjustment: rate=1.0 → +14, rate=0.5 → 0, rate=0.0 → -14
            rate = sum(1 for q in hist if q) / len(hist)
            adj = (rate - 0.5) * _HISTORY_RANGE
            self._scores[cid] = compute_base_score(qr.cycle) + adj

        self._reclassify_all()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def hot_count(self) -> int:
        """Number of cycles in the hot queue."""
        return len(self._hot_ids)

    @property
    def cold_count(self) -> int:
        """Number of cycles in the cold queue."""
        return len(self._cold_ids)

    def score_summary(self) -> dict:
        """Return a dict with hot/cold counts and score statistics."""
        scores = list(self._scores.values())
        if not scores:
            return {}
        return {
            "hot": self.hot_count,
            "cold": self.cold_count,
            "score_min": round(min(scores), 2),
            "score_max": round(max(scores), 2),
            "score_mean": round(sum(scores) / len(scores), 2),
        }
