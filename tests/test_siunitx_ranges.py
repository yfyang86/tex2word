"""siunitx ranges and lists -> Unicode text."""

from __future__ import annotations

from tex2word import ir
from tex2word.frontend import parse_document


def _text(src: str) -> str:
    doc, _ = parse_document(rf"\begin{{document}}{src}\end{{document}}")
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    return "".join(i.value for i in para.inlines if isinstance(i, ir.Text))


def test_numrange():
    assert "10 to 20" in _text(r"\numrange{10}{20}")


def test_sirange_with_unit():
    t = _text(r"\SIrange{1}{5}{\meter}")
    assert "1 to 5" in t and "m" in t


def test_numlist_and():
    assert "1, 2 and 3" in _text(r"\numlist{1;2;3}")


def test_silist_with_unit():
    t = _text(r"\SIlist{2;4}{\kilogram}")
    assert "2 and 4" in t and "kg" in t


def test_qtyrange_modern_syntax():
    t = _text(r"\qtyrange{3}{6}{\second}")
    assert "3 to 6" in t and "s" in t
