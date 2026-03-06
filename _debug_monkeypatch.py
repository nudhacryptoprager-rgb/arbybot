"""Debug script to test monkeypatch behavior."""
import sys
import tempfile
from pathlib import Path

# Create fake tmp_path
tmp_path = Path(tempfile.mkdtemp())
print(f"tmp_path = {tmp_path}")

fake_cache = tmp_path / "cache"
fake_cache.mkdir(exist_ok=True)

# Monkeypatch BEFORE import
import strategy.runtime_disabled

def _fake_runtime_disabled_path(chain_key=None):
    key = chain_key if chain_key and chain_key != "unknown" else "legacy"
    return str(fake_cache / f"runtime_disabled_{key}.json")

strategy.runtime_disabled._get_runtime_disabled_cache_path = _fake_runtime_disabled_path

# Now test the function
from strategy.runtime_disabled import (
    get_runtime_disabled_manager,
    clear_runtime_disabled_manager,
    _get_runtime_disabled_cache_path,
)

print(f"_get_runtime_disabled_cache_path('linea') = {_get_runtime_disabled_cache_path('linea')}")

clear_runtime_disabled_manager()
mgr = get_runtime_disabled_manager(chain_key="linea")
print(f"mgr.cache_path = {mgr.cache_path}")
print(f"len(mgr._entries) = {len(mgr._entries)}")
