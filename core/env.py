from pathlib import Path
import os
from dotenv import load_dotenv


def env_flag_enabled(name: str) -> bool:
    """Return True when an env var is set to a truthy flag value.

    Canonical implementation — used by quotes.py and run_scan_real.py.
    Recognized truthy values: '1', 'true', 'yes', 'on' (case-insensitive).
    """
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def load_root_dotenv() -> bool:
    """Load .env from repository root (core/ is two levels deep).

    Returns True if a .env file was found and loaded, False otherwise.
    """
    try:
        root = Path(__file__).resolve().parents[1]
        # core/ is directly under repo root, so parents[1] == repo root
        dotenv_path = root / ".env"
        if dotenv_path.exists():
            load_dotenv(dotenv_path=str(dotenv_path), override=False)
            return True
        # fallback to default search
        load_dotenv(override=False)
        return False
    except Exception:
        # Do not raise - dotenv loading is best-effort
        try:
            load_dotenv(override=False)
        except Exception:
            pass
        return False
