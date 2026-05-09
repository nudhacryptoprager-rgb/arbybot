"""E1.69 Wave B — multi-hop intent route parsing.

Locks:
  * IntentRoute parsing of 3-token (2-hop) and 4-token (3-hop) lines.
  * Existing 2-token IntentPair behaviour unaffected.
  * intent.txt actually contains multi-hop production routes.
"""
from __future__ import annotations

from discovery.intent_loader import (
    IntentPair,
    IntentRoute,
    IntentUniverse,
    load_intent,
    parse_intent_line,
    parse_intent_route_line,
)


def test_parse_intent_line_still_returns_pair_for_2_tokens() -> None:
    p = parse_intent_line("base:WETH/USDC")
    assert isinstance(p, IntentPair)
    assert p.token_a == "WETH" and p.token_b == "USDC"


def test_parse_intent_line_returns_none_for_3_tokens() -> None:
    """Backward-compat: 3-token lines are NOT IntentPair."""
    assert parse_intent_line("base:cbETH/WETH/USDC") is None


def test_parse_intent_route_line_2_hop() -> None:
    r = parse_intent_route_line("base:cbETH/WETH/USDC")
    assert isinstance(r, IntentRoute)
    assert r.chain == "base"
    assert r.tokens == ("CBETH", "WETH", "USDC")
    assert r.hops == 2


def test_parse_intent_route_line_3_hop() -> None:
    r = parse_intent_route_line("base:A/B/C/D")
    assert r is not None and r.hops == 3


def test_parse_intent_route_line_rejects_2_token() -> None:
    assert parse_intent_route_line("base:WETH/USDC") is None


def test_parse_intent_route_line_rejects_too_many_hops() -> None:
    assert parse_intent_route_line("base:A/B/C/D/E") is None


def test_intent_universe_has_routes_after_load() -> None:
    universe = load_intent()
    routes = universe.get_routes_for_chain("base")
    assert len(routes) >= 8, f"expected multi-hop routes in intent.txt, got {len(routes)}"
    # cbETH -> WETH -> USDC must be present (production path).
    keys = {r.canonical_key for r in routes}
    assert "base:CBETH/WETH/USDC" in keys
    assert "base:WSTETH/WETH/USDC" in keys
    assert "base:CBBTC/WETH/USDC" in keys


def test_intent_universe_pairs_unchanged_by_routes() -> None:
    """Adding multi-hop routes must not reduce 2-token pair count."""
    universe = load_intent()
    base_pairs = universe.get_pairs_for_chain("base")
    # Baseline from E1.67 was 23 canonical pairs on Base.
    assert len(base_pairs) >= 23


def test_intent_route_canonical_key_is_direction_sensitive() -> None:
    fwd = IntentRoute(chain="base", tokens=("A", "B", "C"))
    rev = IntentRoute(chain="base", tokens=("C", "B", "A"))
    assert fwd.canonical_key != rev.canonical_key
