# PATH: strategy/jobs/__init__.py
"""
Strategy jobs package.

Available entry points:
    python -m strategy.jobs.run_scan        # Real scanner (placeholder)
    python -m strategy.jobs.run_scan_smoke  # Smoke simulator
    python -m strategy.jobs.run_paper       # Paper trading runner

NOTE: This __init__.py intentionally does NOT import run_scan or run_scan_smoke
to avoid side effects when importing the package. Import them directly when needed:

    from strategy.jobs.run_scan import run_scanner
    from strategy.jobs.run_scan_smoke import run_scanner as run_smoke
"""

# Intentionally empty to avoid import side effects
# See: https://docs.python.org/3/faq/programming.html#what-is-a-side-effect
__all__: list[str] = []
