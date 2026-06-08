"""Display math wrapped in an alignment environment (`aligned`/`array`/…).

Two real-paper bugs:
* a *bare* ``\\begin{aligned}…\\end{aligned}`` block (no ``$$``/``\\[``) was parsed
  as text, leaking ``\\frac``/``\\int`` as raw inline;
* ``$$\\begin{aligned}…\\end{aligned}$$`` (or ``\\[…\\]``) fell back to raw because
  the block splitter cut the ``\\\\`` *inside* the environment.
"""

from __future__ import annotations

import io
import zipfile

from lxml import etree

from tex2word import convert_source

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _conv(body: str):
    res = convert_source(
        r"\documentclass{article}\usepackage{amsmath,amssymb}\begin{document}"
        + body
        + r"\end{document}"
    )
    root = etree.fromstring(
        zipfile.ZipFile(io.BytesIO(res.docx)).read("word/document.xml")
    )
    omml = len(list(root.iter(f"{{{M}}}oMath")))
    txt = "".join(t.text or "" for t in root.iter(f"{{{W}}}t"))
    return res, omml, txt


def test_bare_aligned_block_is_math_not_text():
    res, omml, txt = _conv(r"\begin{aligned}& \frac{1}{2}\int_B x\,ds = a \\ & = b\end{aligned}")
    assert omml >= 1
    assert "\\frac" not in txt and "\\int" not in txt  # not leaked as raw inline
    assert res.report.math_raw == 0


def test_aligned_inside_dollar_dollar_renders():
    res, omml, txt = _conv(r"$$\begin{aligned}& a=b \\ & c=d\end{aligned}$$")
    assert omml >= 1 and res.report.math_raw == 0
    assert "\\begin{aligned}" not in txt and "\\[" not in txt


def test_aligned_inside_bracket_display_renders():
    res, omml, txt = _conv(r"\[\begin{aligned}& a=b \\ & c=d\end{aligned}\]")
    assert omml >= 1 and res.report.math_raw == 0


def test_array_in_display_parses_directly():
    # the \\ and & live inside the array env -> one whole oMath, no raw fallback
    res, omml, txt = _conv(r"\[\begin{array}{ll}a & b \\ c & d\end{array}\]")
    assert omml == 1 and res.report.math_raw == 0
    assert "\\begin{array}" not in txt


def test_plain_align_block_still_collapses():
    # regression guard: a normal align* (content without a \begin wrapper) still
    # aligns at & as before
    res, omml, txt = _conv(r"\begin{align*}a &= b \\ c &= d\end{align*}")
    assert omml >= 1 and res.report.math_raw == 0
    assert "&" not in txt and "\\\\" not in txt


def test_hline_and_rules_in_math_array_are_dropped_not_raw():
    # array rules (\hline, \cline, \toprule, …) have no OMML equivalent; they must
    # be dropped so the matrix converts instead of dumping the whole block to raw.
    res, omml, txt = _conv(
        r"\[\begin{array}{cc|c}A & B & C \\ \hline D & E & F\end{array}\]"
    )
    assert omml == 1 and res.report.math_raw == 0
    assert "\\hline" not in txt and "\\begin{array}" not in txt


def test_cline_argument_consumed():
    res, omml, txt = _conv(r"\[\begin{array}{cc}a & b \\ \cline{1-2} c & d\end{array}\]")
    assert omml == 1 and res.report.math_raw == 0
    assert "\\cline" not in txt and "1-2" not in txt


def _math_text(body: str) -> tuple[int, str]:
    """(math_raw, concatenated text of all m:t runs) for a \\[ body \\] fragment."""
    res = convert_source(
        r"\documentclass{article}\usepackage{amsmath,amssymb}\begin{document}\["
        + body
        + r"\]\end{document}"
    )
    root = etree.fromstring(
        zipfile.ZipFile(io.BytesIO(res.docx)).read("word/document.xml")
    )
    mtext = "".join(t.text or "" for t in root.iter(f"{{{M}}}t"))
    return res.report.math_raw, mtext


def test_align_wrapped_in_display_keeps_all_content():
    # regression: an align/align* *inside* \[…\] (or $$…$$) reaches the math parser
    # as a whole env; it must render, not silently drop its content via a fallback.
    raw, mt = _math_text(r"\begin{align*}x &= a + b \\ y &= c\end{align*}")
    assert raw == 0
    for ch in "xaby c":
        if ch.strip():
            assert ch in mt


def test_left_brace_wrapping_align_system_renders():
    # \left\{ \begin{align*} … \end{align*} \right.  (a braced system of equations)
    raw, mt = _math_text(r"\left\{\begin{align*}u &= f(v) \\ w &= g(u)\end{align*}\right.")
    assert raw == 0
    for tok in ("u", "f", "v", "w", "g"):
        assert tok in mt
    assert "\\begin" not in mt and "\\left" not in mt


def test_alignat_argument_consumed():
    raw, mt = _math_text(r"\begin{alignat}{2}a &= b & \quad c &= d\end{alignat}")
    assert raw == 0
    assert "a" in mt and "d" in mt and "2" not in mt  # the column-count {2} was consumed
