"""SPRINT-V3 A3: LaTeX -> presentation MathML -> OMML secondary path."""

from __future__ import annotations

import importlib.util

import pytest
from lxml import etree

from latex2word.mathml.cascade import MathCascade
from latex2word.mathml.latex_math import MathUnsupported, parse
from latex2word.mathml.mathml_to_omml import latex_via_mathml, mathml_to_omath
from latex2word.report import ConversionReport

NS = {"m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}
HAVE_PMML = importlib.util.find_spec("latex2mathml") is not None
needs_pmml = pytest.mark.skipif(not HAVE_PMML, reason="latex2mathml not installed")


def _count(o: etree._Element, tag: str) -> int:
    return len(o.findall(f".//{{{NS['m']}}}{tag}"))


def test_mathml_to_omath_fraction():
    mml = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><mrow>'
        "<mfrac><mi>a</mi><mi>b</mi></mfrac></mrow></math>"
    )
    o = mathml_to_omath(etree.fromstring(mml))
    assert _count(o, "f") == 1 and _count(o, "num") == 1 and _count(o, "den") == 1


def test_mathml_to_omath_scripts_and_root():
    sup = '<math xmlns="http://www.w3.org/1998/Math/MathML"><msup><mi>x</mi><mn>2</mn></msup></math>'
    assert _count(mathml_to_omath(etree.fromstring(sup)), "sSup") == 1
    rt = '<math xmlns="http://www.w3.org/1998/Math/MathML"><msqrt><mi>x</mi></msqrt></math>'
    assert _count(mathml_to_omath(etree.fromstring(rt)), "rad") == 1


def test_mathml_to_omath_matrix():
    mml = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><mtable>'
        "<mtr><mtd><mi>a</mi></mtd><mtd><mi>b</mi></mtd></mtr>"
        "<mtr><mtd><mi>c</mi></mtd><mtd><mi>d</mi></mtd></mtr></mtable></math>"
    )
    o = mathml_to_omath(etree.fromstring(mml))
    assert _count(o, "m") == 1 and _count(o, "mr") == 2


def test_binom_no_bar():
    mml = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        '<mfrac linethickness="0"><mi>n</mi><mi>k</mi></mfrac></math>'
    )
    o = mathml_to_omath(etree.fromstring(mml))
    assert _count(o, "type") == 1  # m:type val=noBar


@needs_pmml
def test_latex_via_mathml_handles_substack():
    # \substack is rejected by the direct parser; the pMML path converts it
    with pytest.raises(MathUnsupported):
        parse(r"\substack{a \\ b}")
    o = latex_via_mathml(r"\substack{a \\ b}")
    assert o is not None
    assert _count(o, "m") == 1  # rendered as a stacked matrix


@needs_pmml
def test_cascade_uses_pmml_for_direct_failures():
    report = ConversionReport()
    result = MathCascade(report).inline(r"\substack{a \\ b}")
    assert result.path == "omml"
    assert report.math_omml == 1
    assert any("MathML" in e.message for e in report.entries)


@needs_pmml
def test_cascade_still_prefers_direct_path():
    # supported math must NOT go through the pMML path (direct is exact)
    report = ConversionReport()
    result = MathCascade(report).inline(r"\frac{a}{b}")
    assert result.path == "omml"
    assert not any("MathML" in e.message for e in report.entries)


def test_pmml_disabled_falls_through_to_raw():
    report = ConversionReport()
    result = MathCascade(report, enable_pmml=False).inline(r"\substack{a \\ b}")
    assert result.path == "raw"


def test_latex_via_mathml_returns_none_without_lib(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "latex2mathml.converter":
            raise ImportError("simulated missing latex2mathml")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert latex_via_mathml(r"\frac{a}{b}") is None
