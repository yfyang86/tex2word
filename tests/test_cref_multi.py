"""Fidelity: multi-label \\cref{a,b,c} and \\crefrange{a}{b} (cleveref)."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx

PRE = r"""
\section{A}\label{s:a}
\section{B}\label{s:b}
\section{C}\label{s:c}
"""


def _conv(body: str):
    return convert_source(r"\begin{document}" + PRE + body + r"\end{document}")


def _seq(doc):
    """Flatten the last paragraph to a list of ('ref', key) / ('text', value)."""
    para = [b for b in doc.blocks if type(b).__name__ == "Paragraph"][-1]
    out = []
    for n in para.inlines:
        k = type(n).__name__
        if k == "Ref":
            out.append(("ref", n.key))
        elif k == "Text":
            out.append(("text", n.value))
    return out


def test_two_label_cref_joined_with_and():
    res = _conv(r"See \cref{s:a,s:b}.")
    assert not any("unresolved" in (w.message or "") for w in res.report.warnings)
    seq = _seq(res.document)
    assert ("ref", "s:a") in seq and ("ref", "s:b") in seq
    assert any(k == "text" and "and" in v for k, v in seq)


def test_three_label_cref_uses_comma_and_and():
    seq = _seq(_conv(r"See \cref{s:a,s:b,s:c}.").document)
    refs = [v for k, v in seq if k == "ref"]
    assert refs == ["s:a", "s:b", "s:c"]
    texts = "".join(v for k, v in seq if k == "text")
    assert "," in texts and "and" in texts


def test_only_first_ref_carries_prefix():
    # the first ref keeps the cref style; the rest are bare (plain)
    para = [b for b in _conv(r"\cref{s:a,s:b}.").document.blocks
            if type(b).__name__ == "Paragraph"][-1]
    refs = [n for n in para.inlines if type(n).__name__ == "Ref"]
    assert refs[0].style != "plain"
    assert refs[1].style == "plain"


def test_crefrange_both_endpoints():
    seq = _seq(_conv(r"See \crefrange{s:a}{s:c}.").document)
    refs = [v for k, v in seq if k == "ref"]
    assert refs == ["s:a", "s:c"]
    assert any(k == "text" and "to" in v for k, v in seq)


def test_valid():
    assert validate_docx(_conv(r"\cref{s:a,s:b} and \crefrange{s:a}{s:c}.").docx) == []
