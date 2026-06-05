from __future__ import annotations

from tex2word.mathml.cascade import ImageMathRenderer, MathCascade
from tex2word.report import ConversionReport


def test_omml_path_for_supported_math():
    report = ConversionReport()
    result = MathCascade(report).inline(r"\frac{a}{b}")
    assert result.path == "omml"
    assert result.omath is not None
    assert report.math_omml == 1


def test_raw_fallback_for_unsupported_math():
    # disable the pMML stage to isolate the raw fallback
    report = ConversionReport()
    result = MathCascade(report, enable_pmml=False).inline(r"\someunknownmacro{x}")
    assert result.path == "raw"
    assert result.raw == r"\someunknownmacro{x}"
    assert report.math_raw == 1
    assert any("math" == w.construct for w in report.warnings)


class _FakeRenderer:
    def render(self, latex, display):
        return (b"\x89PNG-fake", "png")


def test_image_hook_used_before_raw():
    assert isinstance(_FakeRenderer(), ImageMathRenderer)
    report = ConversionReport()
    cascade = MathCascade(report, image_renderer=_FakeRenderer(), enable_pmml=False)
    result = cascade.inline(r"\someunknownmacro{x}")
    assert result.path == "image"
    assert result.image == (b"\x89PNG-fake", "png")
    assert report.math_image == 1
    assert report.math_raw == 0


def test_block_collapses_aligned_lines_by_default():
    # &-aligned content collapses to a single column-aligned matrix
    report = ConversionReport()
    result = MathCascade(report).block(r"a &= b \\ c &= d")
    assert result.path == "omml"
    assert len(result.omath) == 1
    assert report.math_omml == 1


def test_block_keeps_lines_when_collapse_disabled():
    # callers (numbered align) can opt out and get one m:oMath per line
    report = ConversionReport()
    result = MathCascade(report).block(r"a &= b \\ c &= d", collapse_align=False)
    assert len(result.omath) == 2
    assert report.math_omml == 2


def test_block_counts_each_line_without_alignment():
    report = ConversionReport()
    result = MathCascade(report).block(r"a = b \\ c = d")  # no & -> per-line
    assert len(result.omath) == 2


def test_unexpected_parser_error_never_aborts(monkeypatch):
    # a non-MathUnsupported bug in the direct path must degrade gracefully
    # (to raw here, pMML disabled), never propagate and abort the conversion.
    from tex2word.mathml import cascade as cascade_mod

    def boom(latex):
        raise IndexError("simulated parser bug")

    monkeypatch.setattr(cascade_mod.omml, "render_inline", boom)
    report = ConversionReport()
    result = MathCascade(report, enable_pmml=False).inline(r"x^2")
    assert result.path == "raw"
    assert report.math_raw == 1
    assert any("falling back" in e.message for e in report.entries)
