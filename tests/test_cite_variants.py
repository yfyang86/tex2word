"""Fidelity: biblatex cite variants (\\autocite/\\Textcite/…) + IEEE \\IEEEPARstart."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _flat(doc):
    out = []

    def walk(inlines):
        for n in inlines:
            k = type(n).__name__
            if k == "Text":
                out.append(("text", n.value))
            elif k == "Cite":
                out.append(("cite", tuple(n.keys), n.mode))
            elif hasattr(n, "inlines"):
                walk(n.inlines)

    for b in doc.blocks:
        if hasattr(b, "inlines"):
            walk(b.inlines)
    return out


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def test_ieee_parstart_joins_dropcap():
    flat = _flat(_conv(r"\IEEEPARstart{T}{his} is text.").document)
    text = "".join(v for k, v, *_ in flat if k == "text")
    assert text.startswith("This is text")


def test_biblatex_autocite_is_parenthetical():
    flat = _flat(_conv(r"See \autocite{x}.").document)
    assert ("cite", ("x",), "paren") in flat


def test_biblatex_capitalised_variants():
    flat = _flat(_conv(r"\Textcite{a} and \Parencite{b} and \Autocite{c}.").document)
    assert ("cite", ("a",), "text") in flat
    assert ("cite", ("b",), "paren") in flat
    assert ("cite", ("c",), "paren") in flat


def test_valid():
    src = r"\IEEEPARstart{A}{bstract} text \autocite{k}."
    assert validate_docx(_conv(src).docx) == []
