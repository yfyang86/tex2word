"""SPRINT-V3 A5: image fallback for math (matplotlib / dvipng)."""

from __future__ import annotations

import importlib.util

import pytest
from conftest import NS

from tex2word import convert_source, ir
from tex2word.backend.document import DocumentWriter
from tex2word.mathml.cascade import MathCascade
from tex2word.mathml.imagemath import (
    DvipngMathRenderer,
    MatplotlibMathRenderer,
    default_renderer,
)
from tex2word.report import ConversionReport

HAVE_MPL = importlib.util.find_spec("matplotlib") is not None
needs_mpl = pytest.mark.skipif(not HAVE_MPL, reason="matplotlib not installed")


def test_default_renderer_selection():
    r = default_renderer()
    if DvipngMathRenderer.available():
        assert isinstance(r, DvipngMathRenderer)
    elif MatplotlibMathRenderer.available():
        assert isinstance(r, MatplotlibMathRenderer)
    else:
        assert r is None


def test_dvipng_unavailable_returns_none(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert DvipngMathRenderer.available() is False
    assert DvipngMathRenderer().render("x^2", False) is None


@needs_mpl
def test_matplotlib_renders_png():
    out = MatplotlibMathRenderer().render(r"x^2 + \frac{a}{b}", display=False)
    assert out is not None
    data, fmt = out
    assert fmt == "png" and data[:8] == b"\x89PNG\r\n\x1a\n"


@needs_mpl
def test_matplotlib_bad_input_returns_none():
    # an un-renderable construct -> None (cascade then falls to raw)
    assert MatplotlibMathRenderer().render(r"\genfrac{}{}{}{}{a}{b}{c}", False) is None


@needs_mpl
def test_cascade_image_stage_when_omml_paths_fail():
    report = ConversionReport()
    cascade = MathCascade(report, image_renderer=MatplotlibMathRenderer(), enable_pmml=False)
    result = cascade.inline(r"\not= y")  # direct parser rejects this
    assert result.path == "image"
    assert result.image is not None and result.image[1] == "png"
    assert report.math_image == 1


@needs_mpl
def test_docx_embeds_image_math():
    # build a doc whose only math can't be OMML; force the image stage
    from lxml import etree

    report = ConversionReport()
    writer = DocumentWriter(report, image_math_renderer=MatplotlibMathRenderer())
    writer.math.enable_pmml = False  # isolate the image fallback
    doc = ir.Document(blocks=[ir.MathBlock(latex=r"\not= y", env="displaymath")])
    root = etree.fromstring(writer.build(doc))
    assert root.xpath("//w:drawing", namespaces=NS)  # the math was embedded as a drawing
    assert any(k.startswith("word/media/") for k in writer.media)  # a media part registered
    assert report.math_image == 1


@needs_mpl
def test_pipeline_math_image_fallback_flag():
    # the flag wires a renderer; normal math still converts to OMML (no image)
    result = convert_source(
        r"\begin{document}$x^2$\end{document}", math_image_fallback=True
    )
    assert result.report.coverage()["math_omml"] == 1
    assert result.report.coverage()["math_image"] == 0
