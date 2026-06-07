"""Math breadth: over-arrow accents and \\bmod/\\pmod render as native OMML."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.mathml import omml
from tex2word.validate import validate_docx


def test_over_arrow_accents_render():
    for expr in (r"\overrightarrow{AB}", r"\overleftarrow{v}", r"\overleftrightarrow{PQ}"):
        assert omml.render_inline(expr) is not None, expr


def test_bmod_pmod_render():
    assert omml.render_inline(r"a \bmod n") is not None
    assert omml.render_inline(r"a \equiv b \pmod{n}") is not None


def test_native_omml_no_raw_fallback():
    src = (
        r"\begin{document}"
        r"Vector \(\overrightarrow{AB}\); modular \(a \equiv b \pmod{n}\), \(c \bmod d\)."
        r"\end{document}"
    )
    res = convert_source(src)
    assert validate_docx(res.docx) == []
    cov = res.report.coverage()
    assert cov["math_raw"] == 0
    assert cov["math_omml"] == cov["math_total"]


def test_overrightarrow_is_an_accent_over_base():
    # the OMML for an over-arrow uses an m:acc accent element
    src = r"\begin{document}\(\overrightarrow{AB}\)\end{document}"
    import io
    import zipfile

    doc = zipfile.ZipFile(io.BytesIO(convert_source(src).docx)).read(
        "word/document.xml"
    ).decode("utf-8")
    assert "m:acc" in doc
