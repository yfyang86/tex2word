"""Fidelity: \\hyperref[label]{text} -> internal hyperlink with custom text."""

from __future__ import annotations

import io
import zipfile

from tex2word import convert_source
from tex2word.roundtrip import to_latex
from tex2word.validate import validate_docx


def _instrs(docx: bytes) -> str:
    doc = zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode("utf-8")
    return doc


SRC = r"""
\begin{document}
\section{Introduction}\label{sec:intro}
See \hyperref[sec:intro]{the intro} for details.
\end{document}
"""


def test_hyperref_emits_internal_hyperlink():
    res = convert_source(SRC)
    assert validate_docx(res.docx) == []
    doc = _instrs(res.docx)
    # internal link uses HYPERLINK \l "bookmark", and the display text is present
    assert 'HYPERLINK \\l "sec_intro"' in doc
    assert "the intro" in doc


def test_hyperref_link_node_has_anchor():
    doc = convert_source(SRC).document
    links = []

    def walk(inlines):
        for n in inlines:
            if type(n).__name__ == "Link":
                links.append(n)
            elif hasattr(n, "inlines"):
                walk(n.inlines)

    for b in doc.blocks:
        if hasattr(b, "inlines"):
            walk(b.inlines)
    assert any(getattr(link, "anchor", None) for link in links)


def test_hyperref_roundtrips():
    tex = to_latex(convert_source(SRC).docx)
    assert tex is not None
    assert "\\hyperref[" in tex
    assert "the intro" in tex


def test_unresolved_hyperref_warns_but_is_valid():
    src = r"\begin{document}See \hyperref[nope]{ghost}.\end{document}"
    res = convert_source(src)
    assert validate_docx(res.docx) == []
    assert any("hyperref" in (w.construct or "") for w in res.report.warnings)
