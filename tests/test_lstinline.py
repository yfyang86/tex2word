"""Inline listings: \\lstinline / \\mintinline (delimiter and brace forms)."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _tt(doc) -> list[str]:
    """Collected typewriter (monospace) inline runs."""
    out: list[str] = []

    def walk(inlines):
        for n in inlines:
            if type(n).__name__ == "Emphasis":
                if getattr(n, "kind_", "") == "typewriter":
                    out.append("".join(getattr(x, "value", "") for x in n.inlines))
                else:
                    walk(n.inlines)
            elif hasattr(n, "inlines"):
                walk(n.inlines)

    for b in doc.blocks:
        if hasattr(b, "inlines"):
            walk(b.inlines)
    return out


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def test_lstinline_pipe_delimiter():
    assert "x = f(a)" in _tt(_conv(r"Code \lstinline|x = f(a)| done.").document)


def test_lstinline_brace_form():
    assert "y <- 1" in _tt(_conv(r"Code \lstinline{y <- 1} done.").document)


def test_lstinline_with_options_and_special_chars():
    # the delimiter form is verbatim: & and other specials must survive
    assert "a & b" in _tt(_conv(r"Code \lstinline[language=Py]!a & b! done.").document)


def test_mintinline_with_language_delimiter():
    tt = _tt(_conv(r"Code \mintinline{python}|def f(): pass| done.").document)
    assert "def f(): pass" in tt


def test_mintinline_brace_form():
    assert "int x;" in _tt(_conv(r"Code \mintinline{c}{int x;} done.").document)


def test_listings_are_valid():
    src = r"A \lstinline|p && q| and \mintinline{c}{a[i]} end."
    assert validate_docx(_conv(src).docx) == []
