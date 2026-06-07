"""Fidelity: csquotes block quotes (\\blockquote/\\blockcquote/displayquote)."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _quotes(doc) -> list[str]:
    out: list[str] = []
    for b in doc.blocks:
        if type(b).__name__ == "Quote":
            text = []
            for bb in b.blocks:
                text.append("".join(getattr(x, "value", "") for x in getattr(bb, "inlines", [])))
            out.append(" ".join(t for t in text if t))
    return out


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def test_blockquote_becomes_quote_block():
    doc = _conv(r"Intro.\blockquote{A quoted passage.}After.").document
    assert "A quoted passage." in _quotes(doc)
    # surrounding prose stays as ordinary paragraphs
    paras = [b for b in doc.blocks if type(b).__name__ == "Paragraph"]
    assert len(paras) == 2


def test_blockcquote_drops_cite_args():
    doc = _conv(r"\blockcquote[p.5]{smith2020}{Cited text here.}").document
    qs = _quotes(doc)
    assert "Cited text here." in qs
    assert not any("smith2020" in q for q in qs)


def test_displayquote_environment():
    doc = _conv(r"\begin{displayquote}Displayed quote.\end{displayquote}").document
    assert "Displayed quote." in _quotes(doc)


def test_valid():
    src = r"\blockquote{X} and \begin{displayquote}Y\end{displayquote}"
    assert validate_docx(_conv(src).docx) == []
