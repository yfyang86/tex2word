"""Fidelity: wrapfig wrapfigure/wraptable floats (consume {placement}{width})."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def _caption(block) -> str:
    return "".join(getattr(x, "value", "") for x in (block.caption or []))


def test_wrapfigure_is_a_figure_with_caption():
    src = (
        r"\begin{wrapfigure}{r}{0.4\textwidth}\centering"
        r"\includegraphics{a.png}\caption{Wrapped fig.}\label{fig:w}"
        r"\end{wrapfigure}"
    )
    doc = _conv(src).document
    fig = next((b for b in doc.blocks if type(b).__name__ == "Figure"), None)
    assert fig is not None
    assert _caption(fig) == "Wrapped fig."


def test_wrapfigure_optional_lines_arg():
    src = (
        r"\begin{wrapfigure}[8]{l}{5cm}\includegraphics{a.png}"
        r"\caption{C}\end{wrapfigure}"
    )
    doc = _conv(src).document
    assert any(type(b).__name__ == "Figure" for b in doc.blocks)


def test_wraptable_is_a_table_with_caption():
    src = (
        r"\begin{wraptable}{r}{0.4\textwidth}"
        r"\begin{tabular}{ll} a & b \\ \end{tabular}\caption{Wrapped tab.}"
        r"\end{wraptable}"
    )
    doc = _conv(src).document
    tbl = next((b for b in doc.blocks if type(b).__name__ == "Table"), None)
    assert tbl is not None
    assert _caption(tbl) == "Wrapped tab."
    assert len(tbl.rows) == 1


def test_valid():
    src = r"\begin{wrapfigure}{r}{3cm}\includegraphics{x.png}\caption{C}\end{wrapfigure}"
    assert validate_docx(_conv(src).docx) == []
