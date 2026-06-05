"""Constructs surfaced by UAT3 (arXiv:2605.23904v2): phantom/box macros that
leaked as raw text, and verbatim bodies (incl. wrapped in a font-size group)
that came back empty."""

from __future__ import annotations

from tex2word import convert_source, ir
from tex2word.frontend import parse_document
from tex2word.validate import validate_docx


def _blocks(src: str) -> list[ir.Block]:
    doc, _ = parse_document(rf"\begin{{document}}{src}\end{{document}}", ".")
    return doc.blocks


def _deep(inlines) -> str:
    out = []
    for i in inlines:
        if isinstance(i, ir.Text):
            out.append(i.value)
        elif hasattr(i, "inlines"):
            out.append(_deep(i.inlines))
    return "".join(out)


def _para_text(blocks) -> str:
    return " ".join(_deep(b.inlines) for b in blocks if isinstance(b, ir.Paragraph))


# -- verbatim (the empty-CodeBlock bug) -------------------------------------- #


def test_verbatim_body_is_captured():
    cb = next(b for b in _blocks("\\begin{verbatim}\nline one\n  indented\n\\end{verbatim}")
              if isinstance(b, ir.CodeBlock))
    assert cb.text == "line one\n  indented"


def test_verbatim_inside_font_size_group_is_captured():
    # the paper's pattern: {\footnotesize \begin{verbatim}...\end{verbatim}}
    src = (
        "{\\footnotesize\n\\begin{verbatim}\n"
        "You are an agent.\nRespond in JSON.\n\\end{verbatim}\n}"
    )
    cb = next(b for b in _blocks(src) if isinstance(b, ir.CodeBlock))
    assert cb.text == "You are an agent.\nRespond in JSON."


# -- phantom / box macros (the \hphantom leak) ------------------------------- #


def test_hphantom_prints_nothing():
    # \dvalp{86.1}{4.1} expands to \hphantom{...}86.1\textsubscript{...}; the
    # \hphantom must NOT leak into the text
    text = _para_text(_blocks(r"x\hphantom{\textsubscript{+4.1}}y"))
    assert "hphantom" not in text and text.replace(" ", "") == "xy"


def test_phantom_and_vphantom_drop():
    assert "phantom" not in _para_text(_blocks(r"a\phantom{ZZ}b\vphantom{Q}c"))


def test_mbox_and_raisebox_are_transparent():
    assert "best_skill.md" in _para_text(_blocks(r"\mbox{\texttt{best\_skill.md}}"))
    assert "M" in _para_text(_blocks(r"\raisebox{-0.5\height}{M}"))


def test_rule_and_font_macros_are_silent():
    res = convert_source(
        r"\begin{document}\fontfamily{qhv}\selectfont text "
        r"\rule{\linewidth}{0.8pt} \fontsize{21}{25}\selectfont more\end{document}"
    )
    assert res.report.warnings == []
    assert validate_docx(res.docx) == []


def test_dvalp_style_macro_in_table_has_no_leak():
    src = (
        r"\newcommand{\dvalp}[2]{\hphantom{\textsubscript{+#2}}#1"
        r"\textsubscript{\textcolor{red}{+#2}}}"
        r"\begin{document}\begin{tabular}{lc}A & \dvalp{86.1}{4.1} \\\end{tabular}\end{document}"
    )
    doc, _ = parse_document(src, ".")
    table = next(b for b in doc.blocks if isinstance(b, ir.Table))
    cell = _deep(table.rows[0].cells[1].blocks[0].inlines)
    assert "hphantom" not in cell and cell.startswith("86.1")
