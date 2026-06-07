"""Fidelity: \\marginpar / \\sidenote degrade to Word footnotes (asides)."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _footnotes(doc):
    found = []

    def walk(inlines):
        for n in inlines:
            if type(n).__name__ == "Footnote":
                found.append(n)
            elif hasattr(n, "inlines"):
                walk(n.inlines)

    for b in doc.blocks:
        if hasattr(b, "inlines"):
            walk(b.inlines)
    return found


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def test_marginpar_becomes_footnote():
    fns = _footnotes(_conv(r"Body\marginpar{a margin note}.").document)
    assert len(fns) == 1
    text = "".join(getattr(x, "value", "") for x in fns[0].inlines)
    assert "a margin note" in text


def test_sidenote_becomes_footnote():
    fns = _footnotes(_conv(r"Body\sidenote{an aside}.").document)
    assert len(fns) == 1


def test_marginpar_optional_left_arg_uses_default_text():
    # \marginpar[left]{right} -> the (right) default text is used
    fns = _footnotes(_conv(r"X\marginpar[L]{R text}.").document)
    text = "".join(getattr(x, "value", "") for x in fns[0].inlines)
    assert "R text" in text


def test_valid():
    assert validate_docx(_conv(r"A\marginpar{m} B\sidenote{s}.").docx) == []
