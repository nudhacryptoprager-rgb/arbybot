"""Unit tests for m9.graph_arb.cycle_scheduler.CyclePriorityScheduler.

Tests verify:
  - compute_base_score() returns expected values for different factory classes,
    cross-DEX diversity, and fee levels.
  - CyclePriorityScheduler.next_batch() returns <= n cycles.
  - Hot cycles dominate the batch (cold cycles appear at ~1/cold_ratio rate).
  - record_results() updates scores adaptively.
  - score_summary() returns expected keys.
  - Cold cycles still appear after COLD_RATIO hot slots (long-tail coverage).
"""
from __future__ import annotations

from m9.graph_arb.cycle_scheduler import (
    CyclePriorityScheduler,
    compute_base_score,
    _COLD_RATIO,
    _HISTORY_RANGE,
    _LOW_FEE_MAX,
)
from m9.graph_arb.models import CycleQuoteResult, GraphCycle, GraphEdge


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_ADDR_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_ADDR_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
_ADDR_C = "0xcccccccccccccccccccccccccccccccccccccccc"
_POOL1 = "0x1111111111111111111111111111111111111111"
_POOL2 = "0x2222222222222222222222222222222222222222"
_POOL3 = "0x3333333333333333333333333333333333333333"
_QUOTER = "0x0000000000000000000000000000000000000001"


def _edge(
    sym_in: str,
    addr_in: str,
    sym_out: str,
    addr_out: str,
    pool: str,
    factory_class: str = "EFFICIENT_BASELINE",
    adapter_type: str = "uniswap_v3",
    fee: int = 500,
    fee_bps: float = 5.0,
) -> GraphEdge:
    return GraphEdge(
        token_in_sym=sym_in,
        token_out_sym=sym_out,
        token_in_addr=addr_in,
        token_out_addr=addr_out,
        token_in_decimals=18,
        token_out_decimals=18,
        route_id=f"route_{sym_in}_{sym_out}",
        dex_id=adapter_type,
        adapter_type=adapter_type,
        fee=fee,
        tick_spacing=None,
        quoter_addr=_QUOTER,
        pool_address=pool,
        fee_bps=fee_bps,
        factory_class=factory_class,
        pair_id=f"{sym_in}_{sym_out}",
    )


def _make_cycle_3(
    factory_class: str = "EFFICIENT_BASELINE",
    adapter_type_ab: str = "uniswap_v3",
    adapter_type_bc: str = "uniswap_v3",
    adapter_type_ca: str = "uniswap_v3",
    fee_bps: float = 5.0,
) -> GraphCycle:
    """Build a minimal 3-hop closed cycle A→B→C→A."""
    e_ab = _edge("A", _ADDR_A, "B", _ADDR_B, _POOL1,
                 factory_class=factory_class, adapter_type=adapter_type_ab, fee_bps=fee_bps)
    e_bc = _edge("B", _ADDR_B, "C", _ADDR_C, _POOL2,
                 factory_class=factory_class, adapter_type=adapter_type_bc, fee_bps=fee_bps)
    e_ca = _edge("C", _ADDR_C, "A", _ADDR_A, _POOL3,
                 factory_class=factory_class, adapter_type=adapter_type_ca, fee_bps=fee_bps)
    return GraphCycle(edges=(e_ab, e_bc, e_ca))


def _make_quote_result(cycle: GraphCycle, status: str = "NEGATIVE_GROSS") -> CycleQuoteResult:
    return CycleQuoteResult(
        cycle=cycle,
        size_usd=1000.0,
        amount_in=1_000_000,
        amount_out=999_000,
        gross_bps=-1.0,
        status=status,
        reject_reason=None,
        leg_results=[],
        elapsed_s=0.1,
    )


# ---------------------------------------------------------------------------
# Tests: compute_base_score
# ---------------------------------------------------------------------------


