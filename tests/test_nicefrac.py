"""\\nicefrac / \\sfrac -> "a/b" in text."""
from __future__ import annotations

from tex2word import ir
from tex2word.frontend import parse_document


def _text(src):
    doc,_=parse_document(rf"\begin{{document}}{src}\end{{document}}")
    p=next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    return "".join(i.value for i in p.inlines if isinstance(i, ir.Text))

def test_nicefrac():
    assert "1/2" in _text(r"\nicefrac{1}{2}")

def test_sfrac():
    assert "3/4" in _text(r"a \sfrac{3}{4} b")
