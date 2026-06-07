"""V5-12: running heads — \\title[short], \\markboth/\\markright -> Word header + page footer."""

from __future__ import annotations

import io
import zipfile

from tex2word import convert_source
from tex2word.backend.latex_writer import write_latex
from tex2word.roundtrip import to_latex
from tex2word.validate import validate_docx


def _parts(docx: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(docx)).namelist()


def _read(docx: bytes, name: str) -> str:
    return zipfile.ZipFile(io.BytesIO(docx)).read(name).decode("utf-8")


TITLE_OPT = r"""
\documentclass{article}
\title[Short Head]{A Long Full Title}
\begin{document}\maketitle
\section{Intro}Body.
\end{document}
"""

MARKBOTH = r"""
\begin{document}
\markboth{Even Side}{Odd Running Head}
\section{S}Text.
\end{document}
"""


def test_title_optional_sets_running_head():
    res = convert_source(TITLE_OPT)
    assert res.document.meta.running_head == "Short Head"
    parts = _parts(res.docx)
    assert "word/header_rh.xml" in parts
    assert "word/footer_rh.xml" in parts
    assert "Short Head" in _read(res.docx, "word/header_rh.xml")
    # the footer carries a live PAGE field
    assert "PAGE" in _read(res.docx, "word/footer_rh.xml")
    # the section references both
    doc = _read(res.docx, "word/document.xml")
    assert "headerReference" in doc and "footerReference" in doc


def test_markboth_uses_recto_head():
    res = convert_source(MARKBOTH)
    assert res.document.meta.running_head == "Odd Running Head"


def test_output_is_valid_with_running_head():
    assert validate_docx(convert_source(TITLE_OPT).docx) == []
    assert validate_docx(convert_source(MARKBOTH).docx) == []


def test_no_running_head_no_header_part():
    res = convert_source(r"\begin{document}\section{S}Text.\end{document}")
    assert res.document.meta.running_head is None
    assert "word/header_rh.xml" not in _parts(res.docx)


def test_running_head_roundtrips_to_latex():
    res = convert_source(TITLE_OPT)
    assert "\\title[Short Head]{" in write_latex(res.document)


def test_running_head_survives_reconcile():
    tex = to_latex(convert_source(TITLE_OPT).docx)
    assert tex is not None
    assert "Short Head" in tex
