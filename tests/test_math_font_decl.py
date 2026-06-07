"""Old-style font *declarations* inside math: ``{\\rm Lik}`` == ``\\mathrm{Lik}``.

These used to raise MathUnsupported, dropping the whole (often multi-line align)
block to raw ``\\[ … \\]`` text. Regression for a real-document ``align*`` that
used ``\\log {\\rm Lik}(\\theta)``.
"""

from __future__ import annotations

import io
import zipfile

from lxml import etree

from tex2word import convert_source

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _convert(src: str):
    res = convert_source(r"\begin{document}" + src + r"\end{document}")
    root = etree.fromstring(
        zipfile.ZipFile(io.BytesIO(res.docx)).read("word/document.xml")
    )
    return res, root


def _omath_count(root) -> int:
    return len(list(root.iter(f"{{{M}}}oMath")))


def _alltext(root) -> str:
    return "".join(t.text or "" for t in root.iter(f"{{{W}}}t"))


def test_rm_declaration_in_math_renders_as_omml():
    res, root = _convert(r"值 $\log {\rm Lik}(\theta)$ 。")
    assert _omath_count(root) == 1
    assert "\\rm" not in _alltext(root) and "\\[" not in _alltext(root)
    assert not [w for w in res.report.warnings if w.construct == "math"]


def test_align_with_rm_not_dumped_as_raw():
    src = (
        r"\begin{align*}"
        r"&\text{Wilks 距离:} & & |\log {\rm Lik}(\theta^*) - \log {\rm Lik}(\hat\theta)| \\"
        r"&\text{score:} & & |S(\theta^*) - 0|"
        r"\end{align*}"
    )
    res, root = _convert(src)
    assert _omath_count(root) >= 1
    txt = _alltext(root)
    assert "\\[" not in txt and "\\rm" not in txt and "&" not in txt


def test_bf_and_it_declarations_in_math():
    # must not raise / fall back to raw
    _, root = _convert(r"$however {\bf B} and {\it I} and {\sf S} and {\tt T}$")
    assert _omath_count(root) == 1
    assert "\\bf" not in _alltext(root) and "\\[" not in _alltext(root)
