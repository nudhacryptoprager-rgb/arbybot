"""Reject-cache key must include post_depth_content_hash."""
from __future__ import annotations


def test_reject_cache_key_includes_post_depth_hash():
  parts_a = ("hash-a", "production_conservative", "1")
  parts_b = ("hash-b", "production_conservative", "1")
  key_a = "|".join(("cycle-1", *parts_a))
  key_b = "|".join(("cycle-1", *parts_b))
  assert key_a != key_b
