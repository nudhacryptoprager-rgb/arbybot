#!/usr/bin/env python3
"""Wrapper script to run ci_m5_0_gate.py and log output."""
import sys
import subprocess

cmd = [
    sys.executable, "scripts/ci_m5_0_gate.py",
    "--online",
    "--config", "config/real_minimal.yaml",
    "--cycles", "1",
    "--prune-keep", "0",
]

print(f"Running: {' '.join(cmd)}")
print("=" * 60)

result = subprocess.run(cmd, capture_output=False, text=True)

print("=" * 60)
print(f"Exit code: {result.returncode}")
