"""Fidelity fixes found by texprobe's TeX oracle (issues #47-#54).

Each test states what LaTeX prints and checks the Word text says the same.
"""

from __future__ import annotations

import io
import re
import zipfile

from tex2word import convert_source


def _text(docx: bytes) -> list[str]:
    """What a reader sees, paragraph by paragraph: text and math runs, the tab
    before an equation number, line breaks as new lines, and the heading and
    list numbers Word computes from numbering.xml."""
    from lxml import etree

    from tex2word.backend.field_results import _num_of, _Numbering

    z = zipfile.ZipFile(io.BytesIO(docx))
    numbering = _Numbering(z.read("word/numbering.xml"))
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    m = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
    out: list[str] = []
    for p in etree.fromstring(z.read("word/document.xml")).iter(w + "p"):
        num = _num_of(p)
        label = numbering.advance(*num) if num else None
        parts = [label[0] + " "] if label else []
        for el in p.iter(w + "t", m + "t", w + "tab", w + "br"):
            if el.tag in (w + "t", m + "t"):
                parts.append(el.text or "")
            else:
                parts.append(" " if el.tag == w + "tab" else "\n")
        for line in "".join(parts).replace("\u00a0", " ").split("\n"):
            # ASCII whitespace only: the thin space of siunitx is content
            line = re.sub(r"[ \t]+", " ", line).strip()
            if line:
                out.append(line)
    return out


def _doc(body: str, preamble: str = "", cls: str = "article") -> list[str]:
    return _text(convert_source(rf"\documentclass{{{cls}}}{preamble}\begin{{document}}"
                                + body + r"\end{document}").docx)


# -- #47 align: \tag, \notag, \nonumber ---------------------------------------- #

def test_tag_notag_nonumber():
    lines = _doc(r"\begin{align} a &= b \tag{A}\label{a}\\ c &= d \notag\\ e &= f\label{e}"
                 r"\end{align} See \eqref{a}, \ref{a}, \eqref{e}.", r"\usepackage{amsmath}")
    assert lines == ["a=b (A)", "c=d", "e=f (1)", "See (A), A, (1)."]


def test_nonumber_does_not_advance_the_counter():
    assert _doc(r"\begin{align} a &= b \nonumber\\ c &= d \end{align}",
                r"\usepackage{amsmath}") == ["a=b", "c=d (1)"]


def test_tag_star_equation_and_unnumbered_display():
    assert _doc(r"\begin{equation} x = y \tag*{B}\end{equation}\[ z \tag{C} \]",
                r"\usepackage{amsmath}") == ["x=y B", "z (C)"]


def test_multline_numbers_its_last_line_only():
    assert _doc(r"\begin{multline} a\label{m} \\ b \end{multline}\eqref{m}",
                r"\usepackage{amsmath}") == ["a", "b (1)", "(1)"]


def test_ref_to_an_equation_has_no_parentheses():
    assert _doc(r"\begin{equation}x\label{q}\end{equation}\ref{q} \eqref{q}",
                r"\usepackage{amsmath}")[-1] == "1 (1)"


# -- #48 \pageref ----------------------------------------------------------- #

def test_pageref_is_not_the_placeholder_zero():
    assert _doc(r"\section{T}\label{t}Page~\pageref{t}.")[-1] == "Page 1."


# -- #49 the abstract's heading ------------------------------------------------ #

ABSTRACT = r"\title{T}\author{A}\date{}\maketitle\begin{abstract}Text.\end{abstract}"


def test_abstract_heading_per_class():
    assert _doc(ABSTRACT)[2:4] == ["Abstract", "Text."]
    assert _doc(ABSTRACT, cls="amsart")[2] == "Abstract. Text."
    assert _doc(ABSTRACT, cls="IEEEtran")[2] == "Abstract—Text."


def test_abstract_name_follows_abstractname_and_babel():
    assert _doc(ABSTRACT, r"\renewcommand{\abstractname}{Summary}")[2] == "Summary"
    assert _doc(ABSTRACT, r"\usepackage[ngerman]{babel}")[2] == "Zusammenfassung"


# -- #50 cleveref names -------------------------------------------------------- #

def test_cleveref_names_match_the_package():
    body = (r"\section{A}\label{a}\section{B}\label{b}\begin{equation}x\label{e}\end{equation}"
            r"\begin{table}\caption{T}\label{t}\begin{tabular}{l}x\\\end{tabular}\end{table}"
            r"\cref{a} \Cref{a} \cref{a,b} \cref{e} \cref{t} \crefrange{a}{b} \autoref{a}")
    assert _doc(body, r"\usepackage{amsmath}\usepackage{hyperref}\usepackage{cleveref}")[-1] \
        == "section 1 Section 1 sections 1 and 2 eq. (1) table 1 sections 1 to 2 section 1"


