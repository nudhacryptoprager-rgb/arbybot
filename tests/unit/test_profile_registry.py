# PATH: tests/unit/test_profile_registry.py
"""Unit tests for ProfileRegistry in artifact_invariants."""

import pytest
from core.artifact_invariants import (
    ProfileRegistry,
    ProfileConfig,
    get_profile,
)


class TestProfileRegistry:
    """Tests for ProfileRegistry."""
    
    def test_default_profiles_exist(self):
        """Default registry should have smoke, profit, scan profiles."""
        registry = ProfileRegistry.default()
        
        assert "smoke" in registry.list_profiles()
        assert "profit" in registry.list_profiles()
        assert "scan" in registry.list_profiles()
    
    def test_get_smoke_profile(self):
        """Smoke profile should have correct config."""
        profile = get_profile("smoke")
        
        assert profile.name == "smoke"
        assert profile.min_simulations == 1
        assert profile.min_profitable_sims == 1
        assert profile.require_net_positive is False
    
    def test_get_profit_profile(self):
        """Profit profile should require net positive."""
        profile = get_profile("profit")
        
        assert profile.name == "profit"
        assert profile.min_simulations == 1
        assert profile.min_profitable_sims == 1
        assert profile.require_net_positive is True
        assert profile.min_net_usdc == 0.0
    
    def test_get_scan_profile(self):
        """Scan profile should not require simulations."""
        profile = get_profile("scan")
        
        assert profile.name == "scan"
        assert profile.min_simulations == 0
        assert profile.min_profitable_sims == 0
    
    def test_unknown_profile_raises(self):
        """Unknown profile should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown profile"):
            get_profile("nonexistent")
    
    def test_custom_profile_registration(self):
        """Can register custom profiles."""
        registry = ProfileRegistry()
        
        custom = ProfileConfig(
            name="custom",
            description="Custom test profile",
            min_simulations=5,
            min_profitable_sims=3,
            require_net_positive=True,
            min_net_usdc=10.0,
        )
        
        registry.register(custom)
        
        retrieved = registry.get("custom")
        assert retrieved.name == "custom"
        assert retrieved.min_simulations == 5
        assert retrieved.min_net_usdc == 10.0
    
    def test_profile_has_accuracy_thresholds(self):
        """Profiles should have estimation accuracy thresholds."""
        profile = get_profile("smoke")
        
        assert hasattr(profile, "max_mae_usdc")
        assert hasattr(profile, "min_sign_correct_rate")
        assert profile.max_mae_usdc == 0.30
        assert profile.min_sign_correct_rate == 0.80


class TestProfileSingleton:
    """Tests for singleton behavior."""
    
    def test_default_returns_same_instance(self):
        """default() should return same instance."""
        r1 = ProfileRegistry.default()
        r2 = ProfileRegistry.default()
        
        assert r1 is r2
    
    def test_new_instance_is_different(self):
        """New instance should be different from default."""
        default = ProfileRegistry.default()
        new = ProfileRegistry()
        
        assert default is not new
        # New instance should be empty
        assert len(new.list_profiles()) == 0
