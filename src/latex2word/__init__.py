"""latex2word: an open-source LaTeX -> Microsoft Word (.docx) converter.

See ``README.md`` for the architecture overview. The public entry points are
:func:`~latex2word.pipeline.convert_source` and
:func:`~latex2word.pipeline.convert_file`.
"""

from __future__ import annotations

from .pipeline import ConversionResult, convert_file, convert_source

__all__ = ["ConversionResult", "convert_file", "convert_source"]
__version__ = "0.8.0"
