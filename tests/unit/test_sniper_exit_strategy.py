"""Unit tests for ``strategy/sniper_exit_strategy.py`` (Phase 2 paper)."""
from __future__ import annotations

import pytest

from strategy.sniper_exit_strategy import (
    DEFAULT_MAX_HOLD_BLOCKS,
    DEFAULT_PROFIT_TAKE_BPS,
    DEFAULT_PROFIT_TAKE_FRACTION,
    ExitAction,
    ExitDecision,
    ExitStateInput,
    ExitTrigger,
    SniperExitStrategy,
    make_default_strategy,
)


def _state(**overrides) -> ExitStateInput:
    base = dict(
        entry_block=100,
        current_block=110,
        realized_pnl_bps=0.0,
        position_fraction_remaining=1.0,
        revert_observed=False,
        honeypot_trigger=False,
    )
    base.update(overrides)
    return ExitStateInput(**base)


class TestStrategyConstruction:
    def test_defaults(self):
        s = make_default_strategy()
        assert s.max_hold_blocks == DEFAULT_MAX_HOLD_BLOCKS
        assert s.profit_take_bps == DEFAULT_PROFIT_TAKE_BPS
        assert s.profit_take_fraction == DEFAULT_PROFIT_TAKE_FRACTION

    def test_invalid_max_hold(self):
        with pytest.raises(ValueError):
            SniperExitStrategy(max_hold_blocks=0)

    def test_invalid_fraction(self):
        with pytest.raises(ValueError):
            SniperExitStrategy(profit_take_fraction=1.5)

    def test_invalid_negative_profit_bps(self):
        with pytest.raises(ValueError):
            SniperExitStrategy(profit_take_bps=-1.0)


class TestExitTriggers:
    def test_hold_when_no_condition_met(self):
        d = make_default_strategy().evaluate(_state())
        assert d.trigger == ExitTrigger.NONE
        assert d.action == ExitAction.HOLD
        assert d.sell_fraction == 0.0

    def test_time_exit_at_ceiling(self):
        d = make_default_strategy().evaluate(
            _state(current_block=100 + DEFAULT_MAX_HOLD_BLOCKS)
        )
        assert d.trigger == ExitTrigger.TIME
        assert d.action == ExitAction.FULL_SELL
        assert d.sell_fraction == 1.0
        assert d.reason == "MAX_HOLD_REACHED"

    def test_profit_take_partial(self):
        d = make_default_strategy().evaluate(
            _state(realized_pnl_bps=DEFAULT_PROFIT_TAKE_BPS + 10)
        )
        assert d.trigger == ExitTrigger.PROFIT_TAKE
        assert d.action == ExitAction.PARTIAL_SELL
        assert d.sell_fraction == DEFAULT_PROFIT_TAKE_FRACTION

    def test_emergency_on_revert(self):
        d = make_default_strategy().evaluate(_state(revert_observed=True))
        assert d.trigger == ExitTrigger.EMERGENCY
        assert d.action == ExitAction.FULL_SELL
        assert d.reason == "REVERT_OBSERVED"

    def test_emergency_on_honeypot(self):
        d = make_default_strategy().evaluate(_state(honeypot_trigger=True))
        assert d.trigger == ExitTrigger.EMERGENCY
        assert d.reason == "HONEYPOT_TRIGGER"

    def test_emergency_preempts_time(self):
        d = make_default_strategy().evaluate(
            _state(
                current_block=100 + DEFAULT_MAX_HOLD_BLOCKS + 50,
                honeypot_trigger=True,
            )
        )
        assert d.trigger == ExitTrigger.EMERGENCY

    def test_profit_take_skipped_when_already_partial(self):
        # Position already at the profit_take fraction (or below) — no further partial.
        d = make_default_strategy().evaluate(
            _state(
                realized_pnl_bps=DEFAULT_PROFIT_TAKE_BPS + 50,
                position_fraction_remaining=DEFAULT_PROFIT_TAKE_FRACTION,
            )
        )
        assert d.trigger == ExitTrigger.NONE


class TestExitValidation:
    def test_current_before_entry_raises(self):
        with pytest.raises(ValueError):
            make_default_strategy().evaluate(_state(entry_block=200, current_block=100))

    def test_to_dict_serialises(self):
        d = make_default_strategy().evaluate(_state())
        out = d.to_dict()
        assert out["trigger"] == "NONE"
        assert out["action"] == "HOLD"
        assert "notes" in out


def test_no_infinite_hold_chaos():
    """Random sequences must always trigger an exit before 2x max_hold_blocks."""
    strat = make_default_strategy()
    for offset in (DEFAULT_MAX_HOLD_BLOCKS, DEFAULT_MAX_HOLD_BLOCKS + 1, 2 * DEFAULT_MAX_HOLD_BLOCKS):
        d = strat.evaluate(_state(current_block=100 + offset))
        assert d.action == ExitAction.FULL_SELL
