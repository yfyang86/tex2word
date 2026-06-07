"""Fidelity: boxed environments (framed/mdframed/tcolorbox/...) -> Quote blocks."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def _quote_text(doc) -> str | None:
    q = next((b for b in doc.blocks if type(b).__name__ == "Quote"), None)
    if q is None:
        return None
    out = []
    for bb in q.blocks:
        for x in getattr(bb, "inlines", []):
            out.append(getattr(x, "value", "") or "".join(
                getattr(y, "value", "") for y in getattr(x, "inlines", [])
            ))
    return "".join(out)


def test_framed_and_shaded_become_quote():
    for env in ("framed", "shaded", "boxedminipage"):
        doc = _conv(rf"\begin{{{env}}} Boxed text. \end{{{env}}}").document
        assert _quote_text(doc) == "Boxed text.", env


def test_mdframed_consumes_options():
    doc = _conv(r"\begin{mdframed}[linewidth=2pt] Inside. \end{mdframed}").document
    # the [options] must not leak into the body
    assert _quote_text(doc) == "Inside."


def test_tcolorbox_consumes_options():
    doc = _conv(r"\begin{tcolorbox}[colback=red!5] Note. \end{tcolorbox}").document
    assert _quote_text(doc) == "Note."


def test_box_content_keeps_formatting():
    doc = _conv(r"\begin{framed}A \textbf{bold} word.\end{framed}").document
    q = next(b for b in doc.blocks if type(b).__name__ == "Quote")
    para = q.blocks[0]
    assert any(type(n).__name__ == "Emphasis" for n in para.inlines)


def test_valid():
    assert validate_docx(_conv(r"\begin{tcolorbox}[title=X]Body.\end{tcolorbox}").docx) == []
