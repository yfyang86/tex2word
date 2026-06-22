"""Breadth: user-defined \\newtheorem environments are recognised."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx

SRC = r"""
\documentclass{article}
\newtheorem{thm}{Theorem}
\newtheorem{mylem}[thm]{My Lemma}
\newtheorem*{rmk}{Remark}
\begin{document}
\begin{thm}\label{t1}A statement.\end{thm}
\begin{mylem}[Euclid]A titled lemma.\end{mylem}
\begin{rmk}An unnumbered remark.\end{rmk}
\end{document}
"""


def _theorems(doc):
    return [b for b in doc.blocks if type(b).__name__ == "Theorem"]


def test_custom_theorem_display_names():
    thms = _theorems(convert_source(SRC).document)
    kinds = [t.kind for t in thms]
    assert kinds == ["Theorem", "My Lemma", "Remark"]


def test_custom_theorem_numbering():
    thms = _theorems(convert_source(SRC).document)
    by_kind = {t.kind: t for t in thms}
    assert by_kind["Theorem"].counter == "Theorem"        # numbered
    # \newtheorem{mylem}[thm]{My Lemma} shares thm's counter, so it numbers
    # against "Theorem" (one running sequence), per LaTeX semantics.
    assert by_kind["My Lemma"].counter == "Theorem"
    assert by_kind["Remark"].counter is None              # \newtheorem* -> unnumbered


def test_custom_theorem_optional_title():
    thms = _theorems(convert_source(SRC).document)
    lemma = next(t for t in thms if t.kind == "My Lemma")
    assert lemma.title is not None
    assert "Euclid" in "".join(getattr(x, "value", "") for x in lemma.title)


def test_custom_theorem_body_and_valid():
    res = convert_source(SRC)
    assert validate_docx(res.docx) == []
    thm = _theorems(res.document)[0]
    body = "".join(
        getattr(x, "value", "") for blk in thm.blocks for x in getattr(blk, "inlines", [])
    )
    assert "A statement." in body


def test_undeclared_theoremlike_name_falls_back():
    # an undefined theorem-like env is not mistaken for a theorem
    doc = convert_source(r"\begin{document}\begin{madeup}x\end{madeup}\end{document}").document
    assert not _theorems(doc)


def test_newtheorem_wrapped_display_title():
    # real preambles wrap the title in a font command: \newtheorem{THM}{\textbf{Theorem}}.
    # The display name must be cleaned to "Theorem", not "\textbf{Theorem".
    doc = convert_source(
        r"\documentclass{article}\newtheorem{THM}{\textbf{Theorem}}"
        r"\begin{document}\begin{THM}Body.\end{THM}\end{document}"
    ).document
    assert _theorems(doc)[0].kind == "Theorem"


def test_newtheorem_defined_in_local_package(tmp_path):
    # \newtheorem living in a \usepackage'd local .sty (a paper's MyPreamble.sty)
    # must be harvested so the environment isn't "unknown / transparent".
    (tmp_path / "mypre.sty").write_text(
        r"\newtheorem{THM}{\textbf{Theorem}}"
        r"\newtheorem{LEM}[THM]{\textbf{Lemma}}" + "\n",
        encoding="utf-8",
    )
    src = (
        r"\documentclass{article}\usepackage{mypre}\begin{document}"
        r"\begin{THM}\label{THM:a}T.\end{THM}\begin{LEM}\label{LEM:b}L.\end{LEM}"
        r"See \ref{THM:a}, \ref{LEM:b}.\end{document}"
    )
    res = convert_source(src, base_dir=str(tmp_path))
    thms = _theorems(res.document)
    assert [t.kind for t in thms] == ["Theorem", "Lemma"]
    # LEM shares THM's counter -> both number against "Theorem"
    assert thms[0].counter == "Theorem" and thms[1].counter == "Theorem"
    # the environments are recognised (no "unknown environment" warning) and the
    # in-theorem labels resolve (no unresolved-reference warning)
    assert not any(
        "unknown environment" in (w.message or "") or "unresolved reference" in (w.message or "")
        for w in res.report.warnings
    )


def test_beginappendix_switches_to_appendix_numbering():
    # fairmeta.cls-style \beginappendix wraps \appendix; it must switch later
    # sections to lettered numbering rather than warning as an unsupported macro.
    res = convert_source(
        r"\documentclass{article}\begin{document}\section{Intro}"
        r"\beginappendix\section{Extra}\end{document}"
    )
    assert not any("beginappendix" in (w.message or "") for w in res.report.warnings)
    headings = [b for b in res.document.blocks if type(b).__name__ == "Heading"]
    assert any(getattr(h, "appendix", False) for h in headings)
