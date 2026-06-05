"""SPRINT-V2.2 T5: .bbl ingestion (formatted .bst output)."""

from __future__ import annotations

from conftest import NS, document_root

from latex2word import convert_file
from latex2word.bib.bbl import bbl_style, parse_bbl

NUMERIC_BBL = r"""
\begin{thebibliography}{1}
\bibitem{einstein1905}
A.~Einstein, \emph{Zur Elektrodynamik bewegter K{\"o}rper}, Annalen der Physik,
  17(10):891--921, 1905.
\bibitem{knuth1984}
D.~E. Knuth, \emph{The TeXbook}, Addison-Wesley, 1984.
\end{thebibliography}
"""

AUTHORYEAR_BBL = r"""
\begin{thebibliography}{Einstein(1905)}
\bibitem[Einstein(1905)]{einstein1905}
Albert Einstein. Zur Elektrodynamik. \emph{Annalen der Physik}, 1905.
\bibitem[Knuth(1984)]{knuth1984}
Donald E. Knuth. \emph{The TeXbook}. Addison-Wesley, 1984.
\end{thebibliography}
"""

BIB = "@article{einstein1905, author={X}, title={WRONG}, year={1900}}\n"


def test_parse_bbl_numeric():
    items = parse_bbl(NUMERIC_BBL)
    assert set(items) == {"einstein1905", "knuth1984"}
    assert items["einstein1905"].csl_fields["_order"] == 1
    assert "_label" not in items["einstein1905"].csl_fields
    assert "Körper" in items["einstein1905"].csl_fields["note"]
    assert bbl_style(items) == "numeric"


def test_parse_bbl_author_year():
    items = parse_bbl(AUTHORYEAR_BBL)
    assert items["einstein1905"].csl_fields["_label"] == "Einstein(1905)"
    assert bbl_style(items) == "author-year"


def _setup(tmp_path, bbl: str):
    (tmp_path / "refs.bib").write_text(BIB, encoding="utf-8")
    (tmp_path / "main.bbl").write_text(bbl, encoding="utf-8")
    tex = tmp_path / "main.tex"
    tex.write_text(
        r"\begin{document}See \cite{einstein1905} and \cite{knuth1984}."
        r"\bibliographystyle{plain}\bibliography{refs}\end{document}",
        encoding="utf-8",
    )
    return tex


def test_bbl_overrides_bib(tmp_path):
    # the .bib has a deliberately wrong title; the .bbl must win.
    tex = _setup(tmp_path, NUMERIC_BBL)
    _, result = convert_file(str(tex))
    text = " ".join(
        t.text or "" for t in document_root(result.docx).xpath("//w:t", namespaces=NS)
    )
    assert "Zur Elektrodynamik" in text
    assert "WRONG" not in text
    assert "[1]" in text and "[2]" in text  # numeric, .bbl order


def test_bbl_author_year_uses_labels(tmp_path):
    tex = _setup(tmp_path, AUTHORYEAR_BBL)
    _, result = convert_file(str(tex))
    text = " ".join(
        t.text or "" for t in document_root(result.docx).xpath("//w:t", namespaces=NS)
    )
    assert "Einstein(1905)" in text  # the .bbl label, not [1]
    # author-year bibliography has no [n] prefix
    refs = [
        " ".join(p.xpath(".//w:t/text()", namespaces=NS))
        for p in document_root(result.docx).xpath("//w:p", namespaces=NS)
        if p.xpath('./w:pPr/w:pStyle[@w:val="Bibliography"]', namespaces=NS)
    ]
    assert refs and not refs[0].startswith("[1]")


def test_bbl_reported(tmp_path):
    tex = _setup(tmp_path, NUMERIC_BBL)
    _, result = convert_file(str(tex))
    assert any(".bbl" in e.message for e in result.report.entries)
