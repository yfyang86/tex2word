"""Fidelity: center/flushleft/flushright apply paragraph alignment (w:jc)."""

from __future__ import annotations

import io
import zipfile

from tex2word import convert_source
from tex2word.roundtrip import recover_ir, to_latex
from tex2word.validate import validate_docx


def _jc_vals(docx: bytes) -> list[str]:
    doc = zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode("utf-8")
    import re

    return re.findall(r'<w:jc w:val="([^"]+)"', doc)


SRC = r"""
\begin{document}
Plain paragraph.
\begin{center}
Centered text.
\end{center}
\begin{flushright}
Right text.
\end{flushright}
\end{document}
"""


def test_center_sets_paragraph_align():
    doc = convert_source(SRC).document
    paras = [b for b in doc.blocks if type(b).__name__ == "Paragraph"]
    aligns = {p.align for p in paras}
    assert "center" in aligns
    assert "right" in aligns


def test_jc_emitted_in_docx():
    vals = _jc_vals(convert_source(SRC).docx)
    assert "center" in vals
    assert "end" in vals  # right -> w:jc end in the current schema


def test_alignment_valid():
    assert validate_docx(convert_source(SRC).docx) == []


def test_alignment_roundtrips():
    tex = to_latex(convert_source(SRC).docx)
    assert tex is not None
    assert "\\begin{center}" in tex
    assert "\\begin{flushright}" in tex


def test_manifest_preserves_align():
    doc = recover_ir(convert_source(SRC).docx)
    assert doc is not None
    aligns = {b.align for b in doc.blocks if type(b).__name__ == "Paragraph"}
    assert {"center", "right"} <= aligns
