"""Multi-column body layout: \\documentclass[twocolumn], figure*/table* spanning.

A two-column paper lays the body out in two Word columns (w:cols num=2), while a
starred float (figure*/table*) and the title/abstract span the full page width --
realised with continuous section breaks that switch the column count.
"""

from __future__ import annotations

import io
import zipfile

from lxml import etree

from tex2word import convert_source, ir
from tex2word.frontend import parse_document

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _doc(src: str) -> ir.Document:
    return parse_document(src)[0]


def _sections(docx: bytes) -> list[tuple[str, int]]:
    """(kind, columns) for each section boundary in document order.

    kind is 'break' for a continuous mid-body break (sectPr in a p/pPr) or 'body'
    for the final body-level sectPr; columns is the w:cols num (1 if absent)."""
    root = etree.fromstring(zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml"))
    body = root.find(f"{{{W}}}body")
    out: list[tuple[str, int]] = []

    def cols_of(sect) -> int:
        c = sect.find(f"{{{W}}}cols")
        return int(c.get(f"{{{W}}}num")) if c is not None and c.get(f"{{{W}}}num") else 1

    for child in body:
        tag = etree.QName(child).localname
        if tag == "sectPr":
            out.append(("body", cols_of(child)))
        elif tag == "p":
            sect = child.find(f"{{{W}}}pPr/{{{W}}}sectPr")
            if sect is not None:
                out.append(("break", cols_of(sect)))
    return out


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #


def test_twocolumn_class_option_detected():
    src = r"\documentclass[twocolumn]{article}\begin{document}x\end{document}"
    assert _doc(src).meta.columns == 2


def test_twocolumn_command_detected():
    src = r"\documentclass{article}\begin{document}\twocolumn x\end{document}"
    assert _doc(src).meta.columns == 2


def test_multicols_environment_count_detected():
    src = (
        r"\documentclass{article}\begin{document}"
        r"\begin{multicols}{3}x\end{multicols}\end{document}"
    )
    assert _doc(src).meta.columns == 3


def test_single_column_by_default():
    assert _doc(r"\documentclass{article}\begin{document}x\end{document}").meta.columns == 1
    # an unrelated option must not be mistaken for twocolumn
    other = r"\documentclass[11pt,a4paper]{article}\begin{document}x\end{document}"
    assert _doc(other).meta.columns == 1


# --------------------------------------------------------------------------- #
# spanning floats
# --------------------------------------------------------------------------- #


def test_begin_star_typo_normalized_to_starred_env():
    # \begin*{figure}/\end*{figure} (star misplaced) is a common typo for
    # \begin{figure*}; it must still be recognised as a spanning float.
    from tex2word.frontend.preprocess import _normalize_begin_star

    got = _normalize_begin_star(r"\begin*{figure}x\end*{figure}")
    assert got == r"\begin{figure*}x\end{figure*}"
    doc = _doc(
        r"\documentclass[twocolumn]{article}\begin{document}"
        r"\begin*{figure}\caption{c}\end*{figure}\end{document}"
    )
    figs = [b for b in doc.blocks if isinstance(b, ir.Figure)]
    assert figs and figs[0].spanning is True


def test_starred_float_marked_spanning():
    doc = _doc(
        r"\documentclass{article}\begin{document}"
        r"\begin{figure*}\caption{wide}\end{figure*}"
        r"\begin{table*}\begin{tabular}{c}a\end{tabular}\caption{wt}\end{table*}"
        r"\begin{figure}\caption{narrow}\end{figure}"
        r"\end{document}"
    )
    figs = [b for b in doc.blocks if isinstance(b, ir.Figure)]
    tabs = [b for b in doc.blocks if isinstance(b, ir.Table)]
    assert figs[0].spanning is True and figs[1].spanning is False
    assert tabs and tabs[0].spanning is True


# --------------------------------------------------------------------------- #
# backend section breaks
# --------------------------------------------------------------------------- #


def test_single_column_has_no_column_breaks():
    secs = _sections(convert_source(
        r"\documentclass{article}\begin{document}\section{A}text\end{document}"
    ).docx)
    assert secs == [("body", 1)]  # one section, single column, no breaks


def test_twocolumn_body_with_spanning_figure_section_breaks():
    src = (
        r"\documentclass[twocolumn]{article}\title{T}\author{A}\begin{document}\maketitle"
        r"\begin{abstract}abs\end{abstract}\section{Intro}Body one."
        r"\begin{figure*}\caption{wide}\end{figure*}More body."
        r"\end{document}"
    )
    secs = _sections(convert_source(src).docx)
    # title/abstract full-width (1), 2-col body, 1-col figure*, 2-col rest
    assert secs == [("break", 1), ("break", 2), ("break", 1), ("body", 2)]


def test_explicit_columns_param_overrides():
    from tex2word import convert_source as cs

    secs = _sections(
        cs(r"\documentclass{article}\begin{document}text\end{document}", columns=2).docx
    )
    assert secs[-1] == ("body", 2)
