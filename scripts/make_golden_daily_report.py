"""Create a golden daily report from the latest runDir and save to docs/artifacts."""
from pathlib import Path
import json
from datetime import date

from scripts.generate_daily_report import aggregate_run


def find_latest_run(runs_root: Path) -> Path:
    candidates = [d for d in runs_root.iterdir() if d.is_dir()]
    if not candidates:
        raise SystemExit("no run dirs found")
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    return latest


def main():
    runs_root = Path("data/runs")
    latest = find_latest_run(runs_root)
    print(f"Found latest run: {latest}")
    report = aggregate_run(latest)
    out = Path("docs/artifacts")
    out.mkdir(parents=True, exist_ok=True)
    target = out / "daily_report_golden.json"
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf8")
    print(f"Wrote golden report to {target}")


if __name__ == "__main__":
    main()