# -- #51 siunitx digit grouping ---------------------------------------------------- #

def test_siunitx_groups_digits_like_siunitx():
    out = _doc(r"\num{12345} \num{1234} \num{0.123456} \num[group-digits=false]{12345} "
               r"\SI{1234567}{\metre}"
               r"\begin{tabular}{lS[table-format=5.1]}a & {Value}\\ b & 12345.5\\\end{tabular}",
               r"\usepackage{siunitx}")
    assert out[0] == "12 345 1234 0.123 456 12345 1 234 567 m"
    assert "12 345.5" in out and "Value" in out


def test_sisetup_changes_the_separator_and_marker():
    out = _doc(r"\num{12345.678}", r"\usepackage{siunitx}"
               r"\sisetup{group-separator={,}, output-decimal-marker={;}}")
    assert out == ["12,345;678"]


# -- #52 nested tabular with a position argument ---------------------------------- #

def test_tabular_position_argument_does_not_leak():
    out = _doc(r"\begin{tabular}{ll}A & \begin{tabular}[t]{@{}l@{}}first\\second\end{tabular}"
               r"\\ B & \begin{tabular}[b]{c}p\end{tabular}\\\end{tabular}")
    assert out == ["A", "first", "second", "B", "p"]


def test_colspec_groups_and_options_are_not_columns():
    from tex2word.frontend.parser import _parse_colspec

    aligns, _ = _parse_colspec(r"@{}lS[table-format=2.2]@{\hspace{1cm}}c*{2}{r}")
    assert aligns == ["left", "center", "center", "right", "right"]


# -- #53 subtables -------------------------------------------------------------- #

def test_subtable_refs_and_caption_order():
    out = _doc(r"\begin{table}\caption{Main}\label{tm}"
               r"\begin{subtable}{.45\textwidth}\caption{Left}\label{ts}"
               r"\begin{tabular}{l}x\\\end{tabular}\end{subtable}"
               r"\begin{subtable}{.45\textwidth}\caption{Right}\label{tr}"
               r"\begin{tabular}{l}y\\\end{tabular}\end{subtable}\end{table}"
               r"\ref{tm} \ref{ts} \subref{tr}", r"\usepackage{subcaption}")
    assert out == ["Table 1: Main", "(a) Left", "x", "(b) Right", "y", "1 1a (b)"]


def test_caption_after_the_tabular_stays_below():
    out = _doc(r"\begin{table}\begin{tabular}{l}z\\\end{tabular}\caption{Below}\end{table}")
    assert out == ["z", "Table 1: Below"]


# -- #54 smaller findings ----------------------------------------------------------- #

def test_setcounter_section():
    assert _doc(r"\setcounter{section}{4}\section{A}\label{s}See \ref{s}.\section{B}") == [
        "5 A", "See 5.", "6 B"]
    out = _doc(r"\section{A}\setcounter{subsection}{3}\subsection{X}\section{B}\subsection{Y}")
    assert out == ["1 A", "1.4 X", "2 B", "2.1 Y"]


def test_atbegindocument_text_is_printed():
    assert _doc(r"Body", r"\AtBeginDocument{KEEP1}\AtEndDocument{TAIL}") == ["KEEP1 Body TAIL"]


def test_classes_without_a_title_date():
    title = r"\title{T}\author{A}\maketitle Body"
    assert _doc(title, cls="IEEEtran") == ["T", "A", "Body"]
    assert len(_doc(title)) == 4  # article prints \today


def test_algorithmic_lines_like_latex():
    alg = (r"\begin{algorithm}\caption{K}\begin{algorithmic}[1]\Require $n$"
           r"\For{$i=1$ to $n$}\If{$i>2$}\State x\EndIf\EndFor\State \Return $y$"
           r"\end{algorithmic}\end{algorithm}")
    assert _doc(alg, r"\usepackage{algorithm,algpseudocode}")[1:] == [
        "Require: n", "1: for i=1 to n do", "2: if i>2 then", "3: x", "4: end if",
        "5: end for", "6: return y"]
    noend = _doc(alg, r"\usepackage{algorithm}\usepackage[noend]{algpseudocode}")
    assert "end if" not in " ".join(noend)
    unnumbered = _doc(alg.replace("[1]", ""), r"\usepackage{algorithm,algpseudocode}")
    assert unnumbered[2] == "for i=1 to n do"