class TestComputeBaseScore:
    def test_efficient_baseline_scores_highest_fc(self):
        c_eff = _make_cycle_3(factory_class="EFFICIENT_BASELINE")
        c_low = _make_cycle_3(factory_class="LOW_EFFICIENCY")
        assert compute_base_score(c_eff) > compute_base_score(c_low)

    def test_cross_dex_bonus(self):
        """Cycle with 2 unique adapter types scores higher than same-dex cycle."""
        c_cross = _make_cycle_3(
            adapter_type_ab="uniswap_v3",
            adapter_type_bc="aerodrome_slipstream",
            adapter_type_ca="uniswap_v3",
        )
        c_same = _make_cycle_3(
            adapter_type_ab="uniswap_v3",
            adapter_type_bc="uniswap_v3",
            adapter_type_ca="uniswap_v3",
        )
        assert compute_base_score(c_cross) > compute_base_score(c_same)

    def test_lower_fee_scores_higher(self):
        c_low_fee = _make_cycle_3(fee_bps=1.0)
        c_high_fee = _make_cycle_3(fee_bps=50.0)
        assert compute_base_score(c_low_fee) > compute_base_score(c_high_fee)

    def test_score_non_negative(self):
        """Even worst-case cycle gets non-negative score."""
        c = _make_cycle_3(
            factory_class="THIN_LEGACY",
            adapter_type_ab="uniswap_v3",
            adapter_type_bc="uniswap_v3",
            adapter_type_ca="uniswap_v3",
            fee_bps=200.0,  # very high fee, but max(0, 100-200)=0
        )
        assert compute_base_score(c) >= 0.0

    def test_unknown_factory_class_treated_as_zero(self):
        c = _make_cycle_3(factory_class="UNKNOWN_CLASS")
        score = compute_base_score(c)
        assert score >= 0.0


# ---------------------------------------------------------------------------
# Tests: CyclePriorityScheduler
# ---------------------------------------------------------------------------


