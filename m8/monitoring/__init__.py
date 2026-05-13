"""m8.monitoring — funnel tracker, artifact writer, honeypot detector.

Re-exports all public symbols from:
  - ``monitoring.sniper_funnel``
  - ``monitoring.sniper_artifacts``
  - ``monitoring.sniper_honeypot``

Migration note:
  Canonical modules are currently at ``monitoring/sniper_*.py``.
  Tests import from those paths.  This package is the forward-compatible
  import path for new M8 code; canonical files move here incrementally.
"""
from monitoring.sniper_funnel import (  # noqa: F401
    EventTrace,
    FunnelTracker,
    FUNNEL_STAGE_NAMES,
)
from monitoring.sniper_artifacts import (  # noqa: F401
    SCHEMA_FAMILY,
    SCHEMA_REVISION,
    ROLLING_ARTIFACT_PATH,
    REQUIRED_TOP_LEVEL_FIELDS,
    make_empty_sniper_state,
    make_sniper_artifact,
    write_sniper_artifact,
    validate_sniper_artifact,
)
from monitoring.sniper_honeypot import (  # noqa: F401
    HoneypotVerdict,
    check_token_honeypot,
    is_safe_for_pipeline,
    KNOWN_SCAM_TOKENS,
    KNOWN_LEGIT_TOKENS,
)

__all__ = [
    # funnel
    "EventTrace",
    "FunnelTracker",
    "FUNNEL_STAGE_NAMES",
    # artifacts
    "SCHEMA_FAMILY",
    "SCHEMA_REVISION",
    "ROLLING_ARTIFACT_PATH",
    "REQUIRED_TOP_LEVEL_FIELDS",
    "make_empty_sniper_state",
    "make_sniper_artifact",
    "write_sniper_artifact",
    "validate_sniper_artifact",
    # honeypot
    "HoneypotVerdict",
    "check_token_honeypot",
    "is_safe_for_pipeline",
    "KNOWN_SCAM_TOKENS",
    "KNOWN_LEGIT_TOKENS",
]
