"""Math breadth: \\DeclareMathOperator defines custom operators (native OMML)."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx

SRC = r"""
\documentclass{article}
\DeclareMathOperator{\argmax}{arg\,max}
\DeclareMathOperator*{\argmin}{argmin}
\begin{document}
Inline \( \argmax_x f(x) \).
\[ \argmin_{y} g(y) \]
\end{document}
"""


def test_custom_operators_render_as_native_omml():
    res = convert_source(SRC)
    assert validate_docx(res.docx) == []
    cov = res.report.coverage()
    assert cov["math_total"] == 2
    assert cov["math_omml"] == 2  # both expand via \operatorname -> OMML
    assert cov["math_raw"] == 0


def test_no_unknown_macro_warnings():
    res = convert_source(SRC)
    assert not any("argmax" in (w.message or "") for w in res.report.warnings)
    assert not any("argmin" in (w.message or "") for w in res.report.warnings)


def test_operator_with_braced_body():
    src = (
        r"\documentclass{article}\DeclareMathOperator{\Var}{Var}"
        r"\begin{document}\( \Var(X) \)\end{document}"
    )
    res = convert_source(src)
    assert validate_docx(res.docx) == []
    assert res.report.coverage()["math_raw"] == 0
