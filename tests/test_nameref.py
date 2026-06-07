"""Fidelity: \\nameref{label} -> the target's title as an internal hyperlink."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def _links(doc):
    found = []

    def walk(inlines):
        for n in inlines:
            if type(n).__name__ == "Link":
                found.append(n)
            elif hasattr(n, "inlines"):
                walk(n.inlines)

    for b in doc.blocks:
        if hasattr(b, "inlines"):
            walk(b.inlines)
    return found


def _link_text(link) -> str:
    return "".join(getattr(x, "value", "") for x in link.inlines)


def test_nameref_to_section_uses_title():
    doc = _conv(
        r"\section{Introduction}\label{sec:intro}See \nameref{sec:intro}."
    ).document
    links = _links(doc)
    assert len(links) == 1
    assert _link_text(links[0]) == "Introduction"
    assert links[0].anchor == "sec_intro"


def test_nameref_to_figure_uses_caption():
    doc = _conv(
        r"\begin{figure}\caption{A nice plot}\label{fig:p}\end{figure}"
        r"Recall \nameref{fig:p}."
    ).document
    links = _links(doc)
    assert any(_link_text(link) == "A nice plot" for link in links)


def test_nameref_to_theorem_uses_kind_or_title():
    doc = _conv(
        r"\begin{theorem}\label{t}Body.\end{theorem}As in \nameref{t}."
    ).document
    links = _links(doc)
    assert links and _link_text(links[0]) == "Theorem"


def test_nameref_unresolved_is_valid_and_warns():
    # unresolved -> the Ref is left in place (warned), still renders, no crash
    res = _conv(r"See \nameref{ghost}.")
    assert validate_docx(res.docx) == []
    assert any("ghost" in (w.message or "") for w in res.report.warnings)


def test_nameref_valid():
    src = r"\section{Methods}\label{m}See \nameref{m}."
    assert validate_docx(_conv(src).docx) == []
