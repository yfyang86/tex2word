"""Math subsystem: LaTeX math -> math AST -> OMML (the primary, direct path)."""

from __future__ import annotations

from .omml import latex_to_omml

__all__ = ["latex_to_omml"]
