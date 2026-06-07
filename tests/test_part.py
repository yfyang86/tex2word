"""V5-12 tail: \\part headings get an independent upper-roman ("Part I") counter."""

from __future__ import annotations

from conftest import NS, document_root

from tex2word import convert_source
from tex2word.backend.latex_writer import write_latex
from tex2word.backend.numbering import PART_NUM_ID
from tex2word.roundtrip import recover_ir, to_latex
from tex2word.validate import validate_docx

SRC = r"""
\begin{document}
\part{Foundations}
\section{Alpha}
\part{Applications}
\section{Beta}
\end{document}
"""


def _heading_numids(docx) -> list[str]:
    root = document_root(docx)
    out: list[str] = []
    for p in root.xpath("//w:body/w:p", namespaces=NS):
        nid = p.xpath(".//w:numPr/w:numId/@w:val", namespaces=NS)
        out.append(nid[0] if nid else "")
    return out


def test_part_uses_dedicated_roman_numbering():
    res = convert_source(SRC)
    headings = [b for b in res.document.blocks if type(b).__name__ == "Heading"]
    parts = [h for h in headings if getattr(h, "part", False)]
    assert len(parts) == 2
    assert all(p.numbered for p in parts)
    # the part numbering definition is referenced in the body
    numids = _heading_numids(res.docx)
    assert str(PART_NUM_ID) in numids


def test_part_numbering_part_is_valid():
    assert validate_docx(convert_source(SRC).docx) == []


def test_starred_part_is_unnumbered():
    res = convert_source(r"\begin{document}\part*{Unnumbered}\end{document}")
    headings = [b for b in res.document.blocks if type(b).__name__ == "Heading"]
    assert len(headings) == 1
    assert headings[0].part is True
    assert headings[0].numbered is False


def test_part_roundtrips_to_latex():
    res = convert_source(SRC)
    tex = write_latex(res.document)
    assert "\\part{Foundations}" in tex
    assert "\\part{Applications}" in tex


def test_part_recovered_from_manifest():
    res = convert_source(SRC)
    doc = recover_ir(res.docx)
    assert doc is not None
    headings = [b for b in doc.blocks if type(b).__name__ == "Heading"]
    parts = [h for h in headings if getattr(h, "part", False)]
    assert len(parts) == 2


def test_part_unedited_reconciles_to_identity():
    # an unedited round-trip keeps the manifest, so \part survives verbatim
    res = convert_source(SRC)
    tex = to_latex(res.docx)
    assert tex is not None
    assert tex.count("\\part{") == 2
