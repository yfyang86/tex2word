"""Image fallback for math (cascade stage 3, A5).

When neither the direct LaTeX->OMML writer nor the LaTeX->MathML->OMML path can
convert a formula, render it to an image so it is at least *shown* (the PRD's
last resort before raw text). Two backends:

* :class:`DvipngMathRenderer` -- a real TeX engine (``latex`` + ``dvipng``):
  full fidelity, handles everything, but needs TeX Live installed.
* :class:`MatplotlibMathRenderer` -- pure-Python via matplotlib's ``mathtext``
  (optional ``latex2word[mathimg]``): self-contained, covers a broad subset.

:func:`default_renderer` picks the best available (dvipng > matplotlib > none).
Image math loses editability, so it is opt-in (``--math-image-fallback``).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile

DEFAULT_DPI = 200


class MatplotlibMathRenderer:
    """Render math to PNG via matplotlib's built-in mathtext (no TeX needed)."""

    def __init__(self, dpi: int = DEFAULT_DPI) -> None:
        self.dpi = dpi

    @staticmethod
    def available() -> bool:
        import importlib.util

        return importlib.util.find_spec("matplotlib") is not None

    def render(self, latex: str, display: bool) -> tuple[bytes, str] | None:
        try:
            from matplotlib import mathtext
        except Exception:
            return None
        try:
            buf = io.BytesIO()
            expr = f"${latex}$"
            mathtext.math_to_image(expr, buf, dpi=self.dpi, format="png")
            data = buf.getvalue()
            return (data, "png") if data[:8] == b"\x89PNG\r\n\x1a\n" else None
        except Exception:
            return None


class DvipngMathRenderer:
    """Render math to PNG via a real TeX engine: latex -> dvi -> dvipng."""

    _PREAMBLE = (
        "\\documentclass[border=2pt]{standalone}\n"
        "\\usepackage{amsmath,amssymb,amsfonts}\n"
        "\\begin{document}\n"
    )

    def __init__(self, dpi: int = DEFAULT_DPI) -> None:
        self.dpi = dpi

    @staticmethod
    def available() -> bool:
        return shutil.which("latex") is not None and shutil.which("dvipng") is not None

    def render(self, latex: str, display: bool) -> tuple[bytes, str] | None:
        if not self.available():
            return None
        body = f"\\[{latex}\\]" if display else f"${latex}$"
        doc = f"{self._PREAMBLE}{body}\n\\end{{document}}\n"
        try:
            with tempfile.TemporaryDirectory() as td:
                tex = os.path.join(td, "m.tex")
                with open(tex, "w", encoding="utf-8") as fh:
                    fh.write(doc)
                latex_proc = subprocess.run(
                    ["latex", "-interaction=nonstopmode", "-halt-on-error", "m.tex"],
                    cwd=td, capture_output=True, timeout=60,
                )
                dvi = os.path.join(td, "m.dvi")
                if latex_proc.returncode != 0 or not os.path.exists(dvi):
                    return None
                png = os.path.join(td, "m.png")
                dvipng = subprocess.run(
                    ["dvipng", "-D", str(self.dpi), "-T", "tight", "-bg", "Transparent",
                     "-o", png, dvi],
                    cwd=td, capture_output=True, timeout=60,
                )
                if dvipng.returncode != 0 or not os.path.exists(png):
                    return None
                with open(png, "rb") as fh:
                    return fh.read(), "png"
        except Exception:
            return None


def default_renderer(dpi: int = DEFAULT_DPI):
    """Return the best available math-image renderer, or ``None``."""
    if DvipngMathRenderer.available():
        return DvipngMathRenderer(dpi)
    if MatplotlibMathRenderer.available():
        return MatplotlibMathRenderer(dpi)
    return None
