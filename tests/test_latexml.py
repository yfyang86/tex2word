"""SPRINT-V3 A1: LaTeXML front-end XML->IR mapping + graceful fallback."""

from __future__ import annotations

from tex2word import convert_source, ir
from tex2word.frontend.latexml import latexml_available, parse_latexml_xml
from tex2word.report import ConversionReport

XML = b"""<?xml version="1.0"?>
<document xmlns="http://dlmf.nist.gov/LaTeXML">
  <title>Expanded <text font="bold">Title</text></title>
  <creator><personname>Ada Lovelace</personname></creator>
  <abstract><para><p>An abstract.</p></para></abstract>
  <section labels="LABEL:sec:intro">
    <title>Introduction</title>
    <para><p>Hello <text font="bold">world</text>, math
      <Math mode="inline" tex="x^2 + 1"/> and ref <ref labelref="LABEL:eq:e"/>
      and cite <cite><bibref bibrefs="knuth"/></cite>.</p></para>
    <equation labels="LABEL:eq:e" refnum="1">
      <Math mode="display" tex="E = mc^2"/>
    </equation>
    <itemize>
      <item><para><p>First</p></para></item>
      <item><para><p>Second <emph>item</emph></p></para></item>
    </itemize>
    <tabular>
      <tr><td>a</td><td>b</td></tr>
      <tr><td>c</td><td>d</td></tr>
    </tabular>
  </section>
</document>"""


def _doc() -> ir.Document:
    return parse_latexml_xml(XML, ConversionReport())


def test_title_author_abstract():
    doc = _doc()
    assert doc.meta.title[0].value == "Expanded "
    assert isinstance(doc.meta.title[1], ir.Emphasis)
    assert doc.meta.authors[0][0].value == "Ada Lovelace"
    assert doc.meta.abstract is not None


def test_heading_with_label():
    doc = _doc()
    h = next(b for b in doc.blocks if isinstance(b, ir.Heading))
    assert h.level == 1
    assert h.inlines[0].value == "Introduction"
    assert h.label == "sec:intro"


def test_inline_math_uses_tex_attribute():
    doc = _doc()
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    math = next(i for i in para.inlines if isinstance(i, ir.Math))
    assert math.latex == "x^2 + 1"


def test_emphasis_ref_cite_recovered():
    para = next(b for b in _doc().blocks if isinstance(b, ir.Paragraph))
    assert any(isinstance(i, ir.Emphasis) and i.kind_ == "bold" for i in para.inlines)
    ref = next(i for i in para.inlines if isinstance(i, ir.Ref))
    assert ref.key == "eq:e"
    cite = next(i for i in para.inlines if isinstance(i, ir.Cite))
    assert cite.keys == ["knuth"]


def test_numbered_equation_from_tex():
    mb = next(b for b in _doc().blocks if isinstance(b, ir.MathBlock))
    assert mb.latex == "E = mc^2"
    assert mb.numbered is True
    assert mb.label == "eq:e"


def test_list_and_table():
    doc = _doc()
    lst = next(b for b in doc.blocks if isinstance(b, ir.ItemList))
    assert len(lst.items) == 2
    tbl = next(b for b in doc.blocks if isinstance(b, ir.Table))
    assert len(tbl.rows) == 2 and len(tbl.rows[0].cells) == 2


def test_latexml_math_flows_to_omml():
    # the tex attribute -> Math -> OMML through the normal writer
    from lxml import etree

    from tex2word.backend.document import DocumentWriter
    from tex2word.transforms.crossref import resolve_crossrefs

    doc = _doc()
    report = ConversionReport()
    resolve_crossrefs(doc, report)
    xml = DocumentWriter(report).build(doc)
    root = etree.fromstring(xml)
    NS = {"m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}
    assert root.xpath("//m:oMath", namespaces=NS)


def test_frontend_latexml_falls_back_when_unavailable():
    # latexml isn't installed in CI/dev -> graceful fallback to the pure parser
    if latexml_available():
        return  # if it is installed, this path isn't exercised
    result = convert_source(
        r"\begin{document}\section{S}$x^2$\end{document}", frontend="latexml"
    )
    assert result.report.errors == []
    assert any("latexml" in w.construct for w in result.report.warnings)
    # still produced editable math via the fallback
    assert result.report.coverage()["math_omml"] == 1
