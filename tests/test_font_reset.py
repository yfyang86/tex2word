"""Correctness: \\textrm/\\textnormal/\\textsf are upright resets, not italic."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _emph_kinds(doc) -> list[str]:
    kinds: list[str] = []

    def walk(inlines):
        for n in inlines:
            if type(n).__name__ == "Emphasis":
                kinds.append(n.kind_)
                walk(n.inlines)
            elif hasattr(n, "inlines"):
                walk(n.inlines)

    for b in doc.blocks:
        if hasattr(b, "inlines"):
            walk(b.inlines)
    return kinds


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def test_textrm_is_not_italic():
    assert "italic" not in _emph_kinds(_conv(r"\textrm{plain}").document)


def test_textsf_renders_without_warning():
    res = _conv(r"\textsf{sans text}")
    assert "italic" not in _emph_kinds(res.document)
    # no graceful-degradation warning for an unsupported macro
    assert not any("textsf" in (w.construct or "") for w in res.report.warnings)


def test_vector_macro_is_bold_upright_not_bold_italic():
    # \vect{v} = \textrm{\textbf{v}} -> bold only (a vector is bold-upright)
    src = r"\newcommand{\vect}[1]{\textrm{\textbf{#1}}}\vect{v}"
    kinds = _emph_kinds(_conv(src).document)
    assert "bold" in kinds
    assert "italic" not in kinds


def test_textbf_textit_still_work():
    assert "bold" in _emph_kinds(_conv(r"\textbf{B}").document)
    assert "italic" in _emph_kinds(_conv(r"\textit{I}").document)


def test_valid():
    assert validate_docx(_conv(r"\textrm{a} \textsf{b} \textup{c}").docx) == []
