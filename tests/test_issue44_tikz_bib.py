"""Issue #44: every TikZ picture of a figure, engine choice, font filtering,
\\foreach \\label, and bibliographies in size groups."""

from __future__ import annotations

import io
import re
import zipfile

from tex2word import convert_source, ir
from tex2word.backend import tikz

_PIC_A = "\\begin{tikzpicture}\\draw (0,0) -- (1,0);\\end{tikzpicture}"
_PIC_B = "\\begin{tikzpicture}\\fill (0,0) circle (1);\\end{tikzpicture}"


def test_extract_pictures_returns_every_top_level_picture():
    src = f"\\centering\n{_PIC_A}\n\\par\\vspace{{2mm}}\n{_PIC_B}\n\\caption{{x}}"
    assert tikz.extract_pictures(src) == [_PIC_A, _PIC_B]
    assert tikz.extract_picture(src) == _PIC_A


def test_nested_picture_stays_inside_the_outer_one():
    nested = (
        "\\begin{tikzpicture}\\node {\\begin{tikzpicture}\\draw (0,0) -- (1,1);"
        "\\end{tikzpicture}}; \\draw (2,2) -- (3,3);\\end{tikzpicture}"
    )
    assert tikz.extract_pictures(nested + _PIC_B) == [nested, _PIC_B]


def test_unbalanced_picture_is_not_extracted():
    assert tikz.extract_pictures("\\begin{tikzpicture}\\draw (0,0);") == []


def test_keep_font_matches_fontspec_and_xecjk():
    pre = "\\usepackage{fontspec}\n\\usepackage{xeCJK}\n\\setmainfont{Times}\n\\setCJKmainfont{X}"
    out = tikz._filtered_preamble(pre, unicode_engine=True)
    for line in pre.splitlines():
        assert line in out
    assert tikz._filtered_preamble(pre, unicode_engine=False) == ""


def test_pdflatex_build_keeps_text_font_packages():
    pre = "\\usepackage{times}\n\\usepackage[T1]{fontenc}\n\\usepackage{newtxmath}"
    out = tikz._filtered_preamble(pre, unicode_engine=False)
    assert "times" in out and "fontenc" in out and "newtxmath" in out
    # xelatex builds leave them out (fontspec handles fonts there)
    assert tikz._filtered_preamble(pre, unicode_engine=True) == ""


def test_engine_order_prefers_pdflatex_for_pdflatex_papers(monkeypatch):
    monkeypatch.setattr(tikz, "available_engines", lambda: ["xelatex", "lualatex", "pdflatex"])
    assert tikz.engine_order(_PIC_A, "\\usepackage{times}")[0] == "pdflatex"
    for pre in ("\\usepackage{fontspec}", "\\usepackage{unicode-math}",
                "\\usepackage{polyglossia}", "\\usepackage[UTF8]{xeCJK}"):
        assert tikz.engine_order(_PIC_A, pre)[0] == "xelatex", pre
    # non-ASCII node text needs a Unicode engine
    assert tikz.engine_order("\\node {示意图};", "")[0] == "xelatex"
    # every engine stays available as a fallback
    assert sorted(tikz.engine_order(_PIC_A, "")) == ["lualatex", "pdflatex", "xelatex"]


def test_figure_definitions_outside_the_picture_are_kept():
    src = "\\definecolor{stage}{RGB}{37,99,235}\n" + _PIC_A + "\n\\caption{c}"
    assert tikz._figure_definitions(src) == "\\definecolor{stage}{RGB}{37,99,235}"


def test_foreach_label_does_not_replace_the_figure_label():
    src = (
        "\\documentclass{article}\\usepackage{tikz}\\begin{document}\n"
        "\\begin{figure}\\begin{tikzpicture}\n"
        "\\foreach \\label/\\value in {A/1, B/2} { \\node at (0,\\value) {\\label}; }\n"
        "\\end{tikzpicture}\\caption{Bars.}\\label{fig:bars}\\end{figure}\n"
        "See Figure~\\ref{fig:bars}.\\end{document}\n"
    )
    r = convert_source(src)
    figs = [b for b in r.document.blocks if isinstance(b, ir.Figure)]
    assert figs[0].label == "fig:bars"
    assert not [w for w in r.report.warnings if "unresolved" in w.message]


_BIB = """@book{knuth1984, author = {Knuth, Donald}, title = {The TeXbook}, year = {1984}}
"""


def _bib_doc(tmp_path, natbib_opts: str, bib: str) -> str:
    (tmp_path / "refs.bib").write_text(_BIB, encoding="utf-8")
    src = (
        f"\\documentclass{{article}}\\usepackage[{natbib_opts}]{{natbib}}\n"
        "\\begin{document}\nSee \\citep{knuth1984}.\n" + bib + "\n\\end{document}\n"
    )
    r = convert_source(src, base_dir=str(tmp_path))
    xml = zipfile.ZipFile(io.BytesIO(r.docx)).read("word/document.xml").decode()
    assert not [w.message for w in r.report.warnings], r.report.warnings
    return "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", xml))


def test_bibliography_inside_a_size_group_is_found(tmp_path):
    text = _bib_doc(
        tmp_path, "authoryear",
        "{\\small\n\\bibliographystyle{plainnat}\n\\bibliography{refs}\n}",
    )
    assert "(Knuth, 1984)" in text
    assert "The TeXbook" in text  # the reference list is there


def test_natbib_numbers_beats_plainnat(tmp_path):
    text = _bib_doc(
        tmp_path, "numbers,sort&compress",
        "\\bibliographystyle{plainnat}\\bibliography{refs}",
    )
    assert "[1]" in text and "Knuth, 1984" not in text
