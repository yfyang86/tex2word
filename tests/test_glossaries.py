from __future__ import annotations

from latex2word import convert_source, ir
from latex2word.frontend import parse_document
from latex2word.validate import validate_docx

_PRE = (
    r"\newacronym{ml}{ML}{machine learning}"
    r"\newacronym{ai}{AI}{artificial intelligence}"
)


def _text(src: str) -> str:
    doc, _ = parse_document(_PRE + r"\begin{document}" + src + r"\end{document}", ".")
    return "".join(
        i.value
        for b in doc.blocks
        if isinstance(b, ir.Paragraph)
        for i in b.inlines
        if isinstance(i, ir.Text)
    )


def test_gls_first_use_is_full_then_short():
    assert _text(r"\gls{ml} and \gls{ml}") == "machine learning (ML) and ML"


def test_capitalised_variant():
    assert _text(r"\Gls{ml}") == "Machine learning (ML)"


def test_acrshort_acrlong_acrfull():
    assert _text(r"\acrshort{ai}") == "AI"
    assert _text(r"\acrlong{ai}") == "artificial intelligence"
    assert _text(r"\acrfull{ai}") == "artificial intelligence (AI)"


def test_plural():
    assert _text(r"\glspl{ml}") == "machine learnings (MLs)"
    assert _text(r"\acrshortpl{ai}") == "AIs"


def test_glsentry_does_not_mark_first_use():
    # \glsentryshort/long never trigger the full form, even before any \gls
    assert _text(r"\glsentrylong{ml}, then \gls{ml}") == (
        "machine learning, then machine learning (ML)"
    )


def test_undefined_acronym_falls_back_to_key():
    assert _text(r"\gls{nosuch}") == "nosuch"


def test_newacronym_emits_nothing_in_body():
    # a \newacronym sitting in the body must not leak its braces as text
    assert _text(r"\newacronym{xy}{XY}{ex why}\acrshort{xy}") == "XY"


def test_acronyms_valid_and_warning_free():
    res = convert_source(
        _PRE + r"\begin{document}We study \gls{ml} via \gls{ai}; "
        r"later \gls{ml} and \gls{ai}.\end{document}"
    )
    assert validate_docx(res.docx) == []
    assert res.report.warnings == []


def test_acronym_round_trips_as_text():
    from latex2word.roundtrip import recover_ir, to_latex

    res = convert_source(
        _PRE + r"\begin{document}\acrfull{ml}\end{document}", embed_manifest=True
    )
    assert recover_ir(res.docx).to_dict() == res.document.to_dict()
    assert "machine learning (ML)" in to_latex(res.docx)
