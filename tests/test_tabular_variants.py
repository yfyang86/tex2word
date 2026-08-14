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


def test_tabularx_X_column_is_counted_and_widths_align():
    # the flexible X column must be counted (else the fixed p{} widths shift
    # onto the wrong columns and the paragraph column vanishes).
    src = (
        r"\begin{tabularx}{\textwidth}{@{}p{2.6cm}Xp{2.5cm}@{}}"
        r" a & b & c \\ d & e & f \\ \end{tabularx}"
    )
    tbl = _table(_conv(src).document)
    assert tbl.colspec == ["left", "left", "left"]        # three columns, X counted
    # p{} columns carry a width; the X column is auto (None), in the right slot
    assert tbl.colwidths[0] is not None and tbl.colwidths[2] is not None
    assert tbl.colwidths[1] is None
    assert _rows(tbl) == [["a", "b", "c"], ["d", "e", "f"]]


def test_tabulary_LCRJ_columns_counted():
    src = r"\begin{tabulary}{\linewidth}{LCRJ} a & b & c & d \\ \end{tabulary}"
    tbl = _table(_conv(src).document)
    assert tbl.colspec == ["left", "center", "right", "left"]
    assert _rows(tbl) == [["a", "b", "c", "d"]]


def test_longtable_colspec_not_eaten_as_row():
    # longtable is not in pylatexenc's defaults; its {colspec} must be consumed
    # as the environment argument, not parsed as the first data row.
    src = (
        r"\begin{longtable}{@{}p{2.4cm}p{4.1cm}p{4.0cm}@{}}"
        r" A & B & C \\ x & y & z \\ \end{longtable}"
    )
    tbl = _table(_conv(src).document)
    assert tbl is not None
    assert tbl.colspec == ["left", "left", "left"]        # colspec parsed
    assert all(w is not None for w in tbl.colwidths)      # p{} widths captured
    assert _rows(tbl) == [["A", "B", "C"], ["x", "y", "z"]]  # colspec not a row


def test_variants_valid():
    src = r"\begin{tabularx}{\textwidth}{lc} a & b \\ \end{tabularx}"
    assert validate_docx(_conv(src).docx) == []
