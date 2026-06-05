"""IR -> IR transforms (cross-reference resolution, ...)."""

from __future__ import annotations

from .crossref import resolve_crossrefs

__all__ = ["resolve_crossrefs"]
