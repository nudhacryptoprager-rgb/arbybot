"""Unit tests for ``strategy/sniper_entry_decision.py`` (Phase 2 paper).

Locks the gate ordering, reject codes, and confidence floor so future
edits cannot silently regress the decision contract.
"""
from __future__ import annotations

import pytest

from strategy.sniper_entry_decision import (
    DEFAULT_ANCHOR_TOKENS,
    EntryCandidate,
    EntryDecision,
    EntryDecisionEngine,
    EntryDecisionVerdict,
    make_default_engine,
)

USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
WETH = "0x4200000000000000000000000000000000000006"
RAND_TOKEN = "0x" + "a" * 40
SECOND_RAND = "0x" + "b" * 40


def _candidate(**overrides) -> EntryCandidate:
    base = dict(
        token0=USDC,
        token1=RAND_TOKEN,
        pool="0x" + "c" * 40,
        liquidity_usd=5000.0,
        estimated_spread_bps=100.0,
        mirror_found=False,
        honeypot_verdict="PASS",
        dex="uniswap_v3",
        block_number=123,
    )
    base.update(overrides)
    return EntryCandidate(**base)


class TestEngineConstruction:
    def test_default_engine_smoke(self):
        e = make_default_engine()
        assert isinstance(e, EntryDecisionEngine)

    def test_negative_liquidity_threshold_rejected(self):
        with pytest.raises(ValueError):
            EntryDecisionEngine(min_liquidity_usd=-1)

    def test_negative_spread_threshold_rejected(self):
        with pytest.raises(ValueError):
            EntryDecisionEngine(min_spread_bps=-1)


class TestHappyPath:
    def test_would_enter_with_anchor_token(self):
        engine = make_default_engine()
        d = engine.decide(_candidate())
        assert d.verdict == EntryDecisionVerdict.WOULD_ENTER
        assert d.reject_reason is None
        assert 0.0 <= d.confidence <= 1.0

    def test_would_enter_with_mirror(self):
        engine = make_default_engine()
        c = _candidate(token0=RAND_TOKEN, token1=SECOND_RAND, mirror_found=True)
        d = engine.decide(c)
        assert d.verdict == EntryDecisionVerdict.WOULD_ENTER

    def test_to_dict_serialises(self):
        engine = make_default_engine()
        d = engine.decide(_candidate())
        out = d.to_dict()
        assert out["verdict"] == "WOULD_ENTER"
        assert out["reject_reason"] is None
        assert "notes" in out


class TestRejectTaxonomy:
    def test_no_liquidity(self):
        d = make_default_engine().decide(_candidate(liquidity_usd=0))
        assert d.verdict == EntryDecisionVerdict.SKIP
        assert d.reject_reason == "NO_LIQUIDITY"

    def test_low_liquidity(self):
        d = make_default_engine().decide(_candidate(liquidity_usd=100))
        assert d.reject_reason == "LOW_LIQUIDITY"

    def test_missing_liquidity(self):
        d = make_default_engine().decide(_candidate(liquidity_usd=None))
        assert d.reject_reason == "INSUFFICIENT_DATA"

    def test_spread_too_tight(self):
        d = make_default_engine().decide(_candidate(estimated_spread_bps=5))
        assert d.reject_reason == "SPREAD_TOO_TIGHT"

    def test_no_mirror_no_anchor(self):
        d = make_default_engine().decide(
            _candidate(token0=RAND_TOKEN, token1=SECOND_RAND, mirror_found=False)
        )
        assert d.reject_reason == "NO_MIRROR_NO_ANCHOR"

    def test_honeypot_fail(self):
        d = make_default_engine().decide(_candidate(honeypot_verdict="FAIL"))
        assert d.reject_reason == "HONEYPOT_FAIL"

    def test_honeypot_unknown_rejected_by_default(self):
        d = make_default_engine().decide(_candidate(honeypot_verdict="UNKNOWN"))
        assert d.reject_reason == "HONEYPOT_UNKNOWN"

    def test_honeypot_unknown_allowed_when_flag_off(self):
        engine = EntryDecisionEngine(reject_unknown_honeypot=False)
        d = engine.decide(_candidate(honeypot_verdict="UNKNOWN"))
        assert d.verdict == EntryDecisionVerdict.WOULD_ENTER


class TestGateOrdering:
    def test_liquidity_evaluated_before_spread(self):
        # Both gates would fail; liquidity should be the surfaced reason.
        d = make_default_engine().decide(
            _candidate(liquidity_usd=0, estimated_spread_bps=5)
        )
        assert d.reject_reason == "NO_LIQUIDITY"

    def test_spread_evaluated_before_mirror(self):
        d = make_default_engine().decide(
            _candidate(
                token0=RAND_TOKEN,
                token1=SECOND_RAND,
                estimated_spread_bps=5,
            )
        )
        assert d.reject_reason == "SPREAD_TOO_TIGHT"


class TestConfidence:
    def test_confidence_zero_on_skip(self):
        d = make_default_engine().decide(_candidate(liquidity_usd=0))
        assert d.confidence == 0.0

    def test_confidence_within_unit_range(self):
        d = make_default_engine().decide(
            _candidate(liquidity_usd=100_000, estimated_spread_bps=400)
        )
        assert 0.0 < d.confidence <= 1.0


def test_anchor_tokens_lowercase_only():
    for t in DEFAULT_ANCHOR_TOKENS:
        assert t == t.lower()
