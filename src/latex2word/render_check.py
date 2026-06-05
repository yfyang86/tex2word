"""V4-1 (partial): a render smoke-check — does the produced .docx open and
render in a real word processor?

The structural validator (:mod:`latex2word.validate`) proves the OOXML is
well-formed and schema-ordered, but not that it *renders*. This module drives
LibreOffice headless to convert ``.docx`` → PDF and inspects the PDF with
``pypdfium2`` (page count + extracted text). It is a smoke check (did it render
to a non-empty page?), not golden-image diffing.

The two halves are split so the inspection logic is unit-testable without a
renderer: :func:`inspect_pdf` works on any PDF; :func:`render_to_pdf` shells out
to ``soffice``. ``soffice`` and ``pypdfium2`` (the ``pdf`` extra) are optional —
the checker reports a clean SKIP when the renderer is unavailable rather than
failing, so it is safe to run anywhere.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SOFFICE_NAMES = ("soffice", "libreoffice")


def find_soffice() -> str | None:
    """Path to a LibreOffice/soffice binary, or None if not installed."""
    for name in _SOFFICE_NAMES:
        path = shutil.which(name)
        if path:
            return path
    return None


def render_to_pdf(docx_path: str | Path, outdir: str | Path, timeout: int = 180) -> Path | None:
    """Convert ``docx_path`` to PDF via LibreOffice; return the PDF path or None.

    Returns None if soffice is missing, errors, times out, or produces no file.
    """
    soffice = find_soffice()
    if soffice is None:
        return None
    docx_path, outdir = Path(docx_path), Path(outdir)
    env = os.environ.copy()
    env.setdefault("HOME", str(outdir))  # soffice needs a writable profile dir
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", str(outdir), str(docx_path)],
            timeout=timeout, capture_output=True, env=env, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    pdf = outdir / (docx_path.stem + ".pdf")
    return pdf if pdf.exists() else None


def inspect_pdf(pdf_path: str | Path, expect_substrings: list[str] | None = None) -> list[str]:
    """Return a list of problems with a rendered PDF (empty == looks fine).

    Checks it has at least one page with non-empty text, and that every string
    in ``expect_substrings`` appears somewhere in the extracted text.
    """
    import pypdfium2 as pdfium  # PDFium, Apache-2.0/BSD (the `pdf` extra)

    problems: list[str] = []
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        if len(doc) < 1:
            return [f"{Path(pdf_path).name}: rendered to 0 pages"]
        text = "".join(page.get_textpage().get_text_range() for page in doc)
    finally:
        doc.close()
    if not text.strip():
        problems.append(f"{Path(pdf_path).name}: rendered text is empty")
    for s in expect_substrings or []:
        if s not in text:
            problems.append(f"{Path(pdf_path).name}: expected text {s!r} not in render")
    return problems


def check_docx(docx_path: str | Path, expect: list[str] | None = None) -> list[str] | None:
    """Render and inspect a .docx. None means 'renderer unavailable' (skip)."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = render_to_pdf(docx_path, tmp)
        if pdf is None:
            return None
        return inspect_pdf(pdf, expect)


def _main(argv: list[str]) -> int:
    """CLI: ``python -m latex2word.render_check a.tex b.tex …`` (or .docx).

    Converts each .tex with the library, renders, and inspects. If no renderer
    is installed at all it SKIPs (exit 0); but once soffice *is* present, a
    failure to produce a PDF is a real failure (exit 1) — so this is safe to use
    as a blocking CI gate.
    """
    from . import convert_file

    if find_soffice() is None:
        print("SKIP render-check: no LibreOffice/soffice on PATH")
        return 0
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for arg in argv:
            src = Path(arg)
            if src.suffix == ".tex":
                docx = Path(tmp) / (src.stem + ".docx")
                _, result = convert_file(str(src), str(docx))
            else:
                docx = src
            res = check_docx(docx)
            if res is None:  # soffice present but produced no PDF -> real failure
                res = [f"{src.name}: LibreOffice produced no PDF"]
            if res:
                problems += res
                print(f"FAIL {src.name}: {'; '.join(res)}")
            else:
                print(f"OK   {src.name}: rendered")
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
