"""E1.30: intent-driven prewarm tests.

Validates that `get_prewarm_pairs()` reads from config/intent.txt first,
and that `IntentUniverse.get_pair_tuples_for_chain()` returns the expected
symbol tuples for each chain.
"""

from discovery.intent_loader import get_intent_universe
from m7.shared.constants import (
    PREWARM_PAIRS_ARBITRUM,
    PREWARM_PAIRS_BASE,
    get_prewarm_pairs,
)


class TestIntentPairTuples:
    def test_get_pair_tuples_for_chain_base(self):
        u = get_intent_universe(reload=True)
        pairs = u.get_pair_tuples_for_chain("base")
        assert len(pairs) >= 9  # original 9 + E1.30 expansion
        # Core Base pairs must be present.
        pair_set = {tuple(sorted(p)) for p in pairs}
        assert tuple(sorted(("WETH", "USDC"))) in pair_set
        assert tuple(sorted(("USDC", "DAI"))) in pair_set
        assert tuple(sorted(("cbBTC", "USDC"))) in pair_set

    def test_get_pair_tuples_for_chain_arbitrum(self):
        u = get_intent_universe(reload=True)
        pairs = u.get_pair_tuples_for_chain("arbitrum_one")
        assert len(pairs) >= 11
        pair_set = {tuple(sorted(p)) for p in pairs}
        assert tuple(sorted(("WETH", "USDC"))) in pair_set
        assert tuple(sorted(("WETH", "USDT"))) in pair_set  # E1.30 addition

    def test_get_pair_tuples_empty_for_unknown_chain(self):
        u = get_intent_universe(reload=True)
        assert u.get_pair_tuples_for_chain("unknown_chain_zzz") == []

    def test_tuples_are_deduplicated_by_canonical_key(self):
        u = get_intent_universe(reload=True)
        pairs = u.get_pair_tuples_for_chain("base")
        canon = [tuple(sorted(p)) for p in pairs]
        assert len(canon) == len(set(canon))


class TestIntentDrivenPrewarm:
    def test_prewarm_uses_intent_for_base_production(self):
        """Base production prewarm is sourced from intent.txt."""
        u = get_intent_universe(reload=True)
        intent_pairs = u.get_pair_tuples_for_chain("base")
        prewarm = get_prewarm_pairs("base", "production")
        # Production returns exactly intent.txt pairs.
        assert prewarm == list(intent_pairs)

    def test_prewarm_base_includes_e1_30_expansion(self):
        """E1.30: cbETH and WETH/USDT must be in Base prewarm now."""
        pairs = get_prewarm_pairs("base", "production")
        pair_set = {tuple(sorted(p)) for p in pairs}
        assert tuple(sorted(("cbETH", "WETH"))) in pair_set
        assert tuple(sorted(("cbETH", "USDC"))) in pair_set
        assert tuple(sorted(("WETH", "USDT"))) in pair_set

    def test_prewarm_arbitrum_includes_e1_30_expansion(self):
        """E1.30: WETH/USDT, GMX/WETH, MAGIC/WETH on Arbitrum."""
        pairs = get_prewarm_pairs("arbitrum_one", "production")
        pair_set = {tuple(sorted(p)) for p in pairs}
        assert tuple(sorted(("WETH", "USDT"))) in pair_set
        assert tuple(sorted(("GMX", "WETH"))) in pair_set
        assert tuple(sorted(("MAGIC", "WETH"))) in pair_set

    def test_prewarm_discovery_is_superset_of_production(self):
        prod = get_prewarm_pairs("base", "production")
        disc = get_prewarm_pairs("base", "discovery")
        prod_canon = {tuple(sorted(p)) for p in prod}
        disc_canon = {tuple(sorted(p)) for p in disc}
        assert prod_canon.issubset(disc_canon)

    def test_prewarm_discovery_keeps_diagnostic_memes(self):
        """Discovery profile retains DEGEN/BRETT/TOSHI meme pairs from hardcoded fallback."""
        disc = get_prewarm_pairs("base", "discovery")
        disc_canon = {tuple(sorted(p)) for p in disc}
        assert tuple(sorted(("DEGEN", "WETH"))) in disc_canon
        assert tuple(sorted(("BRETT", "WETH"))) in disc_canon

    def test_prewarm_unknown_chain_fallback(self):
        """Unknown chain → hardcoded Arbitrum fallback (safety)."""
        pairs = get_prewarm_pairs("zzz_nonexistent_chain")
        assert pairs == list(PREWARM_PAIRS_ARBITRUM)

    def test_prewarm_returns_fresh_list_not_singleton(self):
        """E1.30: returned list is a copy (mutations don't affect next call)."""
        a = get_prewarm_pairs("base", "production")
        a.append(("XXXXX", "YYYYY"))
        b = get_prewarm_pairs("base", "production")
        assert ("XXXXX", "YYYYY") not in b

    def test_prewarm_tuples_are_2_element(self):
        for chain in ("base", "arbitrum_one"):
            for pair in get_prewarm_pairs(chain, "production"):
                assert isinstance(pair, tuple)
                assert len(pair) == 2
                assert all(isinstance(s, str) and s for s in pair)
