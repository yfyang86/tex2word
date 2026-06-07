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
    assert by_kind["My Lemma"].counter == "My Lemma"      # numbered (shared counter)
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
