"""Fidelity: split footnotes \\footnotemark / \\footnotetext are paired in order."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _footnotes(doc):
    out = []

    def walk(inlines):
        for n in inlines:
            if type(n).__name__ == "Footnote":
                out.append("".join(getattr(x, "value", "") for x in n.inlines))
            elif hasattr(n, "inlines"):
                walk(n.inlines)

    for b in doc.blocks:
        if hasattr(b, "inlines"):
            walk(b.inlines)
    return out


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def test_mark_then_text_pairs():
    res = _conv(r"A claim.\footnotemark{} more.\footnotetext{Deferred note.}")
    assert validate_docx(res.docx) == []
    assert _footnotes(res.document) == ["Deferred note."]


def test_multiple_pairs_in_order():
    src = (
        r"X\footnotemark{} Y\footnotemark{}"
        r"\footnotetext{First.}\footnotetext{Second.}"
    )
    assert _footnotes(_conv(src).document) == ["First.", "Second."]


def test_orphan_footnotetext_becomes_footnote():
    # a \footnotetext with no pending mark still surfaces its text
    assert _footnotes(_conv(r"\footnotetext{Standalone.}").document) == ["Standalone."]


def test_split_footnote_in_table_pairs_across_boundary():
    # \footnotemark inside a table cell, paired with a later \footnotetext
    import io
    import zipfile

    src = (
        r"\begin{table}\begin{tabular}{l} a\footnotemark \\ \end{tabular}"
        r"\caption{T}\end{table}\footnotetext{table note}"
    )
    res = _conv(src)
    assert validate_docx(res.docx) == []
    notes = zipfile.ZipFile(io.BytesIO(res.docx)).read("word/footnotes.xml").decode("utf-8")
    assert "table note" in notes
