"""Fidelity: \\epigraph{quote}{source} -> a quote + right-aligned attribution."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def _quote_block(doc):
    return next((b for b in doc.blocks if type(b).__name__ == "Quote"), None)


def _para_text(p) -> str:
    out = []
    for n in p.inlines:
        out.append(getattr(n, "value", "") or "".join(
            getattr(x, "value", "") for x in getattr(n, "inlines", [])
        ))
    return "".join(out)


def test_epigraph_makes_quote_with_attribution():
    doc = _conv(r"\epigraph{A wise saying.}{Anon}").document
    q = _quote_block(doc)
    assert q is not None
    assert _para_text(q.blocks[0]) == "A wise saying."
    # the source line is right-aligned
    assert q.blocks[1].align == "right"
    assert _para_text(q.blocks[1]) == "Anon"


def test_epigraph_source_is_italic():
    doc = _conv(r"\epigraph{Q}{Source Name}").document
    q = _quote_block(doc)
    src_inlines = q.blocks[1].inlines
    assert any(type(n).__name__ == "Emphasis" and n.kind_ == "italic" for n in src_inlines)


def test_epigraph_without_source():
    doc = _conv(r"\epigraph{Just a quote.}{}").document
    q = _quote_block(doc)
    assert q is not None
    assert _para_text(q.blocks[0]) == "Just a quote."
    # an empty source adds no attribution line
    assert len(q.blocks) == 1


def test_valid():
    assert validate_docx(_conv(r"\epigraph{X}{Y}\section{S}Body.").docx) == []
