"""Inline fidelity: csquotes \\enquote + extra text symbols."""

from __future__ import annotations

from tex2word import ir
from tex2word.frontend import parse_document


def _text(src: str) -> str:
    doc, _ = parse_document(src)
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    out = []
    def walk(ns):
        for n in ns:
            if isinstance(n, ir.Text):
                out.append(n.value)
            elif hasattr(n, "inlines"):
                walk(n.inlines)
    walk(para.inlines)
    return "".join(out)


def test_enquote_curly_quotes():
    assert "“hello”" in _text(r"\begin{document}\enquote{hello}\end{document}")


def test_enquote_star_inner_quotes():
    assert "‘x’" in _text(r"\begin{document}\enquote*{x}\end{document}")


def test_enquote_nested_formatting():
    t = _text(r"\begin{document}\enquote{a \textbf{b} c}\end{document}")
    assert t.startswith("“a ") and t.endswith(" c”") and "b" in t


def test_extra_text_symbols():
    t = _text(r"\begin{document}30\textdegree{} \textbullet{} \texttrademark\end{document}")
    assert "°" in t and "•" in t and "™" in t


def test_thanks_becomes_a_footnote():
    # \thanks in the title -> a footnote on the title text
    src = r"\begin{document}\title{Paper\thanks{Funded by X}}\author{A}\maketitle\end{document}"
    doc, _ = parse_document(src)
    assert any(isinstance(i, ir.Footnote) for i in (doc.meta.title or []))


def test_thanks_in_body_is_a_footnote():
    src = r"\begin{document}Text\thanks{a note}.\end{document}"
    doc, _ = parse_document(src)
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    assert any(isinstance(i, ir.Footnote) for i in para.inlines)
