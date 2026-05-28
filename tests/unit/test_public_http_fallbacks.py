"""Tests for the public HTTP RPC fallback pool (todo_RPC_blockers Phase 1)."""
from core.rpc_urls import iter_public_http_fallbacks, _PUBLIC_HTTP_FALLBACKS


def test_iter_public_http_fallbacks_base_nonempty():
    urls = iter_public_http_fallbacks("base")
    assert len(urls) >= 5
    assert all(u.startswith("https://") for u in urls)
    # Must include the canonical Base public endpoint
    assert "https://mainnet.base.org" in urls


def test_iter_public_http_fallbacks_unknown_network():
    assert iter_public_http_fallbacks(None) == []
    assert iter_public_http_fallbacks("") == []
    assert iter_public_http_fallbacks("unknown_chain_xyz") == []


def test_iter_public_http_fallbacks_aliases():
    """`arbitrum_one` alias should resolve to `arbitrum`."""
    assert iter_public_http_fallbacks("arbitrum_one") == iter_public_http_fallbacks("arbitrum")


def test_public_http_fallbacks_no_duplicates_within_network():
    for net, urls in _PUBLIC_HTTP_FALLBACKS.items():
        assert len(set(urls)) == len(urls), f"duplicate URLs in {net}: {urls}"


def test_iter_returns_copy_not_reference():
    a = iter_public_http_fallbacks("base")
    a.append("https://injected.example.com")
    b = iter_public_http_fallbacks("base")
    assert "https://injected.example.com" not in b
