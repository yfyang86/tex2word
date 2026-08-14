"""TikZ figures: compile to an image when a TeX engine is available, else a
clean caption-only figure -- never the developer-facing placeholder text.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from tex2word import convert_source
from tex2word.backend import tikz

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

FIG = (
    r"\begin{figure}\centering"
    r"\begin{tikzpicture}\draw[->] (0,0) -- (2,0) node[right] {$x$};\end{tikzpicture}"
    r"\caption{示意图 caption text}\label{fig:demo}"
    r"\end{figure}"
)


def _alltext(src: str) -> str:
    from lxml import etree

    root = etree.fromstring(
        zipfile.ZipFile(io.BytesIO(convert_source(src).docx)).read("word/document.xml")
    )
    return "".join(t.text or "" for t in root.iter(f"{{{W}}}t"))


def _media_pngs(src: str) -> list[str]:
    names = zipfile.ZipFile(io.BytesIO(convert_source(src).docx)).namelist()
    return [n for n in names if n.startswith("word/media/")]


# -- pure helpers (run everywhere) ------------------------------------------- #

def test_extract_picture():
    pic = tikz.extract_picture(FIG)
    assert pic is not None
    assert pic.startswith(r"\begin{tikzpicture}") and pic.endswith(r"\end{tikzpicture}")


def test_extract_picture_none_when_absent():
    assert tikz.extract_picture(r"\begin{figure}\includegraphics{x}\end{figure}") is None


def test_build_standalone_keeps_tikz_bits_and_drops_class_packages():
    preamble = "\n".join([
        r"\usepackage[margin=1in]{geometry}",
        r"\usepackage{hyperref}",
        r"\usetikzlibrary{calc,positioning}",
        r"\definecolor{myblue}{RGB}{1,2,3}",
        r"\newcommand{\foo}{bar}",
    ])
    std = tikz.build_standalone(r"\begin{tikzpicture}\end{tikzpicture}", preamble)
    assert r"\documentclass[border=2pt]{standalone}" in std
    assert r"\usepackage{tikz}" in std
    assert "myblue" in std and "calc,positioning" in std and r"\newcommand{\foo}" in std
    assert "geometry" not in std and "hyperref" not in std  # class packages dropped


def test_filtered_preamble_drops_fancyhdr_layout_redefinitions():
    # \renewcommand{\headrulewidth}{..} belongs to fancyhdr, which the standalone
    # build drops -> keeping the redefine fails with "\headrulewidth undefined".
    # The header/footer/page-style layout commands must be filtered out while the
    # picture-relevant preamble (colours, tikz libraries) is kept.
    preamble = "\n".join([
        r"\usepackage{fancyhdr}",
        r"\usepackage{tikz}",
        r"\pagestyle{fancy}",
        r"\fancyhf{}",
        r"\fancyhead[L]{\footnotesize\itshape Title}",
        r"\renewcommand{\headrulewidth}{0.4pt}",
        r"\renewcommand{\footrulewidth}{0pt}",
        r"\definecolor{NavyDark}{HTML}{1F3864}",
        r"\usetikzlibrary{positioning}",
        r"\newcommand{\keepme}{ok}",
    ])
    fp = tikz._filtered_preamble(preamble, unicode_engine=False)
    assert "headrulewidth" not in fp and "footrulewidth" not in fp
    assert "pagestyle" not in fp and "fancyhf" not in fp and "fancyhead" not in fp
    # picture-relevant bits and unrelated user macros survive
    assert "NavyDark" in fp and "positioning" in fp and r"\newcommand{\keepme}" in fp


def test_filtered_preamble_keeps_symbol_and_citation_packages():
    # a node's text may use macros from content packages (pifont's \ding,
    # natbib's \citep); those packages must survive so the standalone build
    # doesn't fail with "Undefined control sequence".
    preamble = "\n".join([
        r"\usepackage{pifont}",
        r"\usepackage[round,authoryear]{natbib}",
        r"\usepackage{graphicx}",
        r"\usepackage[margin=1in]{geometry}",
        r"\usepackage{hyperref}",
        r"\usepackage{tikz}",
    ])
    fp = tikz._filtered_preamble(preamble, unicode_engine=False)
    assert "pifont" in fp and "natbib" in fp and "graphicx" in fp
    assert "geometry" not in fp and "hyperref" not in fp


def test_filtered_preamble_keeps_full_multiline_macro():
    # a multi-line \newcommand body must be captured whole; keeping only its
    # opening line leaves an unbalanced "{" that fails the standalone compile.
    preamble = "\n".join([
        r"\newcommand{\callout}[2]{",
        r"  \begin{center}",
        r"  \colorbox{gray}{\begin{minipage}{0.9\linewidth}#1 --- #2\end{minipage}}",
        r"  \end{center}",
        r"}",
        r"\newcommand{\after}{X}",
    ])
    fp = tikz._filtered_preamble(preamble, unicode_engine=False)
    # brace-balanced (no truncation) and the following macro survives intact
    assert sum(tikz._brace_delta(line) for line in fp.splitlines()) == 0
    assert r"\end{center}" in fp and r"\newcommand{\after}{X}" in fp


def test_build_standalone_with_multiline_macro_is_balanced():
    preamble = "\n".join([
        r"\definecolor{c}{gray}{0.9}",
        r"\newcommand{\box}[1]{",
        r"  \colorbox{c}{#1}",
        r"}",
    ])
    std = tikz.build_standalone(r"\begin{tikzpicture}\node {a};\end{tikzpicture}", preamble)
    assert sum(tikz._brace_delta(line) for line in std.splitlines()) == 0


# -- conversion behaviour ---------------------------------------------------- #

def test_figure_never_shows_placeholder_text():
    # whether or not a TeX engine is present, the old "[figure omitted ...]"
    # developer placeholder must never appear in the document.
    out = _alltext(FIG.join((r"\begin{document}", r"\end{document}")))
    assert "figure omitted" not in out and "no convertible graphics" not in out


def test_tikz_figure_keeps_caption():
    out = _alltext(r"\begin{document}" + FIG + r"\end{document}")
    assert "示意图 caption text" in out


@pytest.mark.skipif(tikz.find_engine() is None, reason="no TeX engine on PATH")
def test_tikz_compiles_to_image_when_engine_present():
    # only runs where xelatex/pdflatex is installed (e.g. a CI lane with texlive)
    pytest.importorskip("pypdfium2")
    pngs = _media_pngs(r"\begin{document}" + FIG + r"\end{document}")
    assert pngs, "expected a rendered TikZ image embedded in word/media/"


def test_render_returns_none_without_engine():
    if tikz.find_engine() is not None:
        pytest.skip("a TeX engine is installed; cannot test the no-engine path")
    assert tikz.render(FIG) is None
