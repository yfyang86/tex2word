"""SPRINT-V2.3: description lists (T12) and deep nesting (T8)."""

from __future__ import annotations

from conftest import NS, document_root

from latex2word import convert_source, ir
from latex2word.frontend import parse_document


def _list(src: str) -> ir.ItemList:
    doc, _ = parse_document(src)
    return next(b for b in doc.blocks if isinstance(b, ir.ItemList))


# -- T12: description lists -------------------------------------------------- #


def test_description_terms_parsed():
    lst = _list(
        r"\begin{document}\begin{description}"
        r"\item[Apple] a fruit \item[Bee] an insect"
        r"\end{description}\end{document}"
    )
    assert lst.description is True
    assert lst.items[0].term[0].value == "Apple"
    assert lst.items[1].term[0].value == "Bee"


def test_description_term_keeps_formatting():
    lst = _list(
        r"\begin{document}\begin{description}\item[\textbf{B}] x\end{description}\end{document}"
    )
    assert isinstance(lst.items[0].term[0], ir.Emphasis)


def test_description_rendered_bold_no_bullet():
    src = (
        r"\begin{document}\begin{description}\item[Term] definition"
        r"\end{description}\end{document}"
    )
    root = document_root(convert_source(src).docx)
    # no list numbering for description items
    assert not root.xpath("//w:numPr", namespaces=NS)
    bold = [
        t.text for r in root.xpath("//w:r", namespaces=NS)
        if r.xpath("./w:rPr/w:b", namespaces=NS)
        for t in r.xpath("./w:t", namespaces=NS)
    ]
    assert "Term" in bold


def test_itemize_still_bulleted():
    src = r"\begin{document}\begin{itemize}\item a\item b\end{itemize}\end{document}"
    root = document_root(convert_source(src).docx)
    assert len(root.xpath("//w:numPr", namespaces=NS)) == 2


# -- T8: deep nesting -------------------------------------------------------- #


def test_three_level_nesting_uses_distinct_ilvls():
    src = (
        r"\begin{document}\begin{enumerate}\item a"
        r"\begin{enumerate}\item b"
        r"\begin{enumerate}\item c\end{enumerate}"
        r"\end{enumerate}\end{enumerate}\end{document}"
    )
    root = document_root(convert_source(src).docx)
    ilvls = sorted(e.get(f"{{{NS['w']}}}val") for e in root.xpath("//w:ilvl", namespaces=NS))
    assert ilvls == ["0", "1", "2"]


def test_numbering_defines_five_levels():
    from latex2word.backend.numbering import numbering_xml

    xml = numbering_xml().decode()
    # decimal abstractNum carries an ilvl 4
    assert 'w:ilvl="4"' in xml
    assert "%5." in xml


def test_multi_paragraph_item_marks_once():
    # an item with two paragraphs gets a single bullet, the 2nd indented.
    src = (
        "\\begin{document}\\begin{itemize}\\item first para\n\nsecond para"
        "\\end{itemize}\\end{document}"
    )
    root = document_root(convert_source(src).docx)
    assert len(root.xpath("//w:numPr", namespaces=NS)) == 1
