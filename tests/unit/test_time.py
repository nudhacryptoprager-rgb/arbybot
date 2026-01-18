# PATH: tests/unit/test_time.py
"""
Unit tests for time utilities.
"""

import time
import unittest

from core.time import (
    now_utc,
    now_iso,
    now_timestamp,
    is_fresh,
    is_block_fresh,
    calculate_staleness_score,
    calculate_freshness_score,
)


class TestNowFunctions(unittest.TestCase):
    """Tests for now_* functions."""
    
    def test_now_utc(self):
        """now_utc returns datetime."""
        dt = now_utc()
        self.assertIsNotNone(dt.tzinfo)
    
    def test_now_iso(self):
        """now_iso returns ISO string."""
        iso = now_iso()
        self.assertIn("T", iso)
        self.assertIn("+", iso)  # Has timezone
    
    def test_now_timestamp(self):
        """now_timestamp returns float."""
        ts = now_timestamp()
        self.assertIsInstance(ts, float)
        self.assertGreater(ts, 0)


class TestIsFresh(unittest.TestCase):
    """Tests for is_fresh function."""
    
    def test_fresh_timestamp(self):
        """Recent timestamp is fresh."""
        ts = time.time()
        self.assertTrue(is_fresh(ts, max_age_seconds=2.0))
    
    def test_stale_timestamp(self):
        """Old timestamp is stale."""
        ts = time.time() - 10
        self.assertFalse(is_fresh(ts, max_age_seconds=2.0))
    
    def test_custom_current_time(self):
        """Can use custom current time."""
        ts = 1000.0
        current = 1001.0
        self.assertTrue(is_fresh(ts, max_age_seconds=2.0, current_time=current))
        
        current = 1005.0
        self.assertFalse(is_fresh(ts, max_age_seconds=2.0, current_time=current))


class TestIsBlockFresh(unittest.TestCase):
    """Tests for is_block_fresh function."""
    
    def test_same_block_is_fresh(self):
        """Same block is fresh."""
        self.assertTrue(is_block_fresh(100, 100, max_blocks=2))
    
    def test_one_block_behind_is_fresh(self):
        """One block behind is fresh."""
        self.assertTrue(is_block_fresh(99, 100, max_blocks=2))
    
    def test_many_blocks_behind_is_stale(self):
        """Many blocks behind is stale."""
        self.assertFalse(is_block_fresh(90, 100, max_blocks=2))
    
    def test_zero_block_is_stale(self):
        """Block 0 is considered stale."""
        self.assertFalse(is_block_fresh(0, 100))


class TestStalenessScore(unittest.TestCase):
    """Tests for staleness score functions."""
    
    def test_same_block_zero_staleness(self):
        """Same block has 0 staleness."""
        score = calculate_staleness_score(100, 100, max_blocks=10)
        self.assertEqual(score, 0.0)
    
    def test_max_blocks_full_staleness(self):
        """At max_blocks, staleness is 1.0."""
        score = calculate_staleness_score(90, 100, max_blocks=10)
        self.assertEqual(score, 1.0)
    
    def test_half_blocks_half_staleness(self):
        """Half blocks gives 0.5 staleness."""
        score = calculate_staleness_score(95, 100, max_blocks=10)
        self.assertEqual(score, 0.5)
    
    def test_freshness_is_inverse(self):
        """Freshness is 1 - staleness."""
        staleness = calculate_staleness_score(95, 100, max_blocks=10)
        freshness = calculate_freshness_score(95, 100, max_blocks=10)
        self.assertEqual(freshness, 1.0 - staleness)


if __name__ == "__main__":
    unittest.main()