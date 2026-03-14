# PATH: core/repo_checks.py
"""
Docs-policy constants extracted from scripts/check_repo_safety.py (R28).

These constants define the canonical docs-policy rules (allowed files,
version-exempt paths, timestamp-exempt paths) and are importable by both
the safety gate script and any other tooling that needs them.

The script re-exports these for backward compatibility.
"""

from __future__ import annotations

# DEV_REPORT files allowed in repo
ALLOWED_DEV_REPORTS = [
    "docs/DEV_REPORT_LATEST.md",
    "docs/DEV_REPORT_CANONICAL_UA.md",
]

# Files where version strings are ALLOWED
DOCS_VERSION_EXEMPT = [
    "docs/DEV_REPORT_LATEST.md",
    "docs/DOCS_POLICY.md",
    "docs/m4/ROLLING_CONTRACT.md",
    "docs/m4/M4_POLICY.md",
]

# Path prefixes where versions are allowed (golden fixtures, artifacts)
DOCS_VERSION_EXEMPT_PREFIXES = [
    "docs/artifacts/",
]

# Files where ISO timestamps are allowed
DOCS_TIMESTAMP_EXEMPT = [
    "docs/DEV_REPORT_LATEST.md",
    "docs/m4/ROLLING_CONTRACT.md",
    "docs/m4/M4_POLICY.md",
]

# Keys that should never appear in TRACKED .vscode/settings.json
FORBIDDEN_KEYS_IN_TRACKED = [
    "chat.tools.terminal.autoApprove",
    "chat.tools.codeGeneration.autoApprove",
    "chat.acceptAllTerminalRisks",
    "chat.agent.autoApprove",
]

# Patterns that indicate secrets or credentials
SECRET_PATTERNS = [
    "ALCHEMY_API_KEY=",
    "TENDERLY_ACCESS_KEY=",
    "PRIVATE_KEY=",
    "INFURA_API_KEY=",
    "ETHERSCAN_API_KEY=",
]
