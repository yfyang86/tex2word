from __future__ import annotations

from latex2word import convert_source, ir
from latex2word.frontend import parse_document
from latex2word.frontend.preprocess import replace_inline_tikz


def test_strip_inline_tikz_path_form():
    src = r"before \tikz[baseline] \node[circle] (c) {3}; after"
    out = replace_inline_tikz(src)
    assert "\\tikz" not in out and "\\node" not in out
    assert "③" in out
    assert "before" in out and "after" in out


def test_strip_inline_tikz_brace_form():
    out = replace_inline_tikz(r"x \tikz{\draw (0,0)--(1,1);} y")
    assert "\\tikz" not in out and "\\draw" not in out


def test_circled_numbers_1_to_20():
    assert "①" in replace_inline_tikz(r"\tikz \node {1};")
    assert "⑳" in replace_inline_tikz(r"\tikz \node {20};")
    # out of circled range -> parenthesised fallback
    assert "(99)" in replace_inline_tikz(r"\tikz \node {99};")


def test_tikz_without_number_is_dropped():
    out = replace_inline_tikz(r"keep \tikz \draw (0,0) circle; this")
    assert "\\tikz" not in out
    assert "keep" in out and "this" in out


def test_tikzset_not_touched():
    # \tikzset is a different macro and must not be matched.
    src = r"\tikzset{every node/.style={}}"
    assert replace_inline_tikz(src) == src


def test_inline_tikz_circled_via_macro_expansion():
    # \circled{2} expands to a \tikz...node...{2}; then becomes ②.
    src = (
        r"\newcommand{\circled}[1]{\tikz[baseline]{\node[shape=circle,draw]{#1};}}"
        r"\begin{document}Step \circled{2} here.\end{document}"
    )
    doc, _ = parse_document(src)
    text = "".join(
        t.value for b in doc.blocks if isinstance(b, ir.Paragraph)
        for t in b.inlines if isinstance(t, ir.Text)
    )
    assert "②" in text
    assert "tikz" not in text and "node" not in text


def test_no_tikz_warnings_in_output():
    src = (
        r"\begin{document}Use \tikz[baseline] \node[circle] (c) {1}; markers."
        r"\end{document}"
    )
    result = convert_source(src)
    assert not any("tikz" in w.construct or "node" in w.construct for w in result.report.warnings)
