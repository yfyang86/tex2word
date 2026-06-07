"""Fidelity: extended text symbols (vulgar fractions, currencies, gensymb)."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _txt(doc) -> str:
    out: list[str] = []

    def walk(inlines):
        for n in inlines:
            if type(n).__name__ == "Text":
                out.append(n.value)
            elif hasattr(n, "inlines"):
                walk(n.inlines)

    for b in doc.blocks:
        if hasattr(b, "inlines"):
            walk(b.inlines)
    return "".join(out)


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def test_vulgar_fractions_and_superscripts():
    t = _txt(_conv(r"\textonehalf \textonequarter \textthreequarters \texttwosuperior").document)
    assert "½" in t and "¼" in t and "¾" in t and "²" in t


def test_currencies():
    t = _txt(_conv(r"\texteuro \textcent \textyen \textsterling").document)
    assert "€" in t and "¢" in t and "¥" in t and "£" in t


def test_gensymb_symbols():
    t = _txt(_conv(r"\degree \celsius \ohm \micro \perthousand").document)
    assert "°" in t and "℃" in t and "Ω" in t and "µ" in t and "‰" in t


def test_misc_symbols():
    t = _txt(_conv(r"\checkmark \textnumero \textpm \textdiv \slash").document)
    assert "✓" in t and "№" in t and "±" in t and "÷" in t and "/" in t


def test_valid_output():
    src = r"Temp \degree C is \textonehalf of \texteuro and \checkmark."
    assert validate_docx(_conv(src).docx) == []
