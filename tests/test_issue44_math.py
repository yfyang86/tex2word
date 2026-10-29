"""Issue #44: n-ary bodies, minus sign, row spacing, merged runs, m:nor."""

from __future__ import annotations

import re

from lxml import etree

from tex2word.mathml import latex_math as L
from tex2word.mathml import omml
from tex2word.mathml.omml_reader import omath_to_latex

_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _xml(el) -> str:
    return re.sub(r' xmlns:\w+="[^"]+"', "", etree.tostring(el, encoding="unicode"))


def _nary_body_text(latex: str) -> list[str]:
    """The text of each m:nary's m:e, in document order."""
    root = omml.render_inline(latex)
    return [
        "".join(e.itertext())
        for e in root.iter(f"{{{_M}}}e")
        if e.getparent().tag == f"{{{_M}}}nary"
    ]


# -- n-ary operators own their operand -------------------------------------- #


def test_sum_takes_its_operand():
    assert _nary_body_text(r"\sum_i e_i \sigma") == ["eiσ"]


def test_sum_operand_stops_at_binary_operator_and_relation():
    assert _nary_body_text(r"\sum_i a_i + b = c") == ["ai"]
    assert _nary_body_text(r"\sum_i a_i = c") == ["ai"]


def test_sum_operand_stops_at_comma_and_quad_not_thin_space():
    assert _nary_body_text(r"\sum_i e_i\, \sigma, x") == ["ei σ"]
    assert _nary_body_text(r"\sum_i e_i \qquad x") == ["ei"]


def test_sum_operand_keeps_bracketed_terms_whole():
    # the minus inside the parentheses does not end the operand
    assert _nary_body_text(r"\sum_k (m_k - \bar m)\,\Delta Y_k , z") == [
        "(mk\u2212m)\u2009ΔYk"  # the bar accent is an attribute, not text
    ]


def test_sum_inside_brackets_does_not_swallow_the_closer():
    assert _nary_body_text(r"(\sum_i x_i)") == ["xi"]
    x = _xml(omml.render_inline(r"(\sum_i x_i)"))
    assert x.endswith(">)</m:t></m:r></m:oMath>")


def test_nested_sums():
    # the outer body is the inner sum (its limit j included), not empty
    assert _nary_body_text(r"\sum_i \sum_j a_{ij} + 1") == ["jaij", "aij"]


def test_no_empty_nary_body_in_fractions():
    x = _xml(omml.render_inline(r"\frac{\sum_{i \in A} e_i}{\sum_i e_i}"))
    assert "<m:e/>" not in x


# -- minus sign --------------------------------------------------------------- #


def test_minus_is_u2212_but_hyphen_in_text():
    x = _xml(omml.render_inline(r"a - b - \text{well-known}"))
    assert x.count(">−<") == 2
    assert "well-known" in x


def test_minus_reads_back_as_hyphen():
    latex = omath_to_latex(omml.render_inline(r"a - b"))
    assert "−" not in latex and "-" in latex


# -- row spacing --------------------------------------------------------------- #


def test_row_spacing_does_not_leak_into_cases_or_align():
    x = _xml(omml.render_inline(r"\begin{cases} a & b \\[2pt] 0 & c \\* d & e \end{cases}"))
    assert "pt" not in x and "*" not in x
    lines = omml.render_block_lines(r"a &= b \\[4pt] c &= d \\*[1ex] e &= f", False)
    assert len(lines) == 3
    assert all("pt" not in _xml(o) and "ex<" not in _xml(o) for o in lines)


def test_bracket_after_newline_that_is_not_a_length_is_kept():
    x = _xml(omml.render_inline(r"\begin{matrix} a \\ [b] \end{matrix}"))
    assert ">[<" in x and ">]<" in x


def test_is_dimen():
    for ok in ("2pt", "-.5ex", "1.2em", "\\jot", " 3 mm"):
        assert L.is_dimen(ok), ok
    for bad in ("b", "2", "x pt", ""):
        assert not L.is_dimen(bad), bad


# -- merged runs and m:nor ---------------------------------------------------- #


def test_upright_words_are_one_run():
    assert ">Beta<" in _xml(omml.render_inline(r"\mathrm{Beta}(2,3)"))
    assert ">rel<" in _xml(omml.render_inline(r"\operatorname{rel}_t"))


def test_digits_brackets_and_binary_operators_are_plain_math_runs():
    x = _xml(omml.render_inline(r"f(2) + 3 \times 4"))
    for ch in ("(", "2", ")", "+", "3", "×", "4"):
        run = re.search(rf"<m:r>(<m:rPr>.*?</m:rPr>)?<m:t[^>]*>{re.escape(ch)}</m:t>", x)
        assert run is not None and run.group(1) is None, ch


def test_relations_and_lone_operators_keep_nor():
    x = _xml(omml.render_inline(r"x^{+} = 1"))
    assert re.search(r"<m:sup><m:r><m:rPr><m:nor/></m:rPr><m:t[^>]*>\+</m:t>", x)
    assert re.search(r"<m:rPr><m:nor/></m:rPr><m:t[^>]*>=</m:t>", x)
