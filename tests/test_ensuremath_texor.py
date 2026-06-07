"""Inline fidelity: \\ensuremath, \\texorpdfstring, \\labelcref."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _flat(doc):
    out = []

    def walk(inlines):
        for n in inlines:
            kind = type(n).__name__
            if kind == "Text":
                out.append(("text", n.value))
            elif kind == "Math":
                out.append(("math", n.latex))
            elif kind == "Ref":
                out.append(("ref", n.key))
            elif hasattr(n, "inlines"):
                walk(n.inlines)

    for b in doc.blocks:
        if hasattr(b, "inlines"):
            walk(b.inlines)
    return out


def test_ensuremath_becomes_inline_math():
    doc = convert_source(
        r"\begin{document}The value \ensuremath{\alpha + \beta} holds.\end{document}"
    ).document
    maths = [v for k, v in _flat(doc) if k == "math"]
    assert any("\\alpha" in m and "\\beta" in m for m in maths)


def test_texorpdfstring_keeps_tex_form():
    doc = convert_source(
        r"\begin{document}\section{A \texorpdfstring{\(x^2\)}{x squared} title}"
        r"\end{document}"
    ).document
    flat = _flat(doc)
    assert ("math", "x^2") in flat
    # the PDF-only alternative text must not leak in
    assert not any(k == "text" and "x squared" in v for k, v in flat)


def test_labelcref_is_a_reference():
    doc = convert_source(
        r"\begin{document}\section{S}\label{sec:s}See \labelcref{sec:s}.\end{document}"
    ).document
    assert any(k == "ref" and v == "sec:s" for k, v in _flat(doc))


def test_all_valid():
    src = (
        r"\begin{document}\section{S}\label{s}"
        r"\ensuremath{x} and \texorpdfstring{$y$}{y} see \labelcref{s}.\end{document}"
    )
    assert validate_docx(convert_source(src).docx) == []