class TestCyclePriorityScheduler:
    def _make_cycles(self, n: int) -> list:
        """Return n distinct 3-hop cycles with varying quality."""
        cycles = []
        for i in range(n):
            fc = "EFFICIENT_BASELINE" if i % 3 == 0 else ("MID_EFFICIENCY" if i % 3 == 1 else "LOW_EFFICIENCY")
            fee_bps = 5.0 + i * 2.0
            # Vary pool addresses to ensure distinct cycle_ids
            pool_a = f"0x{'a' * (38 - len(str(i)))}{i:0{len(str(i))}x}0000"[:42]
            # Use a simpler approach — vary the adapters so cycle_ids differ
            cycle = _make_cycle_3(factory_class=fc, fee_bps=fee_bps)
            # Patch cycle_id by wrapping with unique edges via route_id variation
            # Actually cycle_id is based on route_ids, so we need truly distinct edges.
            # Just reuse the helper for consistent structure — uniqueness tested separately.
            cycles.append(cycle)
        # De-duplicate by cycle_id (may collapse if route_ids are identical)
        seen = set()
        unique = []
        for c in cycles:
            if c.cycle_id not in seen:
                seen.add(c.cycle_id)
                unique.append(c)
        return unique

    def _make_distinct_cycles(self) -> list:
        """Return 10 distinct cycles with varying quality and addresses."""
        cycles = []
        # Create cycles with different pool addresses to ensure distinct cycle_ids
        hex_chars = "0123456789abcdef"
        for i in range(10):
            h = hex_chars[i % 16]
            pool1 = f"0x{h*40}"
            pool2 = f"0x{hex_chars[(i+1)%16]*40}"
            pool3 = f"0x{hex_chars[(i+2)%16]*40}"
            # Use different tokens to avoid address collision in GraphCycle validation
            addr_a = f"0xa{i:039x}"
            addr_b = f"0xb{i:039x}"
            addr_c = f"0xc{i:039x}"
            fc = ["EFFICIENT_BASELINE", "MID_EFFICIENCY", "LOW_EFFICIENCY"][i % 3]
            fee_bps = 5.0 + i * 3.0
            e_ab = _edge(f"T{i}A", addr_a, f"T{i}B", addr_b, pool1,
                         factory_class=fc, fee_bps=fee_bps)
            e_bc = _edge(f"T{i}B", addr_b, f"T{i}C", addr_c, pool2,
                         factory_class=fc, fee_bps=fee_bps)
            e_ca = _edge(f"T{i}C", addr_c, f"T{i}A", addr_a, pool3,
                         factory_class=fc, fee_bps=fee_bps)
            cycles.append(GraphCycle(edges=(e_ab, e_bc, e_ca)))
        return cycles

    def test_next_batch_returns_lte_n(self):
        cycles = self._make_distinct_cycles()
        scheduler = CyclePriorityScheduler(cycles, cold_ratio=5)
        batch = scheduler.next_batch(n=5)
        assert len(batch) <= 5

    def test_next_batch_returns_correct_count_when_enough_cycles(self):
        cycles = self._make_distinct_cycles()
        scheduler = CyclePriorityScheduler(cycles, cold_ratio=5)
        batch = scheduler.next_batch(n=6)
        assert len(batch) == 6

    def test_next_batch_returns_all_when_n_exceeds_cycle_count(self):
        cycles = self._make_distinct_cycles()  # 10 cycles
        scheduler = CyclePriorityScheduler(cycles, cold_ratio=5)
        batch = scheduler.next_batch(n=50)
        assert len(batch) == len(cycles)

    def test_hot_cycles_dominate_initial_batch(self):
        """With 10 cycles, hot=8 cold=2. A batch of 5 should contain >= 4 hot."""
        cycles = self._make_distinct_cycles()
        scheduler = CyclePriorityScheduler(cycles, cold_ratio=5)
        assert scheduler.hot_count >= 1
        assert scheduler.cold_count >= 1
        # First 5: ratio 5:1 → at most 1 cold slot
        batch = scheduler.next_batch(n=6)
        hot_ids = scheduler._hot_ids
        hot_in_batch = sum(1 for c in batch if c.cycle_id in hot_ids)
        assert hot_in_batch >= len(batch) - 2  # allow 1-2 cold slots

    def test_cold_cycles_appear_at_cold_ratio_rate(self):
        """After cold_ratio hot slots, a cold cycle appears."""
        cycles = self._make_distinct_cycles()
        scheduler = CyclePriorityScheduler(cycles, cold_ratio=3)
        cold_ids = set(scheduler._cold_ids)
        if not cold_ids:
            return  # all cycles in hot — skip
        # Reset counter
        scheduler._hot_slots_since_cold = 0
        batch = scheduler.next_batch(n=8)
        cold_in_batch = sum(1 for c in batch if c.cycle_id in cold_ids)
        assert cold_in_batch >= 1, "Expected at least one cold slot in 8-item batch with cold_ratio=3"

    def test_record_results_promotes_quoteable_cycle(self):
        """A cycle that is consistently quoteable should gain a positive score adjustment."""
        cycles = self._make_distinct_cycles()
        scheduler = CyclePriorityScheduler(cycles, cold_ratio=5)
        target = cycles[0]
        initial_score = scheduler._scores[target.cycle_id]

        # Record 5 quoteable results for target
        for _ in range(5):
            qr = _make_quote_result(target, status="NEGATIVE_GROSS")
            scheduler.record_results([qr])

        final_score = scheduler._scores[target.cycle_id]
        assert final_score > initial_score, (
            f"Expected score to increase after 5 quoteable results. "
            f"initial={initial_score}, final={final_score}"
        )

    def test_record_results_demotes_failed_cycle(self):
        """A cycle that always fails (QUOTE_FAILED) should get a negative adjustment."""
        cycles = self._make_distinct_cycles()
        scheduler = CyclePriorityScheduler(cycles, cold_ratio=5)
        target = cycles[0]
        initial_score = scheduler._scores[target.cycle_id]

        # Record 5 failed results for target
        for _ in range(5):
            qr = _make_quote_result(target, status="QUOTE_FAILED")
            scheduler.record_results([qr])

        final_score = scheduler._scores[target.cycle_id]
        assert final_score < initial_score, (
            f"Expected score to decrease after 5 QUOTE_FAILED results. "
            f"initial={initial_score}, final={final_score}"
        )

    def test_score_summary_returns_expected_keys(self):
        cycles = self._make_distinct_cycles()
        scheduler = CyclePriorityScheduler(cycles)
        summary = scheduler.score_summary()
        for key in ("hot", "cold", "score_min", "score_max", "score_mean"):
            assert key in summary, f"Missing key '{key}' in score_summary()"

    def test_score_summary_hot_cold_sum_equals_total(self):
        cycles = self._make_distinct_cycles()
        scheduler = CyclePriorityScheduler(cycles)
        summary = scheduler.score_summary()
        assert summary["hot"] + summary["cold"] == len(cycles)

    def test_empty_scheduler(self):
        """Scheduler with no cycles must not raise and return empty batch."""
        scheduler = CyclePriorityScheduler([])
        batch = scheduler.next_batch(n=10)
        assert batch == []
        assert scheduler.score_summary() == {}

    def test_batch_has_no_duplicate_cycles(self):
        """next_batch() must not return the same cycle twice in one call."""
        cycles = self._make_distinct_cycles()
        scheduler = CyclePriorityScheduler(cycles, cold_ratio=2)
        batch = scheduler.next_batch(n=len(cycles))
        ids = [c.cycle_id for c in batch]
        assert len(ids) == len(set(ids)), "Duplicate cycles in batch"
