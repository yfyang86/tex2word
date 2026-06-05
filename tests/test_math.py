from __future__ import annotations

import pytest
from lxml import etree

from tex2word.mathml import latex_math as L
from tex2word.mathml import omml
from tex2word.mathml.latex_math import MathUnsupported

NS = {"m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}


def xml(elem) -> str:
    return etree.tostring(elem, encoding="unicode")


def count(elem, tag) -> int:
    return len(elem.findall(f".//{{{NS['m']}}}{tag}"))


# -- AST --------------------------------------------------------------------- #


def test_parses_fraction_with_power():
    row = L.parse(r"\frac{a}{b}^2")
    assert isinstance(row.items[0], L.Sup)
    assert isinstance(row.items[0].base, L.Frac)


def test_parses_subsup():
    row = L.parse(r"x_i^2")
    assert isinstance(row.items[0], L.SubSup)


def test_nary_captures_limits():
    row = L.parse(r"\sum_{i=1}^n")
    nary = row.items[0]
    assert isinstance(nary, L.Nary)
    assert nary.sub is not None and nary.sup is not None


# -- OMML -------------------------------------------------------------------- #


def test_fraction_to_omml():
    o = omml.render_inline(r"\frac{a}{b}")
    assert count(o, "f") == 1
    assert count(o, "num") == 1
    assert count(o, "den") == 1


def test_power_to_ssup():
    assert count(omml.render_inline("x^2"), "sSup") == 1


def test_subscript_to_ssub():
    assert count(omml.render_inline("x_i"), "sSub") == 1


def test_sqrt_to_rad():
    o = omml.render_inline(r"\sqrt{x+1}")
    assert count(o, "rad") == 1
    assert count(o, "degHide") == 1


def test_nth_root_has_degree():
    o = omml.render_inline(r"\sqrt[3]{x}")
    assert count(o, "rad") == 1
    assert count(o, "degHide") == 0


def test_sum_to_nary():
    o = omml.render_inline(r"\sum_{i=1}^n i")
    assert count(o, "nary") == 1


def test_accent():
    assert count(omml.render_inline(r"\hat{x}"), "acc") == 1


def test_fenced_delimiters():
    o = omml.render_inline(r"\left( x \right)")
    assert count(o, "d") == 1


def test_matrix():
    o = omml.render_inline(r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}")
    assert count(o, "m") >= 1
    assert count(o, "mr") == 2


def test_greek_symbol_present():
    o = omml.render_inline(r"\alpha")
    assert "α" in xml(o)


def test_display_align_collapses_to_aligned_matrix():
    # &-aligned content -> one m:oMath holding a column-justified matrix
    lines = omml.render_block_lines(r"a &= b \\ c &= d")
    assert len(lines) == 1
    o = lines[0]
    assert count(o, "m") == 1
    assert count(o, "mr") == 2  # two rows
    jc = [e.get(f"{{{NS['m']}}}val") for e in o.findall(f".//{{{NS['m']}}}mcJc")]
    assert jc == ["right", "left"]  # right | left -> aligned at the relation


def test_display_align_can_keep_lines():
    lines = omml.render_block_lines(r"a &= b \\ c &= d", collapse_align=False)
    assert len(lines) == 2


def test_label_and_tag_stripped():
    o = omml.render_inline(r"x \label{eq:1} \tag{3}")
    assert "label" not in xml(o)
    assert "tag" not in xml(o)


def test_overbrace_to_groupchr():
    o = omml.render_inline(r"\overbrace{a+b}^{n}")
    assert count(o, "groupChr") == 1


def test_underbrace_to_groupchr():
    o = omml.render_inline(r"\underbrace{x+y}_{z}")
    assert count(o, "groupChr") == 1


def test_unsupported_macro_raises():
    with pytest.raises(MathUnsupported):
        L.parse(r"\someunknownmacro{x}")


# -- constructs surfaced by the arXiv:2507.17026v2 UAT ----------------------- #


def test_literal_braces_in_math():
    # \{ \} are literal set braces, not grouping -- and must not crash
    o = omml.render_inline(r"\{\theta \le t\}")
    txt = xml(o)
    assert "{" in txt and "}" in txt


def test_big_delimiter_sizing_is_transparent():
    # \Big( ... \Big) renders the delimiters; the sizing is dropped, not raw
    o = omml.render_inline(r"\Big( a + b \Big)")
    txt = xml(o)
    assert "big" not in txt.lower()
    assert "(" in txt and ")" in txt


def test_big_with_escaped_brace_delim():
    row = L.parse(r"\big\{ x \big\}")
    assert isinstance(row, L.Row)  # parses without raising


def test_xrightarrow_with_label():
    row = L.parse(r"\xrightarrow{n \to \infty}")
    assert isinstance(row.items[0], L.Sup)  # arrow base + over-label


def test_xrightarrow_with_under_and_over():
    row = L.parse(r"\xrightarrow[a]{b}")
    assert isinstance(row.items[0], L.SubSup)


def test_overset_renders_as_matrix():
    o = omml.render_inline(r"\overset{a}{b}")
    assert count(o, "m") == 1  # stacked 2x1 matrix


def test_underset_renders_as_matrix():
    o = omml.render_inline(r"\underset{x}{y}")
    assert count(o, "m") == 1


def test_textrm_is_upright():
    o = omml.render_inline(r"\textrm{Var}")
    txt = xml(o)
    # letters render upright (m:nor); they appear as individual runs
    assert "<m:nor/>" in txt
    assert ">V<" in txt and ">a<" in txt and ">r<" in txt


def test_new_relation_symbols():
    for cmd, glyph in [("gtrsim", "≳"), ("lesssim", "≲"), ("triangleq", "≜")]:
        assert glyph in xml(omml.render_inline(f"a \\{cmd} b"))


def test_truncated_input_does_not_crash():
    # a command missing its argument at end-of-stream must raise cleanly,
    # never IndexError (the cascade only catches MathUnsupported by name)
    for src in (r"\frac{a}", r"\mathbf", r"x^"):
        try:
            L.parse(src)
        except MathUnsupported:
            pass
        except IndexError as err:  # pragma: no cover - the bug we fixed
            raise AssertionError(f"IndexError on {src!r}") from err


# -- V4-11: mathtools/physics built-in macros -------------------------------- #


def test_paired_delimiter_macros():
    assert count(omml.render_inline(r"\abs{x}"), "d") == 1
    assert count(omml.render_inline(r"\norm{v}"), "d") == 1
    assert "⌈" in xml(omml.render_inline(r"\ceil{n}"))
    assert "⌊" in xml(omml.render_inline(r"\floor{n}"))


def test_paired_delimiter_star_form():
    # \abs*{x} (auto-size) parses, star ignored
    assert count(omml.render_inline(r"\abs*{x}"), "d") == 1


def test_braket_and_ket():
    assert "⟩" in xml(omml.render_inline(r"\ket{\psi}"))
    assert "⟨" in xml(omml.render_inline(r"\braket{\phi}"))


def test_derivative_macros_are_fractions():
    assert count(omml.render_inline(r"\dv{f}{x}"), "f") == 1   # d f / d x
    assert count(omml.render_inline(r"\dv{x}"), "f") == 1      # d / d x
    assert count(omml.render_inline(r"\pdv{L}{q}"), "f") == 1  # partial


def test_user_macro_still_overrides_builtin():
    # if the document \newcommand-s \abs, the expander wins (built-in unused)
    from tex2word.frontend.macros import expand_macros
    out = expand_macros(r"\newcommand{\abs}[1]{ABS(#1)}\abs{y}")
    assert "ABS(y)" in out


# -- V4-9: align/aligned column alignment ------------------------------------ #


def _conv_root(src):
    import io
    import zipfile

    from tex2word import convert_source
    docx = convert_source(rf"\begin{{document}}{src}\end{{document}}").docx
    return etree.fromstring(zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml"))


def _seq_eq_count(root):
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    return sum(1 for i in root.iter(f"{{{W}}}instrText") if "SEQ Equation" in (i.text or ""))


def test_align_star_renders_aligned_matrix_no_numbers():
    root = _conv_root(r"\begin{align*} a &= b \\ cc &= d \end{align*}")
    assert count(root, "m") == 1 and count(root, "mr") == 2
    assert _seq_eq_count(root) == 0


def test_numbered_align_keeps_per_line_numbers():
    # top-level numbered align must not collapse -> two equation numbers
    root = _conv_root(r"\begin{align} a &= b \\ cc &= d \end{align}")
    assert count(root, "m") == 0
    assert _seq_eq_count(root) == 2


def test_equation_with_aligned_is_one_number_and_aligned():
    root = _conv_root(
        r"\begin{equation}\begin{aligned} a &= b \\ cc &= d \end{aligned}\end{equation}"
    )
    assert count(root, "m") == 1            # one aligned matrix
    assert _seq_eq_count(root) == 1         # one equation number


def test_gather_is_not_collapsed():
    root = _conv_root(r"\begin{gather} a=b \\ c=d \end{gather}")
    assert count(root, "m") == 0            # no & -> stacked, not a matrix
