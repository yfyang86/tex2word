from __future__ import annotations

import io
import zipfile

from lxml import etree

from latex2word import convert_source
from latex2word.validate import _check_content_model, validate_docx

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _wdoc(inner: str) -> etree._Element:
    return etree.fromstring(
        f'<w:document xmlns:w="{_W}"><w:body>{inner}</w:body></w:document>'.encode()
    )

SRC = r"""
\begin{document}
\section{S}$\frac{a}{b}$
\begin{equation}\label{eq:e}E=mc^2\end{equation}
See \eqref{eq:e}.
\end{document}
"""


def test_valid_output_passes():
    result = convert_source(SRC)
    assert validate_docx(result.docx) == []


def test_valid_output_with_manifest_passes():
    result = convert_source(SRC, embed_manifest=True)
    problems = validate_docx(result.docx)
    assert problems == [], problems


def test_detects_malformed_xml():
    docx = convert_source(SRC).docx
    broken = _replace_part(docx, "word/document.xml", b"<w:document><unclosed>")
    problems = validate_docx(broken)
    assert any("malformed XML" in p for p in problems)


def test_detects_missing_required_part():
    docx = convert_source(SRC).docx
    stripped = _drop_part(docx, "word/styles.xml")
    problems = validate_docx(stripped)
    assert any("styles.xml" in p for p in problems)


# -- V4-2: schema-aware content-model validation ----------------------------- #


def test_rpr_child_order_violation_detected():
    bad = _wdoc("<w:r><w:rPr><w:highlight w:val='yellow'/><w:b/></w:rPr></w:r>")
    problems = _check_content_model("word/document.xml", bad)
    assert any("w:rPr children out of ECMA-376 order" in p for p in problems)


def test_ppr_child_order_violation_detected():
    bad = _wdoc("<w:p><w:pPr><w:outlineLvl w:val='0'/><w:spacing w:after='40'/></w:pPr></w:p>")
    problems = _check_content_model("word/document.xml", bad)
    assert any("w:pPr children out of ECMA-376 order" in p for p in problems)


def test_tcpr_child_order_violation_detected():
    bad = _wdoc(
        "<w:tbl><w:tr><w:tc><w:tcPr>"
        "<w:shd w:val='clear' w:fill='FF0000'/><w:tcW w:w='100'/>"
        "</w:tcPr></w:tc></w:tr></w:tbl>"
    )
    problems = _check_content_model("word/document.xml", bad)
    assert any("w:tcPr children out of ECMA-376 order" in p for p in problems)


def test_valid_child_order_passes():
    good = _wdoc(
        "<w:r><w:rPr><w:b/><w:i/><w:color w:val='FF0000'/>"
        "<w:sz w:val='24'/><w:highlight w:val='yellow'/></w:rPr></w:r>"
    )
    assert _check_content_model("word/document.xml", good) == []


def test_bad_highlight_enum_detected():
    bad = _wdoc("<w:r><w:rPr><w:highlight w:val='chartreuse'/></w:rPr></w:r>")
    problems = _check_content_model("word/document.xml", bad)
    assert any("w:highlight" in p and "not a valid ST value" in p for p in problems)


def test_bad_vertalign_enum_detected():
    bad = _wdoc("<w:r><w:rPr><w:vertAlign w:val='middle'/></w:rPr></w:r>")
    problems = _check_content_model("word/document.xml", bad)
    assert any("w:vertAlign" in p and "not a valid ST value" in p for p in problems)


def test_non_integer_sz_detected():
    bad = _wdoc("<w:r><w:rPr><w:sz w:val='12pt'/></w:rPr></w:r>")
    problems = _check_content_model("word/document.xml", bad)
    assert any("w:sz@w:val must be an integer" in p for p in problems)


def test_real_output_passes_content_model():
    # the shipped styles.xml + a feature-rich body must be schema-order-clean
    src = (
        r"\begin{document}\section{S}\textbf{\large \sout{x}} "
        r"\textcolor{red}{y} \hl{z}"
        r"\begin{tabular}{ll}\cellcolor{blue}a & b \\\end{tabular}\end{document}"
    )
    assert validate_docx(convert_source(src).docx) == []


def test_validate_docx_flags_injected_bad_order():
    docx = convert_source(SRC).docx
    bad_doc = (
        f'<w:document xmlns:w="{_W}"><w:body><w:p><w:r><w:rPr>'
        "<w:sz w:val='24'/><w:b/></w:rPr><w:t>x</w:t></w:r></w:p></w:body></w:document>"
    )
    broken = _replace_part(docx, "word/document.xml", bad_doc.encode())
    assert any("out of ECMA-376 order" in p for p in validate_docx(broken))


def _rebuild(docx: bytes, transform):
    src = zipfile.ZipFile(io.BytesIO(docx))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name in src.namelist():
            data = transform(name, src.read(name))
            if data is not None:
                zf.writestr(name, data)
    return out.getvalue()


def _replace_part(docx, target, new):
    return _rebuild(docx, lambda n, d: new if n == target else d)


def _drop_part(docx, target):
    return _rebuild(docx, lambda n, d: None if n == target else d)
