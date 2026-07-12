"""tex2word: an open-source LaTeX -> Microsoft Word (.docx) converter.

See ``README.md`` for the architecture overview. The public entry points are
:func:`~tex2word.pipeline.convert_source` and
:func:`~tex2word.pipeline.convert_file`.
"""

from __future__ import annotations

from .pipeline import ConversionResult, convert_file, convert_source

__all__ = ["ConversionResult", "convert_file", "convert_source"]
__version__ = "1.0.5"
