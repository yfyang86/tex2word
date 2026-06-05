"""Reference subsystem: .bib -> CSL-JSON -> formatted bibliography.

V1 ships the static-text mode (numeric / author-year). The PRD's live
``ADDIN ZOTERO_ITEM CSL_CITATION`` field mode is a planned post-V1 upgrade.
"""

from __future__ import annotations

from .bibtex import parse_bibtex
from .render import Bibliography, build_bibliography

__all__ = ["Bibliography", "build_bibliography", "parse_bibtex"]
