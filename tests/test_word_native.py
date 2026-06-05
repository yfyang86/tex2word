"""V4-17: reading Word-native content (foreign equations/tables + field
citations from Zotero / Mendeley / EndNote)."""

from __future__ import annotations

from xml.sax.saxutils import escape

from lxml import etree

from latex2word import convert_source, ir
from latex2word.frontend import docx_reader as R
from latex2word.frontend.docx_reader import read_docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _field_para(instr: str, result: str) -> etree._Element:
    return etree.fromstring(
        f'<w:p xmlns:w="{W}"><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve">{escape(instr)}</w:instrText></w:r>'
        f'<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f'<w:r><w:t>{result}</w:t></w:r>'
        f'<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'.encode()
    )


def _cites(para: etree._Element) -> list[ir.Cite]:
    return [i for i in R._Reader(ir.DocumentMeta())._inlines(para) if isinstance(i, ir.Cite)]


# -- field citations from the three big reference managers ------------------- #


def test_zotero_citation_field_to_cite():
    instr = ('ADDIN ZOTERO_ITEM CSL_CITATION {"citationItems":'
             '[{"uris":["http://zotero.org/users/1/items/ABCD1234"]}]}')
    cites = _cites(_field_para(instr, "[1]"))
    assert cites and cites[0].keys == ["ABCD1234"] and cites[0].rendered == "[1]"


def test_mendeley_citation_field_to_cite():
    instr = ('ADDIN CSL_CITATION {"citationItems":'
             '[{"itemData":{"id":"Smith2020","title":"On Things"}}]}')
    cites = _cites(_field_para(instr, "(Smith, 2020)"))
    assert cites and cites[0].keys == ["Smith2020"]


def test_endnote_citation_field_to_cite():
    instr = ("ADDIN EN.CITE <EndNote><Cite><record>"
             "<rec-number>42</rec-number></record></Cite></EndNote>")
    cites = _cites(_field_para(instr, "(Smith 2020)"))
    assert cites and cites[0].keys == ["42"]


def test_multi_item_csl_citation():
    instr = ('ADDIN CSL_CITATION {"citationItems":'
             '[{"itemData":{"id":"a"}},{"itemData":{"id":"b"}}]}')
    cites = _cites(_field_para(instr, "(a; b)"))
    assert cites and cites[0].keys == ["a", "b"]


# -- foreign equations + tables already round-trip (lock-in) ----------------- #


def _foreign(src: str) -> ir.Document:
    return read_docx(convert_source(src, embed_manifest=False).docx)


def test_foreign_inline_equation_recovers_as_math():
    doc = _foreign(r"\begin{document}Energy $e=mc^2$ holds.\end{document}")
    maths = [i for b in doc.blocks if isinstance(b, ir.Paragraph)
             for i in b.inlines if isinstance(i, ir.Math)]
    latex = maths[0].latex.replace(" ", "") if maths else ""
    assert maths and latex.startswith("e=m") and "^{2}" in latex


def test_foreign_table_recovers():
    src = r"\begin{document}\begin{tabular}{ll}a & b \\ c & d \\\end{tabular}\end{document}"
    table = next(b for b in _foreign(src).blocks if isinstance(b, ir.Table))
    assert len(table.rows) == 2
