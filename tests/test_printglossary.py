"""Fidelity: \\printglossaries/\\printacronyms -> a description list of entries."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _glossary_list(doc):
    return next(
        (b for b in doc.blocks if type(b).__name__ == "ItemList" and b.description), None
    )


def _term(item) -> str:
    return "".join(getattr(x, "value", "") for x in (item.term or []))


def _body(item) -> str:
    return "".join(
        getattr(x, "value", "") for blk in item.blocks for x in getattr(blk, "inlines", [])
    )


SRC = r"""
\documentclass{article}
\newacronym{cpu}{CPU}{Central Processing Unit}
\newacronym{gpu}{GPU}{Graphics Processing Unit}
\begin{document}
\gls{cpu} and \gls{gpu}.
\printglossaries
\end{document}
"""


def test_printglossaries_emits_description_list():
    res = convert_source(SRC)
    assert validate_docx(res.docx) == []
    assert not any("printglossaries" in (w.message or "") for w in res.report.warnings)
    lst = _glossary_list(res.document)
    assert lst is not None
    pairs = {(_term(i), _body(i)) for i in lst.items}
    assert ("CPU", "Central Processing Unit") in pairs
    assert ("GPU", "Graphics Processing Unit") in pairs


def test_printacronyms_alias_works():
    src = SRC.replace(r"\printglossaries", r"\printacronyms")
    assert _glossary_list(convert_source(src).document) is not None


def test_empty_glossary_emits_nothing():
    src = r"\begin{document}Text only.\printglossaries\end{document}"
    res = convert_source(src)
    assert _glossary_list(res.document) is None
    assert validate_docx(res.docx) == []
