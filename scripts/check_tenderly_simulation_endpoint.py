"""
check_tenderly_simulation_endpoint.py — dry-run probe for Tenderly POST /simulate.

Verifies that the Tenderly API key has *simulation* permissions, not just
/user or /project read access.  Uses a minimal no-op call (zero calldata,
zero value, send-to-self on Base) that is cheap and does not require a
funded account.

Exit codes:
  0  — simulate endpoint returned HTTP 200 (sim permission OK)
  1  — simulate returned non-200 (e.g. HTTP 403 insufficient_permissions)
  2  — Tenderly env vars missing
  3  — network error / timeout

Usage:
  py -3.11 scripts/check_tenderly_simulation_endpoint.py

Prints result to stdout; never prints secrets.
"""
import os
import sys


def _check() -> int:
    user = os.environ.get("TENDERLY_USER", "").strip()
    project = os.environ.get("TENDERLY_PROJECT", "").strip()
    key = os.environ.get("TENDERLY_ACCESS_KEY", "").strip()

    if not (user and project and key):
        print("FAIL: TENDERLY_USER / TENDERLY_PROJECT / TENDERLY_ACCESS_KEY not set")
        return 2

    try:
        import httpx
    except ImportError:
        print("FAIL: httpx not installed — run `pip install httpx`")
        return 3

    base_url = f"https://api.tenderly.co/api/v1/account/{user}/project/{project}"
    payload = {
        "network_id": "8453",  # Base
        "from": "0x0000000000000000000000000000000000000001",
        "to": "0x0000000000000000000000000000000000000001",
        "input": "0x",
        "value": "0",
        "save_if_fails": False,
        "simulation_type": "quick",
    }

    try:
        resp = httpx.post(
            f"{base_url}/simulate",
            json=payload,
            headers={
                "X-Access-Key": key,
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )
    except httpx.TimeoutException:
        print("FAIL: request timed out")
        return 3
    except Exception as exc:
        print(f"FAIL: network error — {type(exc).__name__}: {str(exc)[:120]}")
        return 3

    if resp.status_code == 200:
        print(f"PASS: Tenderly simulate endpoint OK (HTTP 200, user={user}, project={project})")
        return 0

    # Print error without revealing the key
    print(
        f"FAIL: Tenderly simulate endpoint returned HTTP {resp.status_code} — "
        f"{resp.text[:300]}"
    )
    return 1


if __name__ == "__main__":
    # Load .env if present
    _env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(_env_path):
        try:
            import dotenv
            dotenv.load_dotenv(_env_path)
        except ImportError:
            pass  # dotenv not installed; rely on env already set

    sys.exit(_check())
