from __future__ import annotations

import io
import zipfile

from conftest import NS, document_root

from latex2word import convert_source


def _zip(docx: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(docx))


FN = r"""\begin{document}
Text.\footnote{First note.}
More.\footnote{Second with $x^2$.}
\end{document}"""


def test_footnotes_part_created():
    docx = convert_source(FN).docx
    assert "word/footnotes.xml" in _zip(docx).namelist()


def test_body_has_footnote_references():
    root = document_root(convert_source(FN).docx)
    ids = root.xpath("//w:footnoteReference/@w:id", namespaces=NS)
    assert ids == ["1", "2"]


def test_footnotes_xml_has_separators_and_notes():
    from lxml import etree

    fn = _zip(convert_source(FN).docx).read("word/footnotes.xml")
    tree = etree.fromstring(fn)
    types = [f.get(f"{{{NS['w']}}}type") for f in tree.xpath("//w:footnote", namespaces=NS)]
    assert types[:2] == ["separator", "continuationSeparator"]
    # two real notes after the separator pair
    assert types.count(None) == 2


def test_footnote_content_rendered():
    fn = _zip(convert_source(FN).docx).read("word/footnotes.xml").decode()
    assert "First note." in fn
    # math inside a footnote becomes OMML, not raw
    assert "oMath" in fn


def test_no_footnotes_part_when_absent():
    docx = convert_source(r"\begin{document}No notes here.\end{document}").docx
    assert "word/footnotes.xml" not in _zip(docx).namelist()


def test_footnote_reference_uses_style():
    root = document_root(convert_source(FN).docx)
    styles = root.xpath(
        "//w:r[w:footnoteReference]/w:rPr/w:rStyle/@w:val", namespaces=NS
    )
    assert all(s == "FootnoteReference" for s in styles)
    assert styles  # at least one
