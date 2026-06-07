"""Breadth: the acronym package (\\acro defs + \\ac/\\acs/\\acl/\\acf refs)."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _txt(doc) -> str:
    out: list[str] = []

    def walk(inlines):
        for n in inlines:
            if type(n).__name__ == "Text":
                out.append(n.value)
            elif hasattr(n, "inlines"):
                walk(n.inlines)

    for b in doc.blocks:
        if hasattr(b, "inlines"):
            walk(b.inlines)
    return "".join(out)


def _conv(body: str, defs: str = r"\acro{CPU}{Central Processing Unit}"):
    src = r"\documentclass{article}" + defs + r"\begin{document}" + body + r"\end{document}"
    return convert_source(src)


def test_ac_first_use_then_short():
    res = _conv(r"\ac{CPU} and \ac{CPU}.")
    assert "Central Processing Unit (CPU)" in _txt(res.document)
    # second use is just the short form
    assert _txt(res.document).count("Central Processing Unit") == 1


def test_acs_acl_acf():
    body = r"\acs{CPU} / \acl{CPU} / \acf{CPU}"
    t = _txt(_conv(body).document)
    assert "CPU / Central Processing Unit / Central Processing Unit (CPU)" in t


def test_acro_optional_short_overrides_key():
    res = _conv(r"\acs{GPU}", defs=r"\acro{GPU}[GfxPU]{Graphics Processing Unit}")
    assert "GfxPU" in _txt(res.document)


def test_plural_and_capitalised():
    res = _conv(r"\acs{CPU} then \acp{CPU} and \Acl{CPU}")
    t = _txt(res.document)
    assert "CPUs" in t                      # \acp -> plural short
    assert "Central Processing Unit" in t   # \Acl -> capitalised long


def test_no_warnings_and_valid():
    res = _conv(r"\ac{CPU} \acs{CPU} \acl{CPU} \acf{CPU}")
    assert validate_docx(res.docx) == []
    assert not any("\\ac" in (w.construct or "") for w in res.report.warnings)
