"""Fidelity: tabularx/tabulary (skip {width}) and supertabular/xtabular."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def _table(doc):
    return next((b for b in doc.blocks if type(b).__name__ == "Table"), None)


def _cell_text(cell) -> str:
    if not cell.blocks:
        return ""
    return "".join(getattr(x, "value", "") for x in cell.blocks[0].inlines)


def _rows(tbl):
    return [[_cell_text(c) for c in r.cells] for r in tbl.rows]


def test_tabularx_skips_width_and_parses_colspec():
    src = r"\begin{tabularx}{\textwidth}{ll} a & b \\ c & d \\ \end{tabularx}"
    tbl = _table(_conv(src).document)
    assert tbl is not None
    assert tbl.colspec == ["left", "left"]  # {ll}, not the {\textwidth}
    assert _rows(tbl) == [["a", "b"], ["c", "d"]]


def test_tabulary_colspec():
    src = r"\begin{tabulary}{\linewidth}{lr} x & y \\ \end{tabulary}"
    tbl = _table(_conv(src).document)
    assert tbl.colspec == ["left", "right"]
    assert _rows(tbl) == [["x", "y"]]


def test_supertabular_and_xtabular():
    for env in ("supertabular", "xtabular"):
        src = rf"\begin{{{env}}}{{ll}} p & q \\ \end{{{env}}}"
        tbl = _table(_conv(src).document)
        assert tbl is not None, env
        assert _rows(tbl) == [["p", "q"]]


def test_variants_valid():
    src = r"\begin{tabularx}{\textwidth}{lc} a & b \\ \end{tabularx}"
    assert validate_docx(_conv(src).docx) == []
