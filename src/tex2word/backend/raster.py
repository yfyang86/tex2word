"""Rasterising vector figures (PDF) to PNG for embedding.

Word cannot embed PDF/EPS directly, so the PRD's image path converts them. This
uses ``pypdfium2`` (Google's PDFium, Apache-2.0/BSD) plus Pillow when available
-- both permissive, so tex2word carries no GPL/AGPL dependency. When the
backend is not installed (or a format like EPS is unsupported), the caller
degrades to a placeholder + a warning suggesting ``pip install tex2word[pdf]``.
"""

from __future__ import annotations

import io
from functools import lru_cache

DEFAULT_DPI = 200


@lru_cache(maxsize=1)
def has_pdf_support() -> bool:
    """True if a PDF rasteriser backend (pypdfium2 + Pillow) is importable."""
    try:
        import PIL.Image  # noqa: F401
        import pypdfium2  # noqa: F401

        return True
    except Exception:
        return False


def rasterize_pdf(path: str, dpi: int = DEFAULT_DPI) -> tuple[bytes, int, int] | None:
    """Render the first page of a PDF to PNG bytes + (width_px, height_px).

    Returns ``None`` if no backend is available or the render fails.
    """
    try:
        import pypdfium2 as pdfium
    except Exception:
        return None
    try:
        doc = pdfium.PdfDocument(path)
        try:
            if len(doc) == 0:
                return None
            # PDF user space is 1/72 inch; scale maps the target DPI onto it.
            bitmap = doc[0].render(scale=dpi / 72.0)
            pil = bitmap.to_pil().convert("RGB")
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            return buf.getvalue(), pil.width, pil.height
        finally:
            doc.close()
    except Exception:
        return None


def rasterize(path: str, fmt: str, dpi: int = DEFAULT_DPI) -> tuple[bytes, int, int] | None:
    """Rasterise a vector image of the given format, or ``None`` if unsupported."""
    if fmt == "pdf":
        return rasterize_pdf(path, dpi)
    # EPS/PS need Ghostscript; not bundled (see SPRINT-V1/05-uat-backlog.md B1).
    return None
