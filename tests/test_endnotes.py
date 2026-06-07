"""V5-12: endnotes (\\endnote -> native Word endnotes)."""

from __future__ import annotations

import io
import zipfile

from tex2word import convert_source, ir
from tex2word.roundtrip import to_latex


def _parts(docx: bytes) -> dict[str, str]:
    z = zipfile.ZipFile(io.BytesIO(docx))
    return {n: z.read(n).decode() for n in z.namelist()}


def test_endnote_emits_endnotes_part_and_reference():
    res = convert_source(
        r"\begin{document}Claim\endnote{see appendix}.\theendnotes\end{document}"
    )
    parts = _parts(res.docx)
    assert "word/endnotes.xml" in parts
    assert "see appendix" in parts["word/endnotes.xml"]
    assert "endnoteReference" in parts["word/document.xml"]
    # content-type override + relationship are present
    assert "endnotes+xml" in parts["[Content_Types].xml"]
    assert "endnotes.xml" in parts["word/_rels/document.xml.rels"]


def test_no_endnotes_means_no_part():
    res = convert_source(r"\begin{document}Plain.\end{document}")
    assert "word/endnotes.xml" not in _parts(res.docx)


def test_theendnotes_is_consumed_not_leaked():
    res = convert_source(r"\begin{document}A\endnote{n}.\theendnotes\end{document}")
    assert "theendnotes" not in _parts(res.docx)["word/document.xml"]


def test_endnote_round_trips():
    res = convert_source(r"\begin{document}Claim\endnote{see appendix}.\end{document}")
    latex = to_latex(res.docx)
    assert r"\endnote{see appendix}" in latex


def test_endnote_in_ir():
    res = convert_source(r"\begin{document}A\endnote{note here}.\end{document}")
    para = next(b for b in res.document.blocks if isinstance(b, ir.Paragraph))
    assert any(isinstance(i, ir.Endnote) for i in para.inlines)


def test_output_with_endnotes_is_valid():
    from tex2word.validate import validate_docx

    res = convert_source(r"\begin{document}A\endnote{n}.\end{document}")
    assert validate_docx(res.docx) == []
