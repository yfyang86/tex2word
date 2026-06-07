"""Fidelity: csquotes inline quotes (\\textquote/\\foreignquote/\\hyphenquote)."""

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


def test_textquote_outer_quotes():
    assert "“hello”" in _txt(_conv(r"\textquote{hello}").document)


def test_textquote_star_inner_quotes():
    assert "‘hi’" in _txt(_conv(r"\textquote*{hi}").document)


def test_foreignquote_quotes_text_not_lang():
    t = _txt(_conv(r"\foreignquote{french}{bonjour}").document)
    assert "“bonjour”" in t
    assert "french" not in t


def test_hyphenquote_quotes_text_not_lang():
    t = _txt(_conv(r"\hyphenquote{german}{guten tag}").document)
    assert "“guten tag”" in t
    assert "german" not in t


def test_valid():
    assert validate_docx(_conv(r"\textquote{a} \foreignquote{en}{b}").docx) == []
