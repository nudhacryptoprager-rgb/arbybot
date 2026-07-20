"""API layer — read-only operator API.

Canonical home for the read-only API over materialized projections.
The API never mutates runtime state; it serves cached, mtime-keyed
projections of the canonical rolling/tmp artifacts with ETag support,
pagination and Prometheus metrics.
"""
from __future__ import annotations

from api.app import ApiApp
from api.projections import ProjectionCache

__all__ = ["ApiApp", "ProjectionCache"]
