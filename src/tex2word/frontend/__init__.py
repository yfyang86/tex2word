"""Front-end: LaTeX source -> IR. (Static-parser based for V1; see SPRINT-V1.)"""

from __future__ import annotations

from .parser import parse_document

__all__ = ["parse_document"]
