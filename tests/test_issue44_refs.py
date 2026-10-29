"""Issue #44: citations and \\ref resolve in every container; extra \\labels alias."""

from __future__ import annotations

import io
import re
import zipfile

from tex2word import convert_source

_BIB = """@article{tk1991,
  author = {Tversky, Amos and Kahneman, Daniel},
  title = {Loss Aversion in Riskless Choice},
  journal = {The Quarterly Journal of Economics},
  year = {1991},
}
"""


def _convert(body: str, tmp_path, preamble: str = ""):
    (tmp_path / "refs.bib").write_text(_BIB, encoding="utf-8")
    src = (
        "\\documentclass{article}\n\\usepackage[authoryear]{natbib}\n"
        + preamble
        + "\\begin{document}\n"
        + body
        + "\n\\bibliographystyle{plainnat}\\bibliography{refs}\n\\end{document}\n"
    )
    return convert_source(src, base_dir=str(tmp_path))


def _text(docx: bytes) -> str:
    xml = zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode()
    return "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", xml))


def _unresolved(r) -> list[str]:
    return [w.message for w in r.report.warnings if "unresolved" in w.message]


def test_cite_and_ref_in_table_cell(tmp_path):
    r = _convert(
        "\\section{S}\\label{sec:a}\n"
        "\\begin{tabular}{ll} X & \\citet{tk1991}, Section~\\ref{sec:a} \\\\ \\end{tabular}",
        tmp_path,
    )
    text = _text(r.docx)
    assert "Tversky & Kahneman (1991)" in text.replace("&amp;", "&")
    assert "tk1991" not in text
    assert not _unresolved(r)


def test_cite_in_theorem_and_captions(tmp_path):
    r = _convert(
        "\\begin{theorem} As in \\citet{tk1991}. \\end{theorem}\n"
        "\\begin{figure}\\caption{Cap \\citep{tk1991}.}\\end{figure}\n"
        "\\begin{table}\\caption{T \\citep{tk1991}.}"
        "\\begin{tabular}{l} a \\\\ \\end{tabular}\\end{table}",
        tmp_path,
        preamble="\\newtheorem{theorem}{Theorem}\n",
    )
    text = _text(r.docx).replace("&amp;", "&")
    assert "tk1991" not in text
    assert text.count("Tversky & Kahneman") >= 3


def test_cite_and_ref_in_colored_and_sized_spans(tmp_path):
    r = _convert(
        "\\section{S}\\label{sec:a}\n"
        "\\textcolor{red}{see \\citet{tk1991} and \\ref{sec:a}} "
        "{\\small \\citep{tk1991}}",
        tmp_path,
        preamble="\\usepackage{xcolor}\n",
    )
    assert "tk1991" not in _text(r.docx)
    assert not _unresolved(r)


def test_second_label_is_an_alias(tmp_path):
    r = _convert(
        "\\section{S}\\label{sec:a}\\label{sec:b}\nSee \\ref{sec:b} and \\ref{sec:a}.",
        tmp_path,
    )
    assert not _unresolved(r)
    assert r.document.labels["sec:b"].bookmark == r.document.labels["sec:a"].bookmark


def test_later_label_does_not_steal_heading_label(tmp_path):
    # a \label in running text after the heading used to replace the heading's
    # own label, leaving \ref{sec:a} unresolved
    r = _convert(
        "\\section{S}\\label{sec:a}\nText \\label{sec:late} more.\n"
        "See \\ref{sec:a} and \\ref{sec:late}.",
        tmp_path,
    )
    assert not _unresolved(r)
