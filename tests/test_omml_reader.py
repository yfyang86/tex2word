"""SPRINT-V3 A2/M2: OMML -> LaTeX reader (math round-trip)."""

from __future__ import annotations

import pytest
from lxml import etree

from tex2word.mathml.omml import render_inline
from tex2word.mathml.omml_reader import ast_to_latex, omath_to_latex

ROUNDTRIP = [
    r"\frac{a}{b}",
    r"x^2 + y_i",
    r"x_i^2",
    r"\sqrt{x+1}",
    r"\sqrt[3]{x}",
    r"\sum_{i=1}^n i",
    r"\int_0^1 f",
    r"\alpha \leq \beta",
    r"\hat{x}",
    r"\mathbb{R}^n",
    r"\mathcal{L}",
    r"\sin x",
    r"\overbrace{a+b}",
    r"\underbrace{x}",
    r"\left( \frac{a}{b} \right)",
    r"a + b - c \cdot d",
    r"\lim_{x \to 0} f",
    r"\begin{matrix} a & b \\ c & d \end{matrix}",
]


@pytest.mark.parametrize("src", ROUNDTRIP)
def test_omml_latex_omml_is_stable(src):
    # latex -> OMML -> latex -> OMML must reproduce the same OMML (structural).
    first = render_inline(src)
    recovered = omath_to_latex(first)
    second = render_inline(recovered)
    assert etree.tostring(first) == etree.tostring(second), recovered


def test_greek_and_relations_reverse_mapped():
    out = omath_to_latex(render_inline(r"\alpha \leq \beta \geq \gamma"))
    assert "\\alpha" in out and "\\leq" in out and "\\beta" in out and "\\gamma" in out


def test_numbers_not_wrapped_in_mathrm():
    out = omath_to_latex(render_inline(r"x^{2} + 10"))
    assert "\\mathrm" not in out
    assert "2" in out and "10" in out


def test_function_names_recovered():
    assert "\\sin" in omath_to_latex(render_inline(r"\sin x"))
    assert "\\log" in omath_to_latex(render_inline(r"\log y"))


def test_mathbb_recovered():
    assert omath_to_latex(render_inline(r"\mathbb{R}")) == "\\mathbb{R}"


def test_fraction_and_root_structure():
    assert ast_to_latex.__module__  # importable
    assert omath_to_latex(render_inline(r"\frac{1}{2}")) == "\\frac{1}{2}"
    assert "\\sqrt[3]" in omath_to_latex(render_inline(r"\sqrt[3]{x}"))


def test_nary_with_limits():
    out = omath_to_latex(render_inline(r"\sum_{i=1}^{n} i"))
    assert out.startswith("\\sum")
    assert "_{i=1}" in out and "^{n}" in out
