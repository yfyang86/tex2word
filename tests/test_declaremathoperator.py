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


def test_operator_body_contains_braced_group():
    # \DeclareMathOperator*{\Exp}{\mathbb{E}}: the operator *body* itself has a
    # braced group; the rewrite must not stop at the inner brace and leave \Exp
    # undefined (real arXiv preamble idiom).
    src = (
        r"\documentclass{article}\usepackage{amssymb}"
        r"\DeclareMathOperator*{\Exp}{\mathbb{E}}\newcommand\AL[1]{\begin{align}#1\end{align}}"
        r"\begin{document}\AL{Q &= \Exp_{x}[f(x)]}\end{document}"
    )
    res = convert_source(src)
    assert res.report.coverage()["math_raw"] == 0
    assert not any("Exp" in (w.message or "") for w in res.report.warnings)


def test_operator_body_with_two_levels_of_braces():
    # \DeclareMathOperator{\E}{\mathbb{\mathcal{E}}}: the body nests braces two
    # deep; the rewrite must capture the whole body, not stop at the inner brace.
    from tex2word.frontend.preprocess import _rewrite_mathoperators

    out = _rewrite_mathoperators(r"\DeclareMathOperator{\E}{\mathbb{\mathcal{E}}}")
    assert r"\operatorname{\mathbb{\mathcal{E}}}" in out


def test_operator_defined_in_local_package(tmp_path):
    # \DeclareMathOperator living in a \usepackage'd local .sty must be harvested
    # too (the operator name was previously unknown and sent the block to raw).
    (tmp_path / "mymac.sty").write_text(
        r"\DeclareMathOperator*{\ExpOp}{\mathbb{E}}" + "\n", encoding="utf-8"
    )
    main = (
        r"\documentclass{article}\usepackage{amssymb}\usepackage{mymac}"
        r"\begin{document}\( \ExpOp_{x}[f] \)\end{document}"
    )
    res = convert_source(main, base_dir=str(tmp_path))
    assert res.report.coverage()["math_raw"] == 0
    assert not any("ExpOp" in (w.message or "") for w in res.report.warnings)
