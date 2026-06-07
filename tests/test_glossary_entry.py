"""V5-12 tail: general \\newglossaryentry terms expand via \\gls/\\glspl/\\Gls."""

from __future__ import annotations

from tex2word import convert_source


def _text(doc) -> str:
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
    return " ".join(out)


SRC = r"""
\newglossaryentry{maths}{name={mathematics},description={the study of numbers}}
\newglossaryentry{set}{name=set,description={a collection}}
\begin{document}
We study \gls{maths}. A \gls{set} and several \glspl{set}. \Gls{maths} is fun.
\end{document}
"""


def test_glossary_term_expands_to_name():
    txt = _text(convert_source(SRC).document)
    assert "mathematics" in txt
    assert "maths" not in txt  # the key itself never leaks into the body


def test_glossary_plural_and_capitalisation():
    txt = _text(convert_source(SRC).document)
    assert "sets" in txt  # \glspl{set}
    assert "Mathematics" in txt  # \Gls{maths}


def test_undefined_key_falls_back_to_key():
    txt = _text(convert_source(r"\begin{document}\gls{ghost}\end{document}").document)
    assert "ghost" in txt


def test_braced_name_with_comma_is_handled():
    src = (
        r"\newglossaryentry{x}{name={alpha, beta},description={d}}"
        r"\begin{document}\gls{x}\end{document}"
    )
    txt = _text(convert_source(src).document)
    assert "alpha, beta" in txt
