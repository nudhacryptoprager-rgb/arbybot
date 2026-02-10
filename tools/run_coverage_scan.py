#!/usr/bin/env python
"""Run coverage scans to generate runs with >= 5 signals."""
import sys
import os
import time
# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from datetime import datetime

logging.basicConfig(level=logging.WARNING)

# Number of scans to run
N_SCANS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
DELAY_SECONDS = 5  # Wait between scans

from strategy.jobs.run_scan import run_scanner, ScannerMode

for i in range(N_SCANS):
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = f'data/runs/coverage_run_{ts}'
    print(f"\n[{i+1}/{N_SCANS}] Starting scan -> {output_dir}")
    
    result = run_scanner(
        mode=ScannerMode.REAL,
        config_path='config/real_test_coverage.yaml',
        cycles=1,
        output_dir=output_dir
    )
    print(f"[{i+1}/{N_SCANS}] Scan complete: {output_dir}")
    
    if i < N_SCANS - 1:
        print(f"[{i+1}/{N_SCANS}] Waiting {DELAY_SECONDS}s before next scan...")
        time.sleep(DELAY_SECONDS)

print(f"\nDone: {N_SCANS} scans completed")
