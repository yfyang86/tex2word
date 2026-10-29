"""Cached field results and list restarts (issue #45)."""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import zipfile

import pytest

from tex2word import convert_source

SRC = r"""\documentclass{article}
\usepackage{amsmath,amsthm}
\newtheorem{theorem}{Theorem}[section]
\newtheorem{lemma}[theorem]{Lemma}
\begin{document}
\section{Intro}\label{s:i}
See \ref{s:m}, \ref{s:sub}, Figure~\ref{f:b}, Table~\ref{t:a}, \eqref{e:2},
Lemma~\ref{l:a} and item~\ref{i:2}.\footnote{Also \ref{s:sub}.}
\begin{equation}a=b\label{e:1}\end{equation}
\begin{figure}[h]\caption{First}\label{f:a}\end{figure}
\section{Method}\label{s:m}
\subsection{Sub}\label{s:sub}
\begin{theorem}\label{th:a}A\end{theorem}
\begin{lemma}\label{l:a}B\end{lemma}
\begin{align}x&=1\label{e:2}\\y&=2\label{e:3}\end{align}
\begin{figure}[h]\caption{Second}\label{f:b}\end{figure}
\begin{table}[h]\caption{Tab}\label{t:a}\begin{tabular}{l}x\\\end{tabular}\end{table}
\begin{enumerate}\item one\item\label{i:2} two\end{enumerate}
\appendix
\section{Proofs}\label{s:a}
\begin{theorem}C\end{theorem}
Refs: \ref{s:a}, \ref{e:3}, \ref{f:a}, \ref{th:a}.
\end{document}
"""


def _paras(docx: bytes, part: str = "word/document.xml") -> list[str]:
    xml = zipfile.ZipFile(io.BytesIO(docx)).read(part).decode()
    out = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        t = "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p)).replace(" ", " ")
        if t.strip():
            out.append(t.strip())
    return out


def test_cached_numbers_and_references_are_real():
    docx = convert_source(SRC).docx
    paras = _paras(docx)
    assert "See 2, 2.1, Figure 2, Table 1, (2), Lemma 2.2 and item 2." in paras
    for line in ("Figure 1: First", "Figure 2: Second", "Table 1: Tab", "(1)", "(3)",
                 "Theorem 2.1. A", "Lemma 2.2. B", "Theorem A.1. C",
                 "Refs: A, (3), 1, 2.1."):
        assert line in paras, line
    assert "Also 2.1." in _paras(docx, "word/footnotes.xml")


def test_per_section_numbering_caches_section_numbers():
    paras = _paras(convert_source(SRC, number_by_section=True).docx)
    assert "Figure 2.1: Second" in paras and "Table 2.1: Tab" in paras
    assert "See 2, 2.1, Figure 2.1, Table 2.1, (2.1), Lemma 2.2 and item 2." in paras


def test_each_ordered_list_restarts():
    src = (r"\documentclass{article}\usepackage{enumitem}\begin{document}"
           r"\begin{enumerate}\item a\item b\end{enumerate}x"
           r"\begin{enumerate}\item c\end{enumerate}"
           r"\begin{enumerate}[start=5]\item d\end{enumerate}\end{document}")
    z = zipfile.ZipFile(io.BytesIO(convert_source(src).docx))
    doc = z.read("word/document.xml").decode()
    num_ids = re.findall(r'<w:numId w:val="(\d+)"/>', doc)
    assert len(set(num_ids)) == 3  # one numbering instance per list
    numbering = z.read("word/numbering.xml").decode()
    assert '<w:startOverride w:val="5"/>' in numbering


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")
def test_cached_values_match_libreoffice(tmp_path):
    """LibreOffice recomputes every field on load: its render must show exactly
    the cached values (both numbering modes)."""
    pdfium = pytest.importorskip("pypdfium2")
    for by_section in (False, True):
        docx = convert_source(SRC, number_by_section=by_section).docx
        path = tmp_path / f"f{int(by_section)}.docx"
        path.write_bytes(docx)
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir",
                        str(tmp_path), str(path)], capture_output=True, timeout=180)
        pdf = pdfium.PdfDocument(str(path.with_suffix(".pdf")))
        rendered = re.sub(r"\s+", "", "".join(p.get_textpage().get_text_range() for p in pdf))
        for line in _paras(docx):
            assert re.sub(r"\s+", "", line) in rendered, (by_section, line)
