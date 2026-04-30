"""M7.E1.47/P2: DISC -> PROD pair promotion.

Pure module that reads discovery-lane evidence (scoreboard + promoted pairs)
and emits a list of pair_keys that have proven repeatable-positive
characteristics in DISC and are therefore candidates for the PROD
priority prewarm queue.

Promotion rules (intentionally conservative):
  1. Family must appear in DISC scoreboard with:
       - scored_positive >= MIN_POSITIVE (default 1)
       - route_viable    >= MIN_VIABLE   (default 2)
       - sessions_with_signal length >= MIN_SESSIONS (default 1)
  2. OR the pair already appears in DISC's `execution` promoted_pairs list
     (already passed cold execution gate in DISC).

This module is read-only on its inputs and emits a simple list of pair_keys
("symbolA/symbolB"). The caller decides where to merge it (e.g., into the
PROD `_promoted_pairs.json` candidate list).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Set


@dataclass(frozen=True)
class PromotionThresholds:
    min_positive: int = 1
    min_viable: int = 2
    min_sessions: int = 1


def families_qualifying_from_scoreboard(
    scoreboard: dict,
    *,
    thresholds: PromotionThresholds | None = None,
) -> Set[str]:
    """Return set of family names (token-A symbol) qualifying by scoreboard.

    `scoreboard` schema follows `_read_discovery_scoreboard()` — a dict with a
    "families" key mapping family-name -> stat dict.
    """
    th = thresholds or PromotionThresholds()
    out: Set[str] = set()
    families = (scoreboard or {}).get("families") or {}
    if not isinstance(families, dict):
        return out
    for fam, rec in families.items():
        if not isinstance(rec, dict):
            continue
        if int(rec.get("scored_positive", 0) or 0) < th.min_positive:
            continue
        if int(rec.get("route_viable", 0) or 0) < th.min_viable:
            continue
        sessions = rec.get("sessions_with_signal") or []
        if not isinstance(sessions, list) or len(sessions) < th.min_sessions:
            continue
        if isinstance(fam, str) and fam:
            out.add(fam)
    return out


def pairs_from_disc_execution(disc_promoted: dict) -> Set[str]:
    """Pair-keys already in DISC's execution-tier promoted list."""
    out: Set[str] = set()
    if not isinstance(disc_promoted, dict):
        return out
    for p in (disc_promoted.get("execution") or []):
        if isinstance(p, str) and "/" in p:
            out.add(p)
    return out


def select_pairs_to_promote(
    disc_scoreboard: dict,
    disc_promoted_pairs: dict,
    *,
    thresholds: PromotionThresholds | None = None,
    candidate_pool: Iterable[str] | None = None,
) -> List[str]:
    """Combine scoreboard + DISC execution into a PROD-candidate pair list.

    `candidate_pool` (optional): if provided, family-based selections are only
    emitted when at least one pair starting with `family/` exists in the pool.
    Without a pool, family-based selections are dropped (we only emit explicit
    pair-keys to avoid synthesising bogus pairs).
    """
    out: Set[str] = set()
    out |= pairs_from_disc_execution(disc_promoted_pairs)

    qual_families = families_qualifying_from_scoreboard(
        disc_scoreboard, thresholds=thresholds
    )
    if qual_families and candidate_pool is not None:
        for pk in candidate_pool:
            if not isinstance(pk, str) or "/" not in pk:
                continue
            fam = pk.split("/", 1)[0]
            if fam in qual_families:
                out.add(pk)

    # Stable ordering for downstream determinism.
    return sorted(out)


def merge_into_prod_candidates(
    prod_promoted: dict,
    new_pairs: Iterable[str],
) -> dict:
    """Return a copy of `prod_promoted` with `new_pairs` merged into candidates.

    Existing execution-tier pairs are preserved; duplicates are deduped.
    """
    if not isinstance(prod_promoted, dict):
        prod_promoted = {}
    candidates = list(prod_promoted.get("candidate") or [])
    seen: Set[str] = {p for p in candidates if isinstance(p, str)}
    for p in new_pairs:
        if isinstance(p, str) and p and p not in seen:
            candidates.append(p)
            seen.add(p)
    return {
        "candidate": candidates,
        "execution": list(prod_promoted.get("execution") or []),
    }
