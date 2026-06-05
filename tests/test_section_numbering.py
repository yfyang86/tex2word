from __future__ import annotations

from conftest import NS, document_root

from tex2word import convert_source
from tex2word.backend import fields

SRC = r"""
\begin{document}
\section{Alpha}
\begin{equation}\label{eq:1}E=mc^2\end{equation}
\section{Beta}
\begin{equation}\label{eq:2}a=b\end{equation}
See \eqref{eq:1} and \eqref{eq:2}.
\end{document}
"""


def _instrs(docx) -> str:
    root = document_root(docx)
    return "".join(t.text or "" for t in root.xpath("//w:instrText", namespaces=NS))


def test_flat_numbering_is_default():
    instrs = _instrs(convert_source(SRC).docx)
    assert "SEQ Equation \\* ARABIC" in instrs
    assert "STYLEREF" not in instrs


def test_by_section_uses_styleref_and_reset_seq():
    instrs = _instrs(convert_source(SRC, number_by_section=True).docx)
    assert "STYLEREF 1 \\s" in instrs
    assert "SEQ Equation \\s 1" in instrs


def test_number_field_helper_flat():
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    runs = fields.number_field("Figure", by_section=False)
    text = "".join((r.findtext(w + "instrText") or "") for r in runs)
    assert "SEQ Figure" in text
    assert "STYLEREF" not in text


def test_number_field_helper_by_section_has_dot():
    runs = fields.number_field("Figure", by_section=True)
    # the literal "." separator between STYLEREF and SEQ is present as a w:t run
    texts = [
        r.findtext("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
        for r in runs
    ]
    assert "." in texts


def test_by_section_ref_bookmark_wraps_full_number():
    # the bookmark around a numbered equation should enclose both the STYLEREF
    # and the SEQ field, so a REF to it reproduces "N.M".
    root = document_root(convert_source(SRC, number_by_section=True).docx)
    # find a bookmarkStart followed (within the paragraph) by STYLEREF + SEQ
    instrs_in_bookmarked = root.xpath(
        "//w:p[.//w:bookmarkStart]//w:instrText/text()", namespaces=NS
    )
    joined = " ".join(instrs_in_bookmarked)
    assert "STYLEREF 1 \\s" in joined and "SEQ Equation \\s 1" in joined


def test_output_valid_in_both_modes():
    from tex2word.validate import validate_docx

    assert validate_docx(convert_source(SRC).docx) == []
    assert validate_docx(convert_source(SRC, number_by_section=True).docx) == []
