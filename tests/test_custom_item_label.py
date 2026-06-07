"""Fidelity: \\item[label] custom labels in itemize/enumerate are rendered."""

from __future__ import annotations

from conftest import NS, document_root

from tex2word import convert_source
from tex2word.validate import validate_docx


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def test_custom_item_label_term_captured():
    doc = _conv(r"\begin{itemize}\item[!] bang\item normal\end{itemize}").document
    lst = next(b for b in doc.blocks if type(b).__name__ == "ItemList")
    assert lst.items[0].term is not None
    assert lst.items[1].term is None


def test_custom_label_is_rendered_without_bullet():
    res = _conv(r"\begin{itemize}\item[!] bang item\end{itemize}")
    assert validate_docx(res.docx) == []
    root = document_root(res.docx)
    paras = root.xpath("//w:body/w:p", namespaces=NS)
    # the custom-label item has no numbering (numPr); its label text is present
    assert paras[0].xpath(".//w:numPr", namespaces=NS) == []
    text = "".join(root.xpath("//w:t/text()", namespaces=NS))
    assert "!" in text and "bang item" in text


def test_mixed_custom_and_bulleted_items():
    res = _conv(
        r"\begin{itemize}\item[!] custom\item plain bullet\end{itemize}"
    )
    root = document_root(res.docx)
    paras = root.xpath("//w:body/w:p", namespaces=NS)
    # plain item keeps its bullet numbering
    assert paras[0].xpath(".//w:numPr", namespaces=NS) == []   # custom -> no bullet
    assert paras[1].xpath(".//w:numPr", namespaces=NS) != []   # plain -> bullet


def test_math_custom_label_valid():
    assert validate_docx(_conv(r"\begin{itemize}\item[$\star$] x\end{itemize}").docx) == []
