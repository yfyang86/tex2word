"""V5-12: index (\\index / \\printindex -> Word XE / INDEX fields)."""

from __future__ import annotations

import io
import zipfile

from tex2word import convert_source, ir
from tex2word.roundtrip import to_latex


def _docxml(docx: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode()


def test_index_entry_emits_xe_field():
    res = convert_source(r"\begin{document}A term\index{term}.\end{document}")
    xml = _docxml(res.docx)
    assert 'XE "term"' in xml
    para = next(b for b in res.document.blocks if isinstance(b, ir.Paragraph))
    assert any(isinstance(i, ir.IndexEntry) and i.term == "term" for i in para.inlines)


def test_printindex_emits_index_field():
    res = convert_source(r"\begin{document}\printindex\end{document}")
    assert "INDEX" in _docxml(res.docx)
    assert any(isinstance(b, ir.Index) for b in res.document.blocks)


def test_index_round_trips():
    res = convert_source(r"\begin{document}A\index{alpha}.\printindex\end{document}")
    latex = to_latex(res.docx)
    assert r"\index{alpha}" in latex
    assert r"\printindex" in latex
    assert "\\makeindex" in latex  # round-trip preamble enables the index


def test_index_quote_is_sanitised():
    res = convert_source(r'\begin{document}\index{a "b"}\end{document}')
    # the embedded quotes are replaced so the XE field string stays well-formed
    assert 'XE "a \'b\'"' in _docxml(res.docx)


def test_output_with_index_is_valid():
    from tex2word.validate import validate_docx

    res = convert_source(r"\begin{document}A\index{t}.\printindex\end{document}")
    assert validate_docx(res.docx) == []
