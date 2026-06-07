"""Math: \\substack{a \\\\ b} renders as a native-OMML stacked column."""

from __future__ import annotations

import io
import zipfile

from tex2word import convert_source
from tex2word.mathml import omml
from tex2word.mathml.latex_math import parse
from tex2word.validate import validate_docx


def test_substack_parses_directly():
    # previously raised MathUnsupported; now handled by the direct parser
    assert parse(r"\substack{a \\ b}") is not None


def test_substack_renders_native_omml():
    assert omml.render_inline(r"\sum_{\substack{i=1 \\ i \neq j}} a_i") is not None


def test_substack_is_a_matrix_stack():
    src = r"\begin{document}\[\sum_{\substack{0 \le i \le n \\ i \neq j}} x_i\]\end{document}"
    res = convert_source(src)
    assert validate_docx(res.docx) == []
    assert res.report.coverage()["math_raw"] == 0
    doc = zipfile.ZipFile(io.BytesIO(res.docx)).read("word/document.xml").decode("utf-8")
    assert "m:m" in doc  # the stack is an OMML matrix


def test_three_row_substack():
    res = convert_source(r"\begin{document}\(\substack{a \\ b \\ c}\)\end{document}")
    assert validate_docx(res.docx) == []
    assert res.report.coverage()["math_raw"] == 0
