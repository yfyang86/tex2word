"""SPRINT-V2.4 T14: corpus coverage dashboard + T10/T11 rendering."""

from __future__ import annotations

from conftest import NS, document_root

from tex2word import convert_source
from tex2word.cli import main
from tex2word.report import ConversionReport, aggregate_html

# -- T14: coverage dashboard ------------------------------------------------- #


def test_aggregate_html_summarises_corpus():
    r1 = ConversionReport(math_omml=3, math_raw=1)
    r1.warn("\\foo", "x")
    r2 = ConversionReport(math_omml=2)
    html = aggregate_html([("a.tex", r1), ("b.tex", r2)])
    assert "corpus coverage" in html
    assert "a.tex" in html and "b.tex" in html
    assert "2 document(s)" in html
    # 5 OMML of 6 total -> 83%
    assert "83%" in html


def test_coverage_cli_writes_dashboard(tmp_path):
    (tmp_path / "one.tex").write_text(
        r"\begin{document}\section{A}$x^2$\end{document}", encoding="utf-8"
    )
    (tmp_path / "two.tex").write_text(
        r"\begin{document}$\frac{a}{b}$\end{document}", encoding="utf-8"
    )
    out = tmp_path / "dash.html"
    rc = main(["coverage", str(tmp_path), "-o", str(out)])
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "one.tex" in html and "two.tex" in html


# -- T10: algorithm ruled box ------------------------------------------------ #


def test_algorithm_rendered_in_ruled_box():
    src = (
        r"\begin{document}\begin{algorithm}\caption{A}\begin{algorithmic}"
        r"\STATE x\end{algorithmic}\end{algorithm}\end{document}"
    )
    root = document_root(convert_source(src).docx)
    # algorithm sits in a table with top+bottom borders and a caption rule
    assert root.xpath("//w:tbl", namespaces=NS)
    border_sides = [
        b.tag.split("}")[1] for b in root.xpath("//w:tblBorders/*", namespaces=NS)
    ]
    assert "top" in border_sides and "bottom" in border_sides
    assert root.xpath("//w:pBdr", namespaces=NS)  # rule under the caption


# -- T11: columns ------------------------------------------------------------ #


def test_columns_option_sets_section_cols():
    docx = convert_source(
        r"\begin{document}text\end{document}", columns=2
    ).docx
    root = document_root(docx)
    cols = root.xpath("//w:sectPr/w:cols", namespaces=NS)
    assert cols and cols[0].get(f"{{{NS['w']}}}num") == "2"


def test_single_column_by_default():
    root = document_root(convert_source(r"\begin{document}t\end{document}").docx)
    assert not root.xpath("//w:sectPr/w:cols", namespaces=NS)
